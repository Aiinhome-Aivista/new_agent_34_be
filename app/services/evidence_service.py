import uuid
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.extensions import db
from app.models.investigation import CaseEvidence
from app.models.source_domain import User, Order, Payment, Chargeback

logger = logging.getLogger("fraud_agent.evidence_service")

class EvidenceService:
    """Read-only evidence retrieval and normalization service."""

    @staticmethod
    def collect_evidence_for_case(case_id: str, transaction_id: Optional[str] = None, user_id: Optional[str] = None, merchant_id: Optional[str] = None) -> List[CaseEvidence]:
        """
        Dynamically dispatches authorized read-only evidence across registered active microservices.
        Respects Admin On/Off toggles, prints live execution to terminal,
        and saves standardized provenance records.
        """
        from app.services.microservice_dispatcher import MicroserviceDispatcher
        evidence_items, _ = MicroserviceDispatcher.dispatch_case_evidence(
            case_id=case_id,
            user_id=user_id,
            transaction_id=transaction_id,
            merchant_id=merchant_id
        )
        return evidence_items
