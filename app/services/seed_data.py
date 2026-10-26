import logging
from backend.app.extensions import db
from backend.app.models.governance import AppUser, PolicyDocument, FraudParameter

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

    db.session.commit()
    logger.info(f"Database seed completed: {seeded_users} users, {seeded_policies} policies, {seeded_params} parameters.")
    return {
        "users": seeded_users,
        "policies": seeded_policies,
        "parameters": seeded_params
    }
