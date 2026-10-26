from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from app.models.transactional import Order

class OrderRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_order_details(self, order_id: str) -> Optional[Dict[str, Any]]:
        order = self.db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            return None
        return {
            "order_id": order.order_id,
            "merchant_order_id": order.merchant_order_id,
            "user_id": order.user_id,
            "merchant_id": order.merchant_id,
            "amount": float(order.amount),
            "currency": order.currency,
            "order_status": order.order_status,
            "description": order.description,
            "ip_address": order.ip_address,
            "device_id": order.device_id,
            "billing_country": order.billing_country,
            "shipping_country": order.shipping_country,
            "created_at": order.created_at.isoformat() if order.created_at else None,
        }

    def get_orders_for_user(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        orders = (
            self.db.query(Order)
            .filter(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "order_id": o.order_id,
                "merchant_id": o.merchant_id,
                "amount": float(o.amount),
                "currency": o.currency,
                "order_status": o.order_status,
                "description": o.description,
                "device_id": o.device_id,
                "ip_address": o.ip_address,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orders
        ]

    def get_orders_for_merchant(self, merchant_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        orders = (
            self.db.query(Order)
            .filter(Order.merchant_id == merchant_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "order_id": o.order_id,
                "merchant_order_id": o.merchant_order_id,
                "user_id": o.user_id,
                "amount": float(o.amount),
                "currency": o.currency,
                "order_status": o.order_status,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orders
        ]
