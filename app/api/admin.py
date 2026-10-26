import logging
import uuid
from flask import Blueprint, request, jsonify
from app.models.governance import PolicyDocument, FraudParameter, AppUser
from app.extensions import db

logger = logging.getLogger("fraud_agent.api.admin")
admin_bp = Blueprint("admin", __name__)

# ============================================================================
# 1. Company Policies Management (CRUD) 
# ============================================================================

@admin_bp.route("/policies", methods=["GET"])
def list_policies():
    """Returns all organizational fraud policies."""
    category = request.args.get("category")
    status = request.args.get("status")

    query = PolicyDocument.query
    if category:
        query = query.filter_by(category=category)
    if status:
        query = query.filter_by(status=status)

    policies = query.order_by(PolicyDocument.document_key.asc()).all()
    return jsonify([p.to_dict() for p in policies]), 200

@admin_bp.route("/policies", methods=["POST"])
def create_policy():
    """Creates a new organizational fraud policy."""
    data = request.get_json(silent=True) or {}
    document_key = data.get("document_key", "").strip().upper()
    title = data.get("title", "").strip()

    if not document_key or not title:
        return jsonify({"error": "Bad Request", "message": "document_key and title are required"}), 400

    existing = PolicyDocument.query.filter_by(document_key=document_key).first()
    if existing:
        return jsonify({"error": "Conflict", "message": f"Policy with key '{document_key}' already exists."}), 409

    policy = PolicyDocument(
        id=str(uuid.uuid4()),
        document_key=document_key,
        title=title,
        version=data.get("version", "1.0").strip(),
        category=data.get("category", "GENERAL").strip().upper(),
        action_impact=data.get("action_impact", "ADVISORY").strip().upper(),
        description=data.get("description", "").strip(),
        content=data.get("content", "").strip(),
        status=data.get("status", "APPROVED").strip().upper(),
        source_reference=data.get("source_reference", "").strip() or None
    )
    db.session.add(policy)
    db.session.commit()
    logger.info(f"Created new policy: {document_key}")
    return jsonify(policy.to_dict()), 201

@admin_bp.route("/policies/<policy_id>", methods=["PUT"])
def update_policy(policy_id):
    """Updates an existing organizational policy."""
    policy = PolicyDocument.query.filter_by(id=policy_id).first()
    if not policy:
        return jsonify({"error": "Not Found", "message": f"Policy {policy_id} not found"}), 404

    data = request.get_json(silent=True) or {}
    if "title" in data and data["title"].strip():
        policy.title = data["title"].strip()
    if "version" in data and data["version"].strip():
        policy.version = data["version"].strip()
    if "category" in data and data["category"].strip():
        policy.category = data["category"].strip().upper()
    if "action_impact" in data and data["action_impact"].strip():
        policy.action_impact = data["action_impact"].strip().upper()
    if "description" in data:
        policy.description = data["description"].strip()
    if "content" in data:
        policy.content = data["content"].strip()
    if "status" in data and data["status"].strip():
        policy.status = data["status"].strip().upper()
    if "source_reference" in data:
        policy.source_reference = data["source_reference"].strip() or None

    db.session.commit()
    logger.info(f"Updated policy: {policy.document_key}")
    return jsonify(policy.to_dict()), 200

@admin_bp.route("/policies/<policy_id>", methods=["DELETE"])
def delete_policy(policy_id):
    """Deletes an organizational policy."""
    policy = PolicyDocument.query.filter_by(id=policy_id).first()
    if not policy:
        return jsonify({"error": "Not Found", "message": f"Policy {policy_id} not found"}), 404

    key = policy.document_key
    db.session.delete(policy)
    db.session.commit()
    logger.info(f"Deleted policy: {key}")
    return jsonify({"status": "SUCCESS", "message": f"Policy {key} deleted successfully"}), 200


# ============================================================================
# 2. Fraud Parameters & Thresholds Management (CRUD)
# ============================================================================

VALID_SECTIONS = [
    "USER_PROFILE",
    "PAYMENT_TRANSACTION",
    "ORDER_DETAILS",
    "CHARGEBACK_DISPUTE",
    "GRAPH_NETWORK",
    "GATEWAY_RULE"
]

@admin_bp.route("/parameters", methods=["GET"])
def list_parameters():
    """Returns all fraud inspection parameters, optionally filtered by section."""
    section = request.args.get("section")
    is_active = request.args.get("is_active")

    query = FraudParameter.query
    if section:
        query = query.filter_by(section=section.upper())
    if is_active is not None:
        query = query.filter_by(is_active=(is_active.lower() == "true"))

    params = query.order_by(FraudParameter.section.asc(), FraudParameter.name.asc()).all()
    return jsonify([p.to_dict() for p in params]), 200

@admin_bp.route("/parameters", methods=["POST"])
def create_parameter():
    """Adds a new fraud parameter under a specific operational section."""
    data = request.get_json(silent=True) or {}
    parameter_key = data.get("parameter_key", "").strip().lower()
    name = data.get("name", "").strip()
    section = data.get("section", "").strip().upper()
    threshold_value = str(data.get("threshold_value", "")).strip()

    if not parameter_key or not name or not section or not threshold_value:
        return jsonify({
            "error": "Bad Request",
            "message": "parameter_key, name, section, and threshold_value are required"
        }), 400

    if section not in VALID_SECTIONS:
        return jsonify({
            "error": "Bad Request",
            "message": f"Invalid section. Must be one of: {', '.join(VALID_SECTIONS)}"
        }), 400

    existing = FraudParameter.query.filter_by(parameter_key=parameter_key).first()
    if existing:
        return jsonify({"error": "Conflict", "message": f"Parameter key '{parameter_key}' already exists."}), 409

    param = FraudParameter(
        id=str(uuid.uuid4()),
        parameter_key=parameter_key,
        name=name,
        section=section,
        data_type=data.get("data_type", "STRING").strip().upper(),
        threshold_value=threshold_value,
        risk_weight=data.get("risk_weight", "HIGH").strip().upper(),
        description=data.get("description", "").strip(),
        is_active=bool(data.get("is_active", True))
    )
    db.session.add(param)
    db.session.commit()
    logger.info(f"Created new fraud parameter: {parameter_key} in section {section}")
    return jsonify(param.to_dict()), 201

@admin_bp.route("/parameters/<param_id>", methods=["PUT"])
def update_parameter(param_id):
    """Updates an existing fraud parameter threshold, risk weight, or status."""
    param = FraudParameter.query.filter_by(id=param_id).first()
    if not param:
        return jsonify({"error": "Not Found", "message": f"Parameter {param_id} not found"}), 404

    data = request.get_json(silent=True) or {}
    if "name" in data and data["name"].strip():
        param.name = data["name"].strip()
    if "section" in data and data["section"].strip():
        sec = data["section"].strip().upper()
        if sec in VALID_SECTIONS:
            param.section = sec
    if "threshold_value" in data and str(data["threshold_value"]).strip():
        param.threshold_value = str(data["threshold_value"]).strip()
    if "risk_weight" in data and data["risk_weight"].strip():
        param.risk_weight = data["risk_weight"].strip().upper()
    if "data_type" in data and data["data_type"].strip():
        param.data_type = data["data_type"].strip().upper()
    if "description" in data:
        param.description = data["description"].strip()
    if "is_active" in data:
        param.is_active = bool(data["is_active"])

    db.session.commit()
    logger.info(f"Updated parameter: {param.parameter_key}")
    return jsonify(param.to_dict()), 200

@admin_bp.route("/parameters/<param_id>", methods=["DELETE"])
def delete_parameter(param_id):
    """Deletes a fraud parameter from the system."""
    param = FraudParameter.query.filter_by(id=param_id).first()
    if not param:
        return jsonify({"error": "Not Found", "message": f"Parameter {param_id} not found"}), 404

    key = param.parameter_key
    db.session.delete(param)
    db.session.commit()
    logger.info(f"Deleted parameter: {key}")
    return jsonify({"status": "SUCCESS", "message": f"Parameter {key} deleted successfully"}), 200

@admin_bp.route("/sections", methods=["GET"])
def get_sections_summary():
    """Returns overview of parameter sections with count of parameters in each."""
    summary = []
    for sec in VALID_SECTIONS:
        count = FraudParameter.query.filter_by(section=sec).count()
        active_count = FraudParameter.query.filter_by(section=sec, is_active=True).count()
        summary.append({
            "section": sec,
            "total_parameters": count,
            "active_parameters": active_count
        })
    return jsonify(summary), 200

# ============================================================================
# 3. Knowledge Base Private Document Upload & Vector Indexing
# ============================================================================

from app.services.knowledge_service import KnowledgeService
from app.services.rag_service import PolicyRAGService

@admin_bp.route("/knowledge/upload", methods=["POST"])
def upload_knowledge_document():    
    """
    Uploads a private company policy document (.pdf, .txt, .md, .json),
    extracts text, chunks it, and indexes it into ChromaDB vector knowledge store.
    """
    if "file" not in request.files:
        return jsonify({"error": "Bad Request", "message": "No file uploaded in form"}), 400

    doc_file = request.files["file"]
    if not doc_file.filename:
        return jsonify({"error": "Bad Request", "message": "No file selected"}), 400

    document_key = request.form.get("document_key", "").strip().upper()
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "GENERAL").strip().upper()
    action_impact = request.form.get("action_impact", "ADVISORY").strip().upper()
    version = request.form.get("version", "1.0").strip()
    description = request.form.get("description", "").strip()

    if not document_key or not title:
        return jsonify({"error": "Bad Request", "message": "document_key and title are required"}), 400

    try:
        content_bytes = doc_file.read()
        res = KnowledgeService.process_and_index_document(
            file_bytes=content_bytes,
            filename=doc_file.filename,
            document_key=document_key,
            title=title,
            category=category,
            action_impact=action_impact,
            version=version,
            description=description
        )
        return jsonify(res), 201
    except ValueError as ve:
        return jsonify({"error": "Validation Error", "message": str(ve)}), 422
    except Exception as e:
        logger.error(f"Error processing policy upload: {e}")
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500

@admin_bp.route("/knowledge/reindex", methods=["POST"])
def reindex_knowledge():
    """Re-indexes all policy documents from MySQL into ChromaDB."""
    try:
        res = KnowledgeService.reindex_all_policies()
        return jsonify(res), 200
    except Exception as e:
        logger.error(f"Error re-indexing knowledge base: {e}")
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500

@admin_bp.route("/knowledge/status", methods=["GET"])
def get_knowledge_status():
    """Returns vector knowledge base collection statistics."""
    collection = PolicyRAGService.get_collection()
    if collection is None:
        return jsonify({"status": "UNAVAILABLE", "vector_count": 0}), 200
    try:
        count = collection.count()
        return jsonify({
            "status": "HEALTHY",
            "collection_name": "fraud_investigation_policies",
            "indexed_vectors_count": count
        }), 200
    except Exception as e:
        return jsonify({"status": "ERROR", "message": str(e)}), 500

