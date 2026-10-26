import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.platform import InvestigationCase, ReviewDecision, AuditEvent, InvestigationRecommendation
from app.schemas.decisions import DecisionSubmitRequest, ReviewDecisionResponse
from app.schemas.rbac import UserProfile
from app.auth.dependencies import get_current_user, require_permission
from app.actions.executor import ActionExecutionService

router = APIRouter(prefix="/cases", tags=["Review Decisions"])

@router.post("/{case_id}/decide", response_model=ReviewDecisionResponse)
def submit_decision(
    case_id: str,
    payload: DecisionSubmitRequest,
    current_user: UserProfile = Depends(require_permission("recommendation.review")),
    db: Session = Depends(get_db)
):
    case = db.query(InvestigationCase).filter(InvestigationCase.case_id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Separation of Duties check per Blueprint Section 7 & 14
    if payload.decision_type == "HUMAN_APPROVED":
        if "recommendation.approve" not in current_user.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Approval requires 'recommendation.approve' permission (Approver or Admin role)"
            )
        
        # Prevent self-approval if assigned investigator
        if case.assigned_to == current_user.user_id and current_user.role == "INVESTIGATOR":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Separation of Duties violation: An investigator cannot approve their own case."
            )

    decision_id = str(uuid.uuid4())
    decision = ReviewDecision(
        decision_id=decision_id,
        case_id=case_id,
        reviewer_id=current_user.user_id,
        decision_type=payload.decision_type,
        selected_action=payload.selected_action,
        decision_rationale=payload.decision_rationale,
        conditions=payload.conditions,
        policy_reference=payload.policy_reference,
        created_at=datetime.utcnow()
    )
    db.add(decision)

    # Audit decision event
    audit = AuditEvent(
        event_id=str(uuid.uuid4()),
        case_id=case_id,
        actor_id=current_user.username,
        actor_type="APPROVER" if current_user.role in ("APPROVER", "ADMIN") else "ANALYST",
        event_type="DECISION_RECORDED",
        event_description=f"Decision {payload.decision_type} recorded: {payload.selected_action}",
        event_payload={
            "decision_id": decision_id,
            "rationale": payload.decision_rationale,
            "conditions": payload.conditions
        }
    )
    db.add(audit)
    db.commit()

    # If action was approved, dispatch to Action Service
    if payload.decision_type in ("HUMAN_APPROVED", "POLICY_AUTO_APPROVED"):
        rec = db.query(InvestigationRecommendation).filter(InvestigationRecommendation.case_id == case_id).first()
        target_type = rec.suggested_target_type if rec else "USER"
        target_id = rec.suggested_target_id if rec else (case.user_id or case_id)

        idempotency_key = f"{case_id}-{payload.selected_action}-{decision_id[:8]}"
        action_svc = ActionExecutionService(db)
        action_svc.dispatch_action(
            case_id=case_id,
            action_type=payload.selected_action,
            target_entity_type=target_type,
            target_entity_id=target_id,
            idempotency_key=idempotency_key,
            requested_by=current_user.username,
            decision_id=decision_id,
            approval_token=str(uuid.uuid4()),
            parameters=payload.conditions
        )

    res = ReviewDecisionResponse.model_validate(decision)
    res.reviewer_name = current_user.full_name
    return res
