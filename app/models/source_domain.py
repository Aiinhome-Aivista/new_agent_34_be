from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, DECIMAL, TIMESTAMP, Boolean, CHAR,
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from app.extensions import db

def utc_now():
    return datetime.now(timezone.utc)

class User(db.Model):
    """Source-domain user table (Customer, Merchant, Admin)."""
    __tablename__ = "users"

    user_id = Column(String(36), primary_key=True)
    external_user_id = Column(String(100), unique=True, nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    email = Column(String(255), unique=True, nullable=False)
    phone_number = Column(String(30), nullable=True)
    user_type = Column(String(30), nullable=False)  # 'CUSTOMER', 'MERCHANT', 'ADMIN'
    status = Column(String(30), nullable=False)     # 'ACTIVE', 'BLOCKED', 'SUSPENDED'
    country_code = Column(CHAR(2), nullable=True)
    kyc_status = Column(String(30), nullable=True)  # 'NOT_STARTED', 'PENDING', 'VERIFIED', 'REJECTED'
    risk_level = Column(String(20), nullable=True)  # 'LOW', 'MEDIUM', 'HIGH'
    risk_score = Column(DECIMAL(5, 2), nullable=True)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)
    last_login_at = Column(TIMESTAMP, nullable=True)

    __table_args__ = (
        Index("idx_users_type_status", "user_type", "status"),
        Index("idx_users_risk", "risk_level", "risk_score"),
    )

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "external_user_id": self.external_user_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "phone_number": self.phone_number,
            "user_type": self.user_type,
            "status": self.status,
            "country_code": self.country_code,
            "kyc_status": self.kyc_status,
            "risk_level": self.risk_level,
            "risk_score": float(self.risk_score) if self.risk_score is not None else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }

class Order(db.Model):
    """Source-domain order table."""
    __tablename__ = "orders"

    order_id = Column(String(36), primary_key=True)
    merchant_order_id = Column(String(100), nullable=True)
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=False)
    merchant_id = Column(String(36), ForeignKey("users.user_id"), nullable=False)
    amount = Column(DECIMAL(18, 2), nullable=False)
    currency = Column(CHAR(3), nullable=False)
    order_status = Column(String(30), nullable=False)  # 'CREATED', 'PENDING', 'PAID', 'FAILED', 'CANCELLED', 'REFUNDED'
    description = Column(String(500), nullable=True)
    ip_address = Column(String(45), nullable=True)
    device_id = Column(String(255), nullable=True)
    billing_country = Column(CHAR(2), nullable=True)
    shipping_country = Column(CHAR(2), nullable=True)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    customer = relationship("User", foreign_keys=[user_id])
    merchant = relationship("User", foreign_keys=[merchant_id])

    __table_args__ = (
        UniqueConstraint("merchant_id", "merchant_order_id", name="uq_merchant_order"),
        Index("idx_orders_user_created", "user_id", "created_at"),
        Index("idx_orders_merchant_created", "merchant_id", "created_at"),
        Index("idx_orders_status_created", "order_status", "created_at"),
    )

    def to_dict(self):
        return {
            "order_id": self.order_id,
            "merchant_order_id": self.merchant_order_id,
            "user_id": self.user_id,
            "merchant_id": self.merchant_id,
            "amount": float(self.amount),
            "currency": self.currency,
            "order_status": self.order_status,
            "description": self.description,
            "ip_address": self.ip_address,
            "device_id": self.device_id,
            "billing_country": self.billing_country,
            "shipping_country": self.shipping_country,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

class Payment(db.Model):
    """Source-domain payment table."""
    __tablename__ = "payments"

    payment_id = Column(String(36), primary_key=True)
    order_id = Column(String(36), ForeignKey("orders.order_id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=False)
    merchant_id = Column(String(36), ForeignKey("users.user_id"), nullable=False)
    gateway_transaction_id = Column(String(150), nullable=True)
    idempotency_key = Column(String(150), nullable=True)
    payment_method = Column(String(30), nullable=False)  # 'CARD', 'UPI', 'WALLET', 'NET_BANKING'
    payment_status = Column(String(30), nullable=False)  # 'INITIATED', 'PROCESSING', 'AUTHORIZED', 'CAPTURED', 'FAILED', etc.
    amount = Column(DECIMAL(18, 2), nullable=False)
    currency = Column(CHAR(3), nullable=False)
    processor_name = Column(String(100), nullable=True)
    failure_code = Column(String(100), nullable=True)
    failure_reason = Column(String(500), nullable=True)
    ip_address = Column(String(45), nullable=True)
    device_id = Column(String(255), nullable=True)
    initiated_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    authorized_at = Column(TIMESTAMP, nullable=True)
    captured_at = Column(TIMESTAMP, nullable=True)
    failed_at = Column(TIMESTAMP, nullable=True)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    order = relationship("Order", foreign_keys=[order_id])
    customer = relationship("User", foreign_keys=[user_id])
    merchant = relationship("User", foreign_keys=[merchant_id])

    __table_args__ = (
        UniqueConstraint("merchant_id", "idempotency_key", name="uq_merchant_idempotency"),
        Index("idx_payments_order", "order_id"),
        Index("idx_payments_user_initiated", "user_id", "initiated_at"),
        Index("idx_payments_merchant_initiated", "merchant_id", "initiated_at"),
        Index("idx_payments_status_initiated", "payment_status", "initiated_at"),
        Index("idx_payments_gateway_tx", "gateway_transaction_id"),
    )

    def to_dict(self):
        return {
            "payment_id": self.payment_id,
            "order_id": self.order_id,
            "user_id": self.user_id,
            "merchant_id": self.merchant_id,
            "gateway_transaction_id": self.gateway_transaction_id,
            "idempotency_key": self.idempotency_key,
            "payment_method": self.payment_method,
            "payment_status": self.payment_status,
            "amount": float(self.amount),
            "currency": self.currency,
            "processor_name": self.processor_name,
            "failure_code": self.failure_code,
            "failure_reason": self.failure_reason,
            "ip_address": self.ip_address,
            "device_id": self.device_id,
            "initiated_at": self.initiated_at.isoformat() if self.initiated_at else None,
            "authorized_at": self.authorized_at.isoformat() if self.authorized_at else None,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "failed_at": self.failed_at.isoformat() if self.failed_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

class Chargeback(db.Model):
    """Source-domain chargeback table."""
    __tablename__ = "chargebacks"

    chargeback_id = Column(String(36), primary_key=True)
    payment_id = Column(String(36), ForeignKey("payments.payment_id"), nullable=False)
    order_id = Column(String(36), ForeignKey("orders.order_id"), nullable=False)
    processor_case_id = Column(String(150), nullable=True)
    amount = Column(DECIMAL(18, 2), nullable=False)
    currency = Column(CHAR(3), nullable=False)
    reason_code = Column(String(50), nullable=True)
    reason_description = Column(String(500), nullable=True)
    chargeback_status = Column(String(30), nullable=False)  # 'OPEN', 'UNDER_REVIEW', 'ACCEPTED', 'DISPUTED', 'WON', 'LOST'
    fraud_indicator = Column(Boolean, default=False)
    received_at = Column(TIMESTAMP, nullable=False)
    response_due_at = Column(TIMESTAMP, nullable=True)
    responded_at = Column(TIMESTAMP, nullable=True)
    resolved_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    payment = relationship("Payment", foreign_keys=[payment_id])
    order = relationship("Order", foreign_keys=[order_id])

    __table_args__ = (
        Index("idx_chargebacks_payment", "payment_id"),
        Index("idx_chargebacks_order", "order_id"),
        Index("idx_chargebacks_status_due", "chargeback_status", "response_due_at"),
        Index("idx_chargebacks_received", "received_at"),
    )

    def to_dict(self):
        return {
            "chargeback_id": self.chargeback_id,
            "payment_id": self.payment_id,
            "order_id": self.order_id,
            "processor_case_id": self.processor_case_id,
            "amount": float(self.amount),
            "currency": self.currency,
            "reason_code": self.reason_code,
            "reason_description": self.reason_description,
            "chargeback_status": self.chargeback_status,
            "fraud_indicator": self.fraud_indicator,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "response_due_at": self.response_due_at.isoformat() if self.response_due_at else None,
            "responded_at": self.responded_at.isoformat() if self.responded_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# =============================================================================
# Dedicated Master Tables with `m_` Prefix
# =============================================================================

class MUser(db.Model):
    """Master Users table (m_users)."""
    __tablename__ = "m_users"

    user_id = Column(String(36), primary_key=True)
    external_user_id = Column(String(100), unique=True, nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    email = Column(String(255), unique=True, nullable=False)
    phone_number = Column(String(30), nullable=True)
    user_type = Column(String(30), nullable=False, default="CUSTOMER")  # CUSTOMER, MERCHANT, ADMIN
    status = Column(String(30), nullable=False, default="ACTIVE")      # ACTIVE, BLOCKED, SUSPENDED, LOCKED, MONITORING
    country_code = Column(CHAR(2), nullable=True, default="IN")
    kyc_status = Column(String(30), nullable=True, default="PENDING")   # NOT_STARTED, PENDING, VERIFIED, REJECTED
    risk_level = Column(String(20), nullable=True, default="LOW")       # LOW, MEDIUM, HIGH, CRITICAL
    risk_score = Column(DECIMAL(5, 2), nullable=True, default=15.00)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)
    last_login_at = Column(TIMESTAMP, nullable=True)

    __table_args__ = (
        Index("idx_m_users_type_status", "user_type", "status"),
        Index("idx_m_users_risk", "risk_level", "risk_score"),
    )

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "external_user_id": self.external_user_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "phone_number": self.phone_number,
            "user_type": self.user_type,
            "status": self.status,
            "country_code": self.country_code,
            "kyc_status": self.kyc_status,
            "risk_level": self.risk_level,
            "risk_score": float(self.risk_score) if self.risk_score is not None else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


class MOrder(db.Model):
    """Master Orders table (m_orders)."""
    __tablename__ = "m_orders"

    order_id = Column(String(36), primary_key=True)
    merchant_order_id = Column(String(100), nullable=True)
    user_id = Column(String(36), nullable=False)
    merchant_id = Column(String(36), nullable=False)
    amount = Column(DECIMAL(18, 2), nullable=False)
    currency = Column(CHAR(3), nullable=False, default="INR")
    order_status = Column(String(30), nullable=False, default="PAID")  # CREATED, PENDING, PAID, FAILED, CANCELLED, REFUNDED
    description = Column(String(500), nullable=True)
    ip_address = Column(String(45), nullable=True)
    device_id = Column(String(255), nullable=True)
    billing_country = Column(CHAR(2), nullable=True, default="IN")
    shipping_country = Column(CHAR(2), nullable=True, default="IN")
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_m_orders_user_created", "user_id", "created_at"),
        Index("idx_m_orders_merchant_created", "merchant_id", "created_at"),
    )

    def to_dict(self):
        return {
            "order_id": self.order_id,
            "merchant_order_id": self.merchant_order_id,
            "user_id": self.user_id,
            "merchant_id": self.merchant_id,
            "amount": float(self.amount),
            "currency": self.currency,
            "order_status": self.order_status,
            "description": self.description,
            "ip_address": self.ip_address,
            "device_id": self.device_id,
            "billing_country": self.billing_country,
            "shipping_country": self.shipping_country,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class MPayment(db.Model):
    """Master Payments table (m_payments)."""
    __tablename__ = "m_payments"

    payment_id = Column(String(36), primary_key=True)
    order_id = Column(String(36), nullable=False)
    user_id = Column(String(36), nullable=False)
    merchant_id = Column(String(36), nullable=False)
    gateway_transaction_id = Column(String(150), nullable=True)
    idempotency_key = Column(String(150), nullable=True)
    payment_method = Column(String(30), nullable=False, default="CARD")  # CARD, UPI, WALLET, NET_BANKING
    payment_status = Column(String(30), nullable=False, default="AUTHORIZED")  # INITIATED, PROCESSING, AUTHORIZED, CAPTURED, FAILED
    amount = Column(DECIMAL(18, 2), nullable=False)
    currency = Column(CHAR(3), nullable=False, default="INR")
    processor_name = Column(String(100), nullable=True)
    failure_code = Column(String(100), nullable=True)
    failure_reason = Column(String(500), nullable=True)
    ip_address = Column(String(45), nullable=True)
    device_id = Column(String(255), nullable=True)
    initiated_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_m_payments_user_initiated", "user_id", "initiated_at"),
        Index("idx_m_payments_order", "order_id"),
    )

    def to_dict(self):
        return {
            "payment_id": self.payment_id,
            "order_id": self.order_id,
            "user_id": self.user_id,
            "merchant_id": self.merchant_id,
            "gateway_transaction_id": self.gateway_transaction_id,
            "idempotency_key": self.idempotency_key,
            "payment_method": self.payment_method,
            "payment_status": self.payment_status,
            "amount": float(self.amount),
            "currency": self.currency,
            "processor_name": self.processor_name,
            "failure_code": self.failure_code,
            "failure_reason": self.failure_reason,
            "ip_address": self.ip_address,
            "device_id": self.device_id,
            "initiated_at": self.initiated_at.isoformat() if self.initiated_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class MChargeback(db.Model):
    """Master Chargebacks table (m_chargebacks)."""
    __tablename__ = "m_chargebacks"

    chargeback_id = Column(String(36), primary_key=True)
    payment_id = Column(String(36), nullable=False)
    order_id = Column(String(36), nullable=False)
    processor_case_id = Column(String(150), nullable=True)
    amount = Column(DECIMAL(18, 2), nullable=False)
    currency = Column(CHAR(3), nullable=False, default="INR")
    reason_code = Column(String(50), nullable=True)
    reason_description = Column(String(500), nullable=True)
    chargeback_status = Column(String(30), nullable=False, default="OPEN")  # OPEN, UNDER_REVIEW, ACCEPTED, DISPUTED, CLOSED
    fraud_indicator = Column(Boolean, default=True)
    received_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_m_chargebacks_payment", "payment_id"),
        Index("idx_m_chargebacks_order", "order_id"),
    )

    def to_dict(self):
        return {
            "chargeback_id": self.chargeback_id,
            "payment_id": self.payment_id,
            "order_id": self.order_id,
            "processor_case_id": self.processor_case_id,
            "amount": float(self.amount),
            "currency": self.currency,
            "reason_code": self.reason_code,
            "reason_description": self.reason_description,
            "chargeback_status": self.chargeback_status,
            "fraud_indicator": self.fraud_indicator,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
