from flask.helpers import stream_with_context
from flask import Response
import json
import logging
import uuid
import time
import requests
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app
from app.models.governance import (
    PolicyDocument, FraudParameter, AppUser, MicroserviceApiRegistry, to_utc_iso
)
from app.models.source_domain import MUser, MOrder, MPayment, MChargeback
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
@admin_bp.route("/knowledge/upload-stream", methods=["POST"])
def upload_knowledge_document():
    """
    Uploads a private company policy document (.pdf, .txt, .md, .json),
    extracts text, chunks it, and indexes it into ChromaDB vector knowledge store.
    Supports real-time SSE progress streaming when stream=true or when calling /knowledge/upload-stream.
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

    stream_mode = (
        request.path.endswith("/knowledge/upload-stream") or
        request.args.get("stream", "false").lower() == "true" or
        "text/event-stream" in request.headers.get("Accept", "")
    )

    try:
        content_bytes = doc_file.read()
        if stream_mode:
            def generate():
                for step in KnowledgeService.process_and_index_document_stream(
                    file_bytes=content_bytes,
                    filename=doc_file.filename,
                    document_key=document_key,
                    title=title,
                    category=category,
                    action_impact=action_impact,
                    version=version,
                    description=description
                ):
                    yield f"data: {json.dumps(step)}\n\n"

            return Response(
                stream_with_context(generate()),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*"
                }
            )

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

# ============================================================================
# 4. Dynamic Microservice API Registry & Connectors (CRUD & Probe Runner)
# ============================================================================

@admin_bp.route("/connectors", methods=["GET"])
def list_connectors():
    """Returns all registered microservice API connectors with optional category/search filters."""
    category = request.args.get("category")
    is_active = request.args.get("is_active")
    search = request.args.get("search", "").strip().lower()

    query = MicroserviceApiRegistry.query
    if category and category.upper() != "ALL":
        query = query.filter_by(service_category=category.upper())
    if is_active is not None and is_active != "":
        query = query.filter_by(is_active=(is_active.lower() == "true"))

    connectors = query.order_by(MicroserviceApiRegistry.created_at.asc()).all()

    if search:
        connectors = [
            c for c in connectors
            if search in c.service_name.lower() or
               search in c.service_key.lower() or
               search in c.endpoint_path.lower() or
               search in c.base_url.lower() or
               (c.description and search in c.description.lower())
        ]

    return jsonify([c.to_dict() for c in connectors]), 200

@admin_bp.route("/connectors/<connector_id>", methods=["GET"])
def get_connector(connector_id):
    """Retrieves single connector details including sensitive token if authorized."""
    connector = MicroserviceApiRegistry.query.filter_by(id=connector_id).first()
    if not connector:
        return jsonify({"error": "Not Found", "message": f"Connector {connector_id} not found"}), 404
    return jsonify(connector.to_dict(include_sensitive=True)), 200

@admin_bp.route("/connectors", methods=["POST"])
def create_connector():
    """Dynamically registers a new microservice API connector."""
    data = request.get_json(silent=True) or {}
    service_key = data.get("service_key", "").strip().upper()
    service_name = data.get("service_name", "").strip()
    service_category = data.get("service_category", "IDENTITY").strip().upper()
    base_url = data.get("base_url", "").strip()
    endpoint_path = data.get("endpoint_path", "").strip()

    if not service_key or not service_name or not base_url or not endpoint_path:
        return jsonify({
            "error": "Bad Request",
            "message": "service_key, service_name, base_url, and endpoint_path are required"
        }), 400

    existing = MicroserviceApiRegistry.query.filter_by(service_key=service_key).first()
    if existing:
        return jsonify({
            "error": "Conflict",
            "message": f"Connector with service_key '{service_key}' already exists."
        }), 409

    auth_token = data.get("auth_token", "").strip()
    connector = MicroserviceApiRegistry(
        id=str(uuid.uuid4()),
        service_key=service_key,
        service_name=service_name,
        service_category=service_category,
        description=data.get("description", "").strip(),
        http_method=data.get("http_method", "GET").strip().upper(),
        base_url=base_url,
        endpoint_path=endpoint_path,
        auth_type=data.get("auth_type", "BEARER_TOKEN").strip().upper(),
        auth_header_key=data.get("auth_header_key", "Authorization").strip(),
        auth_token_encrypted=auth_token or None,
        custom_headers=data.get("custom_headers") or {},
        sample_payload=data.get("sample_payload"),
        sample_response=data.get("sample_response"),
        payload_schema=data.get("payload_schema", "").strip(),
        timeout_ms=int(data.get("timeout_ms", 5000)),
        retry_count=int(data.get("retry_count", 2)),
        is_mock_enabled=bool(data.get("is_mock_enabled", True)),
        is_active=bool(data.get("is_active", True)),
        health_status="HEALTHY",
        last_latency_ms=25,
        last_status_code=200
    )
    if auth_token:
        connector.token_preview = connector.mask_token(auth_token)

    db.session.add(connector)
    db.session.commit()
    logger.info(f"Registered new microservice connector: {service_key}")
    return jsonify(connector.to_dict()), 201

@admin_bp.route("/connectors/<connector_id>", methods=["PUT"])
def update_connector(connector_id):
    """Dynamically updates an existing microservice connector at runtime."""
    connector = MicroserviceApiRegistry.query.filter_by(id=connector_id).first()
    if not connector:
        return jsonify({"error": "Not Found", "message": f"Connector {connector_id} not found"}), 404

    data = request.get_json(silent=True) or {}
    if "service_name" in data and data["service_name"].strip():
        connector.service_name = data["service_name"].strip()
    if "service_category" in data and data["service_category"].strip():
        connector.service_category = data["service_category"].strip().upper()
    if "description" in data:
        connector.description = data["description"].strip()
    if "http_method" in data and data["http_method"].strip():
        connector.http_method = data["http_method"].strip().upper()
    if "base_url" in data and data["base_url"].strip():
        connector.base_url = data["base_url"].strip()
    if "endpoint_path" in data and data["endpoint_path"].strip():
        connector.endpoint_path = data["endpoint_path"].strip()
    if "auth_type" in data and data["auth_type"].strip():
        connector.auth_type = data["auth_type"].strip().upper()
    if "auth_header_key" in data:
        connector.auth_header_key = data["auth_header_key"].strip() or "Authorization"
    if "auth_token" in data and data["auth_token"].strip():
        new_token = data["auth_token"].strip()
        connector.auth_token_encrypted = new_token
        connector.token_preview = connector.mask_token(new_token)
    if "custom_headers" in data:
        connector.custom_headers = data["custom_headers"]
    if "sample_payload" in data:
        connector.sample_payload = data["sample_payload"]
    if "sample_response" in data:
        connector.sample_response = data["sample_response"]
    if "payload_schema" in data:
        connector.payload_schema = data["payload_schema"].strip()
    if "timeout_ms" in data:
        connector.timeout_ms = int(data["timeout_ms"])
    if "retry_count" in data:
        connector.retry_count = int(data["retry_count"])
    if "is_mock_enabled" in data:
        connector.is_mock_enabled = bool(data["is_mock_enabled"])
    if "is_active" in data:
        connector.is_active = bool(data["is_active"])

    db.session.commit()
    logger.info(f"Updated microservice connector: {connector.service_key}")
    return jsonify(connector.to_dict()), 200

@admin_bp.route("/connectors/<connector_id>", methods=["DELETE"])
def delete_connector(connector_id):
    """Deletes or unregisters a microservice connector."""
    connector = MicroserviceApiRegistry.query.filter_by(id=connector_id).first()
    if not connector:
        return jsonify({"error": "Not Found", "message": f"Connector {connector_id} not found"}), 404

    key = connector.service_key
    db.session.delete(connector)
    db.session.commit()
    logger.info(f"Deleted microservice connector: {key}")
    return jsonify({"message": f"Connector {key} successfully removed"}), 200

@admin_bp.route("/connectors/<connector_id>/toggle-mock", methods=["POST"])
def toggle_mock_connector(connector_id):
    """Quickly toggles mock simulation mode vs live network dispatch."""
    connector = MicroserviceApiRegistry.query.filter_by(id=connector_id).first()
    if not connector:
        return jsonify({"error": "Not Found", "message": f"Connector {connector_id} not found"}), 404

    connector.is_mock_enabled = not connector.is_mock_enabled
    db.session.commit()
    return jsonify({
        "id": connector.id,
        "service_key": connector.service_key,
        "is_mock_enabled": connector.is_mock_enabled,
        "message": f"Switched {connector.service_name} to {'MOCK SIMULATOR' if connector.is_mock_enabled else 'LIVE NETWORK'} mode"
    }), 200

@admin_bp.route("/connectors/<connector_id>/test", methods=["POST"])
def test_connector(connector_id):
    """
    Executes an on-demand live or simulated test probe.
    Returns status code, latency, request details, and response body.
    Updates telemetry and health status in MySQL.
    """
    connector = MicroserviceApiRegistry.query.filter_by(id=connector_id).first()
    if not connector:
        return jsonify({"error": "Not Found", "message": f"Connector {connector_id} not found"}), 404

    data = request.get_json(silent=True) or {}
    custom_payload = data.get("custom_payload") if data.get("custom_payload") is not None else connector.sample_payload
    test_params = data.get("test_params") or {}

    # Target URL interpolation: substitute {param} placeholders if provided
    endpoint = connector.endpoint_path
    for param_k, param_v in test_params.items():
        endpoint = endpoint.replace(f"{{{param_k}}}", str(param_v))

    # Resolve dynamic path parameters directly from real database records
    if "{user_id}" in endpoint:
        try:
            m_u = MUser.query.first()
            user_val = m_u.user_id if m_u else "MERCH_NORTH_01"
        except Exception:
            user_val = "MERCH_NORTH_01"
        endpoint = endpoint.replace("{user_id}", user_val)

    if "{order_id}" in endpoint:
        try:
            m_o = MOrder.query.first()
            order_val = m_o.order_id if m_o else "ORD_0A2E73A8"
        except Exception:
            order_val = "ORD_0A2E73A8"
        endpoint = endpoint.replace("{order_id}", order_val)

    if "{payment_id}" in endpoint:
        try:
            m_p = MPayment.query.first()
            pay_val = m_p.payment_id if m_p else "PAY_34D61ED4"
        except Exception:
            pay_val = "PAY_34D61ED4"
        endpoint = endpoint.replace("{payment_id}", pay_val)

    if "{chargeback_id}" in endpoint:
        try:
            m_c = MChargeback.query.first()
            cb_val = m_c.chargeback_id if m_c else "CBK_0464085F"
        except Exception:
            cb_val = "CBK_0464085F"
        endpoint = endpoint.replace("{chargeback_id}", cb_val)

    endpoint = endpoint.replace("{device_id}", "DEV_A9F88172BC")

    target_url = f"{connector.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    now_utc = datetime.now(timezone.utc)

    # 1. Mock Simulation Mode (only if explicitly enabled on a custom connector)
    if connector.is_mock_enabled:
        import random
        simulated_latency = random.randint(18, 48)
        time.sleep(simulated_latency / 1000.0)

        connector.health_status = "HEALTHY"
        connector.last_tested_at = now_utc
        connector.last_latency_ms = simulated_latency
        connector.last_status_code = 200
        connector.last_error_message = None
        db.session.commit()

        token_hint = connector.token_preview or "sk-live-••••••••b49a"
        auth_head = {connector.auth_header_key or "Authorization": f"Bearer {token_hint}"} if connector.auth_type != "NONE" else {}

        return jsonify({
            "success": True,
            "execution_mode": "MOCK_SIMULATION",
            "target_url": target_url,
            "http_method": connector.http_method,
            "status_code": 200,
            "latency_ms": simulated_latency,
            "headers_sent": {
                **auth_head,
                **(connector.custom_headers or {})
            },
            "payload_sent": custom_payload,
            "response_body": connector.sample_response or {"status": "ok", "mock": True},
            "tested_at": to_utc_iso(now_utc),
            "health_status": "HEALTHY"
        }), 200

    # 2. Live Execution Mode
    headers = dict(connector.custom_headers or {})
    token = connector.auth_token_encrypted or ""
    if token.startswith("ENV:"):
        import os
        token = os.environ.get(token[4:], "")

    if connector.auth_type == "BEARER_TOKEN" and token:
        headers[connector.auth_header_key or "Authorization"] = f"Bearer {token}"
    elif connector.auth_type == "API_KEY" and token:
        headers[connector.auth_header_key or "X-API-KEY"] = token
    elif connector.auth_type == "CUSTOM_HEADER" and token:
        headers[connector.auth_header_key or "X-Custom-Auth"] = token

    start_time = time.time()
    try:
        # Check if internal service (e.g. running on localhost or registered in microservices_bp)
        is_internal = (
            connector.service_key in ("USER_SERVICE", "ORDER_SERVICE", "PAYMENT_SERVICE", "CHARGEBACK_SERVICE")
            or "localhost:3052" in target_url
            or "127.0.0.1:3052" in target_url
            or endpoint.startswith("/api/v1/services")
        )

        if is_internal:
            client = current_app.test_client()
            local_path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
            client_kwargs = {
                "method": connector.http_method,
                "path": local_path,
                "headers": headers,
            }
            if connector.http_method in ("POST", "PUT", "PATCH") and custom_payload is not None:
                client_kwargs["json"] = custom_payload

            resp = client.open(**client_kwargs)
            latency = max(2, int((time.time() - start_time) * 1000))
            try:
                resp_body = resp.get_json()
            except Exception:
                resp_body = resp.get_data(as_text=True)

            status_code = resp.status_code
            exec_mode = "LIVE_DATABASE_SERVICE"
        else:
            req_kwargs = {
                "method": connector.http_method,
                "url": target_url,
                "headers": headers,
                "timeout": (connector.timeout_ms or 5000) / 1000.0
            }
            if connector.http_method in ("POST", "PUT", "PATCH") and custom_payload is not None:
                req_kwargs["json"] = custom_payload

            resp = requests.request(**req_kwargs)
            latency = max(2, int((time.time() - start_time) * 1000))
            try:
                resp_body = resp.json()
            except Exception:
                resp_body = resp.text

            status_code = resp.status_code
            exec_mode = "LIVE_NETWORK"

        connector.health_status = "HEALTHY" if status_code < 400 else "DEGRADED"
        connector.last_tested_at = now_utc
        connector.last_latency_ms = latency
        connector.last_status_code = status_code
        connector.last_error_message = None if status_code < 400 else f"HTTP {status_code}"
        db.session.commit()

        return jsonify({
            "success": status_code < 400,
            "execution_mode": exec_mode,
            "target_url": target_url,
            "http_method": connector.http_method,
            "status_code": status_code,
            "latency_ms": latency,
            "headers_sent": {k: (connector.token_preview if ("auth" in k.lower() or "key" in k.lower()) else v) for k, v in headers.items()},
            "payload_sent": custom_payload,
            "response_body": resp_body,
            "tested_at": to_utc_iso(now_utc),
            "health_status": connector.health_status
        }), 200
    except Exception as exc:
        latency = max(2, int((time.time() - start_time) * 1000))
        connector.health_status = "UNAVAILABLE"
        connector.last_tested_at = now_utc
        connector.last_latency_ms = latency
        connector.last_status_code = 504
        connector.last_error_message = str(exc)
        db.session.commit()

        return jsonify({
            "success": False,
            "execution_mode": "LIVE_NETWORK",
            "target_url": target_url,
            "http_method": connector.http_method,
            "status_code": 504,
            "latency_ms": latency,
            "error": str(exc),
            "hint": "Microservice service is currently unreachable or encountered an execution failure.",
            "tested_at": to_utc_iso(now_utc),
            "health_status": "UNAVAILABLE"
        }), 200


