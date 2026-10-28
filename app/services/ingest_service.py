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
from app.models.source_domain import User, Order, Payment, Chargeback
from app.schemas.trigger import TriggerRequest
from app.services.case_service import CaseService
from app.agent.graph import execute_case_investigation

logger = logging.getLogger("fraud_agent.ingest_service")

def utc_now():
    return datetime.now(timezone.utc)

class IngestService:
    """Processes batch transaction records from Excel/CSV and auto-triggers fraud investigations."""

    @classmethod
    def parse_and_ingest_stream(cls, file_content: bytes, filename: str, auto_investigate: bool = True):
        """
        Generator that parses Excel/CSV file content, updates database records,
        triggers investigations, and yields real-time progress events for each row.
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
            "message": f"Parsed {total_rows} records from {filename}. Starting batch ingestion...",
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
            user_id = row.get("user_id") or row.get("customer_id") or f"USR_{uuid.uuid4().hex[:8].upper()}"
            payment_id = row.get("payment_id") or row.get("transaction_id") or f"PAY_{uuid.uuid4().hex[:10].upper()}"

            yield {
                "event": "row_start",
                "status": "PROCESSING",
                "current": current_num,
                "total": total_rows,
                "percent": percent,
                "item_id": payment_id,
                "user_id": user_id,
                "message": f"Processing record {current_num} of {total_rows}: {payment_id} ({user_id})..."
            }

            try:
                # 1. Normalize User / Customer
                user = User.query.filter_by(user_id=user_id).first()
                if not user:
                    user = User(
                        user_id=user_id,
                        email=row.get("email") or f"{user_id.lower()}@customer.com",
                        first_name=row.get("first_name", "Customer"),
                        last_name=row.get("last_name", f"User_{idx+1}"),
                        phone_number=row.get("phone_number", "+919876543210"),
                        user_type="CUSTOMER",
                        status="ACTIVE",
                        country_code=row.get("country_code", "IN")[:2].upper(),
                        kyc_status=row.get("kyc_status", "PENDING").upper(),
                        risk_level=row.get("risk_level", "LOW").upper(),
                        risk_score=float(row.get("risk_score", 15.0)),
                        created_at=utc_now()
                    )
                    db.session.add(user)
                else:
                    if row.get("kyc_status"):
                        user.kyc_status = row.get("kyc_status").upper()
                    if row.get("risk_level"):
                        user.risk_level = row.get("risk_level").upper()

                # 2. Normalize Merchant
                merchant_id = row.get("merchant_id") or "MERCH_PRIME_01"
                merchant = User.query.filter_by(user_id=merchant_id, user_type="MERCHANT").first()
                if not merchant:
                    merchant = User(
                        user_id=merchant_id,
                        email=f"{merchant_id.lower()}@merchant.com",
                        first_name="Merchant",
                        last_name=merchant_id,
                        user_type="MERCHANT",
                        status="ACTIVE",
                        country_code="IN",
                        kyc_status="VERIFIED",
                        risk_level="LOW",
                        created_at=utc_now()
                    )
                    db.session.add(merchant)

                # 3. Normalize Order
                order_id = row.get("order_id") or f"ORD_{uuid.uuid4().hex[:10].upper()}"
                order = Order.query.filter_by(order_id=order_id).first()
                amount_val = float(row.get("amount") or 4500.0)
                currency_val = (row.get("currency") or "INR")[:3].upper()

                if not order:
                    order = Order(
                        order_id=order_id,
                        user_id=user.user_id,
                        merchant_id=merchant.user_id,
                        amount=amount_val,
                        currency=currency_val,
                        order_status=row.get("order_status", "PAID").upper(),
                        ip_address=row.get("ip_address", "192.168.1.50"),
                        device_id=row.get("device_id", f"DEV_{uuid.uuid4().hex[:8].upper()}"),
                        billing_country=row.get("billing_country", "IN")[:2].upper(),
                        shipping_country=row.get("shipping_country", "IN")[:2].upper(),
                        created_at=utc_now()
                    )
                    db.session.add(order)

                # 4. Normalize Payment
                payment = Payment.query.filter_by(payment_id=payment_id).first()
                if not payment:
                    payment = Payment(
                        payment_id=payment_id,
                        order_id=order.order_id,
                        user_id=user.user_id,
                        merchant_id=merchant.user_id,
                        payment_method=row.get("payment_method", "CARD").upper(),
                        payment_status=row.get("payment_status", "AUTHORIZED").upper(),
                        amount=amount_val,
                        currency=currency_val,
                        gateway_transaction_id=f"GW_{payment_id}",
                        ip_address=order.ip_address,
                        device_id=order.device_id,
                        failure_code=row.get("failure_code") or None,
                        failure_reason=row.get("failure_reason") or None,
                        initiated_at=utc_now()
                    )
                    db.session.add(payment)

                # 5. Optional Chargeback
                dispute_count = int(row.get("dispute_count", 0)) if row.get("dispute_count") else 0
                if dispute_count > 0 or row.get("has_chargeback", "").lower() in ["true", "1", "yes"]:
                    chargeback_id = f"CBK_{uuid.uuid4().hex[:8].upper()}"
                    cb = Chargeback(
                        chargeback_id=chargeback_id,
                        payment_id=payment.payment_id,
                        order_id=order.order_id,
                        amount=amount_val,
                        currency=currency_val,
                        reason_code=row.get("chargeback_reason", "FRAUDULENT_TRANSACTION"),
                        chargeback_status="OPEN",
                        fraud_indicator=True,
                        received_at=utc_now()
                    )
                    db.session.add(cb)

                db.session.commit()
                ingested_count += 1

                # 6. Auto-Trigger Fraud Investigation Agent
                case_summary = None
                if auto_investigate:
                    trigger_reason = (
                        row.get("trigger_reason") or
                        f"Batch Ingestion: Transaction {payment.payment_id} for user {user.user_id} (Amount: {currency_val} {amount_val})"
                    )
                    priority = "HIGH" if amount_val > 50000 or dispute_count > 0 else "MEDIUM"
                    idempotency_key = f"INGEST_{payment.payment_id}_{int(time.time())}"

                    trigger_req = TriggerRequest(
                        trigger_type="TRANSACTION_INVESTIGATION",
                        trigger_source="EXCEL_BATCH_INGESTOR",
                        trigger_reason=trigger_reason,
                        priority=priority,
                        idempotency_key=idempotency_key,
                        transaction_id=payment.payment_id,
                        user_id=user.user_id,
                        merchant_id=merchant.user_id
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
                        "transaction_id": payment.payment_id,
                        "user_id": user.user_id,
                        "status": case.status,
                        "priority": case.priority,
                        "assessment": rec.assessment if rec else "PENDING",
                        "recommendation": rec.recommendation_type if rec else "PENDING",
                        "explanation": rec.explanation if rec else "Investigation in progress",
                        "created_at": case.created_at.isoformat()
                    }
                    triggered_cases.append(case_summary)

                yield {
                    "event": "row_done",
                    "status": "PROCESSING",
                    "current": current_num,
                    "total": total_rows,
                    "percent": percent,
                    "item_id": payment_id,
                    "user_id": user.user_id,
                    "case": case_summary,
                    "message": f"Processed record {current_num} of {total_rows}: {case_summary['assessment'] if case_summary else 'SAVED'}"
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
                    "item_id": payment_id,
                    "error": str(row_err),
                    "message": f"Error on record {current_num}: {str(row_err)}"
                }

        yield {
            "event": "complete",
            "status": "SUCCESS",
            "message": f"Processed {total_rows} records. Ingested {ingested_count} transactions and triggered {len(triggered_cases)} fraud investigations.",
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
        """Generates a comprehensive sample CSV with mixed legitimate and fraud test scenarios."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "user_id", "first_name", "last_name", "email", "phone_number",
            "country_code", "kyc_status", "risk_level", "risk_score",
            "merchant_id", "order_id", "payment_id", "amount", "currency",
            "payment_method", "payment_status", "device_id", "ip_address",
            "billing_country", "shipping_country", "dispute_count", "trigger_reason"
        ])

        # Row 1: Normal Legitimate User
        writer.writerow([
            "USR_LEGIT_101", "Sourav", "Ganguly", "sourav.g@example.com", "+919830112233",
            "IN", "VERIFIED", "LOW", "12.5",
            "MERCH_PRIME_01", "ORD_NORMAL_801", "PAY_NORMAL_901", "3450", "INR",
            "UPI", "CAPTURED", "DEV_IPHONE_15_A", "103.21.144.12",
            "IN", "IN", "0", "Standard routine retail transaction check"
        ])

        # Row 2: Card Velocity & High-Risk Failure Fraud
        writer.writerow([
            "USR_VELOCITY_102", "Alex", "Mercer", "alex.bin@darkweb.net", "+14155552671",
            "US", "NOT_STARTED", "HIGH", "88.0",
            "MERCH_PRIME_01", "ORD_TEST_802", "PAY_FAIL_902", "12500", "INR",
            "CARD", "FAILED", "DEV_EMULATOR_CLONE_9", "45.142.120.10",
            "US", "IN", "0", "Multiple consecutive card decline velocity detected"
        ])

        # Row 3: High-Value KYC Unverified Fraud Attempt
        writer.writerow([
            "USR_UNVERIFIED_103", "Rohan", "Mehta", "rohan.unverified@tempmail.org", "+919876500112",
            "IN", "PENDING", "HIGH", "75.0",
            "MERCH_PRIME_01", "ORD_HIGHVAL_803", "PAY_HIGHVAL_903", "185000", "INR",
            "NET_BANKING", "AUTHORIZED", "DEV_MACBOOK_PRO_M3", "103.45.67.89",
            "IN", "IN", "0", "High-value INR 1,85,000 transfer from unverified KYC profile"
        ])

        # Row 4: Multi-Account Hardware Device Ring (Shared Device with Alex)
        writer.writerow([
            "USR_SYBIL_RING_104", "Vikram", "Khanna", "vikram.sybil@proton.me", "+919811223344",
            "IN", "PENDING", "HIGH", "82.0",
            "MERCH_PRIME_01", "ORD_SYBIL_804", "PAY_SYBIL_904", "45000", "INR",
            "CARD", "AUTHORIZED", "DEV_EMULATOR_CLONE_9", "45.142.120.10",
            "IN", "IN", "0", "Hardware device fingerprint matches known multi-user emulator ring"
        ])

        # Row 5: Chargeback Dispute Spike Merchant/User
        writer.writerow([
            "USR_DISPUTE_105", "Anita", "Deshmukh", "anita.disputes@gmail.com", "+919822334455",
            "IN", "VERIFIED", "MEDIUM", "65.0",
            "MERCH_PRIME_01", "ORD_DISPUTE_805", "PAY_DISPUTE_905", "28000", "INR",
            "CARD", "AUTHORIZED", "DEV_ONEPLUS_12", "115.111.45.22",
            "IN", "IN", "3", "Customer has 3 recorded active dispute chargebacks"
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
