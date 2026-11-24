import socket
import logging

# Ensure IPv4 resolution on Windows to avoid IPv6 handshake timeouts on remote APIs
try:
    _orig_getaddrinfo = socket.getaddrinfo
    def _getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
    socket.getaddrinfo = _getaddrinfo_ipv4
except Exception:
    pass

# Ensure pure-python fallback for xxhash if blocked by Windows Application Control (AppLocker/WDAC)
try:
    import xxhash
except (ImportError, OSError):
    try:
        import ppxxh
        import sys
        import types

        xxhash_mod = types.ModuleType("xxhash")
        xxhash_mod.XXHASH_VERSION = getattr(ppxxh, "XXHASH_VERSION", "0.8.2")

        def _wrap_hasher(cls):
            class Wrapped(cls):
                def reset(self):
                    super().__init__(seed=getattr(self, "_seed", 0))
            Wrapped.__name__ = cls.__name__
            Wrapped.__qualname__ = cls.__qualname__
            return Wrapped

        xxhash_mod.xxh32 = _wrap_hasher(ppxxh.xxh32)
        xxhash_mod.xxh64 = _wrap_hasher(ppxxh.xxh64)
        xxhash_mod.xxh3_64 = _wrap_hasher(ppxxh.xxh3_64)
        xxhash_mod.xxh3_128 = _wrap_hasher(ppxxh.xxh3_128)
        xxhash_mod.xxh128 = xxhash_mod.xxh3_128

        xxhash_mod.xxh32_digest = lambda data=b"", seed=0: xxhash_mod.xxh32(data, seed=seed).digest()
        xxhash_mod.xxh32_intdigest = lambda data=b"", seed=0: xxhash_mod.xxh32(data, seed=seed).intdigest()
        xxhash_mod.xxh32_hexdigest = lambda data=b"", seed=0: xxhash_mod.xxh32(data, seed=seed).hexdigest()

        xxhash_mod.xxh64_digest = lambda data=b"", seed=0: xxhash_mod.xxh64(data, seed=seed).digest()
        xxhash_mod.xxh64_intdigest = lambda data=b"", seed=0: xxhash_mod.xxh64(data, seed=seed).intdigest()
        xxhash_mod.xxh64_hexdigest = lambda data=b"", seed=0: xxhash_mod.xxh64(data, seed=seed).hexdigest()

        xxhash_mod.xxh3_64_digest = lambda data=b"", seed=0: xxhash_mod.xxh3_64(data, seed=seed).digest()
        xxhash_mod.xxh3_64_intdigest = lambda data=b"", seed=0: xxhash_mod.xxh3_64(data, seed=seed).intdigest()
        xxhash_mod.xxh3_64_hexdigest = lambda data=b"", seed=0: xxhash_mod.xxh3_64(data, seed=seed).hexdigest()

        xxhash_mod.xxh3_128_digest = lambda data=b"", seed=0: xxhash_mod.xxh3_128(data, seed=seed).digest()
        xxhash_mod.xxh3_128_intdigest = lambda data=b"", seed=0: xxhash_mod.xxh3_128(data, seed=seed).intdigest()
        xxhash_mod.xxh3_128_hexdigest = lambda data=b"", seed=0: xxhash_mod.xxh3_128(data, seed=seed).hexdigest()

        xxhash_mod.xxh128_digest = xxhash_mod.xxh3_128_digest
        xxhash_mod.xxh128_intdigest = xxhash_mod.xxh3_128_intdigest
        xxhash_mod.xxh128_hexdigest = xxhash_mod.xxh3_128_hexdigest
        xxhash_mod.VERSION = "4.1.0"
        xxhash_mod.algorithms_available = {"xxh32", "xxh64", "xxh3_64", "xxh128", "xxh3_128"}
        xxhash_mod.algorithms_guaranteed = xxhash_mod.algorithms_available

        sys.modules["xxhash"] = xxhash_mod
    except Exception:
        pass

# Ensure pure-python fallback for ormsgpack if blocked by Windows Application Control (AppLocker/WDAC)
try:
    import ormsgpack
except (ImportError, OSError):
    try:
        import msgpack
        import sys
        import types

        ormsgpack_mod = types.ModuleType("ormsgpack")
        ormsgpack_mod.__version__ = "1.5.0"
        ormsgpack_mod.OPT_NON_STR_KEYS = 1
        ormsgpack_mod.OPT_PASSTHROUGH_DATACLASS = 2
        ormsgpack_mod.OPT_PASSTHROUGH_DATETIME = 4
        ormsgpack_mod.OPT_PASSTHROUGH_ENUM = 8
        ormsgpack_mod.OPT_PASSTHROUGH_UUID = 16
        ormsgpack_mod.OPT_REPLACE_SURROGATES = 32
        ormsgpack_mod.OPT_SERIALIZE_NUMPY = 64
        ormsgpack_mod.OPT_SERIALIZE_PYDANTIC = 128
        ormsgpack_mod.OPT_DATETIME_AS_TIMESTAMP_EXT = 256
        ormsgpack_mod.OPT_NAIVE_UTC = 512
        ormsgpack_mod.OPT_OMIT_MICROSECONDS = 1024
        ormsgpack_mod.OPT_PASSTHROUGH_BIG_INT = 2048
        ormsgpack_mod.OPT_PASSTHROUGH_SUBCLASS = 4096
        ormsgpack_mod.OPT_PASSTHROUGH_TUPLE = 8192
        ormsgpack_mod.OPT_SORT_KEYS = 16384
        ormsgpack_mod.OPT_UTC_Z = 32768

        class MsgpackDecodeError(ValueError):
            pass

        class MsgpackEncodeError(TypeError):
            pass

        class Ext(msgpack.ExtType):
            def __new__(cls, tag: int, data: bytes):
                return super().__new__(cls, tag, data)

            @property
            def tag(self) -> int:
                return self.code

        class Fragment:
            def __init__(self, data: bytes):
                self.data = data

        def _packb(obj, /, default=None, option=None):
            try:
                return msgpack.packb(obj, default=default, use_bin_type=True, strict_types=False)
            except Exception as exc:
                raise MsgpackEncodeError(str(exc)) from exc

        def _unpackb(obj, /, *, ext_hook=None, option=None):
            try:
                return msgpack.unpackb(obj, ext_hook=ext_hook, raw=False, strict_map_key=False)
            except Exception as exc:
                raise MsgpackDecodeError(str(exc)) from exc

        ormsgpack_mod.MsgpackDecodeError = MsgpackDecodeError
        ormsgpack_mod.MsgpackEncodeError = MsgpackEncodeError
        ormsgpack_mod.Ext = Ext
        ormsgpack_mod.Fragment = Fragment
        ormsgpack_mod.packb = _packb
        ormsgpack_mod.unpackb = _unpackb

        sys.modules["ormsgpack"] = ormsgpack_mod
    except Exception:
        pass
from flask import Flask, jsonify, redirect, request
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

    # Register blueprints
    from app.api.health import health_bp
    from app.api.investigations import investigations_bp
    from app.api.dashboard import dashboard_bp
    from app.api.actions import actions_bp
    from app.api.audit import audit_bp
    from app.api.integrations import integrations_bp
    from app.api.auth import auth_bp
    from app.api.admin import admin_bp
    from app.api.ingestion import ingestion_bp
    from app.api.portal import portal_bp
    from app.api.notifications import notifications_bp

    app.register_blueprint(health_bp, url_prefix="/api/v1/health")
    app.register_blueprint(investigations_bp, url_prefix="/api/v1/investigations")
    app.register_blueprint(dashboard_bp, url_prefix="/api/v1/dashboard")
    app.register_blueprint(actions_bp, url_prefix="/api/v1/actions")
    app.register_blueprint(audit_bp, url_prefix="/api/v1/audit")
    app.register_blueprint(integrations_bp, url_prefix="/api/v1/integrations")
    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")
    app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")
    app.register_blueprint(ingestion_bp, url_prefix="/api/v1/ingest")
    app.register_blueprint(portal_bp, url_prefix="/api/v1/portal")
    app.register_blueprint(notifications_bp, url_prefix="/api/v1/notifications")

    # Seamless redirect: if a customer clicks an evidence link on the backend port (e.g. :3052),
    # automatically 302 redirect them to the frontend port (:5173) so 404 never occurs!
    @app.route("/evidence-submission")
    @app.route("/evidence-portal")
    def redirect_to_frontend_portal():
        token = request.args.get("token", "")
        frontend_base = getattr(Config, "FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
        target_url = f"{frontend_base}/evidence-submission"
        if token:
            target_url += f"?token={token}"
        return redirect(target_url, code=302)

    # Ensure tables exist, seed data is populated, and poller is active
    with app.app_context():
        try:
            from app.services.seed_data import seed_all_defaults
            seed_all_defaults()
        except Exception as seed_err:
            logging.getLogger("fraud_agent.init").warning(f"Seed data initialization note: {seed_err}")

        # Phase 1: Knowledgebase schema migration (idempotent — safe to run on every startup)
        try:
            from app.services.knowledgebase.migrate_knowledgebase import migrate_knowledgebase_tables
            migrate_knowledgebase_tables()
        except Exception as kb_err:
            logging.getLogger("fraud_agent.init").warning(f"Knowledgebase migration note: {kb_err}")

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
