from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

class DecisionSubmitRequest(BaseModel):
    decision_type: str = Field(..., description="HUMAN_APPROVED, HUMAN_REJECTED, HUMAN_MODIFIED, ESCALATED")
    selected_action: str = Field(..., description="Action to take (e.g. TEMPORARY_RESTRICTION, MONITOR, NO_ACTION)")
    decision_rationale: str = Field(..., description="Reviewer justification and conditions")
    conditions: Optional[Dict[str, Any]] = None
    policy_reference: Optional[str] = None

class ReviewDecisionResponse(BaseModel):
    decision_id: str
    case_id: str
    reviewer_id: str
    reviewer_name: Optional[str] = None
    decision_type: str
    selected_action: str
    decision_rationale: str
    conditions: Optional[Dict[str, Any]] = None
    policy_reference: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
