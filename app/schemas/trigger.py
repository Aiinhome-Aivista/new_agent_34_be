from typing import Optional, Literal
from pydantic import BaseModel, Field, model_validator

class TriggerRequest(BaseModel):
    """Trigger contract received from external fraud services or operations."""
    trigger_type: Literal[
        "TRANSACTION_INVESTIGATION",
        "MERCHANT_DISPUTE_SPIKE",
        "USER_TAKEOVER_ALERT",
        "CHARGEBACK_THRESHOLD_EXCEEDED",
        "OPERATIONAL_REQUEST"
    ] = Field(..., description="Classification of the trigger")
    
    trigger_source: str = Field(..., min_length=2, max_length=100, description="Caller system identifier")
    trigger_reason: str = Field(..., min_length=5, max_length=500, description="Authorized rationale for investigation")
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = Field(default="MEDIUM")
    idempotency_key: str = Field(..., min_length=8, max_length=150, description="Caller-generated unique key for deduplication")
    
    transaction_id: Optional[str] = Field(None, max_length=100)
    user_id: Optional[str] = Field(None, max_length=100)
    merchant_id: Optional[str] = Field(None, max_length=100)

    @model_validator(mode="after")
    def validate_entity_reference(self):
        """Require at least one valid entity target (transaction, user, or merchant)."""
        if not any([self.transaction_id, self.user_id, self.merchant_id]):
            raise ValueError("At least one entity reference (transaction_id, user_id, or merchant_id) must be provided.")
        return self

class TriggerResponse(BaseModel):
    case_id: str
    status: str
    priority: str
    idempotency_key: str
    is_duplicate: bool
    message: str
    created_at: str
