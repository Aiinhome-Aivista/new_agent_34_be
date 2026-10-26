from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.platform import AuditEvent
from app.schemas.rbac import UserProfile
from app.auth.dependencies import get_current_user, require_permission

router = APIRouter(prefix="/audit", tags=["Compliance & Audit"])

@router.get("/case/{case_id}")
def get_case_audit_trail(
    case_id: str,
    current_user: UserProfile = Depends(require_permission("audit.view")),
    db: Session = Depends(get_db)
):
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.case_id == case_id)
        .order_by(AuditEvent.created_at.asc())
        .all()
    )
    return [
        {
            "event_id": e.event_id,
            "case_id": e.case_id,
            "actor_id": e.actor_id,
            "actor_type": e.actor_type,
            "event_type": e.event_type,
            "event_description": e.event_description,
            "event_payload": e.event_payload,
            "created_at": e.created_at.isoformat()
        }
        for e in events
    ]

@router.get("/recent")
def get_recent_audit_events(
    limit: int = 50,
    current_user: UserProfile = Depends(require_permission("audit.view")),
    db: Session = Depends(get_db)
):
    events = (
        db.query(AuditEvent)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "event_id": e.event_id,
            "case_id": e.case_id,
            "actor_id": e.actor_id,
            "actor_type": e.actor_type,
            "event_type": e.event_type,
            "event_description": e.event_description,
            "event_payload": e.event_payload,
            "created_at": e.created_at.isoformat()
        }
        for e in events
    ]
