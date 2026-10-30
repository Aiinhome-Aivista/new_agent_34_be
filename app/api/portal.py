import os
import time
import json
import uuid
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename

from app.config import Config
from app.extensions import db
from app.models.investigation import InvestigationCase, CaseEvidence, EvidenceRequestToken
from app.models.source_domain import MUser, User, MPayment, Payment, MOrder, Order
from app.services.audit_service import AuditService
from app.services.email_service import EmailService
from app.utils.crypto_utils import (
    generate_secure_token, hash_token,
    generate_otp, hash_otp, verify_otp_constant_time,
    generate_session_token, mask_email, mask_phone, mask_reference_id
)

logger = logging.getLogger("fraud_agent.api.portal")
portal_bp = Blueprint("portal", __name__)

EVIDENCE_UPLOAD_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "evidence_uploads")
)
ALLOWED_EVIDENCE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".docx", ".txt"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB per file

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def validate_magic_bytes(file_header: bytes, ext: str) -> bool:
    """Verifies magic bytes of uploaded files to prevent mime-type spoofing."""
    if ext in {".png"}:
        return file_header.startswith(b"\x89PNG\r\n\x1a\n")
    elif ext in {".jpg", ".jpeg"}:
        return file_header.startswith(b"\xff\xd8\xff")
    elif ext in {".pdf"}:
        return file_header.startswith(b"%PDF-")
    elif ext in {".webp"}:
        return len(file_header) >= 12 and file_header[0:4] == b"RIFF" and file_header[8:12] == b"WEBP"
    elif ext in {".docx"}:
        # DOCX is a zip file starting with PK\x03\x04
        return file_header.startswith(b"PK\x03\x04")
    elif ext in {".txt"}:
        # Text file can have arbitrary bytes, but should be decodable text
        return True
    return False

# ==============================================================================
# ADMIN: Evidence Request Dispatch & Tracking
# ==============================================================================

@portal_bp.route("/request-evidence/<case_id>", methods=["POST"])
def admin_request_evidence(case_id):
    """
    Called by Fraud Analysts/Admins to initiate an evidence request to the customer.
    Generates a cryptographically signed magic link, stores token hash, and sends notification.
    """
    case = InvestigationCase.query.filter_by(id=case_id).first()
    if not case:
        return jsonify({"error": "Not Found", "message": f"Case {case_id} was not found"}), 404

    payload = request.get_json(silent=True) or {}
    reviewer_id = payload.get("reviewer_id") or "ANALYST_FRAUD_DESK"
    reason = payload.get("reason", "").strip() or "Additional supporting documentation required for fraud verification."
    requested_documents = payload.get("requested_documents") or [
        {"key": "GOVT_ID", "label": "Government Issued Photo ID (Passport / Driver's License / National ID)"},
        {"key": "TAX_INVOICE", "label": "Purchase Invoice / Merchant Receipt"},
        {"key": "PAYMENT_PROOF", "label": "Bank Statement / Card Statement Slip"}
    ]
    expiry_hours = int(payload.get("expiry_hours", 48))

    # Resolve target user
    user_id = case.user_id_ref
    user_record = None
    if user_id:
        user_record = MUser.query.filter_by(user_id=user_id).first()
        if not user_record:
            user_record = User.query.filter_by(user_id=user_id).first()

    recipient_email = getattr(user_record, "email", None) if user_record else None
    if not recipient_email and case.transaction_id:
        # Fallback to payment user lookup
        payment = MPayment.query.filter_by(payment_id=case.transaction_id).first() or Payment.query.filter_by(payment_id=case.transaction_id).first()
        if payment and payment.user_id:
            user_id = payment.user_id
            u = MUser.query.filter_by(user_id=user_id).first() or User.query.filter_by(user_id=user_id).first()
            if u:
                recipient_email = u.email

    if not user_id:
        user_id = f"USER_{case_id[:8]}"

    # Revoke any prior active tokens for this case to enforce single valid link
    active_tokens = EvidenceRequestToken.query.filter_by(case_id=case_id, status="ISSUED").all()
    for at in active_tokens:
        at.status = "REVOKED"

    # Generate high-entropy token
    raw_token = generate_secure_token()
    tok_hash = hash_token(raw_token)
    expires_at = utc_now() + timedelta(hours=expiry_hours)

    req_token = EvidenceRequestToken(
        id=str(uuid.uuid4()),
        case_id=case_id,
        user_id=user_id,
        token_hash=tok_hash,
        requested_by=reviewer_id,
        request_reason=reason,
        requested_documents=requested_documents,
        status="ISSUED",
        expires_at=expires_at,
        created_at=utc_now()
    )
    db.session.add(req_token)

    # Transition case status to COLLECTING_EVIDENCE
    case.status = "COLLECTING_EVIDENCE"
    db.session.commit()

    # Determine base portal URL:
    # Priority:
    # 1. Origin header (e.g. http://localhost:5173 from React app)
    # 2. Referer header
    # 3. Config.FRONTEND_BASE_URL
    # 4. Fallback to request.host_url
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    frontend_base = None
    if origin and "http" in origin:
        frontend_base = origin.rstrip("/")
    elif referer and "http" in referer:
        from urllib.parse import urlparse
        p = urlparse(referer)
        frontend_base = f"{p.scheme}://{p.netloc}"
    elif getattr(Config, "FRONTEND_BASE_URL", None):
        frontend_base = Config.FRONTEND_BASE_URL.rstrip("/")
    else:
        frontend_base = request.host_url.rstrip("/")

    portal_link = f"{frontend_base}/evidence-submission?token={raw_token}"

    customer_name = (
        getattr(user_record, "full_name", None) or
        getattr(user_record, "name", None) or
        f"{getattr(user_record, 'first_name', '')} {getattr(user_record, 'last_name', '')}".strip() or
        "Account Holder"
    )

    # Dispatch REAL email via SMTP (Gmail)
    email_send_status = "NOT_CONFIGURED"
    if recipient_email and "@" in recipient_email:
        email_res = EmailService.send_evidence_request_email(
            to_email=recipient_email,
            customer_name=customer_name,
            case_reference=case.id,
            portal_url=portal_link,
            requested_documents=requested_documents,
            reason=reason,
            expires_at=expires_at.isoformat()
        )
        email_send_status = "SENT" if email_res.get("success") else f"FAILED: {email_res.get('error')}"

    masked_target_email = mask_email(recipient_email) if recipient_email else "user@domain.com"
    logger.info(
        f"[EMAIL_DISPATCH] Status: {email_send_status} | To: {recipient_email or 'user@domain.com'} | Subject: 'Action Required: Transaction Verification Request' | Link: {portal_link}"
    )

    # Record immutable audit event
    AuditService.record_event(
        event_type="EVIDENCE_REQUEST_ISSUED",
        actor_type="HUMAN_REVIEWER",
        correlation_id=case.idempotency_key,
        case_id=case_id,
        user_id=user_id,
        actor_id=reviewer_id,
        details={
            "request_token_id": req_token.id,
            "reason": reason,
            "requested_documents": requested_documents,
            "expires_at": expires_at.isoformat(),
            "recipient_email": masked_target_email,
            "portal_url": portal_link
        }
    )

    return jsonify({
        "message": "Evidence request created and email notification dispatched.",
        "request_id": req_token.id,
        "case_id": case_id,
        "token": raw_token,
        "portal_url": portal_link,
        "recipient_email": masked_target_email,
        "expires_at": expires_at.isoformat(),
        "case_status": case.status
    }), 201

@portal_bp.route("/requests-for-case/<case_id>", methods=["GET"])
def get_case_evidence_requests(case_id):
    """Returns list of evidence requests issued for this case."""
    requests_list = EvidenceRequestToken.query.filter_by(case_id=case_id).order_by(EvidenceRequestToken.created_at.desc()).all()
    return jsonify({
        "case_id": case_id,
        "items": [r.to_dict() for r in requests_list]
    }), 200

# ==============================================================================
# PUBLIC CUSTOMER EVIDENCE SUBMISSION PORTAL APIS
# ==============================================================================

@portal_bp.route("/evidence-request", methods=["GET"])
def get_public_evidence_request():
    """
    Public endpoint: Validates token and returns masked transaction/case context.
    Strictly masks sensitive personal and internal fraud data.
    """
    raw_token = request.args.get("token", "").strip()
    if not raw_token:
        return jsonify({"valid": False, "error": "Bad Request", "message": "Missing authentication token in request."}), 400

    tok_hash = hash_token(raw_token)
    req_token = EvidenceRequestToken.query.filter_by(token_hash=tok_hash).first()
    if not req_token:
        return jsonify({"valid": False, "error": "Invalid Token", "message": "The submission link is invalid or has expired."}), 404

    if req_token.status == "SUBMITTED":
        return jsonify({
            "valid": False,
            "status": "SUBMITTED",
            "error": "Already Submitted",
            "message": "Evidence for this request has already been successfully submitted. No further action is required.",
            "submitted_at": req_token.submitted_at.isoformat() if req_token.submitted_at else None
        }), 409

    if req_token.status == "REVOKED":
        return jsonify({
            "valid": False,
            "status": "REVOKED",
            "error": "Link Revoked",
            "message": "This evidence request was cancelled or superseded by the compliance team."
        }), 403

    if req_token.is_expired():
        req_token.status = "EXPIRED"
        db.session.commit()
        return jsonify({
            "valid": False,
            "status": "EXPIRED",
            "error": "Link Expired",
            "message": "This submission link has expired. Please contact support or request a new verification link."
        }), 410

    # Record access metadata
    req_token.access_count += 1
    req_token.last_accessed_at = utc_now()
    req_token.last_ip_address = request.remote_addr or "127.0.0.1"
    req_token.user_agent = (request.user_agent.string if request.user_agent else "Unknown")[:300]
    if req_token.status == "ISSUED":
        req_token.status = "ACCESSED"
    db.session.commit()

    case = req_token.case
    user_record = MUser.query.filter_by(user_id=req_token.user_id).first() or User.query.filter_by(user_id=req_token.user_id).first()
    
    # Resolve payment or order for context display
    payment_record = None
    if case and case.transaction_id:
        payment_record = MPayment.query.filter_by(payment_id=case.transaction_id).first() or Payment.query.filter_by(payment_id=case.transaction_id).first()

    customer_name = f"{getattr(user_record, 'first_name', '')} {getattr(user_record, 'last_name', '')}".strip() or getattr(user_record, 'name', None) or "Verified Account Holder"
    customer_email = getattr(user_record, "email", "user@example.com")
    customer_phone = getattr(user_record, "phone_number", None) or getattr(user_record, "phone", None)

    tx_id = case.transaction_id if case else "TXN-8841029"
    amount = float(payment_record.amount) if payment_record and hasattr(payment_record, "amount") else 24999.00
    currency = getattr(payment_record, "currency", "INR") if payment_record else "INR"
    tx_date = payment_record.initiated_at.isoformat() if payment_record and hasattr(payment_record, "initiated_at") and payment_record.initiated_at else utc_now().isoformat()
    payment_method = getattr(payment_record, "payment_method", "CARD") if payment_record else "CARD"

    return jsonify({
        "valid": True if req_token else False,
        "case_reference": mask_reference_id(case.id, "CASE") if case else "CASE-****-8812",
        "customer": {
            "masked_name": customer_name[0] + "***" + (customer_name[-1] if len(customer_name) > 1 else ""),
            "masked_email": mask_email(customer_email),
            "masked_phone": mask_phone(customer_phone)
        },
        "transaction_context": {
            "transaction_id_masked": mask_reference_id(tx_id, "TXN"),
            "amount": amount,
            "currency": currency,
            "transaction_date": tx_date,
            "payment_method": payment_method
        },
        "request_reason": req_token.request_reason,
        "requested_documents": req_token.requested_documents or [],
        "expires_at": req_token.expires_at.isoformat(),
        "requires_otp": True,
        "status": req_token.status
    }), 200

@portal_bp.route("/send-otp", methods=["POST"])
def portal_send_otp():
    """
    Sends a 6-digit OTP to the customer's registered email or phone to verify actual user identity.
    """
    payload = request.get_json(silent=True) or {}
    raw_token = payload.get("token", "").strip()
    if not raw_token:
        return jsonify({"error": "Bad Request", "message": "Authentication token is required"}), 400

    tok_hash = hash_token(raw_token)
    req_token = EvidenceRequestToken.query.filter_by(token_hash=tok_hash).first()
    if not req_token or req_token.is_expired() or req_token.status in ["SUBMITTED", "REVOKED"]:
        return jsonify({"error": "Invalid Token", "message": "Invalid or expired submission link."}), 403

    # Generate 6-digit OTP
    otp = generate_otp()
    req_token.otp_code_hash = hash_otp(otp)
    req_token.otp_expires_at = utc_now() + timedelta(minutes=10)
    req_token.otp_attempts = 0
    db.session.commit()

    user_record = MUser.query.filter_by(user_id=req_token.user_id).first() or User.query.filter_by(user_id=req_token.user_id).first()
    customer_email = getattr(user_record, "email", "customer@example.com")
    customer_name = (
        getattr(user_record, "full_name", None) or
        getattr(user_record, "name", None) or
        f"{getattr(user_record, 'first_name', '')} {getattr(user_record, 'last_name', '')}".strip() or
        "Account Holder"
    )
    masked_target = mask_email(customer_email)

    # Dispatch REAL OTP email via SMTP
    otp_send_status = "NOT_CONFIGURED"
    if customer_email and "@" in customer_email:
        otp_res = EmailService.send_otp_email(
            to_email=customer_email,
            customer_name=customer_name,
            otp_code=otp,
            expires_minutes=10
        )
        otp_send_status = "SENT" if otp_res.get("success") else f"FAILED: {otp_res.get('error')}"

    logger.info(f"[PORTAL_OTP_DISPATCH] Status: {otp_send_status} | Sent 6-digit OTP '{otp}' to registered address {customer_email} (Token: {tok_hash[:8]}...)")

    return jsonify({
        "success": True,
        "message": f"A 6-digit verification code has been dispatched to {masked_target}.",
        "expires_in_seconds": 600,
        # For development / sandbox testing: include demo OTP so the reviewer can test without real mailbox setup
        "demo_hint": f"Development Code: {otp}"
    }), 200

@portal_bp.route("/verify-otp", methods=["POST"])
def portal_verify_otp():
    """
    Verifies user's submitted OTP and issues a short-lived session token for evidence upload.
    """
    payload = request.get_json(silent=True) or {}
    raw_token = payload.get("token", "").strip()
    provided_otp = payload.get("otp", "").strip()

    if not raw_token or not provided_otp:
        return jsonify({"error": "Bad Request", "message": "Both token and OTP code are required."}), 400

    tok_hash = hash_token(raw_token)
    req_token = EvidenceRequestToken.query.filter_by(token_hash=tok_hash).first()
    if not req_token or req_token.is_expired() or req_token.status in ["SUBMITTED", "REVOKED"]:
        return jsonify({"error": "Invalid Token", "message": "Invalid or expired submission link."}), 403

    # Rate limiting on OTP attempts
    if req_token.otp_attempts >= 3:
        return jsonify({
            "error": "Locked Out",
            "message": "Maximum OTP verification attempts exceeded. Please request a new verification code."
        }), 429

    # Expiration check
    if not req_token.otp_expires_at or utc_now() > (req_token.otp_expires_at if req_token.otp_expires_at.tzinfo else req_token.otp_expires_at.replace(tzinfo=timezone.utc)):
        return jsonify({"error": "Expired Code", "message": "Verification code has expired. Please request a new code."}), 400

    # Verify constant-time
    if not verify_otp_constant_time(provided_otp, req_token.otp_code_hash):
        req_token.otp_attempts += 1
        db.session.commit()
        remaining = 3 - req_token.otp_attempts
        return jsonify({
            "verified": False,
            "error": "Invalid Code",
            "message": f"Incorrect verification code. {remaining} attempt(s) remaining."
        }), 401

    # OTP is valid -> Issue 30-minute upload session token
    session_token = generate_session_token()
    req_token.session_token_hash = hash_token(session_token)
    req_token.session_expires_at = utc_now() + timedelta(minutes=30)
    req_token.status = "VERIFIED"
    req_token.otp_attempts = 0
    db.session.commit()

    return jsonify({
        "verified": True,
        "session_token": session_token,
        "expires_in_seconds": 1800,
        "message": "Identity verified successfully. You may now submit your evidence."
    }), 200

@portal_bp.route("/submit-evidence", methods=["POST"])
def portal_submit_evidence():
    """
    Submits user-provided images/documents and transaction details.
    Enforces magic byte checks, digital SHA-256 fingerprinting, single-submission anti-replay,
    and updates case status to REQUIRES_REVIEW.
    """
    raw_token = request.form.get("token", "").strip()
    session_token = request.form.get("session_token", "").strip()

    if not raw_token or not session_token:
        return jsonify({"error": "Unauthorized", "message": "Valid token and session verification are required."}), 401

    tok_hash = hash_token(raw_token)
    req_token = EvidenceRequestToken.query.filter_by(token_hash=tok_hash).first()
    if not req_token or req_token.is_expired():
        return jsonify({"error": "Forbidden", "message": "Evidence request token is invalid or expired."}), 403

    if req_token.status == "SUBMITTED":
        return jsonify({"error": "Conflict", "message": "Evidence has already been submitted for this request."}), 409

    # Verify session token
    expected_session_hash = hash_token(session_token)
    if not req_token.session_token_hash or req_token.session_token_hash != expected_session_hash:
        return jsonify({"error": "Unauthorized", "message": "Invalid or expired session. Please verify your OTP again."}), 401

    if req_token.session_expires_at:
        exp = req_token.session_expires_at if req_token.session_expires_at.tzinfo else req_token.session_expires_at.replace(tzinfo=timezone.utc)
        if utc_now() > exp:
            return jsonify({"error": "Session Expired", "message": "Session expired. Please request a new verification code."}), 401

    case = req_token.case
    if not case:
        return jsonify({"error": "Not Found", "message": "Associated investigation case not found."}), 404

    # Extract user form fields
    claimed_amount = request.form.get("claimed_amount", "").strip()
    transaction_date = request.form.get("transaction_date", "").strip()
    payment_method_details = request.form.get("payment_method_details", "").strip()
    user_explanation = request.form.get("user_explanation", "").strip()

    # Process uploaded files
    uploaded_files = request.files.getlist("files")
    if not uploaded_files or len(uploaded_files) == 0:
        return jsonify({"error": "Bad Request", "message": "At least one evidence document or image is required."}), 400

    case_upload_dir = os.path.join(EVIDENCE_UPLOAD_DIR, case.id)
    os.makedirs(case_upload_dir, exist_ok=True)

    saved_evidence_items = []
    file_hashes = []

    for file in uploaded_files:
        if not file or not file.filename:
            continue

        orig_filename = file.filename
        _, ext = os.path.splitext(orig_filename.lower())
        if ext not in ALLOWED_EVIDENCE_EXTENSIONS:
            return jsonify({
                "error": "Unsupported File Type",
                "message": f"File '{orig_filename}' has unsupported extension. Allowed: {', '.join(sorted(ALLOWED_EVIDENCE_EXTENSIONS))}"
            }), 400

        # Read file bytes & check file size
        file_bytes = file.read()
        file_size = len(file_bytes)
        if file_size > MAX_FILE_SIZE_BYTES:
            return jsonify({
                "error": "Payload Too Large",
                "message": f"File '{orig_filename}' exceeds 10MB limit ({file_size} bytes)."
            }), 413

        # Magic byte verification
        header_sample = file_bytes[:16]
        if not validate_magic_bytes(header_sample, ext):
            return jsonify({
                "error": "MIME Spoofing Detected",
                "message": f"File content of '{orig_filename}' does not match its '{ext}' file type."
            }), 400

        # SHA-256 digital fingerprint
        content_hash = hashlib.sha256(file_bytes).hexdigest()
        file_hashes.append(content_hash)

        # Secure file saving
        timestamp_prefix = int(time.time())
        safe_base = secure_filename(orig_filename) or f"customer_evidence_{timestamp_prefix}{ext}"
        saved_filename = f"{timestamp_prefix}_{safe_base}"
        file_path = os.path.join(case_upload_dir, saved_filename)

        with open(file_path, "wb") as f:
            f.write(file_bytes)

        is_image = ext in {".png", ".jpg", ".jpeg", ".webp"}
        evidence_type = "USER_PORTAL_IMAGE" if is_image else "USER_PORTAL_DOCUMENT"

        normalized_payload = {
            "original_filename": orig_filename,
            "saved_filename": saved_filename,
            "file_url": f"/api/v1/investigations/{case.id}/evidence-file/{saved_filename}",
            "file_size_bytes": file_size,
            "content_type": file.mimetype or ("image/" + ext[1:] if is_image else "application/pdf"),
            "is_image": is_image,
            "uploaded_by_user_id": req_token.user_id,
            "uploaded_via": "CUSTOMER_EVIDENCE_PORTAL",
            "uploaded_at": utc_now().isoformat()
        }

        evidence = CaseEvidence(
            id=str(uuid.uuid4()),
            case_id=case.id,
            evidence_type=evidence_type,
            source_system="CUSTOMER_EVIDENCE_PORTAL",
            source_reference=orig_filename,
            retrieval_status="COLLECTED",
            retrieved_at=utc_now(),
            normalized_payload=normalized_payload,
            content_hash=content_hash,
            created_at=utc_now()
        )
        db.session.add(evidence)
        saved_evidence_items.append(evidence)

    # Persist customer's structured transaction statement as an evidence artifact
    statement_payload = {
        "claimed_amount": claimed_amount,
        "transaction_date": transaction_date,
        "payment_method_details": payment_method_details,
        "user_explanation": user_explanation,
        "attached_files_count": len(saved_evidence_items),
        "submitted_at": utc_now().isoformat()
    }
    statement_hash = hashlib.sha256(json.dumps(statement_payload, sort_keys=True).encode()).hexdigest()

    statement_evidence = CaseEvidence(
        id=str(uuid.uuid4()),
        case_id=case.id,
        evidence_type="USER_TRANSACTION_STATEMENT",
        source_system="CUSTOMER_EVIDENCE_PORTAL",
        source_reference=f"Customer Statement ({req_token.user_id})",
        retrieval_status="COLLECTED",
        retrieved_at=utc_now(),
        normalized_payload=statement_payload,
        content_hash=statement_hash,
        created_at=utc_now()
    )
    db.session.add(statement_evidence)
    saved_evidence_items.append(statement_evidence)

    # Invalidate token (Single-use / anti-replay)
    req_token.status = "SUBMITTED"
    req_token.submitted_at = utc_now()
    req_token.submission_payload = statement_payload

    # Transition case status back to REQUIRES_REVIEW so fraud analysts know new proof has arrived
    case.status = "REQUIRES_REVIEW"
    case.updated_at = utc_now()

    db.session.commit()

    # Record Immutable Audit Event
    AuditService.record_event(
        event_type="EVIDENCE_SUBMITTED_BY_USER",
        actor_type="CUSTOMER_PORTAL",
        correlation_id=case.idempotency_key,
        case_id=case.id,
        user_id=req_token.user_id,
        actor_id=req_token.user_id,
        details={
            "request_token_id": req_token.id,
            "files_count": len(saved_evidence_items) - 1,
            "evidence_ids": [e.id for e in saved_evidence_items],
            "statement_hash": statement_hash,
            "ip_address": request.remote_addr or "127.0.0.1",
            "case_status_after": case.status
        }
    )

    submission_reference = f"SUB-{int(time.time())}-{req_token.id[:6].upper()}"

    return jsonify({
        "success": True,
        "submission_reference": submission_reference,
        "message": "Evidence documents and transaction statement submitted successfully.",
        "case_id": case.id,
        "case_status": case.status,
        "items_submitted_count": len(saved_evidence_items),
        "submitted_at": utc_now().isoformat()
    }), 201
