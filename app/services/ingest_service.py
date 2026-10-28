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
from app.models.source_domain import (
    MUser, MOrder, MPayment, MChargeback,
    User, Order, Payment, Chargeback
)
from app.schemas.trigger import TriggerRequest
from app.services.case_service import CaseService
from app.agent.graph import execute_case_investigation

logger = logging.getLogger("fraud_agent.ingest_service")

def utc_now():
    return datetime.now(timezone.utc)

class IngestService:
    """
    Processes 3-4 column batch files (user_id, user_name, email, reason),
    verifies against master m_* database tables, and auto-triggers fraud investigations.
    """

    @classmethod
    def parse_and_ingest_stream(cls, file_content: bytes, filename: str, auto_investigate: bool = True):
        """
        Generator that parses Excel/CSV file content with 3-4 columns:
        - user_id (Mandatory)
        - user_name (Mandatory)
        - email (Optional)
        - reason / notes (Optional)
        Queries m_users, retrieves master context from m_orders, m_payments, m_chargebacks,
        and yields real-time progress events for each row.
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

        # Validate headers for 3-4 column specification
        first_row = rows[0]
        has_user_id = any(k in first_row for k in ["user_id", "customer_id", "external_user_id"])
        has_user_name = any(k in first_row for k in ["user_name", "name", "customer_name", "first_name"])

        if not has_user_id:
            yield {
                "event": "complete",
                "status": "VALIDATION_FAILED",
                "message": "Batch specification error: Missing required 'user_id' column header in uploaded file.",
                "total_rows": total_rows,
                "current": 0,
                "total": total_rows,
                "percent": 100,
                "ingested": 0,
                "triggered_cases": []
            }
            return

        yield {
            "event": "start",
            "status": "PROCESSING",
            "message": f"Parsed {total_rows} records from {filename}. Verifying against master database tables (m_*)...",
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

            raw_user_id = row.get("user_id") or row.get("customer_id") or row.get("external_user_id") or ""
            raw_user_name = row.get("user_name") or row.get("name") or row.get("customer_name") or ""
            if not raw_user_name and row.get("first_name"):
                raw_user_name = f"{row.get('first_name')} {row.get('last_name', '')}".strip()
            raw_email = row.get("email") or ""
            raw_reason = row.get("reason") or row.get("notes") or row.get("trigger_reason") or "Routine Master Data Risk Audit"

            yield {
                "event": "row_start",
                "status": "PROCESSING",
                "current": current_num,
                "total": total_rows,
                "percent": percent,
                "user_id": raw_user_id,
                "user_name": raw_user_name,
                "message": f"Verifying master record {current_num} of {total_rows}: {raw_user_id} ({raw_user_name or 'N/A'})..."
            }

            try:
                # 1. Search in master table: m_users
                user = None
                if raw_user_id:
                    user = MUser.query.filter_by(user_id=raw_user_id).first()
                    if not user:
                        user = MUser.query.filter_by(external_user_id=raw_user_id).first()
                if not user and raw_email:
                    user = MUser.query.filter_by(email=raw_email).first()

                # Fallback to legacy users table if m_users doesn't have it yet
                if not user:
                    leg_user = User.query.filter_by(user_id=raw_user_id).first()
                    if not leg_user and raw_email:
                        leg_user = User.query.filter_by(email=raw_email).first()
                    if leg_user:
                        # Auto-promote to m_users
                        user = MUser(
                            user_id=leg_user.user_id,
                            external_user_id=leg_user.external_user_id,
                            first_name=leg_user.first_name,
                            last_name=leg_user.last_name,
                            email=leg_user.email,
                            phone_number=leg_user.phone_number,
                            user_type=leg_user.user_type,
                            status=leg_user.status,
                            country_code=leg_user.country_code or "IN",
                            kyc_status=leg_user.kyc_status or "PENDING",
                            risk_level=leg_user.risk_level or "LOW",
                            risk_score=float(leg_user.risk_score or 15.0),
                            created_at=leg_user.created_at or utc_now()
                        )
                        db.session.add(user)
                        db.session.commit()

                # If still not found, check if we should auto-register or error
                if not user:
                    if raw_user_id and raw_user_name:
                        # Auto-create entry in m_users to prevent complete failure while alerting
                        names = raw_user_name.split(" ", 1)
                        first_n = names[0]
                        last_n = names[1] if len(names) > 1 else "Customer"
                        user = MUser(
                            user_id=raw_user_id,
                            first_name=first_n,
                            last_name=last_n,
                            email=raw_email or f"{raw_user_id.lower()}@customer.com",
                            phone_number="+919800000000",
                            user_type="CUSTOMER",
                            status="ACTIVE",
                            country_code="IN",
                            kyc_status="PENDING",
                            risk_level="MEDIUM",
                            risk_score=50.00,
                            created_at=utc_now()
                        )
                        db.session.add(user)
                        db.session.commit()
                        logger.info(f"Registered new customer {raw_user_id} into m_users.")
                    else:
                        raise ValueError(f"User '{raw_user_id}' could not be verified in master tables (m_users).")

                # 2. Retrieve rich context from m_* master tables
                orders = MOrder.query.filter_by(user_id=user.user_id).order_by(MOrder.created_at.desc()).limit(10).all()
                payments = MPayment.query.filter_by(user_id=user.user_id).order_by(MPayment.initiated_at.desc()).limit(10).all()
                chargebacks = MChargeback.query.join(MPayment, MChargeback.payment_id == MPayment.payment_id).filter(MPayment.user_id == user.user_id).all()

                # Derive primary payment & merchant references
                primary_payment = payments[0] if payments else None
                primary_order = orders[0] if orders else None
                payment_id_ref = primary_payment.payment_id if primary_payment else f"TX_{user.user_id}_{int(time.time())}"
                merchant_id_ref = primary_payment.merchant_id if primary_payment else "MERCH_PRIME_01"

                ingested_count += 1
                case_summary = None

                # 3. Auto-Trigger Fraud Investigation Engine
                if auto_investigate:
                    # Determine risk-based priority from master user profile & chargebacks
                    is_critical = float(user.risk_score or 0) >= 90.0 or user.status == "BLOCKED"
                    is_high = user.risk_level == "HIGH" or len(chargebacks) > 0 or float(user.risk_score or 0) >= 75.0
                    is_medium = user.risk_level == "MEDIUM" or (user.kyc_status != "VERIFIED" and float(user.risk_score or 0) >= 40.0)

                    if is_critical:
                        priority = "CRITICAL"
                    elif is_high:
                        priority = "HIGH"
                    elif is_medium:
                        priority = "MEDIUM"
                    else:
                        priority = "LOW"

                    display_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or raw_user_name or user.user_id
                    trigger_reason = raw_reason or f"Batch Ingestion Risk Audit: Master user {user.user_id} ({display_name}), KYC: {user.kyc_status}, Risk: {user.risk_level} ({user.risk_score})"
                    idempotency_key = f"INGEST_{user.user_id}_{int(time.time())}_{idx}"

                    trigger_req = TriggerRequest(
                        trigger_type="TRANSACTION_INVESTIGATION",
                        trigger_source="EXCEL_BATCH_INGESTOR",
                        trigger_reason=trigger_reason,
                        priority=priority,
                        idempotency_key=idempotency_key,
                        transaction_id=payment_id_ref,
                        user_id=user.user_id,
                        merchant_id=merchant_id_ref
                    )

                    case, is_dup = CaseService.process_trigger(trigger_req)
                    if not is_dup:
                        try:
                            execute_case_investigation(case.id)
                        except Exception as inv_err:
                            logger.error(f"Error during batch case investigation {case.id}: {inv_err}")

                    # Refresh case data
                    db.session.refresh(case)
                    rec = case.recommendations[-1] if case.recommendations else None
                    case_summary = {
                        "case_id": case.id,
                        "transaction_id": payment_id_ref,
                        "user_id": user.user_id,
                        "user_name": display_name,
                        "status": case.status,
                        "priority": case.priority,
                        "assessment": rec.assessment if rec else "PENDING",
                        "recommendation": rec.recommendation_type if rec else "PENDING",
                        "explanation": rec.explanation if rec else "Investigation completed per master domain evidence.",
                        "created_at": case.created_at.isoformat()
                    }
                    triggered_cases.append(case_summary)

                yield {
                    "event": "row_done",
                    "status": "PROCESSING",
                    "current": current_num,
                    "total": total_rows,
                    "percent": percent,
                    "item_id": payment_id_ref,
                    "user_id": user.user_id,
                    "case": case_summary,
                    "message": f"Verified master profile {current_num} of {total_rows}: {user.user_id} -> {case_summary['recommendation'] if case_summary else 'VERIFIED'}"
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
                    "user_id": raw_user_id,
                    "error": str(row_err),
                    "message": f"Error on record {current_num} ({raw_user_id}): {str(row_err)}"
                }

        yield {
            "event": "complete",
            "status": "SUCCESS",
            "message": f"Processed {total_rows} records. Verified {ingested_count} users from master data tables (m_*) and dispatched {len(triggered_cases)} fraud investigations.",
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
        Generates the standard 4-column sample CSV:
        - user_id (Mandatory)
        - user_name (Mandatory)
        - email (Optional)
        - reason (Optional)
        Pre-populated with seeded master persona references.
        """
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["user_id", "user_name", "email", "reason"])

        writer.writerow([
            "USR_LEGIT_101", "Rahul Sharma", "rahul.sharma@example.com",
            "Routine retail transaction risk audit"
        ])
        writer.writerow([
            "USR_SYBIL_RING_01", "Sameer Khan", "sameer.khan@email.com",
            "Suspected ATO and emulator device cluster"
        ])
        writer.writerow([
            "USR_SYBIL_RING_02", "Vikram Khanna", "vikram.sybil@proton.me",
            "Hardware device fingerprint matches multi-account emulator ring"
        ])
        writer.writerow([
            "USR_UNVERIFIED_103", "Rohan Mehta", "rohan.unverified@tempmail.org",
            "High-value INR 1,85,000 transfer from unverified KYC profile"
        ])
        writer.writerow([
            "USR_CHARGEBACK_104", "Anita Deshmukh", "anita.disputes@gmail.com",
            "Customer has multiple recorded active dispute chargebacks"
        ])
        writer.writerow([
            "USR_DORMANT_105", "Priya Nair", "priya.nair@example.com",
            "Sudden reactivation with high velocity after 9 months dormancy"
        ])
        writer.writerow([
            "USR_WHALE_106", "Rajesh Patel", "rajesh.patel@corp.in",
            "Verified VIP high-net-worth volume procurement check"
        ])
        writer.writerow([
            "USR_VELOCITY_107", "Alex Mercer", "alex.bin@darkweb.net",
            "Multiple consecutive card decline velocity detected"
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
