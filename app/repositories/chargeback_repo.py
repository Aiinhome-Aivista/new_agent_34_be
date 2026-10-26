from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from app.models.transactional import Chargeback

class ChargebackRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_chargeback_details(self, chargeback_id: str) -> Optional[Dict[str, Any]]:
        cb = self.db.query(Chargeback).filter(Chargeback.chargeback_id == chargeback_id).first()
        if not cb:
            return None
        return {
            "chargeback_id": cb.chargeback_id,
            "payment_id": cb.payment_id,
            "order_id": cb.order_id,
            "amount": float(cb.amount),
            "currency": cb.currency,
            "reason_code": cb.reason_code,
            "reason_description": cb.reason_description,
            "chargeback_status": cb.chargeback_status,
            "fraud_indicator": cb.fraud_indicator,
            "received_at": cb.received_at.isoformat() if cb.received_at else None,
            "response_due_at": cb.response_due_at.isoformat() if cb.response_due_at else None,
            "resolved_at": cb.resolved_at.isoformat() if cb.resolved_at else None,
        }

    def get_chargebacks_for_payment(self, payment_id: str) -> List[Dict[str, Any]]:
        cbs = self.db.query(Chargeback).filter(Chargeback.payment_id == payment_id).all()
        return [
            {
                "chargeback_id": cb.chargeback_id,
                "amount": float(cb.amount),
                "reason_code": cb.reason_code,
                "reason_description": cb.reason_description,
                "chargeback_status": cb.chargeback_status,
                "fraud_indicator": cb.fraud_indicator,
                "received_at": cb.received_at.isoformat() if cb.received_at else None,
            }
            for cb in cbs
        ]

    def get_chargebacks_for_order(self, order_id: str) -> List[Dict[str, Any]]:
        cbs = self.db.query(Chargeback).filter(Chargeback.order_id == order_id).all()
        return [
            {
                "chargeback_id": cb.chargeback_id,
                "payment_id": cb.payment_id,
                "amount": float(cb.amount),
                "reason_code": cb.reason_code,
                "chargeback_status": cb.chargeback_status,
                "fraud_indicator": cb.fraud_indicator,
                "received_at": cb.received_at.isoformat() if cb.received_at else None,
            }
            for cb in cbs
        ]
