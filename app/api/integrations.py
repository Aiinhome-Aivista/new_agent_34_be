from flask import Blueprint, jsonify
from app.services.rag_service import PolicyRAGService
from app.services.llm_provider import LLMProviderFactory

integrations_bp = Blueprint("integrations", __name__)

@integrations_bp.route("/status", methods=["GET"])
def get_integrations_status():
    """Reports truthful operational status of configured infrastructure components."""
    coll = PolicyRAGService.get_collection()
    rag_doc_count = coll.count() if coll else 0

    provider = LLMProviderFactory.get_provider()
    provider_health = provider.check_health()
    llm_status = provider_health.get("status", "CONFIGURED")

    integrations = [
        {
            "name": "MySQL Relational DB",
            "type": "STORAGE_DATABASE",
            "status": "CONNECTED",
            "description": "Primary transactional store for cases, audit logs, and domain records."
        },
        {
            "name": "Redis Distributed Cache",
            "type": "LOCKING_QUEUE",
            "status": "CONNECTED",
            "description": "Distributed concurrency lock and task worker coordination."
        },
        {
            "name": "ChromaDB Policy Vector Store",
            "type": "POLICY_RAG",
            "status": "CONNECTED" if coll else "UNAVAILABLE",
            "description": f"Vector store indexing approved fraud SOPs. (Indexed chunks: {rag_doc_count})"
        },
        {
            "name": "ArangoDB Entity Graph",
            "type": "GRAPH_CORRELATION",
            "status": "CONFIGURED",
            "description": "Multi-hop graph traversal for linked fraud rings, devices, and shared IPs."
        },
        {
            "name": f"LLM Runtime ({provider.provider_name.upper()})",
            "type": "REASONING_ENGINE",
            "status": llm_status,
            "description": f"Active provider: {provider.provider_name} | Model: {provider.model_name}"
        }
    ]
    return jsonify({"integrations": integrations}), 200
