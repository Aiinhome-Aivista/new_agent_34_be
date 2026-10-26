import uuid
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.agent.state import InvestigationState
from app.tools.read_tools import EvidenceCollectorTools
from app.tools.policy_rag import PolicyRAGService
from app.agent.llm_client import LLMInvestigationClient

async def intake_and_plan_node(state: InvestigationState, db: Session) -> Dict[str, Any]:
    """Node 1: Parses trigger and prepares investigation context."""
    trigger = state.get("trigger", {})
    return {
        "user_id": trigger.get("user_id"),
        "merchant_id": trigger.get("merchant_id"),
        "order_id": trigger.get("order_id"),
        "payment_id": trigger.get("payment_id"),
        "decision_mode": trigger.get("decision_mode", "ADVISOR"),
        "run_status": "INVESTIGATING",
        "evidence_records": [],
        "missing_evidence": []
    }

async def collect_evidence_node(state: InvestigationState, db: Session) -> Dict[str, Any]:
    """Node 2: Executes bounded, read-only evidence collection."""
    tools = EvidenceCollectorTools(db)
    user_id = state.get("user_id")
    merchant_id = state.get("merchant_id")
    order_id = state.get("order_id")
    payment_id = state.get("payment_id")

    user_data = None
    order_data = None
    payment_data = None
    merchant_data = None
    chargebacks = []
    user_history = {}
    evidence_items = []

    # 1. User evidence
    if user_id:
        res = tools.get_user_profile(user_id)
        if res.get("status") == "SUCCESS":
            user_data = res.get("user")
            evidence_items.append({
                "source_type": "MYSQL_USER",
                "record_identifier": user_id,
                "summary": f"User Profile: {user_data.get('full_name')} (Risk: {user_data.get('risk_level')})",
                "payload": user_data,
                "is_counter_signal": user_data.get("kyc_status") == "VERIFIED"
            })
        
        hist = tools.get_user_payment_history(user_id)
        if hist.get("status") == "SUCCESS":
            user_history = hist
            evidence_items.append({
                "source_type": "MYSQL_PAYMENT_HISTORY",
                "record_identifier": f"HIST_{user_id}",
                "summary": f"User payment history (Avg: ₹{hist.get('stats', {}).get('historical_avg_amount', 0):,.2f})",
                "payload": hist,
                "is_counter_signal": True
            })

    # 2. Payment & Order evidence
    if payment_id:
        p_res = tools.get_payment_details(payment_id)
        if p_res.get("status") == "SUCCESS":
            payment_data = p_res.get("payment")
            evidence_items.append({
                "source_type": "MYSQL_PAYMENT",
                "record_identifier": payment_id,
                "summary": f"Payment {payment_id}: ₹{payment_data.get('amount'):,.2f} via {payment_data.get('payment_method')}",
                "payload": payment_data,
                "is_counter_signal": False
            })
            if not order_id and payment_data.get("order_id"):
                order_id = payment_data.get("order_id")

    if order_id:
        o_res = tools.get_order_details(order_id)
        if o_res.get("status") == "SUCCESS":
            order_data = o_res.get("order")
            evidence_items.append({
                "source_type": "MYSQL_ORDER",
                "record_identifier": order_id,
                "summary": f"Order {order_id}: {order_data.get('description', '')}",
                "payload": order_data,
                "is_counter_signal": order_data.get("shipping_country") == order_data.get("billing_country")
            })
            if not merchant_id and order_data.get("merchant_id"):
                merchant_id = order_data.get("merchant_id")

    # 3. Chargeback evidence
    cb_res = tools.get_chargeback_records(payment_id=payment_id, order_id=order_id)
    if cb_res.get("status") == "SUCCESS" and cb_res.get("count", 0) > 0:
        chargebacks = cb_res.get("chargebacks", [])
        for cb in chargebacks:
            evidence_items.append({
                "source_type": "MYSQL_CHARGEBACK",
                "record_identifier": cb.get("chargeback_id"),
                "summary": f"Chargeback: {cb.get('reason_code')} (Fraud: {cb.get('fraud_indicator')})",
                "payload": cb,
                "is_counter_signal": not cb.get("fraud_indicator")
            })

    # 4. Merchant evidence (Verified mapping check)
    if merchant_id:
        m_res = tools.get_merchant_profile(merchant_id)
        merchant_data = m_res
        if m_res.get("status") == "VERIFIED_MAPPING":
            evidence_items.append({
                "source_type": "MYSQL_MERCHANT",
                "record_identifier": merchant_id,
                "summary": f"Merchant Profile: {m_res.get('business_name')}",
                "payload": m_res,
                "is_counter_signal": True
            })

    return {
        "user": user_data,
        "order": order_data,
        "payment": payment_data,
        "merchant": merchant_data,
        "chargebacks": chargebacks,
        "transaction_history": user_history.get("recent_payments", []),
        "evidence_records": evidence_items,
        "merchant_id": merchant_id,
        "order_id": order_id
    }

async def detect_gaps_node(state: InvestigationState, db: Session) -> Dict[str, Any]:
    """Node 3: Identifies missing evidence and unverified relationships per HLA."""
    missing = []
    merchant = state.get("merchant")
    if merchant and merchant.get("status") == "UNRESOLVED_MERCHANT_RELATIONSHIP":
        missing.append(f"Unverified Merchant relationship for '{merchant.get('merchant_id')}': Merchant record is not directly mapped to internal user table.")

    payment = state.get("payment")
    if not payment and state.get("payment_id"):
        missing.append(f"Payment record '{state.get('payment_id')}' was unavailable in transactional database.")

    user = state.get("user")
    if not user and state.get("user_id"):
        missing.append(f"User account '{state.get('user_id')}' was not found in profile database.")

    # Device & Location telemetry gap checks
    missing.append("Device reputation score and carrier IMEI intelligence unavailable from telecom provider.")

    return {"missing_evidence": missing}

async def retrieve_policy_node(state: InvestigationState, db: Session) -> Dict[str, Any]:
    """Node 4: Retrieves applicable fraud SOPs and policies via RAG."""
    rag = PolicyRAGService(db)
    trigger_reason = state.get("trigger", {}).get("trigger_reason", "")
    query = f"Fraud investigation anomaly {trigger_reason} chargeback user restriction hold"
    policies = rag.search_policy(query=query, limit=3)
    return {"policy_context": policies}

async def synthesize_findings_node(state: InvestigationState, db: Session) -> Dict[str, Any]:
    """Node 5: Invokes LLM to produce structured evidence-grounded findings."""
    llm = LLMInvestigationClient()
    result = await llm.generate_structured_investigation(
        case_id=state.get("case_id", "CASE-001"),
        trigger=state.get("trigger", {}),
        user=state.get("user"),
        order=state.get("order"),
        payment=state.get("payment"),
        chargebacks=state.get("chargebacks", []),
        user_history={"stats": {}, "recent_payments": state.get("transaction_history", [])},
        merchant=state.get("merchant"),
        policies=state.get("policy_context", []),
        missing_evidence=state.get("missing_evidence", [])
    )

    return {
        "assessment": result.assessment,
        "qualitative_confidence": result.qualitative_confidence,
        "summary": result.summary,
        "risk_indicators": [r.model_dump() for r in result.risk_indicators],
        "counter_signals": [c.model_dump() for c in result.counter_signals],
        "policy_references": [p.model_dump() for p in result.policy_references],
        "recommendation": result.recommendation,
        "recommendation_rationale": result.recommendation_rationale,
        "human_review_required": result.human_review_required,
        "auto_eligible": result.auto_eligible,
        "suggested_target_type": result.suggested_target_type,
        "suggested_target_id": result.suggested_target_id,
        "run_status": "COMPLETED"
    }
