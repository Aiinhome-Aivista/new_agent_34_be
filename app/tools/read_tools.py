from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from app.repositories.user_repo import UserRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.chargeback_repo import ChargebackRepository
from app.models.transactional import User

class EvidenceCollectorTools:
    """
    Read-only tools strictly separated from Action Services.
    Bounded, parameterized, and compliant with Section 11 & 13.
    """
    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)
        self.order_repo = OrderRepository(db)
        self.payment_repo = PaymentRepository(db)
        self.chargeback_repo = ChargebackRepository(db)

    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        data = self.user_repo.get_user_profile(user_id)
        if not data:
            return {"status": "NOT_FOUND", "user_id": user_id, "message": "User not found in transactional database"}
        return {"status": "SUCCESS", "user": data}

    def get_order_details(self, order_id: str) -> Dict[str, Any]:
        data = self.order_repo.get_order_details(order_id)
        if not data:
            return {"status": "NOT_FOUND", "order_id": order_id}
        return {"status": "SUCCESS", "order": data}

    def get_payment_details(self, payment_id: str) -> Dict[str, Any]:
        data = self.payment_repo.get_payment_details(payment_id)
        if not data:
            return {"status": "NOT_FOUND", "payment_id": payment_id}
        return {"status": "SUCCESS", "payment": data}

    def get_user_payment_history(self, user_id: str) -> Dict[str, Any]:
        payments = self.payment_repo.get_payments_for_user(user_id, limit=20)
        stats = self.payment_repo.get_user_payment_stats(user_id)
        return {
            "status": "SUCCESS",
            "user_id": user_id,
            "stats": stats,
            "recent_payments": payments
        }

    def get_chargeback_records(self, payment_id: Optional[str] = None, order_id: Optional[str] = None) -> Dict[str, Any]:
        results = []
        if payment_id:
            results.extend(self.chargeback_repo.get_chargebacks_for_payment(payment_id))
        elif order_id:
            results.extend(self.chargeback_repo.get_chargebacks_for_order(order_id))
        
        has_fraud = any(cb.get("fraud_indicator") for cb in results)
        return {
            "status": "SUCCESS",
            "count": len(results),
            "has_fraud_indicator": has_fraud,
            "chargebacks": results
        }

    def get_merchant_profile(self, merchant_id: str) -> Dict[str, Any]:
        """
        In strict accordance with Section 6 of Blueprint:
        Do not invent foreign keys or assume merchant_id == user_id.
        Explicitly flag if the relationship is unverified.
        """
        # Search if a merchant record exists in users with external_user_id or user_id
        user_merchant = (
            self.db.query(User)
            .filter(
                (User.user_type == "MERCHANT") &
                ((User.user_id == merchant_id) | (User.external_user_id == merchant_id))
            )
            .first()
        )

        if user_merchant:
            return {
                "status": "VERIFIED_MAPPING",
                "merchant_id": merchant_id,
                "merchant_user_id": user_merchant.user_id,
                "business_name": f"{user_merchant.first_name} {user_merchant.last_name}",
                "status": user_merchant.status,
                "risk_level": user_merchant.risk_level,
                "risk_score": float(user_merchant.risk_score or 0)
            }
        
        # Explicit gap recording per HLA
        return {
            "status": "UNRESOLVED_MERCHANT_RELATIONSHIP",
            "merchant_id": merchant_id,
            "gap_recorded": True,
            "message": f"Merchant identifier '{merchant_id}' is not mapped to internal users schema. Retaining identifier without speculative join."
        }
