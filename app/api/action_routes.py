from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.platform import ActionExecution, ActionRequest
from app.schemas.actions import ActionDispatchPayload, ActionExecutionResponse
from app.schemas.rbac import UserProfile
from app.auth.dependencies import get_current_user, require_permission
from app.actions.executor import ActionExecutionService

router = APIRouter(prefix="/actions", tags=["Action Service"])

@router.post("/dispatch")
def dispatch_action(
    payload: ActionDispatchPayload,
    current_user: UserProfile = Depends(require_permission("action.request")),
    db: Session = Depends(get_db)
):
    service = ActionExecutionService(db)
    result = service.dispatch_action(
        case_id=payload.case_id,
        action_type=payload.action_type,
        target_entity_type=payload.target_entity_type,
        target_entity_id=payload.target_entity_id,
        idempotency_key=payload.idempotency_key,
        requested_by=current_user.username,
        decision_id=payload.decision_id,
        approval_token=payload.approval_token,
        parameters=payload.parameters
    )
    return result

@router.get("/history/{case_id}")
def get_action_history(
    case_id: str,
    current_user: UserProfile = Depends(require_permission("audit.view")),
    db: Session = Depends(get_db)
):
    requests = db.query(ActionRequest).filter(ActionRequest.case_id == case_id).all()
    history = []
    for req in requests:
        executions = db.query(ActionExecution).filter(ActionExecution.request_id == req.request_id).all()
        history.append({
            "request_id": req.request_id,
            "action_type": req.action_type,
            "target_entity": f"{req.target_entity_type}:{req.target_entity_id}",
            "status": req.request_status,
            "requested_by": req.requested_by,
            "created_at": req.created_at.isoformat(),
            "executions": [
                {
                    "execution_id": ex.execution_id,
                    "status": ex.execution_status,
                    "details": ex.execution_details,
                    "executed_at": ex.executed_at.isoformat()
                }
                for ex in executions
            ]
        })
    return history
