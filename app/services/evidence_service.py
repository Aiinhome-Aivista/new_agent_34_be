import uuid
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.extensions import db
from app.models.investigation import CaseEvidence
from app.models.source_domain import (
    User, Order, Payment, Chargeback,
    MUser, MOrder, MPayment, MChargeback
)

logger = logging.getLogger("fraud_agent.evidence_service")

class EvidenceService:
    """Read-only evidence retrieval and normalization service querying master m_* domain tables."""

    @staticmethod
    def collect_evidence_for_case(case_id: str, transaction_id: Optional[str] = None, user_id: Optional[str] = None, merchant_id: Optional[str] = None) -> List[CaseEvidence]:
        """
        Gathers authorized read-only evidence across master m_* tables (with fallback).
        Normalizes outputs and persists provenance records.
        """
        collected = []
        now = datetime.now(timezone.utc)

        # 1. Transaction & Payment Evidence from m_payments (or payments fallback)
        payment_record = None
        if transaction_id:
            payment_record = MPayment.query.filter_by(payment_id=transaction_id).first()
            if not payment_record:
                payment_record = MPayment.query.filter_by(gateway_transaction_id=transaction_id).first()
            if not payment_record:
                payment_record = Payment.query.filter_by(payment_id=transaction_id).first()
            if not payment_record:
                payment_record = Payment.query.filter_by(gateway_transaction_id=transaction_id).first()

            if payment_record:
                payload = payment_record.to_dict()
                evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="PAYMENT_RECORD",
                    source_system="CORE_PAYMENT_DB (m_payments)",
                    source_reference=payment_record.payment_id,
                    retrieval_status="COLLECTED",
                    retrieved_at=now,
                    normalized_payload=payload,
                    content_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
                )
                db.session.add(evidence)
                collected.append(evidence)

                # Link user and merchant if not provided
                if not user_id:
                    user_id = payment_record.user_id
                if not merchant_id:
                    merchant_id = payment_record.merchant_id

                # Also fetch corresponding order if present from m_orders (or orders fallback)
                if payment_record.order_id:
                    order = MOrder.query.filter_by(order_id=payment_record.order_id).first()
                    if not order:
                        order = Order.query.filter_by(order_id=payment_record.order_id).first()
                    if order:
                        order_payload = order.to_dict()
                        order_evidence = CaseEvidence(
                            id=str(uuid.uuid4()),
                            case_id=case_id,
                            evidence_type="ORDER_DETAILS",
                            source_system="ORDER_MANAGEMENT_DB (m_orders)",
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
                    source_system="CORE_PAYMENT_DB (m_payments)",
                    source_reference=transaction_id,
                    retrieval_status="MISSING",
                    retrieved_at=now,
                    normalized_payload={"reason": f"Payment {transaction_id} not found in master records."}
                )
                db.session.add(missing_evidence)
                collected.append(missing_evidence)

        # 2. Customer Profile Evidence from m_users (or users fallback)
        if user_id:
            user = MUser.query.filter_by(user_id=user_id).first()
            if not user:
                user = User.query.filter_by(user_id=user_id).first()

            if user:
                user_payload = user.to_dict()
                user_evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="USER_PROFILE",
                    source_system="CUSTOMER_IDENTITY_DB (m_users)",
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
                    source_system="CUSTOMER_IDENTITY_DB (m_users)",
                    source_reference=user_id,
                    retrieval_status="MISSING",
                    retrieved_at=now,
                    normalized_payload={"reason": f"User {user_id} profile record was not located in master tables."}
                )
                db.session.add(user_evidence)
                collected.append(user_evidence)

        # 3. Merchant Profile Evidence
        if merchant_id:
            merchant = MUser.query.filter_by(user_id=merchant_id, user_type="MERCHANT").first()
            if not merchant:
                merchant = User.query.filter_by(user_id=merchant_id, user_type="MERCHANT").first()

            if merchant:
                merchant_payload = merchant.to_dict()
                merchant_evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="MERCHANT_PROFILE",
                    source_system="MERCHANT_ONBOARDING_DB (m_users)",
                    source_reference=merchant.user_id,
                    retrieval_status="COLLECTED",
                    retrieved_at=now,
                    normalized_payload=merchant_payload,
                    content_hash=hashlib.sha256(json.dumps(merchant_payload, sort_keys=True).encode()).hexdigest()
                )
                db.session.add(merchant_evidence)
                collected.append(merchant_evidence)

        # 4. Chargeback History Evidence from m_chargebacks / m_payments
        if user_id or merchant_id:
            disputes = []
            m_query = MChargeback.query.join(MPayment, MChargeback.payment_id == MPayment.payment_id)
            if merchant_id:
                m_query = m_query.filter(MPayment.merchant_id == merchant_id)
            elif user_id:
                m_query = m_query.filter(MPayment.user_id == user_id)
            m_disputes = m_query.limit(10).all()

            if m_disputes:
                disputes = [d.to_dict() for d in m_disputes]
            else:
                # Fallback to legacy chargebacks
                query = Chargeback.query.join(Payment, Chargeback.payment_id == Payment.payment_id)
                if merchant_id:
                    query = query.filter(Payment.merchant_id == merchant_id)
                elif user_id:
                    query = query.filter(Payment.user_id == user_id)
                leg_disputes = query.limit(10).all()
                if leg_disputes:
                    disputes = [d.to_dict() for d in leg_disputes]

            if disputes:
                dispute_evidence = CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type="CHARGEBACK_HISTORY",
                    source_system="DISPUTE_MANAGEMENT_DB (m_chargebacks)",
                    source_reference=f"disputes_count_{len(disputes)}",
                    retrieval_status="COLLECTED",
                    retrieved_at=now,
                    normalized_payload={"disputes": disputes, "count": len(disputes)},
                    content_hash=hashlib.sha256(json.dumps(disputes, sort_keys=True).encode()).hexdigest()
                )
                db.session.add(dispute_evidence)
                collected.append(dispute_evidence)

        db.session.commit()
        return collected
