"""
Phase 2: Deterministic Fraud Rule Engine
==========================================
Evaluates configured FraudRule records against structured evidence.
Rules run entirely in Python — NO LLM involvement.
LLM receives only the structured output (triggered/passed rule list).

Evaluator functions are named after FraudRule.condition_evaluator column values.
Add new evaluators simply by adding a method with the matching name.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from app.extensions import db
from app.models.knowledgebase import FraudRule

logger = logging.getLogger("fraud_agent.rule_engine")

RULE_ENGINE_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Result data classes (plain dicts for JSON-serialisability)
# ---------------------------------------------------------------------------

def _rule_result(rule: FraudRule, triggered: bool, observed_value, note: str = "") -> Dict[str, Any]:
    return {
        "rule_id": rule.id,
        "rule_name": rule.rule_name,
        "category": rule.category,
        "severity": rule.severity,
        "weight": rule.weight,
        "threshold_value": rule.threshold_value,
        "threshold_unit": rule.threshold_unit,
        "observed_value": observed_value,
        "triggered": triggered,
        "note": note,
    }


# ---------------------------------------------------------------------------
# Individual evaluator functions
# ---------------------------------------------------------------------------

class RuleEvaluators:
    """
    Each public method here corresponds to a FraudRule.condition_evaluator value.
    Signature: (rule: FraudRule, evidence: Dict) -> Dict (single rule_result)
    """

    @staticmethod
    def eval_user_identity_exists(rule: FraudRule, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """
        FR-001: Check if the user_id exists in m_users.
        Evidence key: 'user_profile' → the found User ORM object dict, or None.
        """
        user_profile = evidence.get("user_profile")
        user_id = evidence.get("user_id")

        if user_profile is None or (isinstance(user_profile, dict) and user_profile.get("status") == "MISSING"):
            return _rule_result(rule, triggered=True, observed_value=0,
                                note=f"User '{user_id}' not found in m_users master directory.")
        return _rule_result(rule, triggered=False, observed_value=1,
                            note=f"User '{user_id}' verified in m_users.")

    @staticmethod
    def eval_shared_device_accounts(rule: FraudRule, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """
        FR-002: Count distinct user accounts sharing the same device_id via entity_relationships.
        """
        from app.models.knowledgebase import EntityRelationship
        device_id = evidence.get("device_id")

        if not device_id:
            return _rule_result(rule, triggered=False, observed_value=0,
                                note="No device_id present in evidence.")

        # Query all relationships for this device
        sharing_rels = db.session.query(EntityRelationship).filter(
            EntityRelationship.target_id == device_id,
            EntityRelationship.relation_type == "USED_DEVICE"
        ).all()

        all_account_ids = list({r.source_id for r in sharing_rels})
        count = len(all_account_ids)
        current_user_id = evidence.get("user_id")
        other_user_ids = [uid for uid in all_account_ids if uid != current_user_id]

        # Check if ANY other account on this device is BLOCKED
        has_blocked_user = False
        blocked_names = []
        if other_user_ids:
            try:
                from app.models.source_domain import MUser
                blocked_users = MUser.query.filter(
                    MUser.user_id.in_(other_user_ids),
                    MUser.status == "BLOCKED"
                ).all()
                if blocked_users:
                    has_blocked_user = True
                    blocked_names = [f"{u.user_id} ({u.name or 'Blocked'})" for u in blocked_users]
            except Exception as b_err:
                logger.warning(f"[RuleEngine] Error checking blocked users on device: {b_err}")

        triggered = (count >= int(rule.threshold_value)) or has_blocked_user

        if has_blocked_user:
            note = f"🚨 DEVICE BAN EVASION DETECTED: Hardware device '{device_id}' is shared with BLOCKED fraud account(s): {', '.join(blocked_names)}. Total accounts on hardware: {count}."
        else:
            note = f"Device '{device_id}' linked to {count} account(s). Threshold: {int(rule.threshold_value)}."

        return _rule_result(
            rule, triggered=triggered, observed_value=count,
            note=note
        )

    @staticmethod
    def eval_transaction_velocity(rule: FraudRule, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """
        FR-003: Count payments in the last 10 minutes for this user.
        """
        from sqlalchemy import text

        user_id = evidence.get("user_id")
        if not user_id:
            return _rule_result(rule, triggered=False, observed_value=0,
                                note="No user_id in evidence — velocity check skipped.")

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        try:
            result = db.session.execute(
                text("""
                    SELECT COUNT(*) FROM m_payments
                    WHERE user_id = :uid
                      AND initiated_at >= :cutoff
                """),
                {"uid": user_id, "cutoff": cutoff}
            ).scalar() or 0
        except Exception as e:
            logger.warning(f"[RuleEngine] FR-003 query error: {e}")
            result = 0

        triggered = result >= int(rule.threshold_value)
        return _rule_result(
            rule, triggered=triggered, observed_value=result,
            note=f"User '{user_id}' made {result} payment(s) in last 10 min. Threshold: {int(rule.threshold_value)}."
        )

    @staticmethod
    def eval_chargeback_count(rule: FraudRule, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """
        FR-004: Count confirmed chargebacks for the user from evidence.
        """
        chargeback_items = [
            item for item in evidence.get("evidence_items", [])
            if item.get("evidence_type") == "CHARGEBACK_HISTORY"
            and item.get("retrieval_status") == "FOUND"
        ]
        # Each evidence item may carry 'content' with a count or a list
        count = 0
        for item in chargeback_items:
            content = item.get("content_json") or {}
            # Support both a list of chargebacks or a summary count
            if isinstance(content, list):
                count += len(content)
            elif isinstance(content, dict):
                count += content.get("total_chargebacks", 1)

        triggered = count >= int(rule.threshold_value)
        return _rule_result(
            rule, triggered=triggered, observed_value=count,
            note=f"Found {count} confirmed chargeback(s). Threshold: {int(rule.threshold_value)}."
        )

    @staticmethod
    def eval_high_ticket_value(rule: FraudRule, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """
        FR-005: Check if any single order/payment amount exceeds the threshold (USD).
        """
        max_amount = 0.0
        for item in evidence.get("evidence_items", []):
            content = item.get("content_json") or {}
            if isinstance(content, dict):
                amount = content.get("amount") or content.get("total_amount") or 0
                try:
                    max_amount = max(max_amount, float(amount))
                except (ValueError, TypeError):
                    pass

        triggered = max_amount >= rule.threshold_value
        return _rule_result(
            rule, triggered=triggered, observed_value=max_amount,
            note=f"Highest single amount: ${max_amount:,.2f}. Threshold: ${rule.threshold_value:,.2f}."
        )


# ---------------------------------------------------------------------------
# Main Rule Engine service
# ---------------------------------------------------------------------------

class FraudRuleEngine:
    """
    Loads active FraudRule records and evaluates them against structured evidence.
    Returns a structured evaluation report consumed by node_execute_fraud_rules
    in the LangGraph pipeline.
    """

    @staticmethod
    def evaluate(evidence: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate all active fraud rules against the provided evidence dict.

        Args:
            evidence: Merged evidence dict from collect_evidence node, containing:
                - user_id, device_id, merchant_id
                - user_profile (dict or None)
                - evidence_items (list of CaseEvidence dicts)

        Returns:
            {
                "triggered_rules": [...],     # Rules that fired (TRIGGERED)
                "passed_rules": [...],        # Rules that did NOT fire
                "total_risk_score": float,    # Sum of weights of triggered rules (0.0–1.0)
                "highest_severity": str,      # CRITICAL | HIGH | MEDIUM | LOW | NONE
                "rule_engine_version": str,
                "evaluated_at": str,
            }
        """
        active_rules = FraudRule.query.filter_by(is_active=True).all()

        if not active_rules:
            logger.warning("[RuleEngine] No active fraud rules found — returning empty evaluation.")
            return {
                "triggered_rules": [],
                "passed_rules": [],
                "total_risk_score": 0.0,
                "highest_severity": "NONE",
                "rule_engine_version": RULE_ENGINE_VERSION,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }

        triggered_rules = []
        passed_rules = []
        total_score = 0.0

        severity_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "NONE": 0}
        highest_sev = "NONE"

        for rule in active_rules:
            evaluator_fn = getattr(RuleEvaluators, rule.condition_evaluator, None)
            if evaluator_fn is None:
                logger.warning(f"[RuleEngine] No evaluator found for '{rule.condition_evaluator}' — skipping {rule.id}.")
                continue

            try:
                result = evaluator_fn(rule, evidence)
            except Exception as e:
                logger.error(f"[RuleEngine] Evaluator '{rule.condition_evaluator}' raised: {e}")
                result = _rule_result(rule, triggered=False, observed_value=None,
                                      note=f"Evaluator error: {str(e)}")

            if result["triggered"]:
                triggered_rules.append(result)
                total_score += rule.weight
                if severity_rank.get(rule.severity, 0) > severity_rank.get(highest_sev, 0):
                    highest_sev = rule.severity
            else:
                passed_rules.append(result)

        # Cap at 1.0
        total_score = min(round(total_score, 4), 1.0)

        logger.info(
            f"[RuleEngine] Evaluation complete. "
            f"Triggered: {len(triggered_rules)}/{len(active_rules)} | "
            f"Score: {total_score} | Severity: {highest_sev}"
        )

        return {
            "triggered_rules": triggered_rules,
            "passed_rules": passed_rules,
            "total_risk_score": total_score,
            "highest_severity": highest_sev,
            "rule_engine_version": RULE_ENGINE_VERSION,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

