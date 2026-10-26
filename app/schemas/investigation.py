from typing import List, Optional, Any
from pydantic import BaseModel, Field

class RiskIndicator(BaseModel):
    indicator: str = Field(..., description="Description of the risk observation")
    evidence_id: str = Field(..., description="Identifier of the evidence item grounding this signal")
    severity: Optional[str] = Field("MEDIUM", description="LOW, MEDIUM, HIGH, CRITICAL")

class CounterSignal(BaseModel):
    indicator: str = Field(..., description="Observation that counters or mitigates the fraud suspicion")
    evidence_id: str = Field(..., description="Identifier of the mitigating evidence item")

class PolicyCitation(BaseModel):
    policy_code: str = Field(..., description="e.g. POL-SOP-001")
    title: str = Field(..., description="Title of the governing policy")
    section: Optional[str] = None
    text: Optional[str] = None

class StructuredAgentOutput(BaseModel):
    case_id: str
    assessment: str = Field(..., description="SUSPICIOUS, LEGITIMATE, or INCONCLUSIVE")
    qualitative_confidence: str = Field(..., description="LOW, MEDIUM, or HIGH (No numerical probability)")
    summary: str = Field(..., description="Holistic correlation and factual synthesis of all evidence")
    risk_indicators: List[RiskIndicator] = Field(default_factory=list)
    counter_signals: List[CounterSignal] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list, description="Identified data gaps or unverified relationships")
    policy_references: List[PolicyCitation] = Field(default_factory=list)
    recommendation: str = Field(..., description="Prescribed action (e.g. TEMPORARY_RESTRICTION, MONITOR, STEP_UP_VERIFICATION)")
    recommendation_rationale: str = Field(..., description="Step-by-step logic explaining the recommended action")
    human_review_required: bool = True
    auto_eligible: bool = False
    suggested_target_type: str = Field("USER", description="USER, MERCHANT, TRANSACTION, ORDER")
    suggested_target_id: str = Field(..., description="Entity ID to which the action should apply")
