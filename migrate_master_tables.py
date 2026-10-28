#!/usr/bin/env python3
"""
Migration script for Master Data Tables (`m_users`, `m_orders`, `m_payments`, `m_chargebacks`)
and adding `user_id` column to `audit_events`.
"""

import sys
from pathlib import Path
root_dir = str(Path(__file__).resolve().parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from sqlalchemy import text, inspect
from app import create_app
from app.extensions import db

def run_migration():
    app = create_app()
    with app.app_context():
        print("Starting Master Tables and Audit Events migration...")
        
        # 1. Create m_* tables using db.create_all() or direct SQL
        db.create_all()
        print("Ensured all SQLAlchemy models (including m_* tables) are registered.")

        # 2. Check if user_id exists in audit_events
        insp = inspect(db.engine)
        columns = [c["name"] for c in insp.get_columns("audit_events")]
        if "user_id" not in columns:
            print("Adding user_id column to audit_events table...")
            try:
                db.session.execute(text("ALTER TABLE audit_events ADD COLUMN user_id VARCHAR(36) NULL AFTER case_id;"))
                db.session.commit()
                print("Added user_id column to audit_events successfully.")
            except Exception as e:
                db.session.rollback()
                print(f"Notice adding user_id column: {e}")

            try:
                db.session.execute(text("CREATE INDEX idx_audit_user_time ON audit_events (user_id, event_timestamp);"))
                db.session.commit()
                print("Created index idx_audit_user_time on audit_events.")
            except Exception as e:
                db.session.rollback()
                print(f"Notice creating idx_audit_user_time: {e}")
        else:
            print("user_id column already exists in audit_events table.")

        # 3. Print verified table names
        table_names = insp.get_table_names()
        print(f"Database tables verified: {[t for t in table_names if t.startswith('m_') or t == 'audit_events']}")
        print("Migration completed successfully!")

if __name__ == "__main__":
    run_migration()

