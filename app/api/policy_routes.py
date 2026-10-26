from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.platform import PolicyDocument
from app.schemas.policies import PolicyDocumentResponse, PolicySearchRequest, PolicySearchHit
from app.schemas.rbac import UserProfile
from app.auth.dependencies import get_current_user, require_permission
from app.tools.policy_rag import PolicyRAGService

router = APIRouter(prefix="/policies", tags=["Policy RAG & Knowledge Base"])

@router.get("", response_model=List[PolicyDocumentResponse])
def get_policies(
    current_user: UserProfile = Depends(require_permission("policy.view")),
    db: Session = Depends(get_db)
):
    policies = db.query(PolicyDocument).filter(PolicyDocument.is_active == True).all()
    return policies

@router.post("/search", response_model=List[PolicySearchHit])
def search_policies(
    payload: PolicySearchRequest,
    current_user: UserProfile = Depends(require_permission("policy.view")),
    db: Session = Depends(get_db)
):
    rag = PolicyRAGService(db)
    results = rag.search_policy(query=payload.query, limit=payload.limit)
    return results
