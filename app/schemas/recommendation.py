from typing import List, Optional, Literal
from pydantic import BaseModel, Field

class IndicatorItem(BaseModel):
    statement: str = Field(..., description="Fact or observation")
    evidence_references: List[str] = Field(default_factory=list, description="IDs of supporting evidence items")

class StructuredRecommendation(BaseModel):
    """Schema-validated structured investigation output contract."""
    case_id: str
    assessment: Literal["SUSPICIOUS", "INCONCLUSIVE", "NOT_SUBSTANTIATED"]
    recommendation: Literal[
        "NO_ACTION",
        "MONITOR",
        "REQUEST_VERIFICATION",
        "SEND_NOTIFICATION",
        "TEMPORARY_RESTRICTION",
        "HOLD_TRANSACTION",
        "BLOCK_TRANSACTION",
        "BLOCK_USER",
        "BLOCK_MERCHANT",
        "ESCALATE"
    ]
    explanation: str = Field(..., min_length=20, max_length=2000)
    confidence_label: Literal["HIGH", "MEDIUM", "LOW"]
    risk_indicators: List[IndicatorItem] = Field(default_factory=list)
    counter_signals: List[IndicatorItem] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    policy_references: List[str] = Field(default_factory=list)
    human_review_required: bool = Field(default=True)
    model_name: str
    prompt_version: str = "1.0"
    policy_version: str = "1.0"
