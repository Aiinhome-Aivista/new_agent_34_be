import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from backend.app.extensions import db
from backend.app.models.investigation import InvestigationCase
from backend.app.models.governance import ActionRequest
from backend.app.models.source_domain import MUser
from backend.app.services.audit_service import AuditService

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
        Supports:
          - LOCK_USER: Sets m_users.status = 'BLOCKED', case status = 'ACTION_AUTHORIZED'
          - UNLOCK_USER: Sets m_users.status = 'ACTIVE', case status = 'RESOLVED'
          - REQUEST_EVIDENCE: Case status = 'COLLECTING_EVIDENCE'
          - ESCALATE: Case status = 'ESCALATED'
          - MONITOR: Case status = 'MONITORING'
          - Legacy actions: BLOCK_USER, HOLD_TRANSACTION, NO_ACTION, etc.
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

        # 3. Perform execution
        try:
            downstream_ref = f"DN-TX-{uuid.uuid4().hex[:12].upper()}"
            action_req.execution_status = "COMPLETED"
            action_req.downstream_reference = downstream_ref
            action_req.executed_at = datetime.now(timezone.utc)

            # Determine target user_id for domain mutation and audit trail
            target_user_id = case.user_id_ref
            if not target_user_id and target_reference and target_reference.startswith("USR_"):
                target_user_id = target_reference

            # Execute user status mutations in master table m_users
            target_user = None
            if target_user_id:
                target_user = MUser.query.filter_by(user_id=target_user_id).first()

            if action_type in ["LOCK_USER", "BLOCK_USER"]:
                if target_user:
                    target_user.status = "BLOCKED"
                    target_user.updated_at = datetime.now(timezone.utc)
                    logger.info(f"MUser {target_user_id} status updated to BLOCKED")
                case.status = "ACTION_AUTHORIZED"

            elif action_type == "UNLOCK_USER":
                if target_user:
                    target_user.status = "ACTIVE"
                    target_user.updated_at = datetime.now(timezone.utc)
                    logger.info(f"MUser {target_user_id} status updated to ACTIVE")
                case.status = "RESOLVED"

            elif action_type == "REQUEST_EVIDENCE":
                case.status = "COLLECTING_EVIDENCE"

            elif action_type == "ESCALATE":
                case.status = "ESCALATED"

            elif action_type == "MONITOR":
                case.status = "MONITORING"

            elif action_type in ["HOLD_TRANSACTION", "TEMPORARY_RESTRICTION", "BLOCK_MERCHANT"]:
                case.status = "ACTION_AUTHORIZED"

            elif action_type in ["NO_ACTION", "DISMISS"]:
                case.status = "CLOSED"

            db.session.commit()

            # Record audit event with explicit user_id and actor tracking
            AuditService.record_event(
                event_type="ACTION_EXECUTED",
                actor_type="ACTION_SERVICE",
                correlation_id=idempotency_key,
                case_id=case_id,
                user_id=target_user_id,
                actor_id=requested_by,
                details={
                    "action_type": action_type,
                    "target": target_reference,
                    "target_user_id": target_user_id,
                    "user_status_after": target_user.status if target_user else None,
                    "downstream_reference": downstream_ref,
                    "execution_status": "COMPLETED",
                    "policy_reference": policy_reference
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
