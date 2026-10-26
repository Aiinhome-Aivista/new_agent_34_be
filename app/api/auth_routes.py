from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.rbac import SystemUser, RolePermission
from app.schemas.rbac import LoginRequest, TokenResponse, UserProfile
from app.auth.security import verify_password, create_access_token
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication & RBAC"])

@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(SystemUser).filter(SystemUser.username == payload.username, SystemUser.is_active == True).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
    
    # Fetch permissions
    role_perms = db.query(RolePermission.permission_id).filter(RolePermission.role == user.role).all()
    permissions = [rp[0] for rp in role_perms]

    token = create_access_token(data={"sub": user.username, "role": user.role, "uid": user.user_id})

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.user_id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        permissions=permissions
    )

@router.get("/me", response_model=UserProfile)
def get_me(current_user: UserProfile = Depends(get_current_user)):
    return current_user
