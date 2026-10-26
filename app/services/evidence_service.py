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
        Gathers authorized read-only evidence across source tables.
        Normalizes outputs and persists provenance records.
        """
        collected = []
        now = datetime.now(timezone.utc)

        # 1. Transaction & Payment Evidence
        if transaction_id:
            payment = Payment.query.filter_by(payment_id=transaction_id).first()
            if not payment:
                payment = Payment.query.filter_by(gateway_transaction_id=transaction_id).first()

            if payment:
                payload = payment.to_dict()
                evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="PAYMENT_RECORD",
                    source_system="CORE_PAYMENT_DB",
                    source_reference=payment.payment_id,
                    retrieval_status="COLLECTED",
                    retrieved_at=now,
                    normalized_payload=payload,
                    content_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
                )
                db.session.add(evidence)
                collected.append(evidence)

                # Link user and merchant if not provided
                if not user_id:
                    user_id = payment.user_id
                if not merchant_id:
                    merchant_id = payment.merchant_id

                # Also fetch corresponding order if present
                if payment.order_id:
                    order = Order.query.filter_by(order_id=payment.order_id).first()
                    if order:
                        order_payload = order.to_dict()
                        order_evidence = CaseEvidence(
                            id=str(uuid.uuid4()),
                            case_id=case_id,
                            evidence_type="ORDER_DETAILS",
                            source_system="ORDER_MANAGEMENT_DB",
                            source_reference=order.order_id,
                            retrieval_status="COLLECTED",
                            retrieved_at=now,
                            normalized_payload=order_payload,
                            content_hash=hashlib.sha256(json.dumps(order_payload, sort_keys=True).encode()).hexdigest()
                        )
                        db.session.add(order_evidence)
                        collected.append(order_evidence)
            else:
                # Explicitly record missing evidence
                missing_evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="PAYMENT_RECORD",
                    source_system="CORE_PAYMENT_DB",
                    source_reference=transaction_id,
                    retrieval_status="MISSING",
                    retrieved_at=now,
                    normalized_payload={"reason": f"Payment {transaction_id} not found in source records."}
                )
                db.session.add(missing_evidence)
                collected.append(missing_evidence)

        # 2. Customer Profile Evidence
        if user_id:
            user = User.query.filter_by(user_id=user_id).first()
            if user:
                user_payload = user.to_dict()
                user_evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="USER_PROFILE",
                    source_system="CUSTOMER_IDENTITY_DB",
                    source_reference=user.user_id,
                    retrieval_status="COLLECTED",
                    retrieved_at=now,
                    normalized_payload=user_payload,
                    content_hash=hashlib.sha256(json.dumps(user_payload, sort_keys=True).encode()).hexdigest()
                )
                db.session.add(user_evidence)
                collected.append(user_evidence)
            else:
                user_evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="USER_PROFILE",
                    source_system="CUSTOMER_IDENTITY_DB",
                    source_reference=user_id,
                    retrieval_status="MISSING",
                    retrieved_at=now,
                    normalized_payload={"reason": f"User {user_id} profile record was not located."}
                )
                db.session.add(user_evidence)
                collected.append(user_evidence)

        # 3. Merchant Profile Evidence
        if merchant_id:
            merchant = User.query.filter_by(user_id=merchant_id, user_type="MERCHANT").first()
            if merchant:
                merchant_payload = merchant.to_dict()
                merchant_evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="MERCHANT_PROFILE",
                    source_system="MERCHANT_ONBOARDING_DB",
                    source_reference=merchant.user_id,
                    retrieval_status="COLLECTED",
                    retrieved_at=now,
                    normalized_payload=merchant_payload,
                    content_hash=hashlib.sha256(json.dumps(merchant_payload, sort_keys=True).encode()).hexdigest()
                )
                db.session.add(merchant_evidence)
                collected.append(merchant_evidence)

        # 4. Chargeback History Evidence
        if user_id or merchant_id:
            query = Chargeback.query.join(Payment, Chargeback.payment_id == Payment.payment_id)
            if merchant_id:
                query = query.filter(Payment.merchant_id == merchant_id)
            elif user_id:
                query = query.filter(Payment.user_id == user_id)
            
            disputes = query.limit(10).all()
            if disputes:
                dispute_list = [d.to_dict() for d in disputes]
                dispute_evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="CHARGEBACK_HISTORY",
                    source_system="DISPUTE_MANAGEMENT_DB",
                    source_reference=f"disputes_count_{len(disputes)}",
                    retrieval_status="COLLECTED",
                    retrieved_at=now,
                    normalized_payload={"disputes": dispute_list, "count": len(dispute_list)},
                    content_hash=hashlib.sha256(json.dumps(dispute_list, sort_keys=True).encode()).hexdigest()
                )
                db.session.add(dispute_evidence)
                collected.append(dispute_evidence)

        db.session.commit()
        return collected
