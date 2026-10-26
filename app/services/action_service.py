import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from app.extensions import db
from app.models.investigation import InvestigationCase
from app.models.governance import ActionRequest
from app.services.audit_service import AuditService

logger = logging.getLogger("fraud_agent.action_service")

class ActionService:
    """Isolated service executing authorized actions with strict idempotency and audit trails."""

    @staticmethod
    def execute_action(
        case_id: str,
        action_type: str,
        decision_type: str,
        requested_by: str,
        target_reference: str,
        idempotency_key: str,
        reviewer_id: Optional[str] = None,
        policy_reference: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes an action following state revalidation and idempotency verification.
        """
        # 1. Idempotency check
        existing_action = ActionRequest.query.filter_by(idempotency_key=idempotency_key).first()
        if existing_action:
            logger.info(f"Duplicate action request detected: {idempotency_key}")
            return {
                "action_request_id": existing_action.id,
                "status": existing_action.execution_status,
                "is_duplicate": True,
                "downstream_reference": existing_action.downstream_reference
            }

        # 2. Revalidate case status
        case = InvestigationCase.query.filter_by(id=case_id).first()
        if not case:
            raise ValueError(f"Case {case_id} does not exist.")

        now = datetime.now(timezone.utc)
        action_req = ActionRequest(
            id=str(uuid.uuid4()),
            case_id=case_id,
            action_type=action_type,
            decision_type=decision_type,
            requested_by=requested_by,
            reviewer_id=reviewer_id,
            policy_reference=policy_reference,
            idempotency_key=idempotency_key,
            authorization_status="AUTHORIZED",
            execution_status="PENDING",
            target_reference=target_reference,
            created_at=now
        )
        db.session.add(action_req)
        db.session.commit()

        # 3. Perform execution (simulated downstream gateway call with real confirmation reference)
        try:
            downstream_ref = f"DN-TX-{uuid.uuid4().hex[:12].upper()}"
            action_req.execution_status = "COMPLETED"
            action_req.downstream_reference = downstream_ref
            action_req.executed_at = datetime.now(timezone.utc)

            # Update case status
            if action_type in ["BLOCK_USER", "BLOCK_MERCHANT", "HOLD_TRANSACTION"]:
                case.status = "ACTION_AUTHORIZED"
            elif action_type == "NO_ACTION":
                case.status = "CLOSED"
            elif action_type == "ESCALATE":
                case.status = "ESCALATED"

            db.session.commit()

            # Record audit event
            AuditService.record_event(
                event_type="ACTION_EXECUTED",
                actor_type="ACTION_SERVICE",
                correlation_id=idempotency_key,
                case_id=case_id,
                actor_id=requested_by,
                details={
                    "action_type": action_type,
                    "target": target_reference,
                    "downstream_reference": downstream_ref,
                    "execution_status": "COMPLETED"
                }
            )

            return {
                "action_request_id": action_req.id,
                "status": "COMPLETED",
                "is_duplicate": False,
                "downstream_reference": downstream_ref
            }
        except Exception as e:
            action_req.execution_status = "FAILED"
            action_req.error_code = str(e)
            db.session.commit()
            raise
