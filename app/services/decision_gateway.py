import logging
from typing import Dict, Any, List
from backend.app.schemas.recommendation import StructuredRecommendation

logger = logging.getLogger("fraud_agent.decision_gateway")

class DecisionGateway:
    """Deterministic routing and decision policy engine."""

    # Explicit policy allowlist for automated action eligibility (low-risk only)
    AUTO_ACTION_ALLOWLIST = {
        "MONITOR",
        "REQUEST_VERIFICATION",
        "SEND_NOTIFICATION"
    }

    # High-impact actions that unconditionally require human approval
    RESTRICTED_ACTIONS = {
        "BLOCK_USER",
        "BLOCK_MERCHANT",
        "BLOCK_TRANSACTION",
        "HOLD_TRANSACTION",
        "TEMPORARY_RESTRICTION"
    }

    @classmethod
    def evaluate_route(cls, recommendation: StructuredRecommendation, evidence_count: int, missing_evidence_count: int) -> Dict[str, Any]:
        """
        Evaluates the case deterministically against policy rules.
        Returns the routed state and required gateway obligations.
        """
        # Rule 1: High missing evidence ratio requires human escalation
        if missing_evidence_count > 2 or evidence_count == 0:
            return {
                "route": "ESCALATE",
                "reason": f"Investigation has significant evidence gaps ({missing_evidence_count} missing items). Requires senior investigator review.",
                "auto_action_eligible": False,
                "review_required": True
            }

        # Rule 2: High impact actions require Human Review
        if recommendation.recommendation in cls.RESTRICTED_ACTIONS:
            return {
                "route": "HUMAN_REVIEW",
                "reason": f"Action '{recommendation.recommendation}' carries material business impact and strictly mandates human authorization per Fraud Policy SOP-04.",
                "auto_action_eligible": False,
                "review_required": True
            }

        # Rule 3: Low impact actions with HIGH confidence and full evidence can be auto-action eligible
        if (
            recommendation.recommendation in cls.AUTO_ACTION_ALLOWLIST and
            recommendation.confidence_label == "HIGH" and
            missing_evidence_count == 0
        ):
            return {
                "route": "AUTO_ACTION_ELIGIBLE",
                "reason": f"Action '{recommendation.recommendation}' meets auto-execution criteria under Policy SOP-02.",
                "auto_action_eligible": True,
                "review_required": False
            }

        # Default fallback: Route to standard human reviewer queue
        return {
            "route": "HUMAN_REVIEW",
            "reason": "Default human-in-the-loop governance applied.",
            "auto_action_eligible": False,
            "review_required": True
        }
