import uuid
import random
from typing import Dict, Any

SCENARIO_TEMPLATES = [
    {
        "trigger_type": "TRANSACTION_INVESTIGATION",
        "trigger_source": "PAYMENT_GATEWAY_MONITOR",
        "trigger_reason": "High velocity checkout spike: 5 high-value transactions within 90 seconds.",
        "priority": "HIGH"
    },
    {
        "trigger_type": "MERCHANT_DISPUTE_SPIKE",
        "trigger_source": "CARD_NETWORK_WEBHOOK",
        "trigger_reason": "Chargeback volume breached 1.5% monthly threshold for international transactions.",
        "priority": "CRITICAL"
    },
    {
        "trigger_type": "USER_TAKEOVER_ALERT",
        "trigger_source": "IDENTITY_RISK_SERVICE",
        "trigger_reason": "Unusual device fingerprint and IP geolocation switch from US to non-domestic ASN.",
        "priority": "HIGH"
    },
    {
        "trigger_type": "OPERATIONAL_REQUEST",
        "trigger_source": "COMPLIANCE_OPS_PORTAL",
        "trigger_reason": "Manual supervisor referral for suspicious merchant settlement pattern.",
        "priority": "MEDIUM"
    }
]

def generate_random_trigger_payload(force_idempotency_key: str = None) -> Dict[str, Any]:
    """Generates a realistic trigger payload adhering to the API trigger contract."""
    template = random.choice(SCENARIO_TEMPLATES).copy()
    key = force_idempotency_key or f"idem_{uuid.uuid4().hex[:16]}"
    
    template["idempotency_key"] = key
    template["transaction_id"] = f"TXN_{uuid.uuid4().hex[:10].upper()}"
    template["user_id"] = f"USR_{uuid.uuid4().hex[:8].upper()}"
    template["merchant_id"] = f"MCH_{uuid.uuid4().hex[:8].upper()}"
    return template
