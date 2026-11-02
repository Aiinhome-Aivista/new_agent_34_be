"""
Phase 1: Knowledgebase Schema Migration & Seed Data
====================================================
Idempotent migration that:
  1. Creates entity_nodes, entity_relationships, fraud_rules,
     investigation_history_snapshots tables if not already present.
  2. Seeds the initial 5 base fraud rules (FR-001 to FR-005).

Run from Flask app context:
    python -m app.services.knowledgebase.migrate_knowledgebase
"""

import logging
from sqlalchemy import text, inspect
from app.extensions import db

logger = logging.getLogger("fraud_agent.kb_migrate")

# ---------------------------------------------------------------------------
# Base fraud rules seed data
# ---------------------------------------------------------------------------

BASE_FRAUD_RULES = [
    {
        "id": "FR-001",
        "rule_name": "User Identity Not Found",
        "description": (
            "Flags a case where the user_id or email address submitted during ingestion "
            "does not correspond to any record in the m_users master directory. "
            "Absence of identity verification is a primary synthetic identity risk signal."
        ),
        "category": "IDENTITY",
        "condition_evaluator": "eval_user_identity_exists",
        "threshold_value": 1.0,   # 1 = must exist; 0 = missing → triggered
        "threshold_unit": "exists_flag",
        "weight": 0.35,
        "severity": "CRITICAL",
        "is_active": True,
        "version": "1.0.0",
    },
    {
        "id": "FR-002",
        "rule_name": "Shared Device Multi-Account Ring",
        "description": (
            "Detects when a device fingerprint is associated with 3 or more distinct "
            "user accounts in the entity_relationships graph. Indicates potential "
            "multi-accounting, mule network, or device farm activity."
        ),
        "category": "DEVICE",
        "condition_evaluator": "eval_shared_device_accounts",
        "threshold_value": 3.0,
        "threshold_unit": "distinct_accounts",
        "weight": 0.25,
        "severity": "HIGH",
        "is_active": True,
        "version": "1.0.0",
    },
    {
        "id": "FR-003",
        "rule_name": "High Transaction Velocity",
        "description": (
            "Triggers when a user submits more than 5 payment transactions within "
            "a rolling 10-minute window. High velocity is a strong indicator of "
            "card testing, credential stuffing, or automated fraud bot activity."
        ),
        "category": "VELOCITY",
        "condition_evaluator": "eval_transaction_velocity",
        "threshold_value": 5.0,
        "threshold_unit": "transactions_per_10min",
        "weight": 0.20,
        "severity": "HIGH",
        "is_active": True,
        "version": "1.0.0",
    },
    {
        "id": "FR-004",
        "rule_name": "Elevated Chargeback Ratio",
        "description": (
            "Evaluates if the customer's historical chargeback count exceeds 2 "
            "confirmed disputes. High chargeback frequency is associated with "
            "friendly fraud, serial dispute abuse, or account takeover patterns."
        ),
        "category": "CHARGEBACK",
        "condition_evaluator": "eval_chargeback_count",
        "threshold_value": 2.0,
        "threshold_unit": "confirmed_chargebacks",
        "weight": 0.15,
        "severity": "MEDIUM",
        "is_active": True,
        "version": "1.0.0",
    },
    {
        "id": "FR-005",
        "rule_name": "High-Value Single Transaction",
        "description": (
            "Flags a single order or payment exceeding USD 2,000. High-value "
            "transactions require enhanced due diligence and are a common vector "
            "for stolen card monetization or money laundering."
        ),
        "category": "VALUE",
        "condition_evaluator": "eval_high_ticket_value",
        "threshold_value": 2000.0,
        "threshold_unit": "usd",
        "weight": 0.05,
        "severity": "MEDIUM",
        "is_active": True,
        "version": "1.0.0",
    },
]


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------

def _table_exists(conn, table_name: str) -> bool:
    """Check if a table already exists in the database."""
    result = conn.execute(
        text("SELECT COUNT(*) FROM information_schema.tables "
             "WHERE table_schema = DATABASE() AND table_name = :tbl"),
        {"tbl": table_name}
    ).scalar()
    return result > 0


def _add_index_safe(conn, ddl: str):
    """Execute an index creation statement, silently ignoring duplicate key name errors."""
    try:
        conn.execute(text(ddl))
        conn.commit()
    except Exception:
        pass  # Index already exists


# ---------------------------------------------------------------------------
# Main migration entry point
# ---------------------------------------------------------------------------

def migrate_knowledgebase_tables():
    """
    Idempotent: creates knowledgebase tables if absent, seeds base fraud rules.
    Safe to call on every app startup.
    """
    logger.info("[KB_MIGRATE] Starting knowledgebase schema migration...")

    with db.engine.connect() as conn:

        # ----------------------------------------------------------------
        # 1. entity_nodes
        # ----------------------------------------------------------------
        if not _table_exists(conn, "entity_nodes"):
            logger.info("[KB_MIGRATE] Creating entity_nodes table...")
            conn.execute(text("""
                CREATE TABLE entity_nodes (
                    id              VARCHAR(64)     NOT NULL,
                    entity_type     VARCHAR(32)     NOT NULL,
                    display_label   VARCHAR(255)    NULL,
                    properties_json JSON            NULL,
                    risk_score      FLOAT           NOT NULL DEFAULT 0.0,
                    is_flagged      TINYINT(1)      NOT NULL DEFAULT 0,
                    created_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """))
            conn.commit()
            _add_index_safe(conn, "CREATE INDEX idx_entity_type_flagged ON entity_nodes (entity_type, is_flagged)")
            _add_index_safe(conn, "CREATE INDEX idx_entity_risk ON entity_nodes (risk_score)")
            logger.info("[KB_MIGRATE] entity_nodes created.")
        else:
            logger.info("[KB_MIGRATE] entity_nodes already exists — skipping.")

        # ----------------------------------------------------------------
        # 2. entity_relationships
        # ----------------------------------------------------------------
        if not _table_exists(conn, "entity_relationships"):
            logger.info("[KB_MIGRATE] Creating entity_relationships table...")
            conn.execute(text("""
                CREATE TABLE entity_relationships (
                    id              BIGINT          NOT NULL AUTO_INCREMENT,
                    source_id       VARCHAR(64)     NOT NULL,
                    source_type     VARCHAR(32)     NOT NULL,
                    relation_type   VARCHAR(64)     NOT NULL,
                    target_id       VARCHAR(64)     NOT NULL,
                    target_type     VARCHAR(32)     NOT NULL,
                    weight          INT             NOT NULL DEFAULT 1,
                    properties_json JSON            NULL,
                    created_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """))
            conn.commit()
            _add_index_safe(conn, "CREATE INDEX idx_rel_source_type ON entity_relationships (source_id, relation_type)")
            _add_index_safe(conn, "CREATE INDEX idx_rel_target_type ON entity_relationships (target_id, relation_type)")
            _add_index_safe(conn, "CREATE INDEX idx_rel_target_source ON entity_relationships (target_id, source_id)")
            logger.info("[KB_MIGRATE] entity_relationships created.")
        else:
            logger.info("[KB_MIGRATE] entity_relationships already exists — skipping.")

        # ----------------------------------------------------------------
        # 3. fraud_rules
        # ----------------------------------------------------------------
        if not _table_exists(conn, "fraud_rules"):
            logger.info("[KB_MIGRATE] Creating fraud_rules table...")
            conn.execute(text("""
                CREATE TABLE fraud_rules (
                    id                  VARCHAR(32)     NOT NULL,
                    rule_name           VARCHAR(128)    NOT NULL,
                    description         TEXT            NULL,
                    category            VARCHAR(32)     NOT NULL,
                    condition_evaluator VARCHAR(64)     NOT NULL,
                    threshold_value     FLOAT           NOT NULL,
                    threshold_unit      VARCHAR(32)     NULL,
                    weight              FLOAT           NOT NULL DEFAULT 0.1,
                    severity            VARCHAR(16)     NOT NULL DEFAULT 'MEDIUM',
                    is_active           TINYINT(1)      NOT NULL DEFAULT 1,
                    version             VARCHAR(16)     NOT NULL DEFAULT '1.0.0',
                    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """))
            conn.commit()
            _add_index_safe(conn, "CREATE INDEX idx_rule_category_active ON fraud_rules (category, is_active)")
            logger.info("[KB_MIGRATE] fraud_rules table created.")
        else:
            logger.info("[KB_MIGRATE] fraud_rules already exists — skipping.")

        # ----------------------------------------------------------------
        # 4. investigation_history_snapshots
        # ----------------------------------------------------------------
        if not _table_exists(conn, "investigation_history_snapshots"):
            logger.info("[KB_MIGRATE] Creating investigation_history_snapshots table...")
            conn.execute(text("""
                CREATE TABLE investigation_history_snapshots (
                    id                      VARCHAR(36)     NOT NULL,
                    case_id                 VARCHAR(36)     NOT NULL,
                    user_id                 VARCHAR(64)     NULL,
                    merchant_id             VARCHAR(64)     NULL,
                    final_disposition       VARCHAR(32)     NOT NULL,
                    triggered_rule_ids      JSON            NULL,
                    final_risk_score        FLOAT           NULL,
                    confidence_label        VARCHAR(32)     NULL,
                    analyst_notes           TEXT            NULL,
                    policy_version_used     VARCHAR(32)     NULL,
                    rule_engine_version     VARCHAR(16)     NULL,
                    created_at              TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """))
            conn.commit()
            _add_index_safe(conn, "CREATE INDEX idx_hist_case ON investigation_history_snapshots (case_id)")
            _add_index_safe(conn, "CREATE INDEX idx_hist_user ON investigation_history_snapshots (user_id)")
            _add_index_safe(conn, "CREATE INDEX idx_hist_disposition ON investigation_history_snapshots (final_disposition)")
            _add_index_safe(conn, "CREATE INDEX idx_hist_merchant ON investigation_history_snapshots (merchant_id)")
            logger.info("[KB_MIGRATE] investigation_history_snapshots created.")
        else:
            logger.info("[KB_MIGRATE] investigation_history_snapshots already exists — skipping.")

    # ----------------------------------------------------------------
    # 5. Seed base fraud rules (idempotent INSERT IGNORE)
    # ----------------------------------------------------------------
    _seed_base_fraud_rules()

    logger.info("[KB_MIGRATE] Knowledgebase migration completed successfully.")


def _seed_base_fraud_rules():
    """
    Inserts the base 5 fraud rules if they don't already exist.
    Uses INSERT IGNORE so repeated calls are fully safe.
    """
    from app.models.knowledgebase import FraudRule

    existing_ids = {r.id for r in FraudRule.query.all()}
    inserted = 0

    for rule_data in BASE_FRAUD_RULES:
        if rule_data["id"] not in existing_ids:
            rule = FraudRule(**rule_data)
            db.session.add(rule)
            inserted += 1

    if inserted:
        db.session.commit()
        logger.info(f"[KB_MIGRATE] Seeded {inserted} base fraud rule(s).")
    else:
        logger.info("[KB_MIGRATE] All base fraud rules already present — skipping seed.")


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from app import create_app
    app = create_app()
    with app.app_context():
        migrate_knowledgebase_tables()
        print("Knowledgebase migration complete.")

