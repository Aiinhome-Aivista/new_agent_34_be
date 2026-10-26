from typing import List, Callable
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth.security import decode_access_token
from app.models.rbac import SystemUser, RolePermission
from app.schemas.rbac import UserProfile

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"/api/v1/auth/login")

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> UserProfile:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = decode_access_token(token)
    if not payload:
        raise credentials_exception
    
    username: str = payload.get("sub")
    if not username:
        raise credentials_exception
    
    user = db.query(SystemUser).filter(SystemUser.username == username, SystemUser.is_active == True).first()
    if not user:
        raise credentials_exception
    
    # Load user's role permissions
    role_perms = db.query(RolePermission.permission_id).filter(RolePermission.role == user.role).all()
    permissions = [rp[0] for rp in role_perms]
    
    return UserProfile(
        user_id=user.user_id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        permissions=permissions
    )

def require_permission(required_permission: str) -> Callable:
    def dependency(current_user: UserProfile = Depends(get_current_user)) -> UserProfile:
        if required_permission not in current_user.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: action requires '{required_permission}' permission"
            )
        return current_user
    return dependency

def require_role(allowed_roles: List[str]) -> Callable:
    def dependency(current_user: UserProfile = Depends(get_current_user)) -> UserProfile:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden for role '{current_user.role}'"
            )
        return current_user
    return dependency
