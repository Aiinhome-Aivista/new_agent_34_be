from datetime import datetime
from sqlalchemy import Column, String, Text, DECIMAL, Boolean, DateTime, ForeignKey, UniqueConstraint, Enum
from sqlalchemy.orm import relationship
from app.models.base import Base

class User(Base):
    __tablename__ = "users"

    user_id = Column(String(36), primary_key=True)
    external_user_id = Column(String(64), unique=True, nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    email = Column(String(255), unique=True, nullable=False)
    phone = Column(String(32), nullable=True)
    user_type = Column(String(20), nullable=False, default="CUSTOMER")
    status = Column(String(20), nullable=False, default="ACTIVE")
    country_code = Column(String(3), nullable=True, default="IN")
    kyc_status = Column(String(32), nullable=True, default="VERIFIED")
    risk_level = Column(String(20), nullable=True, default="LOW")
    risk_score = Column(DECIMAL(5, 2), nullable=True, default=0.00)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="user", cascade="all, delete-orphan")


class Order(Base):
    __tablename__ = "orders"

    order_id = Column(String(36), primary_key=True)
    merchant_order_id = Column(String(64), nullable=False)
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=False)
    merchant_id = Column(String(64), nullable=False)
    amount = Column(DECIMAL(18, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="INR")
    order_status = Column(String(32), nullable=False, default="COMPLETED")
    description = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    device_id = Column(String(128), nullable=True)
    billing_country = Column(String(3), nullable=True, default="IN")
    shipping_country = Column(String(3), nullable=True, default="IN")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("merchant_id", "merchant_order_id", name="uq_merchant_order"),
    )

    user = relationship("User", back_populates="orders")
    payments = relationship("Payment", back_populates="order", cascade="all, delete-orphan")
    chargebacks = relationship("Chargeback", back_populates="order", cascade="all, delete-orphan")


class Payment(Base):
    __tablename__ = "payments"

    payment_id = Column(String(36), primary_key=True)
    order_id = Column(String(36), ForeignKey("orders.order_id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=False)
    merchant_id = Column(String(64), nullable=False)
    gateway_transaction_id = Column(String(128), nullable=True)
    idempotency_key = Column(String(128), nullable=False)
    payment_method = Column(String(32), nullable=False, default="CREDIT_CARD")
    payment_status = Column(String(32), nullable=False, default="SUCCESS")
    amount = Column(DECIMAL(18, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="INR")
    processor_name = Column(String(64), nullable=True, default="Razorpay")
    failure_code = Column(String(64), nullable=True)
    failure_reason = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    device_id = Column(String(128), nullable=True)
    initiated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    authorized_at = Column(DateTime, nullable=True)
    captured_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("merchant_id", "idempotency_key", name="uq_merchant_idempotency"),
    )

    order = relationship("Order", back_populates="payments")
    user = relationship("User", back_populates="payments")
    chargebacks = relationship("Chargeback", back_populates="payment", cascade="all, delete-orphan")


class Chargeback(Base):
    __tablename__ = "chargebacks"

    chargeback_id = Column(String(36), primary_key=True)
    payment_id = Column(String(36), ForeignKey("payments.payment_id"), nullable=False)
    order_id = Column(String(36), ForeignKey("orders.order_id"), nullable=False)
    processor_case_id = Column(String(128), nullable=True)
    amount = Column(DECIMAL(18, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="INR")
    reason_code = Column(String(32), nullable=False, default="FRAUD_UNRECOGNIZED")
    reason_description = Column(Text, nullable=True)
    chargeback_status = Column(String(32), nullable=False, default="OPEN")
    fraud_indicator = Column(Boolean, nullable=False, default=False)
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    response_due_at = Column(DateTime, nullable=True)
    responded_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    payment = relationship("Payment", back_populates="chargebacks")
    order = relationship("Order", back_populates="chargebacks")
