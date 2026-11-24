import uuid
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.extensions import db
from app.models.investigation import CaseEvidence
from app.services.microservice_client import MicroserviceClient

logger = logging.getLogger("fraud_agent.evidence_service")


class EvidenceService:
    """
    API-first evidence retrieval and normalization service.
    Queries registered microservice APIs when LIVE_NETWORK mode is enabled,
    with automatic, zero-downtime fallback to local database queries.
    """

    @staticmethod
    def collect_evidence_for_case(case_id: str, transaction_id: Optional[str] = None, user_id: Optional[str] = None, merchant_id: Optional[str] = None) -> List[CaseEvidence]:
        """
        Gathers evidence across microservice APIs and source tables.
        Normalizes outputs, generates SHA-256 provenance hashes, and persists records.
        """
        collected = []
        now = datetime.now(timezone.utc)

        # 1. Transaction & Payment Evidence
        if transaction_id:
            payload = MicroserviceClient.get_payment(transaction_id)
            if payload:
                source_sys = payload.get("_connector") or payload.get("service_origin") or "PAYMENT_GATEWAY_SERVICE"
                clean_payload = {k: v for k, v in payload.items() if not k.startswith("_")}
                payment_ref = clean_payload.get("payment_id") or transaction_id

                evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="PAYMENT_RECORD",
                    source_system=source_sys,
                    source_reference=payment_ref,
                    retrieval_status="COLLECTED",
                    retrieved_at=now,
                    normalized_payload=clean_payload,
                    content_hash=hashlib.sha256(json.dumps(clean_payload, sort_keys=True).encode()).hexdigest()
                )
                db.session.add(evidence)
                collected.append(evidence)

                # Link user and merchant if not provided
                if not user_id:
                    user_id = clean_payload.get("user_id")
                if not merchant_id:
                    merchant_id = clean_payload.get("merchant_id")

                # Also fetch corresponding order if present
                order_id = clean_payload.get("order_id")
                if order_id:
                    order_payload = MicroserviceClient.get_order(order_id)
                    if order_payload:
                        order_source = order_payload.get("_connector") or order_payload.get("service_origin") or "ORDER_FULFILLMENT_SERVICE"
                        clean_order = {k: v for k, v in order_payload.items() if not k.startswith("_")}
                        order_evidence = CaseEvidence(
                            id=str(uuid.uuid4()),
                            case_id=case_id,
                            evidence_type="ORDER_DETAILS",
                            source_system=order_source,
                            source_reference=clean_order.get("order_id") or order_id,
                            retrieval_status="COLLECTED",
                            retrieved_at=now,
                            normalized_payload=clean_order,
                            content_hash=hashlib.sha256(json.dumps(clean_order, sort_keys=True).encode()).hexdigest()
                        )
                        db.session.add(order_evidence)
                        collected.append(order_evidence)
            else:
                missing_evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="PAYMENT_RECORD",
                    source_system="PAYMENT_GATEWAY_SERVICE",
                    source_reference=transaction_id,
                    retrieval_status="MISSING",
                    retrieved_at=now,
                    normalized_payload={"reason": f"Payment {transaction_id} not located via payment service."}
                )
                db.session.add(missing_evidence)
                collected.append(missing_evidence)

        # 2. Customer Profile Evidence
        if user_id:
            user_payload = MicroserviceClient.get_user(user_id)
            if user_payload:
                user_source = user_payload.get("_connector") or user_payload.get("service_origin") or "USER_PROFILE_SERVICE"
                clean_user = {k: v for k, v in user_payload.items() if not k.startswith("_")}
                user_evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="USER_PROFILE",
                    source_system=user_source,
                    source_reference=clean_user.get("user_id") or user_id,
                    retrieval_status="COLLECTED",
                    retrieved_at=now,
                    normalized_payload=clean_user,
                    content_hash=hashlib.sha256(json.dumps(clean_user, sort_keys=True).encode()).hexdigest()
                )
                db.session.add(user_evidence)
                collected.append(user_evidence)
            else:
                user_evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="USER_PROFILE",
                    source_system="USER_PROFILE_SERVICE",
                    source_reference=user_id,
                    retrieval_status="MISSING",
                    retrieved_at=now,
                    normalized_payload={"reason": f"User {user_id} profile was not located via user service."}
                )
                db.session.add(user_evidence)
                collected.append(user_evidence)

        # 3. Merchant Profile Evidence
        if merchant_id:
            merchant_payload = MicroserviceClient.get_user(merchant_id)
            if merchant_payload:
                merch_source = merchant_payload.get("_connector") or merchant_payload.get("service_origin") or "USER_PROFILE_SERVICE"
                clean_merch = {k: v for k, v in merchant_payload.items() if not k.startswith("_")}
                merchant_evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="MERCHANT_PROFILE",
                    source_system=merch_source,
                    source_reference=clean_merch.get("user_id") or merchant_id,
                    retrieval_status="COLLECTED",
                    retrieved_at=now,
                    normalized_payload=clean_merch,
                    content_hash=hashlib.sha256(json.dumps(clean_merch, sort_keys=True).encode()).hexdigest()
                )
                db.session.add(merchant_evidence)
                collected.append(merchant_evidence)

        # 4. Chargeback History Evidence
        target_dispute_user = user_id or merchant_id
        if target_dispute_user:
            disputes = MicroserviceClient.get_disputes(target_dispute_user)
            if disputes:
                dispute_list = [{k: v for k, v in d.items() if not k.startswith("_")} for d in disputes]
                dispute_evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="CHARGEBACK_HISTORY",
                    source_system="DISPUTE_LEDGER_SERVICE",
                    source_reference=f"disputes_count_{len(dispute_list)}",
                    retrieval_status="COLLECTED",
                    retrieved_at=now,
                    normalized_payload={"disputes": dispute_list, "count": len(dispute_list)},
                    content_hash=hashlib.sha256(json.dumps(dispute_list, sort_keys=True).encode()).hexdigest()
                )
                db.session.add(dispute_evidence)
                collected.append(dispute_evidence)

        db.session.commit()
        return collected
