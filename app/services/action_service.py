import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from app.extensions import db
from app.models.investigation import InvestigationCase
from app.models.governance import ActionRequest
from app.models.source_domain import MUser, User
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
        policy_reference: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes an action following state revalidation and idempotency verification.
        Mutates master tables (e.g. m_users.status for LOCK_USER/UNLOCK_USER)
        and logs audit trail with user_id.
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

        # 3. Perform execution and master table mutations
        try:
            downstream_ref = f"DN-TX-{uuid.uuid4().hex[:12].upper()}"
            action_req.execution_status = "COMPLETED"
            action_req.downstream_reference = downstream_ref
            action_req.executed_at = datetime.now(timezone.utc)

            previous_user_status = None
            new_user_status = None

            # Handle Decision Gateway Actions
            if action_type in ["LOCK_USER", "BLOCK_USER"]:
                case.status = "ACTION_AUTHORIZED"
                if case.user_id_ref:
                    m_user = MUser.query.filter_by(user_id=case.user_id_ref).first()
                    if m_user:
                        previous_user_status = m_user.status
                        m_user.status = "BLOCKED"
                        new_user_status = "BLOCKED"
                    leg_user = User.query.filter_by(user_id=case.user_id_ref).first()
                    if leg_user:
                        leg_user.status = "BLOCKED"

            elif action_type in ["UNLOCK_USER", "UNBLOCK_USER"]:
                case.status = "RESOLVED"
                if case.user_id_ref:
                    m_user = MUser.query.filter_by(user_id=case.user_id_ref).first()
                    if m_user:
                        previous_user_status = m_user.status
                        m_user.status = "ACTIVE"
                        new_user_status = "ACTIVE"
                    leg_user = User.query.filter_by(user_id=case.user_id_ref).first()
                    if leg_user:
                        leg_user.status = "ACTIVE"

            elif action_type == "REQUEST_EVIDENCE":
                case.status = "EVIDENCE_REQUESTED"

            elif action_type == "ESCALATE":
                case.priority = "CRITICAL"
                case.status = "ESCALATED"

            elif action_type == "MONITOR":
                case.status = "MONITORING"
                if case.user_id_ref:
                    m_user = MUser.query.filter_by(user_id=case.user_id_ref).first()
                    if m_user and m_user.status != "BLOCKED":
                        previous_user_status = m_user.status
                        m_user.status = "MONITORING"
                        new_user_status = "MONITORING"

            elif action_type in ["BLOCK_MERCHANT", "HOLD_TRANSACTION"]:
                case.status = "ACTION_AUTHORIZED"

            elif action_type == "NO_ACTION":
                case.status = "CLOSED"

            db.session.commit()

            # Record tamper-evident audit event with user_id
            AuditService.record_event(
                event_type=action_type,
                actor_type="ACTION_SERVICE",
                correlation_id=idempotency_key,
                case_id=case_id,
                user_id=case.user_id_ref,
                actor_id=requested_by,
                details={
                    "action_type": action_type,
                    "target": target_reference,
                    "user_id": case.user_id_ref,
                    "previous_status": previous_user_status,
                    "new_status": new_user_status,
                    "notes": notes,
                    "downstream_reference": downstream_ref,
                    "execution_status": "COMPLETED",
                    "policy_reference": policy_reference
                }
            )

            return {
                "action_request_id": action_req.id,
                "status": "COMPLETED",
                "is_duplicate": False,
                "downstream_reference": downstream_ref,
                "case_status": case.status,
                "user_status": new_user_status
            }
        except Exception as e:
            action_req.execution_status = "FAILED"
            action_req.error_code = str(e)
            db.session.commit()
            raise
