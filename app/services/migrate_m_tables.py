import logging
from sqlalchemy import text
from backend.app.extensions import db

logger = logging.getLogger("fraud_agent.migrate_m_tables")

def migrate_and_ensure_m_tables():
    """
    Ensures that m_users, m_orders, m_payments, m_chargebacks and audit_events.user_id
    are fully provisioned in MySQL. Migrates legacy data if m_* tables are empty.
    """
    db.create_all()

    with db.engine.connect() as conn:
        # 1. Ensure user_id column on audit_events
        try:
            conn.execute(text("ALTER TABLE audit_events ADD COLUMN user_id VARCHAR(36) NULL AFTER case_id"))
            conn.commit()
            logger.info("Added user_id column to audit_events table.")
        except Exception:
            pass  # Already exists

        # 2. Add index on audit_events(user_id, event_timestamp)
        try:
            conn.execute(text("CREATE INDEX idx_audit_user_time ON audit_events (user_id, event_timestamp)"))
            conn.commit()
        except Exception:
            pass

        # 3. Check if legacy users table has data to copy to m_users
        try:
            m_user_count = conn.execute(text("SELECT COUNT(*) FROM m_users")).scalar()
            if m_user_count == 0:
                user_exists = conn.execute(text("SHOW TABLES LIKE 'users'")).scalar()
                if user_exists:
                    conn.execute(text("""
                        INSERT IGNORE INTO m_users (user_id, external_user_id, first_name, last_name, email, phone_number, user_type, status, country_code, kyc_status, risk_level, risk_score, created_at, updated_at, last_login_at)
                        SELECT user_id, external_user_id, first_name, last_name, email, phone_number, user_type, status, country_code, kyc_status, risk_level, risk_score, created_at, updated_at, last_login_at FROM users
                    """))
                    conn.commit()
                    logger.info("Copied legacy users into m_users.")
        except Exception as e:
            logger.warning(f"m_users migration note: {e}")

        # 4. Check if legacy orders table has data to copy to m_orders
        try:
            m_order_count = conn.execute(text("SELECT COUNT(*) FROM m_orders")).scalar()
            if m_order_count == 0:
                orders_exists = conn.execute(text("SHOW TABLES LIKE 'orders'")).scalar()
                if orders_exists:
                    conn.execute(text("""
                        INSERT IGNORE INTO m_orders (order_id, merchant_order_id, user_id, merchant_id, amount, currency, order_status, description, ip_address, device_id, billing_country, shipping_country, created_at, updated_at)
                        SELECT order_id, merchant_order_id, user_id, merchant_id, amount, currency, order_status, description, ip_address, device_id, billing_country, shipping_country, created_at, updated_at FROM orders
                    """))
                    conn.commit()
                    logger.info("Copied legacy orders into m_orders.")
        except Exception as e:
            logger.warning(f"m_orders migration note: {e}")

        # 5. Check if legacy payments table has data to copy to m_payments
        try:
            m_payment_count = conn.execute(text("SELECT COUNT(*) FROM m_payments")).scalar()
            if m_payment_count == 0:
                payments_exists = conn.execute(text("SHOW TABLES LIKE 'payments'")).scalar()
                if payments_exists:
                    conn.execute(text("""
                        INSERT IGNORE INTO m_payments (payment_id, order_id, user_id, merchant_id, gateway_transaction_id, idempotency_key, payment_method, payment_status, amount, currency, processor_name, failure_code, failure_reason, ip_address, device_id, initiated_at, authorized_at, captured_at, failed_at, updated_at)
                        SELECT payment_id, order_id, user_id, merchant_id, gateway_transaction_id, idempotency_key, payment_method, payment_status, amount, currency, processor_name, failure_code, failure_reason, ip_address, device_id, initiated_at, authorized_at, captured_at, failed_at, updated_at FROM payments
                    """))
                    conn.commit()
                    logger.info("Copied legacy payments into m_payments.")
        except Exception as e:
            logger.warning(f"m_payments migration note: {e}")

        # 6. Check if legacy chargebacks table has data to copy to m_chargebacks
        try:
            m_cb_count = conn.execute(text("SELECT COUNT(*) FROM m_chargebacks")).scalar()
            if m_cb_count == 0:
                cb_exists = conn.execute(text("SHOW TABLES LIKE 'chargebacks'")).scalar()
                if cb_exists:
                    conn.execute(text("""
                        INSERT IGNORE INTO m_chargebacks (chargeback_id, payment_id, order_id, processor_case_id, amount, currency, reason_code, reason_description, chargeback_status, fraud_indicator, received_at, response_due_at, responded_at, resolved_at, created_at, updated_at)
                        SELECT chargeback_id, payment_id, order_id, processor_case_id, amount, currency, reason_code, reason_description, chargeback_status, fraud_indicator, received_at, response_due_at, responded_at, resolved_at, created_at, updated_at FROM chargebacks
                    """))
                    conn.commit()
                    logger.info("Copied legacy chargebacks into m_chargebacks.")
        except Exception as e:
            logger.warning(f"m_chargebacks migration note: {e}")

if __name__ == "__main__":
    from backend.app import create_app
    app = create_app()
    with app.app_context():
        migrate_and_ensure_m_tables()
        print("Migration complete for m_* tables.")

