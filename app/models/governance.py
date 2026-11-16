from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column, String, Integer, TIMESTAMP, Boolean, JSON,
    Text, ForeignKey, Index
)
from sqlalchemy.orm import relationship
from app.extensions import db

def utc_now():
    return datetime.now(timezone.utc)

def to_utc_iso(dt):
    if not dt:
        return None
    iso = dt.isoformat()
    if not iso.endswith("Z") and not ("+" in iso[10:] or "-" in iso[10:]):
        return iso + "Z"
    return iso

def generate_uuid():
    return str(uuid.uuid4())

from werkzeug.security import generate_password_hash, check_password_hash

class AppUser(db.Model):
    """Application users (investigators, supervisors, auditors, admins). Distinct from customer users."""
    __tablename__ = "app_users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    identity_subject = Column(String(150), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    status = Column(String(30), nullable=False, default="ACTIVE")  # 'ACTIVE', 'INACTIVE', 'SUSPENDED'
    role = Column(String(50), nullable=False, default="INVESTIGATOR") # 'INVESTIGATOR', 'SENIOR_INVESTIGATOR', 'SUPERVISOR', 'ADMIN', 'AUDITOR'
    avatar = Column(String(10), nullable=True)
    badge = Column(String(50), nullable=True)
    badge_color = Column(String(20), nullable=True)
    description = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "id": self.id,
            "identity_subject": self.identity_subject,
            "display_name": self.display_name,
            "email": self.email,
            "status": self.status,
            "role": self.role,
            "avatar": self.avatar or (self.display_name[:2].upper() if self.display_name else "US"),
            "badge": self.badge or self.role,
            "badge_color": self.badge_color or "#FF5A14",
            "description": self.description or f"Role: {self.role}",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

class PolicyDocument(db.Model):
    """Approved organizational policy documents indexed in vector RAG and DB."""
    __tablename__ = "policy_documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_key = Column(String(100), unique=True, nullable=False, index=True)  # E.g. 'FRAUD_INVESTIGATION_SOP'
    title = Column(String(200), nullable=False)
    version = Column(String(30), nullable=False, default="1.0")
    category = Column(String(100), nullable=True, default="GENERAL") # 'CHARGEBACK', 'AUTO_ACTION', 'DEVICE_RING', 'HUMAN_REVIEW', 'IDENTITY'
    description = Column(String(500), nullable=True)
    content = Column(Text, nullable=True)
    action_impact = Column(String(100), nullable=True, default="ADVISORY") # 'BLOCKING', 'RESTRICTIVE', 'ADVISORY', 'MONITORING'
    status = Column(String(30), nullable=False, default="APPROVED")  # 'APPROVED', 'DRAFT', 'DEPRECATED'
    effective_from = Column(TIMESTAMP, nullable=True)
    effective_to = Column(TIMESTAMP, nullable=True)
    source_reference = Column(String(255), nullable=True)
    checksum = Column(String(64), nullable=True)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "document_key": self.document_key,
            "title": self.title,
            "version": self.version,
            "category": self.category or "GENERAL",
            "description": self.description or "",
            "content": self.content or "",
            "action_impact": self.action_impact or "ADVISORY",
            "status": self.status,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "source_reference": self.source_reference,
            "checksum": self.checksum,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

class FraudParameter(db.Model):
    """System fraud parameters and inspection thresholds by section."""
    __tablename__ = "fraud_parameters"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    parameter_key = Column(String(100), unique=True, nullable=False, index=True) # E.g. 'shared_device_cluster_limit'
    name = Column(String(150), nullable=False)                                   # E.g. 'Shared Hardware Device Cluster Limit'
    section = Column(String(50), nullable=False)                                 # 'USER_PROFILE', 'PAYMENT_TRANSACTION', 'ORDER_DETAILS', 'CHARGEBACK_DISPUTE', 'GRAPH_NETWORK', 'GATEWAY_RULE'
    data_type = Column(String(30), nullable=False, default="STRING")             # 'STRING', 'NUMBER', 'BOOLEAN', 'PERCENTAGE'
    threshold_value = Column(String(255), nullable=False)                        # E.g. '2', '50000', '1.0%', 'VERIFIED'
    risk_weight = Column(String(30), nullable=False, default="HIGH")             # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    description = Column(String(500), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "parameter_key": self.parameter_key,
            "name": self.name,
            "section": self.section,
            "data_type": self.data_type,
            "threshold_value": self.threshold_value,
            "risk_weight": self.risk_weight,
            "description": self.description,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

class ReviewDecision(db.Model):
    """Analyst review decisions."""
    __tablename__ = "review_decisions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    case_id = Column(String(36), ForeignKey("investigation_cases.id"), nullable=False)
    recommendation_id = Column(String(36), ForeignKey("recommendations.id"), nullable=True)
    reviewer_id = Column(String(36), ForeignKey("app_users.id"), nullable=False)
    decision = Column(String(50), nullable=False)  # 'APPROVE', 'REJECT', 'REQUEST_EVIDENCE', 'MONITOR', 'ESCALATE'
    reason = Column(String(1000), nullable=False)
    policy_reference = Column(String(200), nullable=True)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)

    case = relationship("InvestigationCase", back_populates="decisions")
    reviewer = relationship("AppUser")

    def to_dict(self):
        return {
            "id": self.id,
            "case_id": self.case_id,
            "recommendation_id": self.recommendation_id,
            "reviewer_id": self.reviewer_id,
            "reviewer_name": self.reviewer.display_name if self.reviewer else None,
            "decision": self.decision,
            "reason": self.reason,
            "policy_reference": self.policy_reference,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

class ActionRequest(db.Model):
    """Explicit authorized action execution records."""
    __tablename__ = "action_requests"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    case_id = Column(String(36), ForeignKey("investigation_cases.id"), nullable=False)
    action_type = Column(String(50), nullable=False)       # 'HOLD_TRANSACTION', 'TEMPORARY_RESTRICTION', 'BLOCK_MERCHANT', etc.
    decision_type = Column(String(50), nullable=False)     # 'HUMAN_APPROVED', 'POLICY_AUTO_AUTHORIZED'
    requested_by = Column(String(100), nullable=False)
    reviewer_id = Column(String(36), ForeignKey("app_users.id"), nullable=True)
    policy_reference = Column(String(200), nullable=True)
    idempotency_key = Column(String(150), unique=True, nullable=False, index=True)
    authorization_status = Column(String(30), nullable=False, default="AUTHORIZED") # 'AUTHORIZED', 'REJECTED'
    execution_status = Column(String(30), nullable=False, default="PENDING")         # 'PENDING', 'EXECUTING', 'COMPLETED', 'FAILED'
    target_reference = Column(String(200), nullable=False) # Transaction ID, User ID, or Merchant ID
    downstream_reference = Column(String(200), nullable=True) # Downstream response transaction/case ID
    error_code = Column(String(100), nullable=True)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    executed_at = Column(TIMESTAMP, nullable=True)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    case = relationship("InvestigationCase", back_populates="action_requests")
    reviewer = relationship("AppUser")

    def to_dict(self):
        return {
            "id": self.id,
            "case_id": self.case_id,
            "action_type": self.action_type,
            "decision_type": self.decision_type,
            "requested_by": self.requested_by,
            "reviewer_id": self.reviewer_id,
            "policy_reference": self.policy_reference,
            "idempotency_key": self.idempotency_key,
            "authorization_status": self.authorization_status,
            "execution_status": self.execution_status,
            "target_reference": self.target_reference,
            "downstream_reference": self.downstream_reference,
            "error_code": self.error_code,
            "created_at": to_utc_iso(self.created_at),
            "executed_at": to_utc_iso(self.executed_at),
            "updated_at": to_utc_iso(self.updated_at),
        }

class AuditEvent(db.Model):
    """Tamper-evident audit event log."""
    __tablename__ = "audit_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    case_id = Column(String(36), ForeignKey("investigation_cases.id"), nullable=True)
    user_id = Column(String(36), nullable=True, index=True)
    actor_type = Column(String(50), nullable=False)  # 'SYSTEM_TRIGGER', 'AGENT_WORKFLOW', 'HUMAN_REVIEWER', 'ACTION_SERVICE'
    actor_id = Column(String(100), nullable=True)
    event_type = Column(String(100), nullable=False) # 'TRIGGER_RECEIVED', 'EVIDENCE_COLLECTED', 'RECOMMENDATION_GENERATED', 'DECISION_SUBMITTED', 'ACTION_EXECUTED'
    event_timestamp = Column(TIMESTAMP, default=utc_now, nullable=False)
    correlation_id = Column(String(100), nullable=False, index=True)
    details = Column(JSON, nullable=True)
    event_hash = Column(String(64), nullable=True)

    __table_args__ = (
        Index("idx_audit_case_time", "case_id", "event_timestamp"),
        Index("idx_audit_user_time", "user_id", "event_timestamp"),
        Index("idx_audit_event_type", "event_type"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "case_id": self.case_id,
            "user_id": self.user_id,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "event_type": self.event_type,
            "event_timestamp": to_utc_iso(self.event_timestamp),
            "correlation_id": self.correlation_id,
            "details": self.details,
            "event_hash": self.event_hash,
        }

class IntegrationConfig(db.Model):
    """Non-secret integration endpoints and connectivity metadata."""
    __tablename__ = "integration_configs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    integration_name = Column(String(100), unique=True, nullable=False) # 'MYSQL', 'REDIS', 'CHROMADB', 'ARANGODB', 'OLLAMA'
    base_url = Column(String(255), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    health_status = Column(String(30), default="UNKNOWN", nullable=False) # 'HEALTHY', 'DEGRADED', 'UNAVAILABLE', 'DISABLED'
    last_checked_at = Column(TIMESTAMP, nullable=True)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "integration_name": self.integration_name,
            "base_url": self.base_url,
            "enabled": self.enabled,
            "health_status": self.health_status,
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

class AppNotification(db.Model):
    """In-app notifications for senior investigators, admins, and compliance teams."""
    __tablename__ = "app_notifications"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    recipient_role = Column(String(50), nullable=True) # E.g. 'ADMIN', 'SENIOR_INVESTIGATOR', 'ALL'
    recipient_user_id = Column(String(36), nullable=True) # Direct user id if targeted
    case_id = Column(String(36), ForeignKey("investigation_cases.id"), nullable=True)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    sender_name = Column(String(100), nullable=True)
    sender_role = Column(String(50), nullable=True)
    sender_email = Column(String(255), nullable=True)
    target_user_id = Column(String(100), nullable=True)
    category = Column(String(50), nullable=False, default="ESCALATION") # 'ESCALATION', 'ACTION', 'SYSTEM'
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)

    case = relationship("InvestigationCase")

    def to_dict(self):
        return {
            "id": self.id,
            "recipient_role": self.recipient_role,
            "recipient_user_id": self.recipient_user_id,
            "case_id": self.case_id,
            "title": self.title,
            "message": self.message,
            "sender_name": self.sender_name,
            "sender_role": self.sender_role,
            "sender_email": self.sender_email,
            "target_user_id": self.target_user_id,
            "category": self.category,
            "is_read": self.is_read,
            "created_at": to_utc_iso(self.created_at),
        }

class MicroserviceApiRegistry(db.Model):
    """
    Dynamic Enterprise Microservice API Connector Registry.
    Decouples inter-service REST endpoints, headers, auth tokens, sample payloads,
    and mock/live runtime execution flags from code into persistent storage.
    """
    __tablename__ = "microservice_api_registry"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    service_key = Column(String(80), unique=True, nullable=False, index=True)
    service_name = Column(String(150), nullable=False)
    service_category = Column(String(60), nullable=False)  # 'IDENTITY', 'PAYMENT', 'ORDER', 'DEVICE', 'DISPUTE', 'ACTION', 'NOTIFICATION'
    description = Column(Text, nullable=True)

    # HTTP Connectivity Details
    http_method = Column(String(10), nullable=False, default="GET")  # 'GET', 'POST', 'PUT', 'DELETE', 'PATCH'
    base_url = Column(String(255), nullable=False)
    endpoint_path = Column(String(255), nullable=False)

    # Authentication & Security
    auth_type = Column(String(40), nullable=False, default="BEARER_TOKEN")  # 'NONE', 'BEARER_TOKEN', 'API_KEY', 'BASIC_AUTH', 'CUSTOM_HEADER'
    auth_header_key = Column(String(80), nullable=True, default="Authorization")
    auth_token_encrypted = Column(Text, nullable=True)
    token_preview = Column(String(60), nullable=True)
    custom_headers = Column(JSON, nullable=True)

    # Payload & Response Schemas (JSON)
    sample_payload = Column(JSON, nullable=True)
    sample_response = Column(JSON, nullable=True)
    payload_schema = Column(Text, nullable=True)

    # Runtime Execution & Simulation Controls
    timeout_ms = Column(Integer, nullable=False, default=5000)
    retry_count = Column(Integer, nullable=False, default=2)
    is_mock_enabled = Column(Boolean, nullable=False, default=True)  # True = mock simulation, False = live network
    is_active = Column(Boolean, nullable=False, default=True)

    # Health & Telemetry
    health_status = Column(String(30), nullable=False, default="HEALTHY")  # 'HEALTHY', 'DEGRADED', 'UNAVAILABLE', 'UNKNOWN'
    last_tested_at = Column(TIMESTAMP, nullable=True)
    last_latency_ms = Column(Integer, nullable=True)
    last_status_code = Column(Integer, nullable=True)
    last_error_message = Column(Text, nullable=True)

    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)
    updated_by = Column(String(100), nullable=True)

    def mask_token(self, token: str) -> str:
        if not token:
            return ""
        if token.startswith("ENV:"):
            return token
        if len(token) <= 8:
            return "••••••••"
        return f"{token[:4]}••••••••{token[-4:]}"

    def to_dict(self, include_sensitive: bool = False):
        token_display = self.token_preview
        if not token_display and self.auth_token_encrypted:
            token_display = self.mask_token(self.auth_token_encrypted)

        data = {
            "id": self.id,
            "service_key": self.service_key,
            "service_name": self.service_name,
            "service_category": self.service_category,
            "description": self.description or "",
            "http_method": self.http_method,
            "base_url": self.base_url,
            "endpoint_path": self.endpoint_path,
            "full_url": f"{self.base_url.rstrip('/')}/{self.endpoint_path.lstrip('/')}" if self.base_url and self.endpoint_path else "",
            "auth_type": self.auth_type,
            "auth_header_key": self.auth_header_key or "Authorization",
            "token_preview": token_display or "None configured",
            "custom_headers": self.custom_headers or {},
            "sample_payload": self.sample_payload,
            "sample_response": self.sample_response,
            "payload_schema": self.payload_schema or "",
            "timeout_ms": self.timeout_ms,
            "retry_count": self.retry_count,
            "is_mock_enabled": self.is_mock_enabled,
            "is_active": self.is_active,
            "health_status": self.health_status,
            "last_tested_at": to_utc_iso(self.last_tested_at),
            "last_latency_ms": self.last_latency_ms,
            "last_status_code": self.last_status_code,
            "last_error_message": self.last_error_message,
            "created_at": to_utc_iso(self.created_at),
            "updated_at": to_utc_iso(self.updated_at),
            "updated_by": self.updated_by,
        }
        if include_sensitive:
            data["auth_token_raw"] = self.auth_token_encrypted
        return data
