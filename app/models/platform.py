from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.models.base import Base

class InvestigationCase(Base):
    __tablename__ = "investigation_cases"

    case_id = Column(String(36), primary_key=True)
    case_number = Column(String(32), unique=True, nullable=False)
    trigger_type = Column(String(64), nullable=False)
    trigger_source = Column(String(64), nullable=False)
    trigger_reason = Column(Text, nullable=False)
    priority = Column(String(20), nullable=False, default="MEDIUM")
    status = Column(String(32), nullable=False, default="INTAKE")
    entity_type = Column(String(32), nullable=False, default="TRANSACTION")
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=True)
    merchant_id = Column(String(64), nullable=True)
    order_id = Column(String(36), ForeignKey("orders.order_id"), nullable=True)
    payment_id = Column(String(36), ForeignKey("payments.payment_id"), nullable=True)
    assigned_to = Column(String(36), ForeignKey("system_users.user_id"), nullable=True)
    decision_mode = Column(String(32), nullable=False, default="ADVISOR")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    # Relationships
    assignee = relationship("SystemUser", back_populates="assigned_cases")
    runs = relationship("InvestigationRun", back_populates="case", cascade="all, delete-orphan")
    evidence = relationship("EvidenceRecord", back_populates="case", cascade="all, delete-orphan")
    findings = relationship("InvestigationFinding", back_populates="case", cascade="all, delete-orphan")
    recommendations = relationship("InvestigationRecommendation", back_populates="case", cascade="all, delete-orphan")
    decisions = relationship("ReviewDecision", back_populates="case", cascade="all, delete-orphan")
    action_requests = relationship("ActionRequest", back_populates="case", cascade="all, delete-orphan")


class InvestigationRun(Base):
    __tablename__ = "investigation_runs"

    run_id = Column(String(36), primary_key=True)
    case_id = Column(String(36), ForeignKey("investigation_cases.case_id", ondelete="CASCADE"), nullable=False)
    run_status = Column(String(32), nullable=False, default="RUNNING")
    agent_version = Column(String(32), nullable=False, default="1.0.0")
    model_name = Column(String(64), nullable=False, default="qwen2.5:7b")
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    state_checkpoint = Column(JSON, nullable=True)

    case = relationship("InvestigationCase", back_populates="runs")
    evidence = relationship("EvidenceRecord", back_populates="run")
    findings = relationship("InvestigationFinding", back_populates="run")


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"

    evidence_id = Column(String(36), primary_key=True)
    case_id = Column(String(36), ForeignKey("investigation_cases.case_id", ondelete="CASCADE"), nullable=False)
    run_id = Column(String(36), ForeignKey("investigation_runs.run_id", ondelete="SET NULL"), nullable=True)
    source_type = Column(String(64), nullable=False)
    record_identifier = Column(String(128), nullable=False)
    summary = Column(String(255), nullable=False)
    evidence_payload = Column(JSON, nullable=False)
    is_counter_signal = Column(Boolean, nullable=False, default=False)
    collected_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    case = relationship("InvestigationCase", back_populates="evidence")
    run = relationship("InvestigationRun", back_populates="evidence")


class InvestigationFinding(Base):
    __tablename__ = "investigation_findings"

    finding_id = Column(String(36), primary_key=True)
    case_id = Column(String(36), ForeignKey("investigation_cases.case_id", ondelete="CASCADE"), nullable=False)
    run_id = Column(String(36), ForeignKey("investigation_runs.run_id", ondelete="SET NULL"), nullable=True)
    assessment = Column(String(32), nullable=False, default="INCONCLUSIVE")
    qualitative_confidence = Column(String(20), nullable=False, default="MEDIUM")
    summary = Column(Text, nullable=False)
    risk_indicators = Column(JSON, nullable=False)
    counter_signals = Column(JSON, nullable=False)
    missing_evidence = Column(JSON, nullable=False)
    policy_references = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    case = relationship("InvestigationCase", back_populates="findings")
    run = relationship("InvestigationRun", back_populates="findings")
    recommendations = relationship("InvestigationRecommendation", back_populates="finding")


class InvestigationRecommendation(Base):
    __tablename__ = "investigation_recommendations"

    recommendation_id = Column(String(36), primary_key=True)
    case_id = Column(String(36), ForeignKey("investigation_cases.case_id", ondelete="CASCADE"), nullable=False)
    finding_id = Column(String(36), ForeignKey("investigation_findings.finding_id", ondelete="SET NULL"), nullable=True)
    recommended_action = Column(String(64), nullable=False)
    rationale = Column(Text, nullable=False)
    human_review_required = Column(Boolean, nullable=False, default=True)
    auto_eligible = Column(Boolean, nullable=False, default=False)
    suggested_target_type = Column(String(32), nullable=False, default="USER")
    suggested_target_id = Column(String(128), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    case = relationship("InvestigationCase", back_populates="recommendations")
    finding = relationship("InvestigationFinding", back_populates="recommendations")


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    decision_id = Column(String(36), primary_key=True)
    case_id = Column(String(36), ForeignKey("investigation_cases.case_id", ondelete="CASCADE"), nullable=False)
    reviewer_id = Column(String(36), ForeignKey("system_users.user_id"), nullable=False)
    decision_type = Column(String(32), nullable=False)
    selected_action = Column(String(64), nullable=False)
    decision_rationale = Column(Text, nullable=False)
    conditions = Column(JSON, nullable=True)
    policy_reference = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    case = relationship("InvestigationCase", back_populates="decisions")
    reviewer = relationship("SystemUser", back_populates="review_decisions")
    action_requests = relationship("ActionRequest", back_populates="decision")


class ActionRequest(Base):
    __tablename__ = "action_requests"

    request_id = Column(String(36), primary_key=True)
    case_id = Column(String(36), ForeignKey("investigation_cases.case_id", ondelete="CASCADE"), nullable=False)
    decision_id = Column(String(36), ForeignKey("review_decisions.decision_id", ondelete="SET NULL"), nullable=True)
    action_type = Column(String(64), nullable=False)
    target_entity_type = Column(String(32), nullable=False)
    target_entity_id = Column(String(128), nullable=False)
    parameters = Column(JSON, nullable=True)
    idempotency_key = Column(String(128), unique=True, nullable=False)
    request_status = Column(String(32), nullable=False, default="PENDING")
    requested_by = Column(String(64), nullable=False)
    approval_token = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    case = relationship("InvestigationCase", back_populates="action_requests")
    decision = relationship("ReviewDecision", back_populates="action_requests")
    executions = relationship("ActionExecution", back_populates="request", cascade="all, delete-orphan")


class ActionExecution(Base):
    __tablename__ = "action_executions"

    execution_id = Column(String(36), primary_key=True)
    request_id = Column(String(36), ForeignKey("action_requests.request_id", ondelete="CASCADE"), nullable=False)
    executed_action = Column(String(64), nullable=False)
    execution_status = Column(String(32), nullable=False, default="SUCCESS")
    execution_details = Column(JSON, nullable=True)
    executed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    request = relationship("ActionRequest", back_populates="executions")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    event_id = Column(String(36), primary_key=True)
    case_id = Column(String(36), nullable=True)
    actor_id = Column(String(64), nullable=False)
    actor_type = Column(String(32), nullable=False)
    event_type = Column(String(64), nullable=False)
    event_description = Column(String(255), nullable=False)
    event_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PolicyDocument(Base):
    __tablename__ = "policy_documents"

    policy_id = Column(String(36), primary_key=True)
    policy_code = Column(String(32), unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    category = Column(String(64), nullable=False)
    version = Column(String(16), nullable=False, default="1.0")
    content = Column(Text, nullable=False)
    metadata_json = Column("metadata", JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
