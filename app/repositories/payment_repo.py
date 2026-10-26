from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.transactional import Payment

class PaymentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_payment_details(self, payment_id: str) -> Optional[Dict[str, Any]]:
        payment = self.db.query(Payment).filter(Payment.payment_id == payment_id).first()
        if not payment:
            return None
        return {
            "payment_id": payment.payment_id,
            "order_id": payment.order_id,
            "user_id": payment.user_id,
            "merchant_id": payment.merchant_id,
            "gateway_transaction_id": payment.gateway_transaction_id,
            "payment_method": payment.payment_method,
            "payment_status": payment.payment_status,
            "amount": float(payment.amount),
            "currency": payment.currency,
            "processor_name": payment.processor_name,
            "failure_code": payment.failure_code,
            "failure_reason": payment.failure_reason,
            "ip_address": payment.ip_address,
            "device_id": payment.device_id,
            "initiated_at": payment.initiated_at.isoformat() if payment.initiated_at else None,
            "authorized_at": payment.authorized_at.isoformat() if payment.authorized_at else None,
            "captured_at": payment.captured_at.isoformat() if payment.captured_at else None,
        }

    def get_payments_for_user(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        payments = (
            self.db.query(Payment)
            .filter(Payment.user_id == user_id)
            .order_by(Payment.initiated_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "payment_id": p.payment_id,
                "order_id": p.order_id,
                "merchant_id": p.merchant_id,
                "amount": float(p.amount),
                "currency": p.currency,
                "payment_method": p.payment_method,
                "payment_status": p.payment_status,
                "device_id": p.device_id,
                "ip_address": p.ip_address,
                "initiated_at": p.initiated_at.isoformat() if p.initiated_at else None,
            }
            for p in payments
        ]

    def get_user_payment_stats(self, user_id: str) -> Dict[str, Any]:
        result = (
            self.db.query(
                func.count(Payment.payment_id),
                func.avg(Payment.amount),
                func.max(Payment.amount),
                func.min(Payment.amount)
            )
            .filter(Payment.user_id == user_id, Payment.payment_status == "SUCCESS")
            .first()
        )
        count = result[0] or 0
        avg_amount = float(result[1]) if result[1] else 0.0
        max_amount = float(result[2]) if result[2] else 0.0
        min_amount = float(result[3]) if result[3] else 0.0

        return {
            "successful_payment_count": count,
            "historical_avg_amount": round(avg_amount, 2),
            "historical_max_amount": round(max_amount, 2),
            "historical_min_amount": round(min_amount, 2),
        }
