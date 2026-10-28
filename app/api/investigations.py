import os
import uuid
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from flask import Blueprint, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from pydantic import ValidationError

from app.models.governance import AppUser, ReviewDecision
from app.models.investigation import InvestigationCase, CaseEvidence
from app.models.source_domain import MUser, User
from app.schemas.trigger import TriggerRequest, TriggerResponse
from app.schemas.decision import ReviewDecisionRequest
from app.services.case_service import CaseService
from app.services.audit_service import AuditService
from app.services.action_service import ActionService
from app.agent.graph import execute_case_investigation
from app.extensions import db

logger = logging.getLogger("fraud_agent.api.investigations")
investigations_bp = Blueprint("investigations", __name__)

# Base directory for storing case evidence uploads
EVIDENCE_UPLOAD_BASE = Path(__file__).resolve().parent.parent.parent / "data" / "evidence_uploads"
ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "webp", "gif", "svg",
    "pdf", "txt", "json", "csv"
}

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


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
    Submits an analyst decision:
    - LOCK_USER: Updates m_users.status to BLOCKED, sets case.status to ACTION_AUTHORIZED
    - UNLOCK_USER: Updates m_users.status to ACTIVE, sets case.status to RESOLVED
    - REQUEST_EVIDENCE: Updates case.status to EVIDENCE_REQUESTED, activates upload portal
    - ESCALATE: Sets case.priority to CRITICAL, case.status to ESCALATED
    - MONITOR: Sets case.status to MONITORING, enrolls into watchlist
    - APPROVE / REJECT: Legacy compatibility
    All actions record user_id, actor_id, timestamp, and audit rationale into audit_events.
    """
    case = InvestigationCase.query.filter_by(id=case_id).first()
    if not case:
        return jsonify({"error": "Not Found", "message": "Case not found"}), 404

    payload = request.get_json(silent=True) or {}
    try:
        dec_req = ReviewDecisionRequest(**payload)
    except ValidationError as e:
        return jsonify({"error": "Validation Error", "details": e.errors()}), 422

    # Resolve reviewer user from AppUser table to enforce foreign key integrity
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
    latest_rec = case.recommendations[-1] if case.recommendations else None
    target_user_id = case.user_id_ref

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
    db.session.commit()

    action_code = dec_req.decision
    actor_name = reviewer.display_name or reviewer.identity_subject or dec_req.reviewer_id
    idempotency_key = f"act_{case.id}_{action_code}_{int(datetime.now(timezone.utc).timestamp())}"

    # Execute action through ActionService
    if action_code in ["LOCK_USER", "UNLOCK_USER", "REQUEST_EVIDENCE", "ESCALATE", "MONITOR"]:
        ActionService.execute_action(
            case_id=case_id,
            action_type=action_code,
            decision_type="HUMAN_APPROVED",
            requested_by=actor_name,
            target_reference=target_user_id or case.transaction_id or case_id,
            idempotency_key=idempotency_key,
            reviewer_id=resolved_reviewer_id,
            policy_reference=dec_req.policy_reference,
            notes=dec_req.reason
        )
    elif action_code == "APPROVE":
        case.status = "ACTION_AUTHORIZED"
        rec_type = latest_rec.recommendation_type if latest_rec else "HOLD_TRANSACTION"
        ActionService.execute_action(
            case_id=case_id,
            action_type=rec_type,
            decision_type="HUMAN_APPROVED",
            requested_by=actor_name,
            target_reference=case.transaction_id or target_user_id or case_id,
            idempotency_key=idempotency_key,
            reviewer_id=resolved_reviewer_id,
            policy_reference=dec_req.policy_reference,
            notes=dec_req.reason
        )
    elif action_code == "REJECT":
        case.status = "CLOSED"
        db.session.commit()

    # Tamper-evident Audit Event for the decision submission
    AuditService.record_event(
        event_type=f"DECISION_{action_code}",
        actor_type="HUMAN_REVIEWER",
        correlation_id=case.idempotency_key,
        case_id=case_id,
        user_id=target_user_id,
        actor_id=reviewer.identity_subject or resolved_reviewer_id,
        details={
            "action": action_code,
            "decision": dec_req.decision,
            "target_user_id": target_user_id,
            "reason": dec_req.reason,
            "policy_reference": dec_req.policy_reference,
            "reviewer_name": reviewer.display_name,
            "reviewer_role": reviewer.role,
            "case_status_after": case.status
        }
    )

    db.session.refresh(case)
    return jsonify({
        "message": f"Decision '{action_code}' committed successfully.",
        "case_id": case_id,
        "status": case.status,
        "priority": case.priority,
        "user_id": target_user_id
    }), 200


# ============================================================================
# Evidence Document Upload & Lightbox File Server
# ============================================================================

@investigations_bp.route("/<case_id>/evidence-upload", methods=["POST"])
def upload_evidence_document(case_id):
    """
    Accepts multipart document/image uploads for a case.
    Saves file to disk, links a CaseEvidence record, and logs an AuditEvent.
    """
    case = InvestigationCase.query.filter_by(id=case_id).first()
    if not case:
        return jsonify({"error": "Not Found", "message": f"Case {case_id} was not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "Bad Request", "message": "No 'file' field provided in multipart form data."}), 400

    uploaded_file = request.files["file"]
    if not uploaded_file.filename:
        return jsonify({"error": "Bad Request", "message": "No file selected."}), 400

    if not allowed_file(uploaded_file.filename):
        return jsonify({
            "error": "Unsupported Media Type",
            "message": f"File type not permitted. Allowed extensions: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        }), 415

    document_type = request.form.get("document_type", "IDENTITY_PROOF").strip().upper()
    notes = request.form.get("notes", "").strip()
    uploader_name = request.form.get("uploader_name", "Analyst / User Portal").strip()

    # Ensure case-specific directory exists
    case_upload_dir = EVIDENCE_UPLOAD_BASE / case_id
    case_upload_dir.mkdir(parents=True, exist_ok=True)

    original_filename = secure_filename(uploaded_file.filename)
    timestamp_prefix = int(datetime.now(timezone.utc).timestamp())
    stored_filename = f"{timestamp_prefix}_{original_filename}"
    file_path = case_upload_dir / stored_filename

    # Read and hash content
    content_bytes = uploaded_file.read()
    file_size_bytes = len(content_bytes)
    content_hash = hashlib.sha256(content_bytes).hexdigest()

    # Write file to disk
    with open(file_path, "wb") as f:
        f.write(content_bytes)

    # Determine preview URL
    preview_url = f"/api/v1/investigations/{case_id}/evidence-files/{stored_filename}"

    # Build evidence payload
    evidence_payload = {
        "filename": original_filename,
        "stored_filename": stored_filename,
        "file_path": preview_url,
        "file_size": file_size_bytes,
        "document_type": document_type,
        "notes": notes,
        "uploader": uploader_name,
        "content_hash": content_hash,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "is_image": original_filename.lower().rsplit(".", 1)[-1] in ["png", "jpg", "jpeg", "webp", "gif", "svg"]
    }

    # Create CaseEvidence record
    evidence_id = str(uuid.uuid4())
    evidence_item = CaseEvidence(
        id=evidence_id,
        case_id=case_id,
        evidence_type="USER_UPLOADED_DOCUMENT",
        source_system="ANALYST_EVIDENCE_PORTAL",
        source_reference=original_filename,
        retrieval_status="COLLECTED",
        retrieved_at=datetime.now(timezone.utc),
        normalized_payload=evidence_payload,
        content_hash=content_hash
    )
    db.session.add(evidence_item)

    # Update case status if it was in EVIDENCE_REQUESTED
    if case.status == "EVIDENCE_REQUESTED":
        case.status = "UNDER_INVESTIGATION"

    db.session.commit()

    # Record tamper-evident audit log with target user_id
    AuditService.record_event(
        event_type="DOCUMENT_UPLOADED",
        actor_type="HUMAN_REVIEWER",
        correlation_id=case.idempotency_key,
        case_id=case_id,
        user_id=case.user_id_ref,
        actor_id=uploader_name,
        details={
            "action": "DOCUMENT_UPLOADED",
            "evidence_id": evidence_id,
            "filename": original_filename,
            "document_type": document_type,
            "file_size_bytes": file_size_bytes,
            "content_hash": content_hash,
            "notes": notes,
            "uploader": uploader_name
        }
    )

    return jsonify({
        "status": "SUCCESS",
        "message": f"Evidence document '{original_filename}' uploaded successfully.",
        "evidence": evidence_item.to_dict()
    }), 201


@investigations_bp.route("/<case_id>/evidence-files/<filename>", methods=["GET"])
def serve_evidence_file(case_id, filename):
    """Serves uploaded evidence images/documents for in-app preview/lightbox."""
    case_upload_dir = EVIDENCE_UPLOAD_BASE / secure_filename(case_id)
    safe_filename = secure_filename(filename)
    return send_from_directory(str(case_upload_dir), safe_filename)


@investigations_bp.route("/<case_id>/evidence/<evidence_id>/verify", methods=["POST"])
def verify_evidence_item(case_id, evidence_id):
    """Analyst verification of an uploaded document (VERIFIED, FORGED, REJECTED)."""
    case = InvestigationCase.query.filter_by(id=case_id).first()
    if not case:
        return jsonify({"error": "Not Found", "message": "Case not found"}), 404

    evidence = CaseEvidence.query.filter_by(id=evidence_id, case_id=case_id).first()
    if not evidence:
        return jsonify({"error": "Not Found", "message": "Evidence item not found"}), 404

    payload = request.get_json(silent=True) or {}
    verification_status = payload.get("status", "VERIFIED").upper()  # 'VERIFIED', 'FORGED', 'REJECTED'
    analyst_notes = payload.get("notes", "").strip()
    analyst_name = payload.get("analyst_name", "Investigator").strip()

    # Update payload
    norm = dict(evidence.normalized_payload or {})
    norm["verification_status"] = verification_status
    norm["verification_notes"] = analyst_notes
    norm["verified_by"] = analyst_name
    norm["verified_at"] = datetime.now(timezone.utc).isoformat()
    evidence.normalized_payload = norm
    evidence.retrieval_status = "COLLECTED" if verification_status == "VERIFIED" else "FAILED"

    db.session.commit()

    AuditService.record_event(
        event_type="EVIDENCE_VERIFIED",
        actor_type="HUMAN_REVIEWER",
        correlation_id=case.idempotency_key,
        case_id=case_id,
        user_id=case.user_id_ref,
        actor_id=analyst_name,
        details={
            "action": "EVIDENCE_VERIFIED",
            "evidence_id": evidence_id,
            "verification_status": verification_status,
            "notes": analyst_notes,
            "analyst_name": analyst_name
        }
    )

    return jsonify({
        "status": "SUCCESS",
        "message": f"Document marked as {verification_status}.",
        "evidence": evidence.to_dict()
    }), 200
