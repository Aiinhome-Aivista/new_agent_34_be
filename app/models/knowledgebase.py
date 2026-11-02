"""
Phase 1: Knowledgebase Data Models
===================================
Four core tables supporting the Fraud Intelligence Architecture:
  1. entity_nodes           — Graph node registry (User, Device, IP, Payment Method, Merchant)
  2. entity_relationships   — Pre-computed directed edges between nodes (USED_DEVICE, SHARED_IP, etc.)
  3. fraud_rules            — Deterministic rule engine configuration with thresholds & weights
  4. investigation_history_snapshots — Analyst-resolved case outcomes for historical intelligence
"""

from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column, String, Integer, BigInteger, Float, TIMESTAMP, Boolean, JSON,
    Text, Index
)
from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc)


def generate_uuid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Layer 2: Entity Graph Store
# ---------------------------------------------------------------------------

class EntityNode(db.Model):
    """
    Represents a named entity in the fraud intelligence graph.
    Entity types: USER, DEVICE, IP_ADDRESS, PAYMENT_METHOD, MERCHANT
    Populated incrementally during batch ingestion (Pipeline A).
    """
    __tablename__ = "entity_nodes"

    id = Column(String(64), primary_key=True)                    # Stable natural key (e.g. user_id, device fingerprint, IP string)
    entity_type = Column(String(32), nullable=False, index=True) # USER | DEVICE | IP_ADDRESS | PAYMENT_METHOD | MERCHANT
    display_label = Column(String(255), nullable=True)           # Human-readable label for UI
    properties_json = Column(JSON, nullable=True)                # Flexible metadata (email, user_name, etc.)
    risk_score = Column(Float, default=0.0, nullable=False)      # Aggregate risk score 0.0–1.0
    is_flagged = Column(Boolean, default=False, nullable=False)  # Quick filter for known bad entities
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_entity_type_flagged", "entity_type", "is_flagged"),
        Index("idx_entity_risk", "risk_score"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "display_label": self.display_label,
            "properties": self.properties_json or {},
            "risk_score": self.risk_score,
            "is_flagged": self.is_flagged,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<EntityNode {self.entity_type}:{self.id}>"


class EntityRelationship(db.Model):
    """
    Represents a directed edge between two EntityNodes.
    Relation types: USED_DEVICE, CONNECTED_FROM_IP, SHARES_PAYMENT_METHOD,
                    PLACED_ORDER_AT, SUBMITTED_CHARGEBACK_AT
    Pre-computed during ingestion so investigations traverse the graph
    instead of scanning full transaction tables.
    """
    __tablename__ = "entity_relationships"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_id = Column(String(64), nullable=False)               # Source entity node id
    source_type = Column(String(32), nullable=False)             # Entity type of source
    relation_type = Column(String(64), nullable=False)           # Directed relationship label
    target_id = Column(String(64), nullable=False)               # Target entity node id
    target_type = Column(String(32), nullable=False)             # Entity type of target
    weight = Column(Integer, default=1, nullable=False)          # Co-occurrence count
    properties_json = Column(JSON, nullable=True)                # Edge metadata (timestamps, etc.)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        # Primary lookup: "All relationships originating from source X of type R"
        Index("idx_rel_source_type", "source_id", "relation_type"),
        # Reverse lookup: "All entities that point to target Y"
        Index("idx_rel_target_type", "target_id", "relation_type"),
        # Cross-traversal: find shared targets between sources
        Index("idx_rel_target_source", "target_id", "source_id"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "relation_type": self.relation_type,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "weight": self.weight,
            "properties": self.properties_json or {},
        }

    def __repr__(self):
        return f"<Rel {self.source_id} --[{self.relation_type}]--> {self.target_id}>"


# ---------------------------------------------------------------------------
# Layer 3: Deterministic Fraud Rule Engine
# ---------------------------------------------------------------------------

class FraudRule(db.Model):
    """
    Configurable deterministic fraud rule.
    Each rule maps to a named evaluator function in rule_engine.py.
    Rules are evaluated purely in code — never delegated to the LLM.
    LLM receives only the triggered rule set as structured input.
    """
    __tablename__ = "fraud_rules"

    id = Column(String(32), primary_key=True)                         # e.g. 'FR-001'
    rule_name = Column(String(128), nullable=False)                   # Human-readable name
    description = Column(Text, nullable=True)                         # Full description for UI
    category = Column(String(32), nullable=False, index=True)         # IDENTITY | DEVICE | VELOCITY | CHARGEBACK | VALUE
    condition_evaluator = Column(String(64), nullable=False)          # Function name in rule_engine.py
    threshold_value = Column(Float, nullable=False)                   # Numeric threshold
    threshold_unit = Column(String(32), nullable=True)                # e.g. 'count', 'percent', 'usd', 'per_minute'
    weight = Column(Float, nullable=False, default=0.1)               # Contribution to composite risk score (0.0–1.0)
    severity = Column(String(16), nullable=False, default="MEDIUM")   # CRITICAL | HIGH | MEDIUM | LOW
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    version = Column(String(16), default="1.0.0", nullable=False)
    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)
    updated_at = Column(TIMESTAMP, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_rule_category_active", "category", "is_active"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "rule_name": self.rule_name,
            "description": self.description,
            "category": self.category,
            "condition_evaluator": self.condition_evaluator,
            "threshold_value": self.threshold_value,
            "threshold_unit": self.threshold_unit,
            "weight": self.weight,
            "severity": self.severity,
            "is_active": self.is_active,
            "version": self.version,
        }

    def __repr__(self):
        return f"<FraudRule {self.id}: {self.rule_name} (active={self.is_active})>"


# ---------------------------------------------------------------------------
# Layer 4: Historical Intelligence Snapshots
# ---------------------------------------------------------------------------

class InvestigationHistorySnapshot(db.Model):
    """
    Stores the final analyst-validated outcome of each closed investigation.
    Pipeline A reads these records to build historical intelligence context.
    Pipeline B queries them during parallel retrieval to provide precedent.
    """
    __tablename__ = "investigation_history_snapshots"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    case_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(64), nullable=True, index=True)
    merchant_id = Column(String(64), nullable=True, index=True)

    # Final outcome set by analyst or automated decision gateway
    final_disposition = Column(String(32), nullable=False, index=True)
    # Values: FRAUD_CONFIRMED | FALSE_POSITIVE | INSUFFICIENT_EVIDENCE | DISMISSED | ACCOUNT_CLOSED

    # Which rules were triggered in this case (list of FR-XXX IDs)
    triggered_rule_ids = Column(JSON, nullable=True)

    # Risk score at time of closure
    final_risk_score = Column(Float, nullable=True)
    confidence_label = Column(String(32), nullable=True)   # HIGH | MEDIUM | LOW

    # Free-text notes from analyst (captured for historical context)
    analyst_notes = Column(Text, nullable=True)

    # Knowledgebase versioning — which snapshot was used during investigation
    policy_version_used = Column(String(32), nullable=True)
    rule_engine_version = Column(String(16), nullable=True)

    created_at = Column(TIMESTAMP, default=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_hist_disposition_user", "final_disposition", "user_id"),
        Index("idx_hist_merchant", "merchant_id"),
        Index("idx_hist_created", "created_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "case_id": self.case_id,
            "user_id": self.user_id,
            "merchant_id": self.merchant_id,
            "final_disposition": self.final_disposition,
            "triggered_rule_ids": self.triggered_rule_ids or [],
            "final_risk_score": self.final_risk_score,
            "confidence_label": self.confidence_label,
            "analyst_notes": self.analyst_notes,
            "policy_version_used": self.policy_version_used,
            "rule_engine_version": self.rule_engine_version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<HistorySnapshot case={self.case_id} disposition={self.final_disposition}>"

