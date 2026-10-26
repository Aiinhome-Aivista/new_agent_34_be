from typing import Optional, Literal
from pydantic import BaseModel, Field

class ReviewDecisionRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT", "REQUEST_EVIDENCE", "MONITOR", "ESCALATE"]
    reason: str = Field(..., min_length=5, max_length=1000)
    policy_reference: Optional[str] = None
    reviewer_id: str = Field(..., description="Identity of authenticated reviewer")

class ActionExecuteRequest(BaseModel):
    case_id: str
    action_type: Literal[
        "HOLD_TRANSACTION",
        "TEMPORARY_RESTRICTION",
        "BLOCK_USER",
        "BLOCK_MERCHANT",
        "SEND_NOTIFICATION",
        "NO_ACTION",
        "ESCALATE"
    ]
    target_reference: str
    idempotency_key: str
    reviewer_id: Optional[str] = None
    policy_reference: Optional[str] = None
