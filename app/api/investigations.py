import os
import uuid
import time
import hashlib
import logging
from datetime import datetime, timezone
from werkzeug.utils import secure_filename
from flask import Blueprint, request, jsonify, send_from_directory
from pydantic import ValidationError

from backend.app.schemas.trigger import TriggerRequest, TriggerResponse
from backend.app.schemas.decision import ReviewDecisionRequest
from backend.app.services.case_service import CaseService
from backend.app.services.audit_service import AuditService
from backend.app.services.action_service import ActionService
from backend.app.models import InvestigationCase, ReviewDecision, AppUser
from backend.app.models.investigation import CaseEvidence
from backend.app.agent.graph import execute_case_investigation
from backend.app.extensions import db

logger = logging.getLogger("fraud_agent.api.investigations")
investigations_bp = Blueprint("investigations", __name__)

EVIDENCE_UPLOAD_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "evidence_uploads")
)
ALLOWED_EVIDENCE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".docx", ".txt"}

def utc_now():
    return datetime.now(timezone.utc)

@investigations_bp.route("", methods=["POST"])
def create_investigation():
    """Receives and validates external fraud signals; enforces idempotency."""
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Bad Request", "message": "Missing JSON request body"}), 400

    try:
        trigger_req = TriggerRequest(**payload)
    except ValidationError as e:
        return jsonify({"error": "Validation Error", "details": e.errors()}), 422

    try:
        case, is_duplicate = CaseService.process_trigger(trigger_req)
        
        # If not duplicate, trigger investigation workflow
        if not is_duplicate:
            try:
                execute_case_investigation(case.id)
            except Exception as e:
                logger.error(f"Investigation execution encountered error: {e}")

        response_data = TriggerResponse(
            case_id=case.id,
            status=case.status,
            priority=case.priority,
            idempotency_key=case.idempotency_key,
            is_duplicate=is_duplicate,
            message="Investigation completed and routed." if not is_duplicate else "Duplicate signal received; returning existing case.",
            created_at=case.created_at.isoformat()
        )
        return jsonify(response_data.model_dump()), 201 if not is_duplicate else 200

    except ValueError as ve:
        return jsonify({"error": "Conflict", "message": str(ve)}), 409
    except Exception as e:
        logger.error(f"Error creating investigation: {e}")
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500

@investigations_bp.route("", methods=["GET"])
def list_investigations():
    """Returns paginated investigations with filtering."""
    status = request.args.get("status")
    priority = request.args.get("priority")
    search = request.args.get("search")
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))

    data = CaseService.list_cases(status=status, priority=priority, search=search, page=page, page_size=page_size)
    return jsonify(data), 200

@investigations_bp.route("/<case_id>", methods=["GET"])
def get_investigation(case_id):
    """Returns detailed investigation case information."""
    data = CaseService.get_case(case_id)
    if not data:
        return jsonify({"error": "Not Found", "message": f"Case {case_id} was not found"}), 404
    return jsonify(data), 200

@investigations_bp.route("/<case_id>/evidence", methods=["GET"])
def get_evidence(case_id):
    """Returns evidence inventory for the case."""
    case = InvestigationCase.query.filter_by(id=case_id).first()
    if not case:
        return jsonify({"error": "Not Found", "message": "Case not found"}), 404
    return jsonify({
        "case_id": case_id,
        "items": [e.to_dict() for e in case.evidence_items]
    }), 200

@investigations_bp.route("/<case_id>/recommendation", methods=["GET"])
def get_recommendation(case_id):
    """Returns latest structured recommendation for the case."""
    case = InvestigationCase.query.filter_by(id=case_id).first()
    if not case:
        return jsonify({"error": "Not Found", "message": "Case not found"}), 404
    
    rec = case.recommendations[-1] if case.recommendations else None
    if not rec:
        return jsonify({"case_id": case_id, "recommendation": None}), 200
    return jsonify(rec.to_dict()), 200

@investigations_bp.route("/<case_id>/decisions", methods=["POST"])
def submit_decision(case_id):
    """
    Submits an analyst reviewer decision with exact audit tracking.
    Actions supported:
      - LOCK_USER: Locks user profile in m_users and authorizes restriction
      - UNLOCK_USER: Re-activates user in m_users and resolves case
      - REQUEST_EVIDENCE: Keeps case open for document/image submission
      - ESCALATE: Escalates to senior fraud committee
      - MONITOR: Places customer on active monitoring watchlist
      - APPROVE / REJECT: Legacy compatibility
    """
    case = InvestigationCase.query.filter_by(id=case_id).first()
    if not case:
        return jsonify({"error": "Not Found", "message": "Case not found"}), 404

    payload = request.get_json(silent=True) or {}
    try:
        dec_req = ReviewDecisionRequest(**payload)
    except ValidationError as e:
        return jsonify({"error": "Validation Error", "details": e.errors()}), 422

    # Resolve reviewer from AppUser table
    reviewer = None
    if dec_req.reviewer_id:
        reviewer = AppUser.query.filter(
            (AppUser.id == dec_req.reviewer_id) |
            (AppUser.identity_subject == dec_req.reviewer_id) |
            (AppUser.email == dec_req.reviewer_id)
        ).first()

    if not reviewer:
        reviewer = (
            AppUser.query.filter(AppUser.role.ilike("%INVESTIGATOR%"), AppUser.status == "ACTIVE").first()
            or AppUser.query.filter_by(status="ACTIVE").first()
            or AppUser.query.first()
        )

    if not reviewer:
        return jsonify({
            "error": "Reviewer Not Found",
            "message": "No registered system reviewer account found in app_users database table."
        }), 400

    resolved_reviewer_id = reviewer.id
    reviewer_label = reviewer.display_name or reviewer.identity_subject or dec_req.reviewer_id
    latest_rec = case.recommendations[-1] if case.recommendations else None

    # Persist Review Decision
    decision = ReviewDecision(
        id=str(uuid.uuid4()),
        case_id=case_id,
        recommendation_id=latest_rec.id if latest_rec else None,
        reviewer_id=resolved_reviewer_id,
        decision=dec_req.decision,
        reason=dec_req.reason,
        policy_reference=dec_req.policy_reference
    )
    db.session.add(decision)

    target_ref = case.user_id_ref or case.transaction_id or case.merchant_id_ref or case_id
    decision_type_label = "HUMAN_APPROVED"

    # Action routing & execution
    if dec_req.decision in ["LOCK_USER", "BLOCK_USER"]:
        case.status = "ACTION_AUTHORIZED"
        ActionService.execute_action(
            case_id=case_id,
            action_type="LOCK_USER",
            decision_type=decision_type_label,
            requested_by=reviewer_label,
            target_reference=target_ref,
            idempotency_key=f"act_{case.idempotency_key}_LOCK_{int(time.time())}",
            reviewer_id=resolved_reviewer_id,
            policy_reference=dec_req.policy_reference
        )

    elif dec_req.decision == "UNLOCK_USER":
        case.status = "RESOLVED"
        ActionService.execute_action(
            case_id=case_id,
            action_type="UNLOCK_USER",
            decision_type=decision_type_label,
            requested_by=reviewer_label,
            target_reference=target_ref,
            idempotency_key=f"act_{case.idempotency_key}_UNLOCK_{int(time.time())}",
            reviewer_id=resolved_reviewer_id,
            policy_reference=dec_req.policy_reference
        )

    elif dec_req.decision == "REQUEST_EVIDENCE":
        case.status = "COLLECTING_EVIDENCE"

    elif dec_req.decision == "ESCALATE":
        case.status = "ESCALATED"

    elif dec_req.decision == "MONITOR":
        case.status = "MONITORING"

    elif dec_req.decision == "APPROVE":
        case.status = "ACTION_AUTHORIZED"
        if latest_rec:
            ActionService.execute_action(
                case_id=case_id,
                action_type=latest_rec.recommendation_type,
                decision_type=decision_type_label,
                requested_by=reviewer_label,
                target_reference=target_ref,
                idempotency_key=f"act_{case.idempotency_key}_{latest_rec.recommendation_type}_{int(time.time())}",
                reviewer_id=resolved_reviewer_id,
                policy_reference=dec_req.policy_reference
            )

    elif dec_req.decision in ["REJECT", "CLOSE"]:
        case.status = "CLOSED"

    db.session.commit()

    # Record Immutable Audit Event with user_id & exact reviewer inputs
    AuditService.record_event(
        event_type="DECISION_SUBMITTED",
        actor_type="HUMAN_REVIEWER",
        correlation_id=case.idempotency_key,
        case_id=case_id,
        user_id=case.user_id_ref,
        actor_id=reviewer.identity_subject or resolved_reviewer_id,
        details={
            "decision": dec_req.decision,
            "reason": dec_req.reason,
            "policy_reference": dec_req.policy_reference,
            "reviewer_name": reviewer.display_name,
            "reviewer_role": reviewer.role,
            "reviewer_email": reviewer.email,
            "target_user_id": case.user_id_ref,
            "target_transaction_id": case.transaction_id,
            "case_status_after": case.status
        }
    )

    return jsonify({
        "message": f"Decision '{dec_req.decision}' recorded successfully.",
        "case_id": case_id,
        "status": case.status
    }), 200

# --------------------------------------------------------------------------
# Evidence Upload & File Serving Endpoints
# --------------------------------------------------------------------------

@investigations_bp.route("/<case_id>/evidence-upload", methods=["POST"])
def upload_evidence_file(case_id):
    """
    Uploads supporting evidence documents (e.g. KYC IDs, utility bills, chargeback proofs,
    screenshots, transaction slips) for an investigation case.
    Saves file to disk, persists provenance in CaseEvidence, and records AuditEvent with user_id.
    """
    case = InvestigationCase.query.filter_by(id=case_id).first()
    if not case:
        return jsonify({"error": "Not Found", "message": "Case not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "Bad Request", "message": "No file part in upload request"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "Bad Request", "message": "No file selected"}), 400

    orig_filename = file.filename
    _, ext = os.path.splitext(orig_filename.lower())
    if ext not in ALLOWED_EVIDENCE_EXTENSIONS:
        return jsonify({
            "error": "Unsupported File Type",
            "message": f"Extension '{ext}' not permitted. Allowed: {', '.join(sorted(ALLOWED_EVIDENCE_EXTENSIONS))}"
        }), 400

    notes = request.form.get("notes", "").strip()
    reviewer_id = request.form.get("reviewer_id") or "ANALYST_UPLOAD"

    # Ensure storage directory
    case_upload_dir = os.path.join(EVIDENCE_UPLOAD_DIR, case_id)
    os.makedirs(case_upload_dir, exist_ok=True)

    timestamp_prefix = int(time.time())
    safe_base = secure_filename(orig_filename) or f"evidence_{timestamp_prefix}{ext}"
    saved_filename = f"{timestamp_prefix}_{safe_base}"
    file_path = os.path.join(case_upload_dir, saved_filename)

    file_bytes = file.read()
    file_size = len(file_bytes)
    content_hash = hashlib.sha256(file_bytes).hexdigest()

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    is_image = ext in {".png", ".jpg", ".jpeg", ".webp"}
    evidence_type = "USER_UPLOADED_IMAGE" if is_image else "USER_UPLOADED_DOCUMENT"

    normalized_payload = {
        "original_filename": orig_filename,
        "saved_filename": saved_filename,
        "file_url": f"/api/v1/investigations/{case_id}/evidence-file/{saved_filename}",
        "file_size_bytes": file_size,
        "content_type": file.mimetype or ("image/" + ext[1:] if is_image else "application/pdf"),
        "is_image": is_image,
        "notes": notes,
        "uploaded_by": reviewer_id,
        "uploaded_at": utc_now().isoformat()
    }

    evidence = CaseEvidence(
        id=str(uuid.uuid4()),
        case_id=case_id,
        evidence_type=evidence_type,
        source_system="ANALYST_PORTAL_UPLOAD",
        source_reference=orig_filename,
        retrieval_status="COLLECTED",
        retrieved_at=utc_now(),
        normalized_payload=normalized_payload,
        content_hash=content_hash,
        created_at=utc_now()
    )
    db.session.add(evidence)
    db.session.commit()

    # Record audit event
    AuditService.record_event(
        event_type="EVIDENCE_UPLOADED",
        actor_type="HUMAN_REVIEWER",
        correlation_id=case.idempotency_key,
        case_id=case_id,
        user_id=case.user_id_ref,
        actor_id=reviewer_id,
        details={
            "evidence_id": evidence.id,
            "filename": orig_filename,
            "saved_filename": saved_filename,
            "file_size": file_size,
            "notes": notes,
            "user_id": case.user_id_ref
        }
    )

    return jsonify({
        "message": "Evidence file uploaded and recorded successfully.",
        "case_id": case_id,
        "evidence": evidence.to_dict()
    }), 201

@investigations_bp.route("/<case_id>/evidence-file/<filename>", methods=["GET"])
def serve_evidence_file(case_id, filename):
    """Serves uploaded evidence images and documents for in-browser review."""
    safe_name = secure_filename(filename)
    case_upload_dir = os.path.join(EVIDENCE_UPLOAD_DIR, case_id)
    if not os.path.exists(os.path.join(case_upload_dir, safe_name)):
        return jsonify({"error": "Not Found", "message": "Requested evidence file does not exist."}), 404
    return send_from_directory(case_upload_dir, safe_name)
