from flask import Blueprint, jsonify
from sqlalchemy import text
from backend.app.extensions import db, redis_client
from backend.app.services.rag_service import PolicyRAGService
from backend.app.services.graph_service import GraphEntityService

health_bp = Blueprint("health", __name__)

@health_bp.route("/live", methods=["GET"])
def liveness():
    """Process liveness probe."""
    return jsonify({
        "status": "UP",
        "service": "FraudInvestigationAgent",
        "timestamp": "OK"
    }), 200

@health_bp.route("/ready", methods=["GET"])
def readiness():
    """Dependency readiness probe inspecting MySQL, Redis, ChromaDB, and ArangoDB."""
    readiness_details = {}
    is_ready = True

    # 1. MySQL Check
    try:
        db.session.execute(text("SELECT 1"))
        readiness_details["mysql"] = {"status": "CONNECTED", "details": "Query execution succeeded"}
    except Exception as e:
        readiness_details["mysql"] = {"status": "UNAVAILABLE", "error": str(e)}
        is_ready = False

    # 2. Redis Check
    if redis_client:
        try:
            redis_client.ping()
            readiness_details["redis"] = {"status": "CONNECTED", "details": "Ping succeeded"}
        except Exception as e:
            readiness_details["redis"] = {"status": "DEGRADED", "error": str(e)}
    else:
        readiness_details["redis"] = {"status": "UNAVAILABLE", "details": "Not initialized or offline"}

    # 3. ChromaDB Check
    try:
        coll = PolicyRAGService.get_collection()
        if coll:
            readiness_details["chromadb"] = {
                "status": "CONNECTED",
                "collection": coll.name,
                "document_count": coll.count()
            }
        else:
            readiness_details["chromadb"] = {"status": "UNAVAILABLE"}
    except Exception as e:
        readiness_details["chromadb"] = {"status": "ERROR", "error": str(e)}

    # 4. ArangoDB Check
    try:
        arango = GraphEntityService.get_arango_connection()
        readiness_details["arangodb"] = {
            "status": "CONNECTED" if arango else "UNCONFIGURED_OR_OFFLINE"
        }
    except Exception as e:
        readiness_details["arangodb"] = {"status": "ERROR", "error": str(e)}

    # 5. LLM Provider Check
    try:
        from backend.app.services.llm_provider import LLMProviderFactory
        provider = LLMProviderFactory.get_provider()
        readiness_details["llm_provider"] = {
            "provider": provider.provider_name,
            "model": provider.model_name,
            **provider.check_health()
        }
    except Exception as e:
        readiness_details["llm_provider"] = {"status": "ERROR", "error": str(e)}

    return jsonify({
        "status": "READY" if is_ready else "DEGRADED",
        "dependencies": readiness_details
    }), 200 if is_ready else 503
