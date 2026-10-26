from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models.transactional import User

class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        user = self.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return None
        return {
            "user_id": user.user_id,
            "external_user_id": user.external_user_id,
            "full_name": f"{user.first_name or ''} {user.last_name or ''}".strip(),
            "email": user.email,
            "phone": user.phone,
            "user_type": user.user_type,
            "status": user.status,
            "country_code": user.country_code,
            "kyc_status": user.kyc_status,
            "risk_level": user.risk_level,
            "risk_score": float(user.risk_score) if user.risk_score is not None else 0.0,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        }
