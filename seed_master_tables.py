#!/usr/bin/env python3
"""
Seed script for Master Data Tables (`m_users`, `m_orders`, `m_payments`, `m_chargebacks`).
Populates 10+ realistic fraud and legitimate personas.
"""

import sys
from pathlib import Path
root_dir = str(Path(__file__).resolve().parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from datetime import datetime, timezone, timedelta
from app import create_app
from app.extensions import db
from app.models.source_domain import MUser, MOrder, MPayment, MChargeback

def utc_now():
    return datetime.now(timezone.utc)

def seed_master_domain_data():
    """Seeds rich personas into m_users, m_orders, m_payments, and m_chargebacks."""
    print("Seeding master tables: m_users, m_orders, m_payments, m_chargebacks...")

    # Merchant
    merchant_id = "MERCH_PRIME_01"
    merchant = MUser.query.filter_by(user_id=merchant_id).first()
    if not merchant:
        merchant = MUser(
            user_id=merchant_id,
            external_user_id="EXT_MERCH_01",
            first_name="Prime",
            last_name="Retail Hub",
            email="merchant@primeretail.com",
            phone_number="+918000011222",
            user_type="MERCHANT",
            status="ACTIVE",
            country_code="IN",
            kyc_status="VERIFIED",
            risk_level="LOW",
            risk_score=5.00,
            created_at=utc_now() - timedelta(days=365)
        )
        db.session.add(merchant)

    personas = [
        # 1. Normal Legitimate Customer
        {
            "user_id": "USR_LEGIT_101",
            "first_name": "Rahul",
            "last_name": "Sharma",
            "email": "rahul.sharma@example.com",
            "phone_number": "+919830112233",
            "user_type": "CUSTOMER",
            "status": "ACTIVE",
            "country_code": "IN",
            "kyc_status": "VERIFIED",
            "risk_level": "LOW",
            "risk_score": 12.50,
            "orders": [
                {
                    "order_id": "ORD_LEGIT_101A",
                    "amount": 3450.00,
                    "order_status": "PAID",
                    "description": "Electronics accessory order",
                    "device_id": "DEV_IPHONE_15_A",
                    "ip_address": "103.21.144.12",
                    "payments": [
                        {
                            "payment_id": "PAY_LEGIT_101A",
                            "payment_method": "UPI",
                            "payment_status": "CAPTURED",
                            "processor_name": "RAZORPAY",
                            "device_id": "DEV_IPHONE_15_A",
                            "ip_address": "103.21.144.12"
                        }
                    ]
                }
            ]
        },
        # 2. Sybil Ring Member #1 (Shared Device with Ring Member #2)
        {
            "user_id": "USR_SYBIL_RING_01",
            "first_name": "Sameer",
            "last_name": "Khan",
            "email": "sameer.khan@email.com",
            "phone_number": "+919811002233",
            "user_type": "CUSTOMER",
            "status": "ACTIVE",
            "country_code": "IN",
            "kyc_status": "PENDING",
            "risk_level": "HIGH",
            "risk_score": 85.00,
            "orders": [
                {
                    "order_id": "ORD_SYBIL_01",
                    "amount": 45000.00,
                    "order_status": "PAID",
                    "description": "High value phone purchase on emulator",
                    "device_id": "DEV_EMULATOR_CLONE_9",
                    "ip_address": "45.142.120.10",
                    "payments": [
                        {
                            "payment_id": "PAY_SYBIL_01",
                            "payment_method": "CARD",
                            "payment_status": "AUTHORIZED",
                            "processor_name": "PAYU",
                            "device_id": "DEV_EMULATOR_CLONE_9",
                            "ip_address": "45.142.120.10",
                            "chargeback": {
                                "chargeback_id": "CBK_SYBIL_01",
                                "reason_code": "FRAUDULENT_TRANSACTION",
                                "reason_description": "Cardholder disputes charge as stolen card misuse",
                                "chargeback_status": "OPEN",
                                "fraud_indicator": True
                            }
                        }
                    ]
                }
            ]
        },
        # 3. Sybil Ring Member #2 (Shared Device with Ring Member #1)
        {
            "user_id": "USR_SYBIL_RING_02",
            "first_name": "Vikram",
            "last_name": "Khanna",
            "email": "vikram.sybil@proton.me",
            "phone_number": "+919811223344",
            "user_type": "CUSTOMER",
            "status": "ACTIVE",
            "country_code": "IN",
            "kyc_status": "PENDING",
            "risk_level": "HIGH",
            "risk_score": 88.00,
            "orders": [
                {
                    "order_id": "ORD_SYBIL_02",
                    "amount": 49000.00,
                    "order_status": "PAID",
                    "description": "High value gadget purchase on emulator",
                    "device_id": "DEV_EMULATOR_CLONE_9",
                    "ip_address": "45.142.120.10",
                    "payments": [
                        {
                            "payment_id": "PAY_SYBIL_02",
                            "payment_method": "CARD",
                            "payment_status": "AUTHORIZED",
                            "processor_name": "PAYU",
                            "device_id": "DEV_EMULATOR_CLONE_9",
                            "ip_address": "45.142.120.10",
                            "chargeback": {
                                "chargeback_id": "CBK_SYBIL_02",
                                "reason_code": "FRAUDULENT_TRANSACTION",
                                "reason_description": "Suspected ATO and multi-account bot cluster",
                                "chargeback_status": "OPEN",
                                "fraud_indicator": True
                            }
                        }
                    ]
                }
            ]
        },
        # 4. Unverified KYC Spike
        {
            "user_id": "USR_UNVERIFIED_103",
            "first_name": "Rohan",
            "last_name": "Mehta",
            "email": "rohan.unverified@tempmail.org",
            "phone_number": "+919876500112",
            "user_type": "CUSTOMER",
            "status": "ACTIVE",
            "country_code": "IN",
            "kyc_status": "PENDING",
            "risk_level": "HIGH",
            "risk_score": 78.00,
            "orders": [
                {
                    "order_id": "ORD_HIGHVAL_103",
                    "amount": 185000.00,
                    "order_status": "PAID",
                    "description": "Extremely high value jewelry order without verified KYC",
                    "device_id": "DEV_MACBOOK_PRO_M3",
                    "ip_address": "103.45.67.89",
                    "payments": [
                        {
                            "payment_id": "PAY_HIGHVAL_103",
                            "payment_method": "NET_BANKING",
                            "payment_status": "AUTHORIZED",
                            "processor_name": "HDFC_GATEWAY",
                            "device_id": "DEV_MACBOOK_PRO_M3",
                            "ip_address": "103.45.67.89"
                        }
                    ]
                }
            ]
        },
        # 5. Chargeback Spike Account
        {
            "user_id": "USR_CHARGEBACK_104",
            "first_name": "Anita",
            "last_name": "Deshmukh",
            "email": "anita.disputes@gmail.com",
            "phone_number": "+919822334455",
            "user_type": "CUSTOMER",
            "status": "ACTIVE",
            "country_code": "IN",
            "kyc_status": "VERIFIED",
            "risk_level": "HIGH",
            "risk_score": 82.00,
            "orders": [
                {
                    "order_id": "ORD_DISP_104A",
                    "amount": 28000.00,
                    "order_status": "PAID",
                    "description": "Home appliance purchase",
                    "device_id": "DEV_ONEPLUS_12",
                    "ip_address": "115.111.45.22",
                    "payments": [
                        {
                            "payment_id": "PAY_DISP_104A",
                            "payment_method": "CARD",
                            "payment_status": "AUTHORIZED",
                            "processor_name": "CASHFREE",
                            "device_id": "DEV_ONEPLUS_12",
                            "ip_address": "115.111.45.22",
                            "chargeback": {
                                "chargeback_id": "CBK_DISP_104A",
                                "reason_code": "MERCHANDISE_NOT_RECEIVED",
                                "reason_description": "Dispute filed: Customer states item never delivered",
                                "chargeback_status": "OPEN",
                                "fraud_indicator": True
                            }
                        }
                    ]
                },
                {
                    "order_id": "ORD_DISP_104B",
                    "amount": 32000.00,
                    "order_status": "PAID",
                    "description": "Designer clothing order",
                    "device_id": "DEV_ONEPLUS_12",
                    "ip_address": "115.111.45.22",
                    "payments": [
                        {
                            "payment_id": "PAY_DISP_104B",
                            "payment_method": "CARD",
                            "payment_status": "AUTHORIZED",
                            "processor_name": "CASHFREE",
                            "device_id": "DEV_ONEPLUS_12",
                            "ip_address": "115.111.45.22",
                            "chargeback": {
                                "chargeback_id": "CBK_DISP_104B",
                                "reason_code": "UNAUTHORIZED_CHARGE",
                                "reason_description": "Cardholder disputes charge authenticity",
                                "chargeback_status": "UNDER_REVIEW",
                                "fraud_indicator": True
                            }
                        }
                    ]
                }
            ]
        },
        # 6. Dormant Account Reactivation
        {
            "user_id": "USR_DORMANT_105",
            "first_name": "Priya",
            "last_name": "Nair",
            "email": "priya.nair@example.com",
            "phone_number": "+919845012345",
            "user_type": "CUSTOMER",
            "status": "ACTIVE",
            "country_code": "IN",
            "kyc_status": "VERIFIED",
            "risk_level": "MEDIUM",
            "risk_score": 62.00,
            "orders": [
                {
                    "order_id": "ORD_DORM_105",
                    "amount": 75000.00,
                    "order_status": "PAID",
                    "description": "Sudden high-velocity purchase after 270 days of dormancy",
                    "device_id": "DEV_SAMSUNG_S24",
                    "ip_address": "182.73.12.8",
                    "payments": [
                        {
                            "payment_id": "PAY_DORM_105",
                            "payment_method": "CARD",
                            "payment_status": "AUTHORIZED",
                            "processor_name": "RAZORPAY",
                            "device_id": "DEV_SAMSUNG_S24",
                            "ip_address": "182.73.12.8"
                        }
                    ]
                }
            ]
        },
        # 7. Verified High-Net-Worth VIP Whale
        {
            "user_id": "USR_WHALE_106",
            "first_name": "Rajesh",
            "last_name": "Patel",
            "email": "rajesh.patel@corp.in",
            "phone_number": "+919820099887",
            "user_type": "CUSTOMER",
            "status": "ACTIVE",
            "country_code": "IN",
            "kyc_status": "VERIFIED",
            "risk_level": "LOW",
            "risk_score": 8.00,
            "orders": [
                {
                    "order_id": "ORD_WHALE_106",
                    "amount": 350000.00,
                    "order_status": "PAID",
                    "description": "VIP corporate luxury procurement",
                    "device_id": "DEV_IPHONE_15_PRO_MAX",
                    "ip_address": "14.143.45.66",
                    "payments": [
                        {
                            "payment_id": "PAY_WHALE_106",
                            "payment_method": "NET_BANKING",
                            "payment_status": "CAPTURED",
                            "processor_name": "ICICI_CORPORATE",
                            "device_id": "DEV_IPHONE_15_PRO_MAX",
                            "ip_address": "14.143.45.66"
                        }
                    ]
                }
            ]
        },
        # 8. Card Velocity Fraud Attack
        {
            "user_id": "USR_VELOCITY_107",
            "first_name": "Alex",
            "last_name": "Mercer",
            "email": "alex.bin@darkweb.net",
            "phone_number": "+14155552671",
            "user_type": "CUSTOMER",
            "status": "ACTIVE",
            "country_code": "US",
            "kyc_status": "NOT_STARTED",
            "risk_level": "HIGH",
            "risk_score": 92.00,
            "orders": [
                {
                    "order_id": "ORD_VEL_107A",
                    "amount": 12500.00,
                    "order_status": "FAILED",
                    "description": "Automated card testing attempt 1",
                    "device_id": "DEV_TOR_EXIT_NODE_1",
                    "ip_address": "185.220.101.5",
                    "payments": [
                        {
                            "payment_id": "PAY_VEL_107A",
                            "payment_method": "CARD",
                            "payment_status": "FAILED",
                            "failure_code": "CARD_DECLINED",
                            "failure_reason": "Excessive PIN / CVV retry failures",
                            "processor_name": "STRIPE",
                            "device_id": "DEV_TOR_EXIT_NODE_1",
                            "ip_address": "185.220.101.5"
                        }
                    ]
                },
                {
                    "order_id": "ORD_VEL_107B",
                    "amount": 12500.00,
                    "order_status": "FAILED",
                    "description": "Automated card testing attempt 2",
                    "device_id": "DEV_TOR_EXIT_NODE_1",
                    "ip_address": "185.220.101.5",
                    "payments": [
                        {
                            "payment_id": "PAY_VEL_107B",
                            "payment_method": "CARD",
                            "payment_status": "FAILED",
                            "failure_code": "FRAUD_SUSPECTED",
                            "failure_reason": "High velocity BIN testing attack pattern detected",
                            "processor_name": "STRIPE",
                            "device_id": "DEV_TOR_EXIT_NODE_1",
                            "ip_address": "185.220.101.5"
                        }
                    ]
                }
            ]
        },
        # 9. Previously Blocked User
        {
            "user_id": "USR_BLOCKED_108",
            "first_name": "Suresh",
            "last_name": "Raina",
            "email": "suresh.blocked@example.com",
            "phone_number": "+919810123456",
            "user_type": "CUSTOMER",
            "status": "BLOCKED",
            "country_code": "IN",
            "kyc_status": "REJECTED",
            "risk_level": "HIGH",
            "risk_score": 95.00,
            "orders": [
                {
                    "order_id": "ORD_BLK_108",
                    "amount": 62000.00,
                    "order_status": "CANCELLED",
                    "description": "Order on permanently restricted user account",
                    "device_id": "DEV_REDMI_NOTE_9",
                    "ip_address": "49.36.12.88",
                    "payments": [
                        {
                            "payment_id": "PAY_BLK_108",
                            "payment_method": "CARD",
                            "payment_status": "FAILED",
                            "failure_code": "ACCOUNT_RESTRICTED",
                            "failure_reason": "Account is blocked due to prior confirmed fraud",
                            "processor_name": "PAYU",
                            "device_id": "DEV_REDMI_NOTE_9",
                            "ip_address": "49.36.12.88",
                            "chargeback": {
                                "chargeback_id": "CBK_BLK_108",
                                "reason_code": "STOLEN_CARD",
                                "reason_description": "Historical chargeback on blocked fraud identity",
                                "chargeback_status": "CLOSED",
                                "fraud_indicator": True
                            }
                        }
                    ]
                }
            ]
        },
        # 10. Normal Everyday Retail Buyer
        {
            "user_id": "USR_NEW_RETAIL_109",
            "first_name": "Ananya",
            "last_name": "Sen",
            "email": "ananya.sen@outlook.com",
            "phone_number": "+919831122334",
            "user_type": "CUSTOMER",
            "status": "ACTIVE",
            "country_code": "IN",
            "kyc_status": "VERIFIED",
            "risk_level": "LOW",
            "risk_score": 14.00,
            "orders": [
                {
                    "order_id": "ORD_RET_109",
                    "amount": 4200.00,
                    "order_status": "PAID",
                    "description": "Books and stationary retail purchase",
                    "device_id": "DEV_PIXEL_8",
                    "ip_address": "122.163.45.19",
                    "payments": [
                        {
                            "payment_id": "PAY_RET_109",
                            "payment_method": "UPI",
                            "payment_status": "CAPTURED",
                            "processor_name": "PHONEPE",
                            "device_id": "DEV_PIXEL_8",
                            "ip_address": "122.163.45.19"
                        }
                    ]
                }
            ]
        },
        # 11. Cross-Border International User
        {
            "user_id": "USR_OVERSEAS_110",
            "first_name": "David",
            "last_name": "Miller",
            "email": "david.m@globalpay.com",
            "phone_number": "+442079460912",
            "user_type": "CUSTOMER",
            "status": "ACTIVE",
            "country_code": "GB",
            "kyc_status": "VERIFIED",
            "risk_level": "MEDIUM",
            "risk_score": 48.00,
            "orders": [
                {
                    "order_id": "ORD_OVR_110",
                    "amount": 85000.00,
                    "order_status": "PAID",
                    "description": "International cross-border handicraft export order",
                    "device_id": "DEV_MACBOOK_AIR_M2",
                    "ip_address": "81.2.69.142",
                    "billing_country": "GB",
                    "shipping_country": "IN",
                    "payments": [
                        {
                            "payment_id": "PAY_OVR_110",
                            "payment_method": "CARD",
                            "payment_status": "AUTHORIZED",
                            "processor_name": "STRIPE_GLOBAL",
                            "device_id": "DEV_MACBOOK_AIR_M2",
                            "ip_address": "81.2.69.142"
                        }
                    ]
                }
            ]
        }
    ]

    inserted_users = 0
    inserted_orders = 0
    inserted_payments = 0
    inserted_chargebacks = 0

    for p in personas:
        u = MUser.query.filter_by(user_id=p["user_id"]).first()
        if not u:
            u = MUser(
                user_id=p["user_id"],
                external_user_id=f"EXT_{p['user_id']}",
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
                created_at=utc_now() - timedelta(days=60)
            )
            db.session.add(u)
            inserted_users += 1
        else:
            # Refresh fields if needed
            u.first_name = p["first_name"]
            u.last_name = p["last_name"]
            u.email = p["email"]
            u.status = p["status"]
            u.kyc_status = p["kyc_status"]
            u.risk_level = p["risk_level"]
            u.risk_score = p["risk_score"]

        db.session.flush()

        for o in p.get("orders", []):
            order = MOrder.query.filter_by(order_id=o["order_id"]).first()
            if not order:
                order = MOrder(
                    order_id=o["order_id"],
                    merchant_order_id=f"M_{o['order_id']}",
                    user_id=u.user_id,
                    merchant_id=merchant_id,
                    amount=o["amount"],
                    currency="INR",
                    order_status=o["order_status"],
                    description=o.get("description", "Retail transaction"),
                    device_id=o.get("device_id", "DEV_DEFAULT"),
                    ip_address=o.get("ip_address", "192.168.1.1"),
                    billing_country=o.get("billing_country", p["country_code"]),
                    shipping_country=o.get("shipping_country", "IN"),
                    created_at=utc_now() - timedelta(days=5)
                )
                db.session.add(order)
                inserted_orders += 1
            db.session.flush()

            for pm in o.get("payments", []):
                payment = MPayment.query.filter_by(payment_id=pm["payment_id"]).first()
                if not payment:
                    payment = MPayment(
                        payment_id=pm["payment_id"],
                        order_id=order.order_id,
                        user_id=u.user_id,
                        merchant_id=merchant_id,
                        gateway_transaction_id=f"GW_{pm['payment_id']}",
                        idempotency_key=f"IDEMP_{pm['payment_id']}",
                        payment_method=pm["payment_method"],
                        payment_status=pm["payment_status"],
                        amount=o["amount"],
                        currency="INR",
                        processor_name=pm.get("processor_name", "RAZORPAY"),
                        failure_code=pm.get("failure_code"),
                        failure_reason=pm.get("failure_reason"),
                        device_id=pm.get("device_id", order.device_id),
                        ip_address=pm.get("ip_address", order.ip_address),
                        initiated_at=utc_now() - timedelta(days=5)
                    )
                    db.session.add(payment)
                    inserted_payments += 1
                db.session.flush()

                cb_data = pm.get("chargeback")
                if cb_data:
                    cb = MChargeback.query.filter_by(chargeback_id=cb_data["chargeback_id"]).first()
                    if not cb:
                        cb = MChargeback(
                            chargeback_id=cb_data["chargeback_id"],
                            payment_id=payment.payment_id,
                            order_id=order.order_id,
                            processor_case_id=f"CASE_{cb_data['chargeback_id']}",
                            amount=o["amount"],
                            currency="INR",
                            reason_code=cb_data["reason_code"],
                            reason_description=cb_data["reason_description"],
                            chargeback_status=cb_data["chargeback_status"],
                            fraud_indicator=cb_data.get("fraud_indicator", True),
                            received_at=utc_now() - timedelta(days=2),
                            created_at=utc_now() - timedelta(days=2)
                        )
                        db.session.add(cb)
                        inserted_chargebacks += 1

    db.session.commit()
    print(f"Master tables seeded: {inserted_users} new users ({len(personas)} total), {inserted_orders} orders, {inserted_payments} payments, {inserted_chargebacks} chargebacks.")

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed_master_domain_data()

