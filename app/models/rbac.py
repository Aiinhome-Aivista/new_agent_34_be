from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base

class SystemUser(Base):
    __tablename__ = "system_users"

    user_id = Column(String(36), primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    full_name = Column(String(128), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False, default="INVESTIGATOR")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    assigned_cases = relationship("InvestigationCase", back_populates="assignee")
    review_decisions = relationship("ReviewDecision", back_populates="reviewer")


class RbacPermission(Base):
    __tablename__ = "rbac_permissions"

    permission_id = Column(String(64), primary_key=True)
    description = Column(String(255), nullable=False)
    category = Column(String(64), nullable=False)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role = Column(String(32), primary_key=True)
    permission_id = Column(String(64), ForeignKey("rbac_permissions.permission_id", ondelete="CASCADE"), primary_key=True)
