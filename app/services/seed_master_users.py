import uuid
import logging
from datetime import datetime, timezone, timedelta
from backend.app.extensions import db
from backend.app.models.source_domain import MUser, MOrder, MPayment, MChargeback

logger = logging.getLogger("fraud_agent.seed_master_users")

def utc_now():
    return datetime.now(timezone.utc)

MASTER_PERSONAS = [
    {
        "user_id": "USR_FRAUD_RING_01",
        "external_user_id": "EXT_FR_9011",
        "first_name": "Sameer",
        "last_name": "Khan",
        "email": "sameer.khan@email.com",
        "phone_number": "+919811002233",
        "user_type": "CUSTOMER",
        "status": "ACTIVE",
        "country_code": "IN",
        "kyc_status": "REJECTED",
        "risk_level": "HIGH",
        "risk_score": 88.50,
        "device_id": "DEV_EMULATOR_FARM_09",
        "ip_address": "103.212.45.88",
        "orders": [
            {"amount": 75000.0, "status": "FAILED", "reason": "STOLEN_CARD_SUSPECT"},
            {"amount": 92000.0, "status": "PAID", "has_chargeback": True, "cb_reason": "FRAUDULENT_TRANSACTION"}
        ]
    },
    {
        "user_id": "USR_KYC_PENDING_02",
        "external_user_id": "EXT_KP_8820",
        "first_name": "Ankit",
        "last_name": "Mehta",
        "email": "ankit.m@email.com",
        "phone_number": "+919822334455",
        "user_type": "CUSTOMER",
        "status": "ACTIVE",
        "country_code": "IN",
        "kyc_status": "PENDING",
        "risk_level": "MEDIUM",
        "risk_score": 62.00,
        "device_id": "DEV_ONEPLUS_9R_01",
        "ip_address": "49.36.12.102",
        "orders": [
            {"amount": 55000.0, "status": "PAID", "has_chargeback": False}
        ]
    },
    {
        "user_id": "USR_VIP_LEGIT_03",
        "external_user_id": "EXT_VIP_1001",
        "first_name": "Sunita",
        "last_name": "Rao",
        "email": "sunita.rao@corporate.in",
        "phone_number": "+919833445566",
        "user_type": "CUSTOMER",
        "status": "ACTIVE",
        "country_code": "IN",
        "kyc_status": "VERIFIED",
        "risk_level": "LOW",
        "risk_score": 8.00,
        "device_id": "DEV_IPHONE15_PRO_MAX",
        "ip_address": "122.161.44.12",
        "orders": [
            {"amount": 12500.0, "status": "PAID", "has_chargeback": False},
            {"amount": 4200.0, "status": "PAID", "has_chargeback": False}
        ]
    },
    {
        "user_id": "USR_DORMANT_SPIKE_04",
        "external_user_id": "EXT_DS_4401",
        "first_name": "Rajesh",
        "last_name": "Iyer",
        "email": "rajesh.iyer@gmail.com",
        "phone_number": "+919844556677",
        "user_type": "CUSTOMER",
        "status": "ACTIVE",
        "country_code": "IN",
        "kyc_status": "VERIFIED",
        "risk_level": "HIGH",
        "risk_score": 79.00,
        "device_id": "DEV_SAMSUNG_S24_UNKNOWN",
        "ip_address": "185.220.101.5",  # Tor exit node / proxy IP
        "orders": [
            {"amount": 120000.0, "status": "PAID", "has_chargeback": False}
        ]
    },
    {
        "user_id": "USR_SUSPENDED_05",
        "external_user_id": "EXT_SUSP_7712",
        "first_name": "Devendra",
        "last_name": "Pal",
        "email": "dev.pal@tempmail.org",
        "phone_number": "+919855667788",
        "user_type": "CUSTOMER",
        "status": "BLOCKED",
        "country_code": "IN",
        "kyc_status": "NOT_STARTED",
        "risk_level": "HIGH",
        "risk_score": 95.00,
        "device_id": "DEV_ROOTED_REDMI_9",
        "ip_address": "194.26.29.11",
        "orders": [
            {"amount": 35000.0, "status": "FAILED", "reason": "USER_LOCKED"}
        ]
    },
    {
        "user_id": "USR_CHARGEBACK_06",
        "external_user_id": "EXT_CB_2290",
        "first_name": "Pooja",
        "last_name": "Joshi",
        "email": "pooja.joshi@yahoo.com",
        "phone_number": "+919866778899",
        "user_type": "CUSTOMER",
        "status": "ACTIVE",
        "country_code": "IN",
        "kyc_status": "VERIFIED",
        "risk_level": "HIGH",
        "risk_score": 74.00,
        "device_id": "DEV_PIXEL_8_PJ",
        "ip_address": "106.51.78.204",
        "orders": [
            {"amount": 28000.0, "status": "PAID", "has_chargeback": True, "cb_reason": "DISPUTED_PRODUCT_NOT_RECEIVED"},
            {"amount": 31000.0, "status": "PAID", "has_chargeback": True, "cb_reason": "UNAUTHORIZED_TRANSACTION"}
        ]
    },
    {
        "user_id": "USR_ATO_VICTIM_07",
        "external_user_id": "EXT_ATO_3311",
        "first_name": "Amit",
        "last_name": "Sengupta",
        "email": "amit.sengupta@kolkata.gov.in",
        "phone_number": "+919877889900",
        "user_type": "CUSTOMER",
        "status": "ACTIVE",
        "country_code": "IN",
        "kyc_status": "VERIFIED",
        "risk_level": "HIGH",
        "risk_score": 81.50,
        "device_id": "DEV_MACBOOK_NEW_LOCATION",
        "ip_address": "45.142.122.9",
        "orders": [
            {"amount": 89000.0, "status": "PAID", "has_chargeback": False}
        ]
    },
    {
        "user_id": "USR_EMULATOR_08",
        "external_user_id": "EXT_EM_6602",
        "first_name": "Karan",
        "last_name": "Malhotra",
        "email": "karan.malhotra@rediffmail.com",
        "phone_number": "+919888990011",
        "user_type": "CUSTOMER",
        "status": "ACTIVE",
        "country_code": "IN",
        "kyc_status": "PENDING",
        "risk_level": "HIGH",
        "risk_score": 85.00,
        "device_id": "DEV_NOX_EMULATOR_GEN4",
        "ip_address": "103.212.45.88", # Shared IP with USR_FRAUD_RING_01
        "orders": [
            {"amount": 47000.0, "status": "PAID", "has_chargeback": False}
        ]
    }
]

MASTER_MERCHANTS = [
    {
        "user_id": "MERCH_PRIME_01",
        "email": "settlements@primeretail.in",
        "first_name": "Prime",
        "last_name": "Retail Corp",
        "user_type": "MERCHANT",
        "status": "ACTIVE",
        "kyc_status": "VERIFIED",
        "risk_level": "LOW",
        "risk_score": 5.00
    },
    {
        "user_id": "MERCH_SUSPICIOUS_02",
        "email": "support@quickcash.biz",
        "first_name": "QuickCash",
        "last_name": "Digital Services",
        "user_type": "MERCHANT",
        "status": "ACTIVE",
        "kyc_status": "PENDING",
        "risk_level": "HIGH",
        "risk_score": 78.00
    }
]

def seed_master_tables():
    """Seeds the m_* tables with realistic users, orders, payments, and disputes."""
    now = utc_now()

    # 1. Seed Merchants in m_users
    for m in MASTER_MERCHANTS:
        existing = MUser.query.filter_by(user_id=m["user_id"]).first()
        if not existing:
            merch = MUser(
                user_id=m["user_id"],
                email=m["email"],
                first_name=m["first_name"],
                last_name=m["last_name"],
                user_type=m["user_type"],
                status=m["status"],
                kyc_status=m["kyc_status"],
                risk_level=m["risk_level"],
                risk_score=m["risk_score"],
                created_at=now - timedelta(days=90)
            )
            db.session.add(merch)
    db.session.commit()

    # 2. Seed Customers and their transactions in m_* tables
    seeded_count = 0
    for p in MASTER_PERSONAS:
        user = MUser.query.filter_by(user_id=p["user_id"]).first()
        if not user:
            user = MUser(
                user_id=p["user_id"],
                external_user_id=p["external_user_id"],
                first_name=p["first_name"],
                last_name=p["last_name"],
                email=p["email"],
                phone_number=p["phone_number"],
                user_type=p["user_type"],
                status=p["status"],
                country_code=p["country_code"],
                kyc_status=p["kyc_status"],
                risk_level=p["risk_level"],
                risk_score=p["risk_score"],
                created_at=now - timedelta(days=60),
                last_login_at=now - timedelta(hours=2)
            )
            db.session.add(user)
            db.session.commit()
            seeded_count += 1

        # Seed Orders & Payments
        for idx, o in enumerate(p.get("orders", [])):
            order_id = f"ORD_{p['user_id']}_{idx+1}"
            order = MOrder.query.filter_by(order_id=order_id).first()
            if not order:
                order = MOrder(
                    order_id=order_id,
                    merchant_order_id=f"M_ORD_{uuid.uuid4().hex[:6].upper()}",
                    user_id=user.user_id,
                    merchant_id="MERCH_PRIME_01",
                    amount=o["amount"],
                    currency="INR",
                    order_status=o["status"],
                    description=f"E-commerce cart checkout order {idx+1}",
                    ip_address=p["ip_address"],
                    device_id=p["device_id"],
                    created_at=now - timedelta(days=idx+1)
                )
                db.session.add(order)
                db.session.commit()

            payment_id = f"PAY_{p['user_id']}_{idx+1}"
            payment = MPayment.query.filter_by(payment_id=payment_id).first()
            if not payment:
                payment = MPayment(
                    payment_id=payment_id,
                    order_id=order.order_id,
                    user_id=user.user_id,
                    merchant_id="MERCH_PRIME_01",
                    gateway_transaction_id=f"GW_{payment_id}",
                    idempotency_key=f"IDEMP_{payment_id}",
                    payment_method="CARD" if idx % 2 == 0 else "UPI",
                    payment_status="AUTHORIZED" if o["status"] == "PAID" else "FAILED",
                    amount=o["amount"],
                    currency="INR",
                    ip_address=p["ip_address"],
                    device_id=p["device_id"],
                    initiated_at=now - timedelta(days=idx+1),
                    failure_code=o.get("reason")
                )
                db.session.add(payment)
                db.session.commit()

            if o.get("has_chargeback"):
                cb_id = f"CBK_{payment.payment_id}"
                cb = MChargeback.query.filter_by(chargeback_id=cb_id).first()
                if not cb:
                    cb = MChargeback(
                        chargeback_id=cb_id,
                        payment_id=payment.payment_id,
                        order_id=order.order_id,
                        processor_case_id=f"PROC_CB_{uuid.uuid4().hex[:8].upper()}",
                        amount=o["amount"],
                        currency="INR",
                        reason_code=o.get("cb_reason", "FRAUDULENT_DISPUTE"),
                        reason_description=f"Issuer disputed chargeback: {o.get('cb_reason')}",
                        chargeback_status="OPEN",
                        fraud_indicator=True,
                        received_at=now - timedelta(days=idx)
                    )
                    db.session.add(cb)
                    db.session.commit()

    logger.info(f"Master seed complete: {len(MASTER_PERSONAS)} personas ensured in m_* tables.")
    return {"personas": len(MASTER_PERSONAS)}

if __name__ == "__main__":
    from backend.app import create_app
    app = create_app()
    with app.app_context():
        from backend.app.services.migrate_m_tables import migrate_and_ensure_m_tables
        migrate_and_ensure_m_tables()
        seed_master_tables()
        print("Master table seeding verified successfully!")

