from typing import List, Optional
from pydantic import BaseModel, EmailStr

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    full_name: str
    role: str
    permissions: List[str]

class UserProfile(BaseModel):
    user_id: str
    username: str
    full_name: str
    email: str
    role: str
    is_active: bool
    permissions: List[str]

class TokenData(BaseModel):
    user_id: Optional[str] = None
    username: Optional[str] = None
    role: Optional[str] = None
