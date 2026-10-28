from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column, String, Integer, TIMESTAMP, Boolean, JSON,
    ForeignKey, Index
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

class InvestigationCase(db.Model):
    """Investigation case lifecycle and governance table."""
    __tablename__ = "investigation_cases"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    external_case_id = Column(String(100), nullable=True, index=True)
    trigger_type = Column(String(50), nullable=False)    # 'TRANSACTION_INVESTIGATION', 'MERCHANT_DISPUTE_SPIKE', etc.
    trigger_source = Column(String(100), nullable=False)  # 'EXTERNAL_FRAUD_SYSTEM', 'OPERATIONS_TOOL', 'ANALYST'
    trigger_reason = Column(String(500), nullable=False)
    priority = Column(String(20), nullable=False, default="MEDIUM")  # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    status = Column(String(40), nullable=False, default="RECEIVED")  # 'RECEIVED', 'COLLECTING_EVIDENCE', 'UNDER_INVESTIGATION', 'REQUIRES_REVIEW', 'ACTION_AUTHORIZED', 'CLOSED', 'ESCALATED'
    
    transaction_id = Column(String(100), nullable=True, index=True)
    user_id_ref = Column(String(100), nullable=True, index=True)
    merchant_id_ref = Column(String(100), nullable=True, index=True)
    
    created_by = Column(String(100), nullable=False, default="SYSTEM_TRIGGER")
    idempotency_key = Column(String(150), unique=True, nullable=False, index=True)
    
    started_at = Column(TIMESTAMP, nullable=True)
    completed_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    evidence_items = relationship("CaseEvidence", back_populates="case", cascade="all, delete-orphan")
    runs = relationship("InvestigationRun", back_populates="case", cascade="all, delete-orphan")
    recommendations = relationship("Recommendation", back_populates="case", cascade="all, delete-orphan")
    decisions = relationship("ReviewDecision", back_populates="case", cascade="all, delete-orphan")
    action_requests = relationship("ActionRequest", back_populates="case", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_cases_status_priority", "status", "priority"),
        Index("idx_cases_created_at", "created_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "external_case_id": self.external_case_id,
            "trigger_type": self.trigger_type,
            "trigger_source": self.trigger_source,
            "trigger_reason": self.trigger_reason,
            "priority": self.priority,
            "status": self.status,
            "transaction_id": self.transaction_id,
            "user_id_ref": self.user_id_ref,
            "merchant_id_ref": self.merchant_id_ref,
            "created_by": self.created_by,
            "idempotency_key": self.idempotency_key,
            "started_at": to_utc_iso(self.started_at),
            "completed_at": to_utc_iso(self.completed_at),
            "created_at": to_utc_iso(self.created_at),
            "updated_at": to_utc_iso(self.updated_at),
        }

class CaseEvidence(db.Model):
    """Forensic evidence items collected for an investigation case."""
    __tablename__ = "case_evidence"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    case_id = Column(String(36), ForeignKey("investigation_cases.id"), nullable=False)
    evidence_type = Column(String(50), nullable=False)     # 'TRANSACTION', 'USER_PROFILE', 'CHARGEBACK_HISTORY', 'GRAPH_NETWORK', 'DEVICE_GEO'
    source_system = Column(String(100), nullable=False)    # 'PAYMENT_CORE', 'KYC_SYSTEM', 'ARANGO_GRAPH', 'DEVICE_INTEL'
    source_reference = Column(String(200), nullable=True) # E.g. Record ID or query identifier
    retrieval_status = Column(String(30), nullable=False)  # 'COLLECTED', 'MISSING', 'UNAVAILABLE', 'FAILED'
    retrieved_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    normalized_payload = Column(JSON, nullable=True)
    content_hash = Column(String(64), nullable=True)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)

    case = relationship("InvestigationCase", back_populates="evidence_items")

    __table_args__ = (
        Index("idx_evidence_case_type", "case_id", "evidence_type"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "case_id": self.case_id,
            "evidence_type": self.evidence_type,
            "source_system": self.source_system,
            "source_reference": self.source_reference,
            "retrieval_status": self.retrieval_status,
            "retrieved_at": to_utc_iso(self.retrieved_at),
            "normalized_payload": self.normalized_payload,
            "content_hash": self.content_hash,
            "created_at": to_utc_iso(self.created_at),
        }

class InvestigationRun(db.Model):
    """Execution run tracking for LangGraph workflow."""
    __tablename__ = "investigation_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    case_id = Column(String(36), ForeignKey("investigation_cases.id"), nullable=False)
    run_number = Column(Integer, nullable=False, default=1)
    status = Column(String(30), nullable=False)  # 'STARTED', 'COMPLETED', 'FAILED', 'TIMED_OUT'
    workflow_version = Column(String(50), nullable=False, default="1.0.0")
    started_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    completed_at = Column(TIMESTAMP, nullable=True)
    error_code = Column(String(100), nullable=True)
    error_summary = Column(String(500), nullable=True)

    case = relationship("InvestigationCase", back_populates="runs")

    def to_dict(self):
        return {
            "id": self.id,
            "case_id": self.case_id,
            "run_number": self.run_number,
            "status": self.status,
            "workflow_version": self.workflow_version,
            "started_at": to_utc_iso(self.started_at),
            "completed_at": to_utc_iso(self.completed_at),
            "error_code": self.error_code,
            "error_summary": self.error_summary,
        }

class Recommendation(db.Model):
    """Structured LLM investigation recommendation."""
    __tablename__ = "recommendations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    case_id = Column(String(36), ForeignKey("investigation_cases.id"), nullable=False)
    investigation_run_id = Column(String(36), ForeignKey("investigation_runs.id"), nullable=True)
    assessment = Column(String(50), nullable=False)         # 'SUSPICIOUS', 'INCONCLUSIVE', 'NOT_SUBSTANTIATED'
    recommendation_type = Column(String(50), nullable=False) # 'HOLD_TRANSACTION', 'TEMPORARY_RESTRICTION', 'BLOCK_MERCHANT', 'MONITOR', 'NO_ACTION', 'ESCALATE'
    explanation = Column(String(2000), nullable=False)
    confidence_label = Column(String(30), nullable=False)   # 'HIGH', 'MEDIUM', 'LOW' (categorical qualitative label)
    human_review_required = Column(Boolean, default=True, nullable=False)
    model_name = Column(String(100), nullable=False)
    model_version = Column(String(50), nullable=True)
    prompt_version = Column(String(50), nullable=False, default="1.0")
    policy_version = Column(String(50), nullable=False, default="1.0")
    structured_result = Column(JSON, nullable=False)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)

    case = relationship("InvestigationCase", back_populates="recommendations")

    def to_dict(self):
        return {
            "id": self.id,
            "case_id": self.case_id,
            "investigation_run_id": self.investigation_run_id,
            "assessment": self.assessment,
            "recommendation_type": self.recommendation_type,
            "explanation": self.explanation,
            "confidence_label": self.confidence_label,
            "human_review_required": self.human_review_required,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "policy_version": self.policy_version,
            "structured_result": self.structured_result,
            "created_at": to_utc_iso(self.created_at),
        }

class RecommendationEvidence(db.Model):
    """Many-to-many relationship linking recommendations directly to specific evidence items."""
    __tablename__ = "recommendation_evidence"

    recommendation_id = Column(String(36), ForeignKey("recommendations.id"), primary_key=True)
    evidence_id = Column(String(36), ForeignKey("case_evidence.id"), primary_key=True)
    relationship_type = Column(String(50), nullable=False)  # 'RISK_INDICATOR', 'COUNTER_SIGNAL', 'SUPPORTING_FACT'

    def to_dict(self):
        return {
            "recommendation_id": self.recommendation_id,
            "evidence_id": self.evidence_id,
            "relationship_type": self.relationship_type,
        }
