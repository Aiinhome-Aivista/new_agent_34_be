import logging
from app.extensions import db
from app.models.governance import AppUser, PolicyDocument, FraudParameter, MicroserviceApiRegistry

logger = logging.getLogger("fraud_agent.seed_data")

DEFAULT_PERSONAS = [
    {
        "identity_subject": "SUB_ADMIN_01",
        "display_name": "Vikramaditya Roy",
        "email": "admin@fraudops.ai",
        "password": "admin@123",
        "role": "ADMIN",
        "avatar": "VR",
        "badge": "ADMIN",
        "badge_color": "#EF4444",
        "description": "Full system authority: policy manager, parameter engine, and user administration"
    },
    {
        "identity_subject": "SUB_ANALYST_01",
        "display_name": "Priya Sharma",
        "email": "priya.sharma@fraudops.ai",
        "password": "analyst123",
        "role": "SENIOR_INVESTIGATOR",
        "avatar": "PS",
        "badge": "SENIOR",
        "badge_color": "#16A34A",
        "description": "Full access to case queue, decisions, and simulator"
    },
    {
        "identity_subject": "SUB_LEAD_01",
        "display_name": "Rahul Verma",
        "email": "rahul.verma@fraudops.ai",
        "password": "riskops99",
        "role": "SUPERVISOR",
        "avatar": "RV",
        "badge": "LEAD",
        "badge_color": "#FF5A14",
        "description": "Dashboard analytics and infrastructure oversight"
    },
    {
        "identity_subject": "SUB_AUDIT_01",
        "display_name": "Ananya Bose",
        "email": "ananya.bose@fraudops.ai",
        "password": "audit2024",
        "role": "AUDITOR",
        "avatar": "AB",
        "badge": "AUDIT",
        "badge_color": "#6D28D9",
        "description": "Read-only access with full audit trail visibility"
    }
]

DEFAULT_POLICIES = [
    {
        "document_key": "FRAUD_SOP_01",
        "title": "Dispute & Chargeback Spike Threshold SOP",
        "version": "1.2",
        "category": "CHARGEBACK",
        "action_impact": "RESTRICTIVE",
        "description": "Mandatory investigation when merchant dispute ratio exceeds 1.0% or 3 consecutive chargebacks are received within 30 days.",
        "content": "Any merchant or user experiencing dispute ratios above 1.0% of total volume shall be subject to immediate temporary payment holds pending investigation.",
        "status": "APPROVED",
        "source_reference": "RISK_GOV_DOC_SOP_01"
    },
    {
        "document_key": "FRAUD_SOP_02",
        "title": "Policy-Authorized Auto Action Framework",
        "version": "2.0",
        "category": "AUTO_ACTION",
        "action_impact": "MONITORING",
        "description": "Permits automated low-risk protective actions (MONITOR, REQUEST_VERIFICATION) strictly when evidence is 100% complete and confidence is HIGH.",
        "content": "Only non-disruptive actions like watchlist monitoring and automated KYC verification requests may be executed autonomously without prior human sign-off.",
        "status": "APPROVED",
        "source_reference": "RISK_GOV_DOC_SOP_02"
    },
    {
        "document_key": "FRAUD_SOP_03",
        "title": "Hardware Fingerprint & Sybil Ring Defense SOP",
        "version": "1.0",
        "category": "DEVICE_RING",
        "action_impact": "BLOCKING",
        "description": "Protocols for identifying multi-user device clustering, hardware fingerprint spoofing, and emulator farm attacks.",
        "content": "When more than 2 distinct KYC accounts share the same physical device ID or IP subnet within a 24-hour window, initiate immediate protective freeze.",
        "status": "APPROVED",
        "source_reference": "RISK_GOV_DOC_SOP_03"
    },
    {
        "document_key": "FRAUD_SOP_04",
        "title": "High-Impact Human Review Gate Policy",
        "version": "1.5",
        "category": "HUMAN_REVIEW",
        "action_impact": "BLOCKING",
        "description": "Restricted actions (BLOCK_USER, BLOCK_MERCHANT, BLOCK_TRANSACTION) unconditionally require authorized analyst review and dual-eye signoff.",
        "content": "No automated agent or algorithm may permanently terminate customer access or seize merchant settlements without explicit analyst review rationale.",
        "status": "APPROVED",
        "source_reference": "RISK_GOV_DOC_SOP_04"
    },
    {
        "document_key": "FRAUD_SOP_05",
        "title": "KYC Identity & Transaction Velocity SOP",
        "version": "1.1",
        "category": "IDENTITY",
        "action_impact": "ADVISORY",
        "description": "High-value transactions above INR 50,000 from accounts with pending or unverified KYC status require enhanced due diligence.",
        "content": "Unverified users attempting transactions beyond threshold limit must submit government identity documents before funds are released.",
        "status": "APPROVED",
        "source_reference": "RISK_GOV_DOC_SOP_05"
    }
]

DEFAULT_PARAMETERS = [
    # 1. USER_PROFILE
    {
        "parameter_key": "user_kyc_verification_required",
        "name": "Mandatory KYC Verification State",
        "section": "USER_PROFILE",
        "data_type": "STRING",
        "threshold_value": "VERIFIED",
        "risk_weight": "HIGH",
        "description": "Users without verified KYC transacting high amounts are flagged for forensic identity audit."
    },
    {
        "parameter_key": "user_risk_level_flag",
        "name": "Upstream User Risk Level Threshold",
        "section": "USER_PROFILE",
        "data_type": "STRING",
        "threshold_value": "HIGH",
        "risk_weight": "CRITICAL",
        "description": "Upstream CRM/Identity system classification where HIGH risk triggers immediate agent prioritization."
    },
    {
        "parameter_key": "user_dormant_reactivation_days",
        "name": "Dormant Account Sudden Reactivation",
        "section": "USER_PROFILE",
        "data_type": "NUMBER",
        "threshold_value": "90",
        "risk_weight": "MEDIUM",
        "description": "Accounts inactive for >90 days that suddenly conduct high-value transactions are flagged."
    },

    # 2. PAYMENT_TRANSACTION
    {
        "parameter_key": "high_value_transaction_limit",
        "name": "High Value Transaction Ceiling",
        "section": "PAYMENT_TRANSACTION",
        "data_type": "NUMBER",
        "threshold_value": "50000",
        "risk_weight": "HIGH",
        "description": "Transactions exceeding INR 50,000 (or equivalent) trigger enhanced evidence collection."
    },
    {
        "parameter_key": "rapid_payment_failure_velocity",
        "name": "Rapid Payment Failure Velocity (10 Min)",
        "section": "PAYMENT_TRANSACTION",
        "data_type": "NUMBER",
        "threshold_value": "3",
        "risk_weight": "CRITICAL",
        "description": "Detects automated card-testing or bin-attack loops when 3+ failures occur in short succession."
    },
    {
        "parameter_key": "payment_method_strict_mode",
        "name": "Card / UPI Risk Scoring Strict Mode",
        "section": "PAYMENT_TRANSACTION",
        "data_type": "BOOLEAN",
        "threshold_value": "TRUE",
        "risk_weight": "MEDIUM",
        "description": "Enforces strict BIN-level verification and issuer risk score checking on card transactions."
    },

    # 3. ORDER_DETAILS
    {
        "parameter_key": "geo_country_mismatch_detection",
        "name": "Billing vs Shipping Geo Country Mismatch",
        "section": "ORDER_DETAILS",
        "data_type": "BOOLEAN",
        "threshold_value": "TRUE",
        "risk_weight": "HIGH",
        "description": "Flags cross-border mismatch between issued card billing country and physical goods delivery country."
    },
    {
        "parameter_key": "order_basket_volume_spike_ratio",
        "name": "Order Basket Spike Multiplier",
        "section": "ORDER_DETAILS",
        "data_type": "PERCENTAGE",
        "threshold_value": "300%",
        "risk_weight": "MEDIUM",
        "description": "Flags single cart purchase values that exceed 3x the 30-day historical customer mean."
    },

    # 4. CHARGEBACK_DISPUTE
    {
        "parameter_key": "dispute_volume_ratio_limit",
        "name": "Visa / Mastercard Dispute Ratio Limit",
        "section": "CHARGEBACK_DISPUTE",
        "data_type": "PERCENTAGE",
        "threshold_value": "1.0%",
        "risk_weight": "CRITICAL",
        "description": "Card scheme threshold. If merchant disputes exceed 1.0% of volume, initiate automated merchant freeze."
    },
    {
        "parameter_key": "historical_chargeback_count_ceiling",
        "name": "Customer Lifetime Chargeback Threshold",
        "section": "CHARGEBACK_DISPUTE",
        "data_type": "NUMBER",
        "threshold_value": "1",
        "risk_weight": "HIGH",
        "description": "Customers with 1 or more unresolved historical chargebacks are classified as SUSPICIOUS."
    },

    # 5. GRAPH_NETWORK
    {
        "parameter_key": "shared_device_cluster_limit",
        "name": "Hardware Device Sharing Identity Limit",
        "section": "GRAPH_NETWORK",
        "data_type": "NUMBER",
        "threshold_value": "2",
        "risk_weight": "CRITICAL",
        "description": "Maximum allowed customer accounts linked to an identical hardware device fingerprint before flagging as a Fraud Ring."
    },
    {
        "parameter_key": "shared_ip_cluster_limit",
        "name": "IP Address Concurrent Account Footprint",
        "section": "GRAPH_NETWORK",
        "data_type": "NUMBER",
        "threshold_value": "3",
        "risk_weight": "HIGH",
        "description": "Maximum distinct accounts initiating checkout simultaneously from identical IP address."
    },

    # 6. GATEWAY_RULE
    {
        "parameter_key": "auto_action_confidence_floor",
        "name": "Autonomous Action Minimum Confidence Floor",
        "section": "GATEWAY_RULE",
        "data_type": "STRING",
        "threshold_value": "HIGH",
        "risk_weight": "HIGH",
        "description": "Decision Gateway rule: Automated protective actions require at least HIGH confidence."
    },
    {
        "parameter_key": "max_tolerable_missing_evidence",
        "name": "Maximum Tolerable Missing Evidence Count",
        "section": "GATEWAY_RULE",
        "data_type": "NUMBER",
        "threshold_value": "2",
        "risk_weight": "HIGH",
        "description": "If more than 2 forensic evidence items cannot be retrieved, case automatically escalates to senior review."
    }
]

DEFAULT_MICROSERVICES = [
    {
        "service_key": "USER_PROFILE_SERVICE",
        "service_name": "Customer 360 & KYC Service",
        "service_category": "IDENTITY",
        "description": "Retrieves comprehensive customer KYC tier, verification documents, identity risk score, and linked accounts across banking verticals.",
        "http_method": "GET",
        "base_url": "http://127.0.0.1:5000",
        "endpoint_path": "/api/v1/users/{user_id}",
        "auth_type": "BEARER_TOKEN",
        "auth_header_key": "Authorization",
        "auth_token_encrypted": "sk-live-sec-kyc992038472910ab38c",
        "token_preview": "sk-l••••••••ab38c",
        "custom_headers": {"Content-Type": "application/json", "X-Consumer-Service": "Agent-34-FraudOps"},
        "sample_payload": {"query": {"include_kyc_details": True, "include_linked_devices": True}},
        "sample_response": {
            "user_id": "USR_10029",
            "full_name": "Rohan Deshmukh",
            "email": "rohan.deshmukh@enterprise.in",
            "phone": "+91-98200-11223",
            "kyc_status": "VERIFIED",
            "kyc_tier": "TIER_3_FULL",
            "account_created_at": "2023-04-12T10:15:00Z",
            "identity_risk_score": 0.12,
            "watchlist_match": False,
            "linked_devices_count": 2,
            "country_code": "IN",
            "city": "Mumbai"
        },
        "payload_schema": "Path param: {user_id}. Query params: include_kyc_details (bool), include_linked_devices (bool).",
        "timeout_ms": 4000,
        "retry_count": 2,
        "is_mock_enabled": True,
        "is_active": True,
        "health_status": "HEALTHY",
        "last_latency_ms": 32,
        "last_status_code": 200
    },
    {
        "service_key": "PAYMENT_GATEWAY_SERVICE",
        "service_name": "Payment Gateway Switch & Clearing",
        "service_category": "PAYMENT",
        "description": "Fetches card processor response codes, 3D-Secure authentication state, card BIN details, routing hop, and settlement logs.",
        "http_method": "GET",
        "base_url": "http://127.0.0.1:5000",
        "endpoint_path": "/api/v1/payments/{payment_id}",
        "auth_type": "API_KEY",
        "auth_header_key": "X-Gateway-API-Key",
        "auth_token_encrypted": "gwk_live_49921048759201948572",
        "token_preview": "gwk_••••••••8572",
        "custom_headers": {"X-Gateway-Version": "2026-01-01"},
        "sample_payload": {"include_3ds_metadata": True, "include_routing_trace": True},
        "sample_response": {
            "payment_id": "PAY_8839210",
            "transaction_ref": "TXN_9920184",
            "amount": 45000.0,
            "currency": "INR",
            "status": "CAPTURED",
            "gateway_code": "00_APPROVED",
            "card_bin": "411111",
            "card_type": "VISA_PLATINUM_CREDIT",
            "card_issuer": "HDFC Bank Ltd",
            "three_ds_version": "2.2.0",
            "three_ds_authenticated": True,
            "liability_shift": True,
            "avs_result": "MATCH_EXACT",
            "cvv_result": "MATCH"
        },
        "payload_schema": "Path param: {payment_id}. Query params: include_3ds_metadata (bool).",
        "timeout_ms": 3500,
        "retry_count": 2,
        "is_mock_enabled": True,
        "is_active": True,
        "health_status": "HEALTHY",
        "last_latency_ms": 48,
        "last_status_code": 200
    },
    {
        "service_key": "VELOCITY_ENGINE_SERVICE",
        "service_name": "Transaction Velocity & Spike Engine",
        "service_category": "PAYMENT",
        "description": "Calculates high-frequency velocity metrics, rolling 10-minute/1-hour transaction volume, and geo-velocity hops across nodes.",
        "http_method": "POST",
        "base_url": "https://velocity.risk.internal",
        "endpoint_path": "/api/v1/velocity/query",
        "auth_type": "BEARER_TOKEN",
        "auth_header_key": "Authorization",
        "auth_token_encrypted": "vel_sec_token_992104928174",
        "token_preview": "vel_••••••••8174",
        "custom_headers": {"Content-Type": "application/json"},
        "sample_payload": {"user_id": "USR_10029", "card_hash": "a8fbc72910", "window_minutes": 60},
        "sample_response": {
            "user_id": "USR_10029",
            "window_evaluated": "60_MINUTES",
            "txns_in_window": 4,
            "total_amount_in_window": 128500.0,
            "avg_amount_last_30d": 3500.0,
            "amount_spike_ratio": 36.7,
            "rapid_fire_flag": True,
            "distinct_ips_count": 3,
            "geo_velocity_km_per_hr": 840.5,
            "impossible_travel_detected": True
        },
        "payload_schema": "JSON Body: {user_id: string, card_hash?: string, window_minutes: number}",
        "timeout_ms": 2500,
        "retry_count": 3,
        "is_mock_enabled": True,
        "is_active": True,
        "health_status": "HEALTHY",
        "last_latency_ms": 19,
        "last_status_code": 200
    },
    {
        "service_key": "ORDER_FULFILLMENT_SERVICE",
        "service_name": "Order & Fulfillment Service",
        "service_category": "ORDER",
        "description": "Fetches order items, digital goods vs physical shipping address, consignment status, and delivery milestones.",
        "http_method": "GET",
        "base_url": "http://127.0.0.1:5000",
        "endpoint_path": "/api/v1/orders/{order_id}",
        "auth_type": "BEARER_TOKEN",
        "auth_token_encrypted": "ord_auth_jwt_991823746519",
        "token_preview": "ord_••••••••6519",
        "custom_headers": {"Content-Type": "application/json"},
        "sample_payload": {"expand": "line_items,shipping_address"},
        "sample_response": {
            "order_id": "ORD_5582910",
            "merchant_id": "MERCH_AMAZ_IN",
            "order_type": "HIGH_VALUE_ELECTRONICS",
            "items_count": 2,
            "line_items": [
                {"sku": "APPL-IP16-PRO-256", "name": "Apple iPhone 16 Pro 256GB", "price": 119900.0, "qty": 1},
                {"sku": "APPL-MAGSAFE-CASE", "name": "Silicone Case with MagSafe", "price": 4900.0, "qty": 1}
            ],
            "shipping_method": "SAME_DAY_EXPRESS",
            "shipping_address": {
                "city": "Bengaluru",
                "pincode": "560103",
                "country": "IN",
                "is_forwarding_agent_address": True
            },
            "delivery_hold_capable": True
        },
        "payload_schema": "Path param: {order_id}. Query: expand (comma-delimited string).",
        "timeout_ms": 3000,
        "retry_count": 2,
        "is_mock_enabled": True,
        "is_active": True,
        "health_status": "HEALTHY",
        "last_latency_ms": 41,
        "last_status_code": 200
    },
    {
        "service_key": "DEVICE_INTELLIGENCE_SERVICE",
        "service_name": "Device Intelligence & Fingerprint Hub",
        "service_category": "DEVICE",
        "description": "Inspects hardware integrity, jailbreak/root status, emulator detection, VPN/proxy flags, and Sybil clustering.",
        "http_method": "GET",
        "base_url": "https://device-intel.security.internal",
        "endpoint_path": "/api/v1/devices/{device_id}",
        "auth_type": "API_KEY",
        "auth_header_key": "X-Device-Intel-Key",
        "auth_token_encrypted": "dev_int_key_9938172648102",
        "token_preview": "dev_••••••••8102",
        "custom_headers": {"Content-Type": "application/json"},
        "sample_payload": {"include_cluster_users": True},
        "sample_response": {
            "device_id": "DEV_A9F88172BC",
            "os_family": "Android 14 (HyperOS)",
            "is_emulator": False,
            "is_rooted": True,
            "tampered_runtime": True,
            "ip_address": "103.21.244.18",
            "is_vpn_or_datacenter": True,
            "vpn_provider": "NordVPN_Exit_Node",
            "associated_user_count_24h": 5,
            "device_reputation_score": 0.94,
            "sybil_ring_suspect": True
        },
        "payload_schema": "Path param: {device_id}. Query: include_cluster_users (bool).",
        "timeout_ms": 2500,
        "retry_count": 2,
        "is_mock_enabled": True,
        "is_active": True,
        "health_status": "HEALTHY",
        "last_latency_ms": 22,
        "last_status_code": 200
    },
    {
        "service_key": "DISPUTE_LEDGER_SERVICE",
        "service_name": "Chargeback & Dispute Ledger",
        "service_category": "DISPUTE",
        "description": "Provides historical dispute cases, friendly fraud flags, pre-arbitration warnings, and merchant chargeback ratios.",
        "http_method": "GET",
        "base_url": "http://127.0.0.1:5000",
        "endpoint_path": "/api/v1/disputes/summary/{user_id}",
        "auth_type": "BEARER_TOKEN",
        "auth_token_encrypted": "dsp_ledger_sec_2984710293",
        "token_preview": "dsp_••••••••293",
        "custom_headers": {"Content-Type": "application/json"},
        "sample_payload": {"lookback_days": 180},
        "sample_response": {
            "user_id": "USR_10029",
            "total_chargebacks_180d": 4,
            "chargeback_amount_sum": 164000.0,
            "dispute_reason_breakdown": {
                "10.4_FRAUD_CARD_ABSENT": 3,
                "13.1_SERVICES_NOT_PROVIDED": 1
            },
            "friendly_fraud_probability": 0.82,
            "dispute_to_purchase_ratio": "14.2%",
            "dispute_status": "HIGH_RISK_REPEAT_OFFENDER"
        },
        "payload_schema": "Path param: {user_id}. Query: lookback_days (int).",
        "timeout_ms": 3500,
        "retry_count": 2,
        "is_mock_enabled": True,
        "is_active": True,
        "health_status": "HEALTHY",
        "last_latency_ms": 53,
        "last_status_code": 200
    },
    {
        "service_key": "ACCOUNT_ENFORCEMENT_SERVICE",
        "service_name": "Downstream Account Enforcement",
        "service_category": "ACTION",
        "description": "Dispatches real-time protective enforcement: lock user, cancel pending payments, freeze payouts, or force OTP.",
        "http_method": "PUT",
        "base_url": "http://127.0.0.1:5000",
        "endpoint_path": "/api/v1/accounts/{user_id}/status",
        "auth_type": "BEARER_TOKEN",
        "auth_token_encrypted": "enf_auth_token_secret_8819",
        "token_preview": "enf_••••••••8819",
        "custom_headers": {"Content-Type": "application/json", "X-Enforcement-Source": "FraudOps_Agent34"},
        "sample_payload": {
            "action": "LOCK_USER",
            "enforcement_reason": "High-risk hardware fingerprint spoofing and dispute ratio spike",
            "duration": "INDEFINITE",
            "notify_customer": True,
            "authorized_by": "admin@fraudops.ai"
        },
        "sample_response": {
            "status": "SUCCESS",
            "action_id": "ACT_99182310",
            "account_id": "USR_10029",
            "previous_state": "ACTIVE",
            "current_state": "LOCKED",
            "active_sessions_revoked": 3,
            "payouts_frozen": True,
            "timestamp": "2026-11-16T12:20:00Z"
        },
        "payload_schema": "Path param: {user_id}. JSON Body: action (string), enforcement_reason (string), duration (string), notify_customer (bool), authorized_by (string).",
        "timeout_ms": 3000,
        "retry_count": 3,
        "is_mock_enabled": True,
        "is_active": True,
        "health_status": "HEALTHY",
        "last_latency_ms": 38,
        "last_status_code": 200
    },
    {
        "service_key": "CUSTOMER_NOTIFICATION_SERVICE",
        "service_name": "Customer Notification Relay",
        "service_category": "NOTIFICATION",
        "description": "Sends multi-channel customer communications: SMS OTP, evidence submission magic links, and urgent security notices.",
        "http_method": "POST",
        "base_url": "https://notify.relay.internal",
        "endpoint_path": "/api/v1/notifications/dispatch",
        "auth_type": "API_KEY",
        "auth_header_key": "X-Notification-API-Key",
        "auth_token_encrypted": "notif_api_sec_key_4481029",
        "token_preview": "noti••••••••1029",
        "custom_headers": {"Content-Type": "application/json"},
        "sample_payload": {
            "recipient": {"user_id": "USR_10029", "phone": "+91-98200-11223", "email": "rohan.deshmukh@enterprise.in"},
            "channel": "SMS_AND_EMAIL",
            "template_id": "FRAUD_EVIDENCE_REQUEST_V1",
            "parameters": {
                "customer_name": "Rohan",
                "case_ref": "CASE_882910",
                "portal_url": "https://fraudops.ai/portal?token=sec_tok_991"
            }
        },
        "sample_response": {
            "dispatch_id": "NOTIF_DISPATCH_77192",
            "sms_status": "DELIVERED",
            "email_status": "QUEUED",
            "provider_msg_id": "msg_99218472910",
            "dispatched_at": "2026-11-16T12:20:02Z"
        },
        "payload_schema": "JSON Body: recipient (object), channel (string), template_id (string), parameters (object).",
        "timeout_ms": 4000,
        "retry_count": 2,
        "is_mock_enabled": True,
        "is_active": True,
        "health_status": "HEALTHY",
        "last_latency_ms": 64,
        "last_status_code": 200
    }
]

from sqlalchemy import text

def _ensure_table_columns():
    """Safely adds missing columns to existing MySQL tables if they were created earlier."""
    with db.engine.connect() as conn:
        cols_app_users = [
            ("password_hash", "VARCHAR(255) NULL"),
            ("avatar", "VARCHAR(10) NULL"),
            ("badge", "VARCHAR(50) NULL"),
            ("badge_color", "VARCHAR(20) NULL"),
            ("description", "VARCHAR(255) NULL"),
        ]
        for col, col_type in cols_app_users:
            try:
                conn.execute(text(f"ALTER TABLE app_users ADD COLUMN {col} {col_type}"))
                conn.commit()
            except Exception:
                pass

        cols_policies = [
            ("category", "VARCHAR(100) NULL DEFAULT 'GENERAL'"),
            ("description", "VARCHAR(500) NULL"),
            ("content", "TEXT NULL"),
            ("action_impact", "VARCHAR(100) NULL DEFAULT 'ADVISORY'"),
        ]
        for col, col_type in cols_policies:
            try:
                conn.execute(text(f"ALTER TABLE policy_documents ADD COLUMN {col} {col_type}"))
                conn.commit()
            except Exception:
                pass

def seed_all_defaults():
    """Seeds default Personas, Policies, and Parameters into MySQL if not present."""
    _ensure_table_columns()
    db.create_all()

    # 1. Seed Personas
    seeded_users = 0
    for p in DEFAULT_PERSONAS:
        user = AppUser.query.filter_by(email=p["email"]).first()
        if not user:
            user = AppUser(
                identity_subject=p["identity_subject"],
                display_name=p["display_name"],
                email=p["email"],
                role=p["role"],
                avatar=p["avatar"],
                badge=p["badge"],
                badge_color=p["badge_color"],
                description=p["description"],
                status="ACTIVE"
            )
            user.set_password(p["password"])
            db.session.add(user)
            seeded_users += 1
        else:
            # Update password hash if not set
            if not user.password_hash:
                user.set_password(p["password"])
            if not user.avatar:
                user.avatar = p["avatar"]
            if not user.badge:
                user.badge = p["badge"]
            if not user.badge_color:
                user.badge_color = p["badge_color"]
            if not user.description:
                user.description = p["description"]

    # 2. Seed Policies
    seeded_policies = 0
    for pol in DEFAULT_POLICIES:
        p_obj = PolicyDocument.query.filter_by(document_key=pol["document_key"]).first()
        if not p_obj:
            p_obj = PolicyDocument(
                document_key=pol["document_key"],
                title=pol["title"],
                version=pol["version"],
                category=pol["category"],
                action_impact=pol["action_impact"],
                description=pol["description"],
                content=pol["content"],
                status=pol["status"],
                source_reference=pol["source_reference"]
            )
            db.session.add(p_obj)
            seeded_policies += 1

    # 3. Seed Fraud Parameters
    seeded_params = 0
    for param in DEFAULT_PARAMETERS:
        p_record = FraudParameter.query.filter_by(parameter_key=param["parameter_key"]).first()
        if not p_record:
            p_record = FraudParameter(
                parameter_key=param["parameter_key"],
                name=param["name"],
                section=param["section"],
                data_type=param["data_type"],
                threshold_value=param["threshold_value"],
                risk_weight=param["risk_weight"],
                description=param["description"],
                is_active=True
            )
            db.session.add(p_record)
            seeded_params += 1

    # 4. Seed Microservice Connectors
    seeded_connectors = 0
    for conn_def in DEFAULT_MICROSERVICES:
        existing_conn = MicroserviceApiRegistry.query.filter_by(service_key=conn_def["service_key"]).first()
        if not existing_conn:
            new_conn = MicroserviceApiRegistry(
                service_key=conn_def["service_key"],
                service_name=conn_def["service_name"],
                service_category=conn_def["service_category"],
                description=conn_def.get("description"),
                http_method=conn_def.get("http_method", "GET"),
                base_url=conn_def["base_url"],
                endpoint_path=conn_def["endpoint_path"],
                auth_type=conn_def.get("auth_type", "BEARER_TOKEN"),
                auth_header_key=conn_def.get("auth_header_key", "Authorization"),
                auth_token_encrypted=conn_def.get("auth_token_encrypted"),
                token_preview=conn_def.get("token_preview"),
                custom_headers=conn_def.get("custom_headers"),
                sample_payload=conn_def.get("sample_payload"),
                sample_response=conn_def.get("sample_response"),
                payload_schema=conn_def.get("payload_schema"),
                timeout_ms=conn_def.get("timeout_ms", 5000),
                retry_count=conn_def.get("retry_count", 2),
                is_mock_enabled=conn_def.get("is_mock_enabled", True),
                is_active=conn_def.get("is_active", True),
                health_status=conn_def.get("health_status", "HEALTHY"),
                last_latency_ms=conn_def.get("last_latency_ms", 30),
                last_status_code=conn_def.get("last_status_code", 200)
            )
            db.session.add(new_conn)
            seeded_connectors += 1
        else:
            # Sync base_url and endpoint_path if they were pointing to legacy or unresolvable internal domains
            if "internal" in (existing_conn.base_url or ""):
                existing_conn.base_url = conn_def["base_url"]
                existing_conn.endpoint_path = conn_def["endpoint_path"]

    db.session.commit()
    logger.info(f"Database seed completed: {seeded_users} users, {seeded_policies} policies, {seeded_params} parameters, {seeded_connectors} connectors.")
    return {
        "users": seeded_users,
        "policies": seeded_policies,
        "parameters": seeded_params,
        "connectors": seeded_connectors
    }
