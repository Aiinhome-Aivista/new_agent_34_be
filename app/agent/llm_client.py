import json
import logging
from typing import Dict, Any, Optional
import httpx
from app.config import settings
from app.schemas.investigation import StructuredAgentOutput

logger = logging.getLogger(__name__)

class LLMInvestigationClient:
    """
    Interfaces with Ollama for local LLM reasoning (Qwen2.5 / Gemma2).
    Enforces structured Pydantic schema validation.
    Provides robust, evidence-grounded fallback if Ollama service is unavailable.
    """
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL

    async def generate_structured_investigation(
        self,
        case_id: str,
        trigger: Dict[str, Any],
        user: Optional[Dict[str, Any]],
        order: Optional[Dict[str, Any]],
        payment: Optional[Dict[str, Any]],
        chargebacks: list,
        user_history: Dict[str, Any],
        merchant: Optional[Dict[str, Any]],
        policies: list,
        missing_evidence: list
    ) -> StructuredAgentOutput:
        prompt = self._build_prompt(
            case_id, trigger, user, order, payment, chargebacks, user_history, merchant, policies, missing_evidence
        )

        # 1. Attempt local Ollama inference
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json"
                    }
                )
                if res.status_code == 200:
                    raw_text = res.json().get("response", "")
                    parsed = json.loads(raw_text)
                    return StructuredAgentOutput(**parsed)
        except Exception as e:
            logger.warning(f"Ollama local inference unavailable ({str(e)}). Applying deterministic expert engine fallback.")

        # 2. Robust deterministic evidence-grounded reasoning fallback
        return self._deterministic_synthesizer(
            case_id, trigger, user, order, payment, chargebacks, user_history, merchant, policies, missing_evidence
        )

    def _build_prompt(self, case_id, trigger, user, order, payment, chargebacks, user_history, merchant, policies, missing_evidence) -> str:
        return f"""You are Agent 34, a Merchant & User Fraud Investigation Agent.
Correlate the following evidence, identify missing evidence, and output ONLY valid JSON adhering strictly to the schema.
DO NOT invent a numerical fraud probability. Use qualitative confidence: LOW, MEDIUM, or HIGH.

CASE ID: {case_id}
TRIGGER: {json.dumps(trigger)}
USER PROFILE: {json.dumps(user)}
ORDER: {json.dumps(order)}
PAYMENT: {json.dumps(payment)}
CHARGEBACKS: {json.dumps(chargebacks)}
USER HISTORY STATS: {json.dumps(user_history)}
MERCHANT: {json.dumps(merchant)}
POLICIES: {json.dumps(policies)}
KNOWN MISSING EVIDENCE: {json.dumps(missing_evidence)}

Schema requirements:
{{
  "case_id": "{case_id}",
  "assessment": "SUSPICIOUS | LEGITIMATE | INCONCLUSIVE",
  "qualitative_confidence": "LOW | MEDIUM | HIGH",
  "summary": "Factual evidence synthesis",
  "risk_indicators": [{{"indicator": "...", "evidence_id": "...", "severity": "HIGH | MEDIUM | LOW"}}],
  "counter_signals": [{{"indicator": "...", "evidence_id": "..."}}],
  "missing_evidence": ["..."],
  "policy_references": [{{"policy_code": "...", "title": "...", "section": "..."}}],
  "recommendation": "TEMPORARY_RESTRICTION | MONITOR | REQUEST_VERIFICATION | NO_ACTION | HOLD_TRANSACTION | BLOCK_USER | ESCALATE",
  "recommendation_rationale": "...",
  "human_review_required": true,
  "auto_eligible": false,
  "suggested_target_type": "USER | MERCHANT | TRANSACTION | ORDER",
  "suggested_target_id": "..."
}}
"""

    def _deterministic_synthesizer(
        self, case_id, trigger, user, order, payment, chargebacks, user_history, merchant, policies, missing_evidence
    ) -> StructuredAgentOutput:
        risk_indicators = []
        counter_signals = []
        target_id = (user.get("user_id") if user else None) or (payment.get("payment_id") if payment else None) or case_id
        target_type = "USER" if user else "TRANSACTION"

        # Check chargebacks
        open_fraud_cb = [cb for cb in chargebacks if cb.get("fraud_indicator")]
        if open_fraud_cb:
            risk_indicators.append({
                "indicator": f"Active fraud dispute logged: {open_fraud_cb[0].get('reason_code', 'FRAUD')} ({open_fraud_cb[0].get('reason_description', '')})",
                "evidence_id": f"CB_{open_fraud_cb[0].get('chargeback_id')}",
                "severity": "HIGH"
            })

        # Check payment amount anomaly
        stats = user_history.get("stats", {}) if isinstance(user_history, dict) else {}
        hist_avg = stats.get("historical_avg_amount", 0.0)
        curr_amount = payment.get("amount") if payment else (order.get("amount") if order else 0.0)

        if hist_avg > 0 and curr_amount > (hist_avg * 4):
            risk_indicators.append({
                "indicator": f"Transaction amount ₹{curr_amount:,.2f} deviates significantly from 90-day moving average (₹{hist_avg:,.2f})",
                "evidence_id": f"PAY_{payment.get('payment_id') if payment else 'TX'}",
                "severity": "HIGH"
            })

        # Check device shift
        if order and payment:
            device_id = order.get("device_id") or payment.get("device_id")
            if device_id and "DEV-MAC" in device_id or "DEV-UNKNOWN" in device_id:
                risk_indicators.append({
                    "indicator": f"Unrecognized hardware device identifier '{device_id}' detected during checkout",
                    "evidence_id": f"DEV_{device_id}",
                    "severity": "MEDIUM"
                })

        # Check counter signals
        if user and user.get("kyc_status") == "VERIFIED":
            counter_signals.append({
                "indicator": "User account possesses verified KYC status and active credentials",
                "evidence_id": f"USR_{user.get('user_id')}"
            })
        if order and order.get("shipping_country") == order.get("billing_country"):
            counter_signals.append({
                "indicator": f"Billing country matches shipping destination ({order.get('shipping_country')})",
                "evidence_id": f"ORD_{order.get('order_id')}"
            })

        # Policy references
        policy_refs = []
        for p in policies[:2]:
            policy_refs.append({
                "policy_code": p.get("policy_code", "POL-SOP-001"),
                "title": p.get("title", "Standard Operating Procedure: Fraud Investigation"),
                "section": "Section 2. Anomaly Criteria"
            })

        # Assessment logic
        if open_fraud_cb or len(risk_indicators) >= 2:
            assessment = "SUSPICIOUS"
            confidence = "HIGH" if open_fraud_cb else "MEDIUM"
            recommendation = "TEMPORARY_RESTRICTION"
            rationale = "Corroborated fraud dispute and substantial ticket size deviation warrant temporary restriction of user payment privileges and holding associated fulfillment."
            human_review = True
            auto_eligible = False
        elif len(risk_indicators) == 1:
            assessment = "SUSPICIOUS"
            confidence = "MEDIUM"
            recommendation = "REQUEST_VERIFICATION"
            rationale = "Mild risk deviation detected with supporting counter-signals. Recommend requesting 2FA or identity step-up verification."
            human_review = True
            auto_eligible = False
        else:
            assessment = "LEGITIMATE"
            confidence = "HIGH" if counter_signals else "MEDIUM"
            recommendation = "NO_ACTION"
            rationale = "No corroborated risk anomalies found; transactions align with baseline customer history."
            human_review = False
            auto_eligible = True

        summary = (
            f"Investigation conducted for {case_id} regarding trigger '{trigger.get('trigger_reason', '')}'. "
            f"Evaluated {len(risk_indicators)} risk indicators against {len(counter_signals)} counter-signals. "
            f"{'Chargeback dispute confirmed by card issuer.' if open_fraud_cb else 'No card disputes reported.'}"
        )

        return StructuredAgentOutput(
            case_id=case_id,
            assessment=assessment,
            qualitative_confidence=confidence,
            summary=summary,
            risk_indicators=risk_indicators,
            counter_signals=counter_signals,
            missing_evidence=missing_evidence,
            policy_references=policy_refs,
            recommendation=recommendation,
            recommendation_rationale=rationale,
            human_review_required=human_review,
            auto_eligible=auto_eligible,
            suggested_target_type=target_type,
            suggested_target_id=str(target_id)
        )
