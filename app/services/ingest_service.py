import os
import csv
import io
import time
import uuid
import shutil
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from app.extensions import db
from app.config import Config
from app.models.source_domain import MUser, MOrder, MPayment, MChargeback
from app.models.investigation import Recommendation, CaseEvidence
from app.schemas.trigger import TriggerRequest
from app.services.case_service import CaseService
from app.agent.graph import execute_case_investigation

logger = logging.getLogger("fraud_agent.ingest_service")

def utc_now():
    return datetime.now(timezone.utc)

class IngestService:
    """
    Microservice-pattern batch ingestion service.
    Accepts simplified 3-4 column CSV/Excel files (user_id, user_name, email, reason).
    Resolves users against master tables (m_users, m_orders, m_payments, m_chargebacks)
    and triggers LangGraph fraud investigations.
    """

    USER_ID_ALIASES = {"user_id", "userid", "customer_id", "id", "account_id", "user"}
    NAME_ALIASES = {"user_name", "username", "name", "customer_name", "full_name"}
    EMAIL_ALIASES = {"email", "email_address", "user_email", "mail"}
    REASON_ALIASES = {"reason", "trigger_reason", "investigation_reason", "notes", "description"}

    @classmethod
    def _extract_column(cls, row: Dict[str, str], aliases: set) -> Optional[str]:
        for k, v in row.items():
            if k in aliases and v:
                return v.strip()
        return None

    @classmethod
    def parse_and_ingest_stream(cls, file_content: bytes, filename: str, auto_investigate: bool = True):
        """
        Generator that parses 3-4 column Excel/CSV file content, resolves users against
        m_users/m_orders/m_payments/m_chargebacks, auto-provisions missing users,
        triggers investigations, and yields real-time SSE progress events.
        """
        rows = []
        is_excel = filename.lower().endswith(".xlsx") or filename.lower().endswith(".xls")

        if is_excel:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True)
                ws = wb.active
                data = list(ws.iter_rows(values_only=True))
                if not data or len(data) < 2:
                    raise ValueError("Excel worksheet is empty or missing data rows.")

                headers = [str(h).strip().lower().replace(" ", "_") for h in data[0] if h is not None]
                for r in data[1:]:
                    if not any(r):
                        continue
                    row_dict = {}
                    for h, val in zip(headers, r):
                        row_dict[h] = str(val).strip() if val is not None else ""
                    rows.append(row_dict)
            except Exception as e:
                logger.error(f"Failed to parse Excel file: {e}")
                raise ValueError(f"Excel parsing error: {str(e)}")
        else:
            try:
                text_content = file_content.decode("utf-8-sig", errors="replace")
                reader = csv.DictReader(io.StringIO(text_content))
                for r in reader:
                    cleaned_row = {k.strip().lower().replace(" ", "_"): str(v).strip() for k, v in r.items() if k}
                    if any(cleaned_row.values()):
                        rows.append(cleaned_row)
            except Exception as e:
                logger.error(f"Failed to parse CSV file: {e}")
                raise ValueError(f"CSV parsing error: {str(e)}")

        total_rows = len(rows)
        if total_rows == 0:
            yield {
                "event": "complete",
                "status": "EMPTY",
                "message": "No valid data rows found in uploaded file.",
                "total_rows": 0,
                "current": 0,
                "total": 0,
                "percent": 100,
                "ingested": 0,
                "triggered_cases": []
            }
            return

        yield {
            "event": "start",
            "status": "PROCESSING",
            "message": f"Parsed {total_rows} user records from {filename}. Resolving against m_* master tables...",
            "total_rows": total_rows,
            "current": 0,
            "total": total_rows,
            "percent": 5,
            "filename": filename
        }

        ingested_count = 0
        triggered_cases = []

        for idx, row in enumerate(rows):
            current_num = idx + 1
            percent = min(95, round(5 + (current_num / total_rows) * 90))

            raw_user_id = cls._extract_column(row, cls.USER_ID_ALIASES)
            raw_email = cls._extract_column(row, cls.EMAIL_ALIASES)
            raw_name = cls._extract_column(row, cls.NAME_ALIASES)
            raw_reason = cls._extract_column(row, cls.REASON_ALIASES)

            if not raw_user_id and not raw_email:
                yield {
                    "event": "row_error",
                    "status": "PROCESSING",
                    "current": current_num,
                    "total": total_rows,
                    "percent": percent,
                    "error": "Row missing both user_id and email identifier",
                    "message": f"Row {current_num} skipped: missing both user_id and email"
                }
                continue

            yield {
                "event": "row_start",
                "status": "PROCESSING",
                "current": current_num,
                "total": total_rows,
                "percent": percent,
                "item_id": raw_user_id or raw_email,
                "user_id": raw_user_id or raw_email,
                "message": f"Resolving user {raw_user_id or raw_email} against m_users master table..."
            }

            try:
                # 1. Direct entity resolution from m_users (NO fallback to email if user_id is provided)
                user = None
                if raw_user_id:
                    user = MUser.query.filter_by(user_id=raw_user_id).first()
                elif raw_email:
                    user = MUser.query.filter_by(email=raw_email).first()

                is_provisioned = False
                case_summary = None

                if not user:
                    # User details do NOT exist in m_users core database.
                    # Do NOT auto-provision into m_users, m_orders, or m_payments.
                    # Directly log that user details do not exist in the database,
                    # professionally record the trigger reason, and queue the case for investigation.
                    target_user_id = raw_user_id or raw_email
                    user_display = f"Unregistered Customer ({raw_name.strip()})" if raw_name else f"Unregistered User ({target_user_id})"
                    base_reason = raw_reason.strip() if raw_reason else "Batch Ingestion Ingestion"

                    # Professional reason explaining that user details do not exist in the database
                    enriched_reason = (
                        f"Unregistered Customer Record / Profile Missing in Core Database | "
                        f"Target: {target_user_id} | Reason: {base_reason} | "
                        f"Audit Note: No matching record found in m_users directory; flagged for missing identity verification."
                    )[:495]

                    priority = "HIGH"
                    ingested_count += 1

                    # Enqueue case directly into investigation queue
                    idempotency_key = f"USER_UNREGISTERED_{target_user_id}_{int(time.time())}"
                    trigger_req = TriggerRequest(
                        trigger_type="TRANSACTION_INVESTIGATION",
                        trigger_source="USER_BATCH_INGESTOR",
                        trigger_reason=enriched_reason,
                        priority=priority,
                        idempotency_key=idempotency_key,
                        transaction_id=None,
                        user_id=target_user_id,
                        merchant_id=None
                    )

                    case, is_dup = CaseService.process_trigger(trigger_req)

                    # Direct and concise explanation - No fallbacks, no fabricated graph/SOP narratives
                    direct_explanation = (
                        f"Target user details for '{target_user_id}' do not exist in the master m_users database. "
                        f"Unregistered customer identity with zero account, order, or transaction history. "
                        f"Action recommended: BLOCK_USER to prevent unauthorized access."
                    )

                    # Record missing profile evidence item
                    missing_evidence = CaseEvidence(
                        id=str(uuid.uuid4()),
                        case_id=case.id,
                        evidence_type="USER_PROFILE",
                        source_system="CUSTOMER_IDENTITY_DB",
                        source_reference=target_user_id,
                        retrieval_status="MISSING",
                        retrieved_at=utc_now(),
                        normalized_payload={"reason": f"User {target_user_id} profile record was not located in m_users database."}
                    )
                    db.session.add(missing_evidence)

                    # Record direct recommendation (no fallbacks)
                    rec = Recommendation(
                        id=str(uuid.uuid4()),
                        case_id=case.id,
                        assessment="SUSPICIOUS",
                        recommendation_type="BLOCK_USER",
                        explanation=direct_explanation,
                        confidence_label="HIGH",
                        human_review_required=True,
                        model_name="System Core Verification Engine",
                        prompt_version="1.0",
                        policy_version="1.0",
                        structured_result={
                            "assessment": "SUSPICIOUS",
                            "recommendation": "BLOCK_USER",
                            "explanation": direct_explanation,
                            "confidence_label": "HIGH",
                            "risk_indicators": [{
                                "statement": f"User '{target_user_id}' was not located in master m_users directory.",
                                "evidence_references": [missing_evidence.id]
                            }],
                            "counter_signals": []
                        }
                    )
                    db.session.add(rec)
                    case.status = "ACTION_PROPOSED"
                    db.session.commit()

                    case_summary = {
                        "case_id": case.id,
                        "transaction_id": "N/A",
                        "user_id": target_user_id,
                        "user_name": user_display,
                        "email": raw_email or "Not Provided",
                        "status": case.status,
                        "priority": case.priority,
                        "assessment": "SUSPICIOUS",
                        "recommendation": "BLOCK_USER",
                        "explanation": direct_explanation,
                        "created_at": case.created_at.isoformat(),
                        "orders_count": 0,
                        "payments_count": 0,
                        "chargebacks_count": 0,
                        "is_provisioned": False,
                        "user_exists": False
                    }
                    triggered_cases.append(case_summary)

                    yield {
                        "event": "row_done",
                        "status": "PROCESSING",
                        "current": current_num,
                        "total": total_rows,
                        "percent": percent,
                        "item_id": target_user_id,
                        "user_id": target_user_id,
                        "case": case_summary,
                        "message": f"User {target_user_id} details not found in database; case queued: SUSPICIOUS (BLOCK_USER)"
                    }
                    continue

                # 2. Existing User: Fetch linked data from m_orders, m_payments, m_chargebacks
                linked_orders = MOrder.query.filter_by(user_id=user.user_id).order_by(MOrder.created_at.desc()).all()
                linked_payments = MPayment.query.filter_by(user_id=user.user_id).order_by(MPayment.initiated_at.desc()).all()
                payment_ids = [p.payment_id for p in linked_payments]
                linked_chargebacks = (
                    MChargeback.query.filter(MChargeback.payment_id.in_(payment_ids)).all()
                    if payment_ids else []
                )

                orders_count = len(linked_orders)
                payments_count = len(linked_payments)
                chargebacks_count = len(linked_chargebacks)
                target_tx_id = linked_payments[0].payment_id if linked_payments else None
                target_merch_id = linked_payments[0].merchant_id if linked_payments else None
                ingested_count += 1

                # 3. Compute Dynamic Priority based on master domain state & policy signals
                is_high_risk = (
                    user.risk_level == "HIGH" or
                    user.kyc_status in ["REJECTED", "NOT_STARTED"] or
                    chargebacks_count > 0 or
                    (user.risk_score and float(user.risk_score) >= 70.0) or
                    any(term in (raw_reason or "").lower() for term in ["fraud", "suspicious", "stolen", "decline", "emulator", "ring", "chargeback"])
                )
                priority = "HIGH" if is_high_risk else "MEDIUM"

                # 4. Enrich Trigger Reason with Master Tables Evidence Context
                base_reason = raw_reason.strip() if raw_reason else "Batch Ingestion User Audit"
                user_display = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.user_id
                enriched_reason = (
                    f"{base_reason} | Target: {user.user_id} ({user_display}) | "
                    f"KYC: {user.kyc_status} | Risk Level: {user.risk_level} (Score: {user.risk_score or 0}) | "
                    f"Domain Profile: {orders_count} orders, {payments_count} payments, {chargebacks_count} disputes"
                )[:495]

                # 5. Auto-Trigger Fraud Investigation Agent
                if auto_investigate:
                    idempotency_key = f"USER_INGEST_{user.user_id}_{int(time.time())}"
                    trigger_req = TriggerRequest(
                        trigger_type="TRANSACTION_INVESTIGATION",
                        trigger_source="USER_BATCH_INGESTOR",
                        trigger_reason=enriched_reason,
                        priority=priority,
                        idempotency_key=idempotency_key,
                        transaction_id=target_tx_id,
                        user_id=user.user_id,
                        merchant_id=target_merch_id
                    )

                    case, is_dup = CaseService.process_trigger(trigger_req)
                    if not is_dup:
                        try:
                            execute_case_investigation(case.id)
                        except Exception as inv_err:
                            logger.error(f"Error executing case investigation {case.id}: {inv_err}")

                    db.session.refresh(case)
                    rec = case.recommendations[-1] if case.recommendations else None
                    case_summary = {
                        "case_id": case.id,
                        "transaction_id": target_tx_id or "N/A",
                        "user_id": user.user_id,
                        "user_name": user_display,
                        "email": user.email,
                        "status": case.status,
                        "priority": case.priority,
                        "assessment": rec.assessment if rec else "PENDING",
                        "recommendation": rec.recommendation_type if rec else "PENDING",
                        "explanation": rec.explanation if rec else "Investigation in progress",
                        "created_at": case.created_at.isoformat(),
                        "orders_count": orders_count,
                        "payments_count": payments_count,
                        "chargebacks_count": chargebacks_count,
                        "is_provisioned": False,
                        "user_exists": True
                    }
                    triggered_cases.append(case_summary)

                yield {
                    "event": "row_done",
                    "status": "PROCESSING",
                    "current": current_num,
                    "total": total_rows,
                    "percent": percent,
                    "item_id": user.user_id,
                    "user_id": user.user_id,
                    "case": case_summary,
                    "message": f"Processed user {user.user_id} ({user_display}): {case_summary['assessment'] if case_summary else 'SAVED'}"
                }

            except Exception as row_err:
                db.session.rollback()
                logger.error(f"Error processing row {idx+1}: {row_err}")
                yield {
                    "event": "row_error",
                    "status": "PROCESSING",
                    "current": current_num,
                    "total": total_rows,
                    "percent": percent,
                    "item_id": raw_user_id or raw_email or f"ROW_{current_num}",
                    "error": str(row_err),
                    "message": f"Error on user row {current_num}: {str(row_err)}"
                }

        yield {
            "event": "complete",
            "status": "SUCCESS",
            "message": f"Successfully ingested {ingested_count} user records. Resolved against m_* tables and initiated {len(triggered_cases)} fraud investigations.",
            "total_rows": total_rows,
            "current": total_rows,
            "total": total_rows,
            "percent": 100,
            "ingested": ingested_count,
            "triggered_cases": triggered_cases
        }

    @classmethod
    def parse_and_ingest(cls, file_content: bytes, filename: str, auto_investigate: bool = True) -> Dict[str, Any]:
        """Synchronous wrapper for parse_and_ingest_stream."""
        final_res = None
        for step in cls.parse_and_ingest_stream(file_content, filename, auto_investigate=auto_investigate):
            if step.get("event") == "complete":
                final_res = step

        if final_res:
            return {
                "status": final_res.get("status", "SUCCESS"),
                "message": final_res.get("message", ""),
                "total_rows": final_res.get("total_rows", 0),
                "ingested": final_res.get("ingested", 0),
                "triggered_cases": final_res.get("triggered_cases", [])
            }
        return {
            "status": "EMPTY",
            "message": "No valid data rows found in uploaded file.",
            "total_rows": 0,
            "ingested": 0,
            "triggered_cases": []
        }

    @classmethod
    def generate_sample_csv(cls) -> str:
        """
        Generates clean 4-column sample CSV (user_id, user_name, email, reason)
        matching the new microservice ingestion pattern.
        """
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["user_id", "user_name", "email", "reason"])

        # Row 1: Known Fraud Ring Member
        writer.writerow([
            "USR_FRAUD_RING_01",
            "Rajesh Kumar",
            "rajesh.fraud@darkweb.net",
            "Suspected member of organized emulator fraud ring"
        ])

        # Row 2: KYC Pending with Velocity
        writer.writerow([
            "USR_KYC_PENDING_02",
            "Vikram Khanna",
            "vikram.pending@tempmail.org",
            "Unverified KYC profile with sudden high transaction velocity"
        ])

        # Row 3: Verified VIP Customer (Legitimate)
        writer.writerow([
            "USR_VIP_LEGIT_03",
            "Priya Sharma",
            "priya.vip@example.com",
            "Routine quarterly audit for verified high-value VIP customer"
        ])

        # Row 4: Multiple Dispute Chargebacks
        writer.writerow([
            "USR_CHARGEBACK_06",
            "Neha Gupta",
            "neha.chargeback@dispute.org",
            "Multiple dispute chargebacks flagged by acquiring bank"
        ])

        # Row 5: Account Takeover Victim
        writer.writerow([
            "USR_ATO_VICTIM_07",
            "Amit Patel",
            "amit.patel@corporate.in",
            "Potential account takeover - anomalous device footprint and IP change"
        ])

        # Row 6: Dormant Account Spike
        writer.writerow([
            "USR_DORMANT_04",
            "Sunil Rao",
            "sunil.dormant@domain.com",
            "Dormant account reactivation with rapid high-frequency checkouts"
        ])

        return output.getvalue()


# ============================================================================
# Background Watcher / Poller Thread
# ============================================================================

class AutoTriggerScheduler:
    """Background polling thread that monitors watch folder and executes auto-triggers."""

    _thread: Optional[threading.Thread] = None
    _running: bool = False
    _last_run: Optional[str] = None
    _total_processed: int = 0

    @classmethod
    def start(cls, app):
        """Starts background poller thread if enabled in Config."""
        if cls._running:
            return

        if not Config.AUTO_TRIGGER_ENABLED:
            logger.info("Auto-trigger poller is disabled in environment configuration.")
            return

        cls._running = True
        cls._thread = threading.Thread(target=cls._poll_loop, args=(app,), daemon=True)
        cls._thread.start()
        logger.info(
            f"Auto-trigger poller started. Polling every {Config.TRIGGER_POLL_INTERVAL_SECONDS}s on watch dir: {Config.EXCEL_INGEST_WATCH_DIR}"
        )

    @classmethod
    def _poll_loop(cls, app):
        watch_dir = Config.EXCEL_INGEST_WATCH_DIR
        processed_dir = os.path.join(watch_dir, "processed")
        os.makedirs(watch_dir, exist_ok=True)
        os.makedirs(processed_dir, exist_ok=True)

        interval = max(5, Config.TRIGGER_POLL_INTERVAL_SECONDS)

        while cls._running:
            try:
                files = [
                    f for f in os.listdir(watch_dir)
                    if os.path.isfile(os.path.join(watch_dir, f)) and (f.endswith(".csv") or f.endswith(".xlsx"))
                ]

                if files:
                    logger.info(f"Auto-trigger poller found {len(files)} file(s) in watch directory.")
                    with app.app_context():
                        for fname in files:
                            fpath = os.path.join(watch_dir, fname)
                            try:
                                with open(fpath, "rb") as f:
                                    content = f.read()
                                res = IngestService.parse_and_ingest(content, fname, auto_investigate=True)
                                cls._total_processed += res.get("ingested", 0)
                                cls._last_run = utc_now().isoformat()
                                logger.info(f"Auto-ingested {fname}: {res.get('message')}")

                                # Move to processed
                                dest = os.path.join(processed_dir, f"{int(time.time())}_{fname}")
                                shutil.move(fpath, dest)
                            except Exception as file_err:
                                logger.error(f"Error processing watched file {fname}: {file_err}")

                cls._last_run = utc_now().isoformat()
            except Exception as e:
                logger.error(f"Error in auto-trigger poll loop: {e}")

            time.sleep(interval)

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        return {
            "auto_trigger_enabled": Config.AUTO_TRIGGER_ENABLED,
            "poll_interval_seconds": Config.TRIGGER_POLL_INTERVAL_SECONDS,
            "watch_directory": os.path.abspath(Config.EXCEL_INGEST_WATCH_DIR),
            "is_running": cls._running,
            "last_polled_at": cls._last_run,
            "total_auto_ingested": cls._total_processed
        }
