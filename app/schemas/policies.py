from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel

class PolicyDocumentResponse(BaseModel):
    policy_id: str
    policy_code: str
    title: str
    category: str
    version: str
    content: str
    metadata_json: Optional[Dict[str, Any]] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class PolicySearchRequest(BaseModel):
    query: str
    limit: int = 3
    category: Optional[str] = None

class PolicySearchHit(BaseModel):
    policy_code: str
    title: str
    category: str
    score: float
    snippet: str
