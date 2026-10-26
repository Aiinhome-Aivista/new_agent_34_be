import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, List
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.investigation import InvestigationCase, InvestigationRun
from app.schemas.trigger import TriggerRequest
from app.services.idempotency_service import IdempotencyService
from app.services.audit_service import AuditService

logger = logging.getLogger("fraud_agent.case_service")

class CaseService:
    """Manages the lifecycle and state transitions of fraud investigation cases."""

    @staticmethod
    def process_trigger(trigger: TriggerRequest) -> Tuple[InvestigationCase, bool]:
        """
        Processes an incoming trigger safely and idempotently.
        Returns (InvestigationCase, is_duplicate).
        """
        # 1. Check if case already exists in database with this idempotency key
        existing_case = InvestigationCase.query.filter_by(idempotency_key=trigger.idempotency_key).first()
        if existing_case:
            logger.info(f"Duplicate trigger detected for idempotency key: {trigger.idempotency_key}")
            return existing_case, True

        # 2. Acquire atomic distributed lock to prevent race conditions during concurrent incoming calls
        lock_acquired = IdempotencyService.acquire_lock(trigger.idempotency_key, ttl_seconds=30)
        if not lock_acquired:
            # Another concurrent thread is processing this identical trigger right now
            # Wait briefly and re-query
            import time
            time.sleep(0.2)
            case_check = InvestigationCase.query.filter_by(idempotency_key=trigger.idempotency_key).first()
            if case_check:
                return case_check, True
            raise ValueError("Conflict: Trigger with this idempotency key is actively being processed by another worker.")

        try:
            # 3. Create case record
            case = InvestigationCase(
                id=str(uuid.uuid4()),
                trigger_type=trigger.trigger_type,
                trigger_source=trigger.trigger_source,
                trigger_reason=trigger.trigger_reason,
                priority=trigger.priority,
                status="RECEIVED",
                transaction_id=trigger.transaction_id,
                user_id_ref=trigger.user_id,
                merchant_id_ref=trigger.merchant_id,
                created_by=trigger.trigger_source,
                idempotency_key=trigger.idempotency_key,
                started_at=datetime.now(timezone.utc)
            )
            db.session.add(case)
            db.session.commit()

            # Record audit event
            AuditService.record_event(
                event_type="TRIGGER_RECEIVED",
                actor_type="SYSTEM_TRIGGER",
                correlation_id=trigger.idempotency_key,
                case_id=case.id,
                details={
                    "trigger_type": trigger.trigger_type,
                    "priority": trigger.priority,
                    "target_transaction": trigger.transaction_id,
                    "target_user": trigger.user_id,
                    "target_merchant": trigger.merchant_id
                }
            )

            logger.info(f"Successfully created investigation case: {case.id}")
            return case, False

        except IntegrityError:
            db.session.rollback()
            existing_case = InvestigationCase.query.filter_by(idempotency_key=trigger.idempotency_key).first()
            if existing_case:
                return existing_case, True
            raise
        finally:
            IdempotencyService.release_lock(trigger.idempotency_key)

    @staticmethod
    def list_cases(
        status: Optional[str] = None,
        priority: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """Returns paginated cases filtered by status, priority, or search term."""
        query = InvestigationCase.query

        if status and status != "ALL":
            query = query.filter(InvestigationCase.status == status)
        if priority and priority != "ALL":
            query = query.filter(InvestigationCase.priority == priority)
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (InvestigationCase.id.like(search_pattern)) |
                (InvestigationCase.transaction_id.like(search_pattern)) |
                (InvestigationCase.user_id_ref.like(search_pattern)) |
                (InvestigationCase.merchant_id_ref.like(search_pattern)) |
                (InvestigationCase.trigger_reason.like(search_pattern))
            )

        total_count = query.count()
        cases = query.order_by(InvestigationCase.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

        return {
            "items": [case.to_dict() for case in cases],
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_count + page_size - 1) // page_size if total_count > 0 else 0
        }

    @staticmethod
    def get_case(case_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves full case details including evidence items, recommendations, and decisions."""
        case = InvestigationCase.query.filter_by(id=case_id).first()
        if not case:
            return None

        result = case.to_dict()
        result["evidence_items"] = [e.to_dict() for e in case.evidence_items]
        result["recommendations"] = [r.to_dict() for r in case.recommendations]
        result["decisions"] = [d.to_dict() for d in case.decisions]
        result["action_requests"] = [a.to_dict() for a in case.action_requests]
        return result
