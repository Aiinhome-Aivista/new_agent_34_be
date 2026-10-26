from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.platform import InvestigationCase, EvidenceRecord, InvestigationRun, InvestigationFinding, InvestigationRecommendation
from app.models.rbac import SystemUser
from app.schemas.cases import CaseSummary, CaseDetail, CaseAssignRequest
from app.schemas.rbac import UserProfile
from app.auth.dependencies import get_current_user, require_permission
from app.api.trigger_routes import _execute_investigation_background

router = APIRouter(prefix="/cases", tags=["Case Management"])

@router.get("", response_model=List[CaseSummary])
def list_cases(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    current_user: UserProfile = Depends(require_permission("case.view")),
    db: Session = Depends(get_db)
):
    query = db.query(InvestigationCase)
    if status:
        query = query.filter(InvestigationCase.status == status)
    if priority:
        query = query.filter(InvestigationCase.priority == priority)

    cases = query.order_by(InvestigationCase.created_at.desc()).all()
    results = []
    for c in cases:
        assignee_name = None
        if c.assigned_to:
            u = db.query(SystemUser).filter(SystemUser.user_id == c.assigned_to).first()
            if u:
                assignee_name = u.full_name
        
        item = CaseSummary.model_validate(c)
        item.assignee_name = assignee_name
        results.append(item)
    return results

@router.get("/{case_id}", response_model=CaseDetail)
def get_case(
    case_id: str,
    current_user: UserProfile = Depends(require_permission("case.view")),
    db: Session = Depends(get_db)
):
    case = db.query(InvestigationCase).filter(InvestigationCase.case_id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    assignee_name = None
    if case.assigned_to:
        u = db.query(SystemUser).filter(SystemUser.user_id == case.assigned_to).first()
        if u:
            assignee_name = u.full_name

    detail = CaseDetail.model_validate(case)
    detail.assignee_name = assignee_name
    return detail

@router.post("/{case_id}/investigate")
def trigger_investigation(
    case_id: str,
    background_tasks: BackgroundTasks,
    current_user: UserProfile = Depends(require_permission("case.investigate")),
    db: Session = Depends(get_db)
):
    case = db.query(InvestigationCase).filter(InvestigationCase.case_id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    trigger_dict = {
        "case_id": case.case_id,
        "trigger_type": case.trigger_type,
        "trigger_source": case.trigger_source,
        "trigger_reason": case.trigger_reason,
        "priority": case.priority,
        "user_id": case.user_id,
        "merchant_id": case.merchant_id,
        "order_id": case.order_id,
        "payment_id": case.payment_id,
        "decision_mode": case.decision_mode
    }

    background_tasks.add_task(_execute_investigation_background, case_id, trigger_dict)

    return {
        "status": "QUEUED",
        "message": f"Investigation run queued for case {case.case_number}",
        "case_id": case_id
    }

@router.post("/{case_id}/assign")
def assign_case(
    case_id: str,
    payload: CaseAssignRequest,
    current_user: UserProfile = Depends(require_permission("case.assign")),
    db: Session = Depends(get_db)
):
    case = db.query(InvestigationCase).filter(InvestigationCase.case_id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    analyst = db.query(SystemUser).filter(SystemUser.user_id == payload.assigned_to).first()
    if not analyst:
        raise HTTPException(status_code=404, detail="Analyst user not found")

    case.assigned_to = payload.assigned_to
    db.commit()

    return {
        "status": "ASSIGNED",
        "case_id": case_id,
        "assigned_to": analyst.full_name
    }
