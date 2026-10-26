from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

class ActionDispatchPayload(BaseModel):
    case_id: str
    decision_id: Optional[str] = None
    action_type: str
    target_entity_type: str
    target_entity_id: str
    parameters: Optional[Dict[str, Any]] = None
    idempotency_key: str
    approval_token: Optional[str] = None

class ActionExecutionResponse(BaseModel):
    execution_id: str
    request_id: str
    case_id: str
    executed_action: str
    execution_status: str
    execution_details: Optional[Dict[str, Any]] = None
    executed_at: datetime

    class Config:
        from_attributes = True
