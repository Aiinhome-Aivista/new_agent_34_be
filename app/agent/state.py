"""
Phase 3: Enhanced InvestigationState
======================================
Extended with knowledgebase intelligence fields:
  - rule_evaluation_results: Output from the Deterministic Rule Engine (FR-001..FR-005)
  - historical_patterns: Past investigation outcomes from InvestigationHistorySnapshot
These fields are populated by the 4 parallel retrieval nodes introduced in Phase 3.
"""

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

    # ----------------------------------------------------------------
    # Core MySQL Evidence (node_collect_evidence)
    # ----------------------------------------------------------------
    evidence_items: List[Dict[str, Any]]
    missing_evidence: List[str]

    # ----------------------------------------------------------------
    # Parallel Knowledgebase Intelligence (Phase 3 nodes)
    # ----------------------------------------------------------------

    # Layer 2: Pre-computed entity graph traversal
    graph_analysis: Dict[str, Any]

    # Layer 3: Deterministic Rule Engine output
    # Structure: {triggered_rules: [...], passed_rules: [...], total_risk_score: float, highest_severity: str}
    rule_evaluation_results: Dict[str, Any]

    # Layer 1: Active policy passages from ChromaDB (version-filtered)
    retrieved_policies: List[Dict[str, Any]]

    # Layer 4: Historical intelligence from past confirmed cases
    historical_patterns: List[Dict[str, Any]]

    # ----------------------------------------------------------------
    # LLM Synthesis Output (node_reason_llm)
    # ----------------------------------------------------------------
    assessment: Optional[str]
    recommendation: Optional[str]
    explanation: Optional[str]
    confidence_label: Optional[str]
    risk_indicators: List[Dict[str, Any]]
    counter_signals: List[Dict[str, Any]]
    model_name: Optional[str]

    # ----------------------------------------------------------------
    # Decision Gateway Output (node_route_decision)
    # ----------------------------------------------------------------
    gateway_route: Optional[str]
    gateway_reason: Optional[str]
    auto_action_eligible: bool
    review_required: bool
    status: str
