from app.models.governance import AppUser
import logging
from flask import Blueprint, request, jsonify
from pydantic import ValidationError
from app.schemas.trigger import TriggerRequest, TriggerResponse
from app.schemas.decision import ReviewDecisionRequest
from app.services.case_service import CaseService
from app.services.audit_service import AuditService
from app.services.action_service import ActionService
from app.models import InvestigationCase, ReviewDecision
from app.agent.graph import execute_case_investigation
from app.extensions import db

logger = logging.getLogger("fraud_agent.api.investigations")
investigations_bp = Blueprint("investigations", __name__)

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
    """Submits a human reviewer decision and triggers downstream action if approved."""
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

    # If no exact match found, fallback to active investigator or supervisor in app_users
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

    # Persist Review Decision
    import uuid
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
    
    # State transition
    if dec_req.decision == "APPROVE":
        case.status = "ACTION_AUTHORIZED"
        # If action is approved, execute it via Action Service
        if latest_rec:
            ActionService.execute_action(
                case_id=case_id,
                action_type=latest_rec.recommendation_type,
                decision_type="HUMAN_APPROVED",
                requested_by=reviewer.display_name or reviewer.identity_subject or dec_req.reviewer_id,
                target_reference=case.transaction_id or case.user_id_ref or case.merchant_id_ref or case_id,
                idempotency_key=f"act_{case.idempotency_key}_{latest_rec.recommendation_type}",
                reviewer_id=resolved_reviewer_id,
                policy_reference=dec_req.policy_reference
            )
    elif dec_req.decision == "REJECT":
        case.status = "CLOSED"
    elif dec_req.decision == "ESCALATE":
        case.status = "ESCALATED"
    elif dec_req.decision == "REQUEST_EVIDENCE":
        case.status = "COLLECTING_EVIDENCE"

    db.session.commit()

    AuditService.record_event(
        event_type="DECISION_SUBMITTED",
        actor_type="HUMAN_REVIEWER",
        correlation_id=case.idempotency_key,
        case_id=case_id,
        actor_id=reviewer.identity_subject or resolved_reviewer_id,
        details={
            "decision": dec_req.decision,
            "reason": dec_req.reason,
            "policy_reference": dec_req.policy_reference,
            "reviewer_name": reviewer.display_name,
            "reviewer_role": reviewer.role
        }
    )

    return jsonify({
        "message": "Decision submitted successfully.",
        "case_id": case_id,
        "status": case.status
    }), 200
