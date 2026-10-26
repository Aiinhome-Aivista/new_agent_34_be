from typing import Optional, List, Dict, Any
from typing_extensions import TypedDict

class InvestigationState(TypedDict, total=False):
    case_id: str
    case_number: str
    trigger: Dict[str, Any]
    user_id: Optional[str]
    merchant_id: Optional[str]
    order_id: Optional[str]
    payment_id: Optional[str]
    
    # Collected Evidence
    user: Optional[Dict[str, Any]]
    merchant: Optional[Dict[str, Any]]
    transaction: Optional[Dict[str, Any]]
    order: Optional[Dict[str, Any]]
    transaction_history: List[Dict[str, Any]]
    chargebacks: List[Dict[str, Any]]
    policy_context: List[Dict[str, Any]]
    evidence_records: List[Dict[str, Any]]
    missing_evidence: List[str]
    
    # LLM Structured Output
    assessment: Optional[str]               # SUSPICIOUS, LEGITIMATE, INCONCLUSIVE
    qualitative_confidence: Optional[str]   # LOW, MEDIUM, HIGH
    summary: Optional[str]
    risk_indicators: List[Dict[str, Any]]
    counter_signals: List[Dict[str, Any]]
    policy_references: List[Dict[str, Any]]
    
    # Prescriptive Recommendation
    recommendation: Optional[str]           # TEMPORARY_RESTRICTION, MONITOR, etc.
    recommendation_rationale: Optional[str]
    human_review_required: bool
    auto_eligible: bool
    suggested_target_type: str
    suggested_target_id: str
    
    # Decision Gateway Routing
    decision_mode: Optional[str]            # ADVISOR, CONDITIONAL_AUTOMATION, POLICY_CONTROLLED
    gateway_route: Optional[str]            # HUMAN_REVIEW, AUTO_ACTION, ESCALATE
    
    # Lifecycle Tracking
    error_message: Optional[str]
    run_status: str
