from typing import Dict, Any, Tuple

class DecisionGateway:
    """
    Deterministic Decision Gateway.
    Evaluates agent recommendations, confidence, and policy mode.
    LLM NEVER bypasses this gateway.
    """
    SENSITIVE_ACTIONS = {
        "BLOCK_USER",
        "BLOCK_MERCHANT",
        "BLOCK_TRANSACTION",
        "HOLD_TRANSACTION",
        "TEMPORARY_RESTRICTION"
    }

    LOW_IMPACT_ACTIONS = {
        "MONITOR",
        "SEND_NOTIFICATION",
        "REQUEST_VERIFICATION",
        "NO_ACTION"
    }

    @classmethod
    def evaluate_route(
        cls,
        decision_mode: str,
        recommended_action: str,
        qualitative_confidence: str,
        amount: float = 0.0,
        has_conflicts: bool = False
    ) -> Tuple[str, str]:
        """
        Returns (route, rationale)
        route in ['HUMAN_REVIEW', 'AUTO_ACTION', 'ESCALATE']
        """
        # 1. Escalation check (POL-ESC-004)
        if amount > 100000.0:
            return (
                "ESCALATE",
                f"High transaction value ₹{amount:,.2f} exceeds ₹100,000 threshold, mandating senior risk committee review."
            )
        
        if has_conflicts:
            return (
                "ESCALATE",
                "Conflicting evidence or unverified core records require expert analyst escalation."
            )

        # 2. Advisor Mode (Initial rollout default per HLA 16.1)
        if decision_mode == "ADVISOR":
            return (
                "HUMAN_REVIEW",
                "Advisor Mode is active. All agent recommendations require authorized human approval."
            )

        # 3. Conditional / Policy-Controlled Automation
        if decision_mode in ("CONDITIONAL_AUTOMATION", "POLICY_CONTROLLED"):
            # Consequential actions always mandate human approval
            if recommended_action in cls.SENSITIVE_ACTIONS:
                return (
                    "HUMAN_REVIEW",
                    f"Sensitive action '{recommended_action}' has high business impact and legally mandates human sign-off."
                )

            # Low impact actions can be auto-approved only if confidence is HIGH
            if recommended_action in cls.LOW_IMPACT_ACTIONS:
                if qualitative_confidence == "HIGH":
                    return (
                        "AUTO_ACTION",
                        f"Action '{recommended_action}' is low-impact and supported by HIGH qualitative confidence per Policy POL-AUTO-005."
                    )
                else:
                    return (
                        "HUMAN_REVIEW",
                        f"Action '{recommended_action}' requires human review because confidence is {qualitative_confidence}."
                    )

        # Default fallback
        return ("HUMAN_REVIEW", "Routed to analyst review queue by default safety rule.")
