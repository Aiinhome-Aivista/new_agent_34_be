from typing import TypedDict, List, Dict, Any, Optional

class InvestigationState(TypedDict):
    """LangGraph investigation workflow state container."""
    case_id: str
    trigger_type: str
    trigger_reason: str
    priority: str
    transaction_id: Optional[str]
    user_id: Optional[str]
    merchant_id: Optional[str]
    
    # Evidence & Analysis
    evidence_items: List[Dict[str, Any]]
    missing_evidence: List[str]
    graph_analysis: Dict[str, Any]
    retrieved_policies: List[Dict[str, Any]]
    
    # Reasoning Output
    assessment: Optional[str]
    recommendation: Optional[str]
    explanation: Optional[str]
    confidence_label: Optional[str]
    risk_indicators: List[Dict[str, Any]]
    counter_signals: List[Dict[str, Any]]
    model_name: Optional[str]
    
    # Decision Gateway
    gateway_route: Optional[str]
    gateway_reason: Optional[str]
    auto_action_eligible: bool
    review_required: bool
    status: str
