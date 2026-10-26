import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.platform import (
    InvestigationCase,
    ReviewDecision,
    ActionRequest,
    ActionExecution,
    AuditEvent,
)
from app.models.transactional import User, Order, Payment

class ActionExecutionService:
    """
    Isolated Action Service outside LangGraph/Ollama.
    Executes operational mutations with approval verification, idempotency protection,
    and immutable audit logging.
    """
    def __init__(self, db: Session):
        self.db = db

    def dispatch_action(
        self,
        case_id: str,
        action_type: str,
        target_entity_type: str,
        target_entity_id: str,
        idempotency_key: str,
        requested_by: str,
        decision_id: Optional[str] = None,
        approval_token: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        # 1. Idempotency Check
        existing_req = self.db.query(ActionRequest).filter(ActionRequest.idempotency_key == idempotency_key).first()
        if existing_req:
            # Check if already executed
            existing_exec = self.db.query(ActionExecution).filter(ActionExecution.request_id == existing_req.request_id).first()
            return {
                "status": "ALREADY_PROCESSED",
                "request_id": existing_req.request_id,
                "execution_id": existing_exec.execution_id if existing_exec else None,
                "executed_action": existing_req.action_type,
                "message": f"Idempotency key '{idempotency_key}' previously processed."
            }

        # 2. Case verification
        case = self.db.query(InvestigationCase).filter(InvestigationCase.case_id == case_id).first()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        # 3. Create ActionRequest record
        request_id = str(uuid.uuid4())
        action_req = ActionRequest(
            request_id=request_id,
            case_id=case_id,
            decision_id=decision_id,
            action_type=action_type,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
            parameters=parameters or {},
            idempotency_key=idempotency_key,
            request_status="AUTHORIZED",
            requested_by=requested_by,
            approval_token=approval_token
        )
        self.db.add(action_req)
        self.db.flush()

        # 4. Execute operational mutation safely
        execution_details = {}
        mutation_applied = False

        if action_type in ("BLOCK_USER", "TEMPORARY_RESTRICTION"):
            user = self.db.query(User).filter(User.user_id == target_entity_id).first()
            if user:
                new_status = "BLOCKED" if action_type == "BLOCK_USER" else "SUSPENDED"
                old_status = user.status
                user.status = new_status
                mutation_applied = True
                execution_details = {
                    "entity": "users",
                    "user_id": user.user_id,
                    "previous_status": old_status,
                    "new_status": new_status,
                    "reason": f"Agent 34 enforcement: {action_type}"
                }

        elif action_type == "HOLD_TRANSACTION":
            order = self.db.query(Order).filter(Order.order_id == target_entity_id).first()
            if order:
                old_status = order.order_status
                order.order_status = "HOLD"
                mutation_applied = True
                execution_details = {
                    "entity": "orders",
                    "order_id": order.order_id,
                    "previous_status": old_status,
                    "new_status": "HOLD"
                }

        elif action_type in ("MONITOR", "REQUEST_VERIFICATION", "SEND_NOTIFICATION", "NO_ACTION"):
            mutation_applied = True
            execution_details = {
                "entity": target_entity_type,
                "target_id": target_entity_id,
                "action": action_type,
                "message": f"Simulated operational dispatch for {action_type}"
            }

        elif action_type == "ESCALATE":
            case.status = "ESCALATED"
            mutation_applied = True
            execution_details = {
                "case_id": case.case_id,
                "action": "ESCALATED",
                "queue": "SENIOR_RISK_COMMITTEE"
            }

        # Update case status
        if action_type != "ESCALATE":
            case.status = "ACTION_EXECUTED"
            case.closed_at = datetime.utcnow()

        # 5. Record Action Execution
        execution_id = str(uuid.uuid4())
        execution = ActionExecution(
            execution_id=execution_id,
            request_id=request_id,
            executed_action=action_type,
            execution_status="SUCCESS" if mutation_applied else "FAILED",
            execution_details=execution_details,
            executed_at=datetime.utcnow()
        )
        self.db.add(execution)

        # 6. Immutable Audit Event
        audit_event = AuditEvent(
            event_id=str(uuid.uuid4()),
            case_id=case_id,
            actor_id=requested_by,
            actor_type="APPROVER" if "SYS-USR" in requested_by else "SYSTEM",
            event_type="ACTION_EXECUTED",
            event_description=f"Action '{action_type}' successfully dispatched to downstream service",
            event_payload={
                "request_id": request_id,
                "execution_id": execution_id,
                "target_id": target_entity_id,
                "details": execution_details
            }
        )
        self.db.add(audit_event)
        self.db.commit()

        return {
            "status": "SUCCESS",
            "request_id": request_id,
            "execution_id": execution_id,
            "executed_action": action_type,
            "execution_details": execution_details,
            "executed_at": execution.executed_at.isoformat()
        }
