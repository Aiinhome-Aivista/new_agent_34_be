from datetime import datetime
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field
from app.schemas.investigation import StructuredAgentOutput

class EvidenceItemResponse(BaseModel):
    evidence_id: str
    case_id: str
    source_type: str
    record_identifier: str
    summary: str
    evidence_payload: Dict[str, Any]
    is_counter_signal: bool
    collected_at: datetime

    class Config:
        from_attributes = True

class InvestigationRunResponse(BaseModel):
    run_id: str
    case_id: str
    run_status: str
    agent_version: str
    model_name: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True

class FindingResponse(BaseModel):
    finding_id: str
    case_id: str
    assessment: str
    qualitative_confidence: str
    summary: str
    risk_indicators: List[Dict[str, Any]]
    counter_signals: List[Dict[str, Any]]
    missing_evidence: List[str]
    policy_references: List[Dict[str, Any]]
    created_at: datetime

    class Config:
        from_attributes = True

class RecommendationResponse(BaseModel):
    recommendation_id: str
    case_id: str
    recommended_action: str
    rationale: str
    human_review_required: bool
    auto_eligible: bool
    suggested_target_type: str
    suggested_target_id: str
    created_at: datetime

    class Config:
        from_attributes = True

class CaseSummary(BaseModel):
    case_id: str
    case_number: str
    trigger_type: str
    trigger_source: str
    trigger_reason: str
    priority: str
    status: str
    entity_type: str
    user_id: Optional[str] = None
    merchant_id: Optional[str] = None
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    assigned_to: Optional[str] = None
    assignee_name: Optional[str] = None
    decision_mode: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class CaseDetail(CaseSummary):
    evidence: List[EvidenceItemResponse] = Field(default_factory=list)
    runs: List[InvestigationRunResponse] = Field(default_factory=list)
    findings: List[FindingResponse] = Field(default_factory=list)
    recommendations: List[RecommendationResponse] = Field(default_factory=list)

class CaseAssignRequest(BaseModel):
    assigned_to: str = Field(..., description="User ID of analyst to assign case to")
