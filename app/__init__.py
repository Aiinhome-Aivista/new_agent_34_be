import logging
from flask import Flask, jsonify
from app.config import Config
from app.extensions import db, migrate, cors, init_redis

def create_app(config_class=Config):
    """Application factory for Merchant & User Fraud Investigation Agent backend."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, app.config.get("LOG_LEVEL", "INFO")),
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    )

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    cors.init_app(app, resources={r"/api/*": {"origins": "*"}})
    init_redis(app)

    # Initialize Swagger UI documentation
    from app.api.swagger_config import init_swagger
    init_swagger(app)

    # Register blueprints
    from app.api.health import health_bp
    from app.api.investigations import investigations_bp
    from app.api.dashboard import dashboard_bp
    from app.api.actions import actions_bp
    from app.api.audit import audit_bp
    from app.api.integrations import integrations_bp

    app.register_blueprint(health_bp, url_prefix="/api/v1/health")
    app.register_blueprint(investigations_bp, url_prefix="/api/v1/investigations")
    app.register_blueprint(dashboard_bp, url_prefix="/api/v1/dashboard")
    app.register_blueprint(actions_bp, url_prefix="/api/v1/actions")
    app.register_blueprint(audit_bp, url_prefix="/api/v1/audit")
    app.register_blueprint(integrations_bp, url_prefix="/api/v1/integrations")
    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")
    app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")
    app.register_blueprint(ingestion_bp, url_prefix="/api/v1/ingest")

    # Ensure tables exist, seed data is populated, and poller is active
    with app.app_context():
        try:
            from app.services.seed_data import seed_all_defaults
            seed_all_defaults()
        except Exception as seed_err:
            logging.getLogger("fraud_agent.init").warning(f"Seed data initialization note: {seed_err}")

        try:
            from app.services.ingest_service import AutoTriggerScheduler
            AutoTriggerScheduler.start(app)
        except Exception as poller_err:
            logging.getLogger("fraud_agent.init").warning(f"Auto-trigger scheduler note: {poller_err}")

    # Global Error Handlers
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not Found", "message": "The requested endpoint does not exist."}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"error": "Method Not Allowed", "message": "HTTP method not supported on this endpoint."}), 405

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({"error": "Internal Server Error", "message": "An unexpected server error occurred."}), 500

    return app
