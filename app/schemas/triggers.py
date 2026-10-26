from typing import Optional
from pydantic import BaseModel, Field

class ExternalTriggerPayload(BaseModel):
    case_id: Optional[str] = Field(None, description="External case identifier if present")
    trigger_type: str = Field(..., description="e.g. TRANSACTION_INVESTIGATION, VELOCITY_EXCEEDED, CHARGEBACK_ALERT")
    trigger_source: str = Field("EXTERNAL_FRAUD_SYSTEM", description="Originating system or service")
    trigger_reason: str = Field(..., description="Reason why investigation was triggered")
    priority: str = Field("MEDIUM", description="LOW, MEDIUM, HIGH, CRITICAL")
    user_id: Optional[str] = None
    merchant_id: Optional[str] = None
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    entity_type: Optional[str] = Field("TRANSACTION", description="TRANSACTION, USER, MERCHANT, ORDER")
    decision_mode: Optional[str] = Field("ADVISOR", description="ADVISOR, CONDITIONAL_AUTOMATION, POLICY_CONTROLLED")

class IngestTriggerResponse(BaseModel):
    status: str
    message: str
    case_id: str
    case_number: str
    is_new: bool
