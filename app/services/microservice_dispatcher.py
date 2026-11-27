"""
Microservice Dispatcher & Evidence Gathering Orchestrator
=========================================================
Dynamically queries registered microservices from `microservice_api_registry`,
respects Admin Active/Inactive (True/False) toggles, executes active HTTP
endpoints in parallel per investigation case with a synchronization barrier,
prints live terminal execution summaries, and synthesizes evidence records.
"""

import os
import re
import time
import uuid
import json
import hashlib
import logging
import concurrent.futures
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

import httpx
from flask import current_app

from app.config import Config
from app.extensions import db
from app.models.governance import MicroserviceApiRegistry
from app.models.investigation import CaseEvidence

logger = logging.getLogger("fraud_agent.microservice_dispatcher")

# ANSI color codes for prominent terminal output
COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_CYAN = "\033[96m"
COLOR_BOLD = "\033[1m"
COLOR_DIM = "\033[2m"

CORE_SERVICE_KEYS = (
    "USER_SERVICE",
    "ORDER_SERVICE",
    "PAYMENT_SERVICE",
    "CHARGEBACK_SERVICE",
    "REFUND_SERVICE",
)

TARGET_TABLE_MAP = {
    "USER_SERVICE": "m_users",
    "ORDER_SERVICE": "m_orders",
    "PAYMENT_SERVICE": "m_payments",
    "CHARGEBACK_SERVICE": "m_chargebacks",
    "REFUND_SERVICE": "m_refunds",
}

DEFAULT_CORE_SPECS: List[Dict[str, Any]] = [
    {
        "id": "default-chargeback",
        "service_key": "CHARGEBACK_SERVICE",
        "service_name": "Chargeback & Dispute Service",
        "service_category": "DISPUTE",
        "http_method": "GET",
        "base_url": "http://localhost:3052",
        "endpoint_path": "/api/v1/services/chargebacks/{chargeback_id}",
        "auth_type": "NONE",
        "auth_header_key": "Authorization",
        "auth_token_encrypted": None,
        "custom_headers": {},
        "sample_payload": None,
        "sample_response": None,
        "timeout_ms": 5000,
        "retry_count": 1,
        "is_mock_enabled": False,
        "is_active": True,
    },
    {
        "id": "default-order",
        "service_key": "ORDER_SERVICE",
        "service_name": "Order & Fulfillment Service",
        "service_category": "ORDER",
        "http_method": "GET",
        "base_url": "http://localhost:3052",
        "endpoint_path": "/api/v1/services/orders/{order_id}",
        "auth_type": "NONE",
        "auth_header_key": "Authorization",
        "auth_token_encrypted": None,
        "custom_headers": {},
        "sample_payload": None,
        "sample_response": None,
        "timeout_ms": 5000,
        "retry_count": 1,
        "is_mock_enabled": False,
        "is_active": True,
    },
    {
        "id": "default-payment",
        "service_key": "PAYMENT_SERVICE",
        "service_name": "Payment Gateway Service",
        "service_category": "PAYMENT",
        "http_method": "GET",
        "base_url": "http://localhost:3052",
        "endpoint_path": "/api/v1/services/payments/{payment_id}",
        "auth_type": "NONE",
        "auth_header_key": "Authorization",
        "auth_token_encrypted": None,
        "custom_headers": {},
        "sample_payload": None,
        "sample_response": None,
        "timeout_ms": 5000,
        "retry_count": 1,
        "is_mock_enabled": False,
        "is_active": True,
    },
    {
        "id": "default-refund",
        "service_key": "REFUND_SERVICE",
        "service_name": "Refund & Return Service",
        "service_category": "PAYMENT",
        "http_method": "GET",
        "base_url": "http://localhost:3052",
        "endpoint_path": "/api/v1/services/refunds/{refund_id}",
        "auth_type": "NONE",
        "auth_header_key": "Authorization",
        "auth_token_encrypted": None,
        "custom_headers": {},
        "sample_payload": None,
        "sample_response": None,
        "timeout_ms": 5000,
        "retry_count": 1,
        "is_mock_enabled": False,
        "is_active": True,
    },
    {
        "id": "default-user",
        "service_key": "USER_SERVICE",
        "service_name": "User / Customer 360 Service",
        "service_category": "IDENTITY",
        "http_method": "GET",
        "base_url": "http://localhost:3052",
        "endpoint_path": "/api/v1/services/users/{user_id}",
        "auth_type": "NONE",
        "auth_header_key": "Authorization",
        "auth_token_encrypted": None,
        "custom_headers": {},
        "sample_payload": None,
        "sample_response": None,
        "timeout_ms": 5000,
        "retry_count": 1,
        "is_mock_enabled": False,
        "is_active": True,
    },
]


def _target_table_for_service(service_key: str) -> str:
    return TARGET_TABLE_MAP.get(service_key, "external_api")


def _serialize_connector_spec(conn: MicroserviceApiRegistry) -> Dict[str, Any]:
    """Extracts plain Python values from a MicroserviceApiRegistry row on the main thread."""
    return {
        "id": conn.id,
        "service_key": conn.service_key,
        "service_name": conn.service_name,
        "service_category": conn.service_category,
        "http_method": (conn.http_method or "GET").upper(),
        "base_url": (conn.base_url or "").strip(),
        "endpoint_path": (conn.endpoint_path or "").strip(),
        "auth_type": (conn.auth_type or "NONE").upper(),
        "auth_header_key": conn.auth_header_key or "Authorization",
        "auth_token_encrypted": conn.auth_token_encrypted,
        "custom_headers": dict(conn.custom_headers or {}),
        "sample_payload": conn.sample_payload,
        "sample_response": conn.sample_response,
        "timeout_ms": int(conn.timeout_ms or 5000),
        "retry_count": int(conn.retry_count if conn.retry_count is not None else 1),
        "is_mock_enabled": bool(conn.is_mock_enabled),
        "is_active": bool(conn.is_active),
    }


def _resolve_headers(spec: Dict[str, Any]) -> Dict[str, str]:
    headers = dict(spec.get("custom_headers") or {})
    token = spec.get("auth_token_encrypted") or ""
    if isinstance(token, str) and token.startswith("ENV:"):
        token = os.environ.get(token[4:], "")

    auth_type = (spec.get("auth_type") or "NONE").upper()
    auth_header_key = spec.get("auth_header_key") or "Authorization"
    if auth_type == "BEARER_TOKEN" and token:
        headers[auth_header_key] = f"Bearer {token}"
    elif auth_type == "API_KEY" and token:
        headers[auth_header_key or "X-API-KEY"] = token
    elif auth_type == "CUSTOM_HEADER" and token:
        headers[auth_header_key or "X-Custom-Auth"] = token
    elif auth_type == "BASIC_AUTH" and token:
        headers[auth_header_key] = token if token.startswith("Basic ") else f"Basic {token}"
    return headers


def _resolve_connector_http_target(
    spec: Dict[str, Any],
    user_id: Optional[str] = None,
    transaction_id: Optional[str] = None,
    order_id: Optional[str] = None,
    merchant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolves endpoint path, query params, and payload for a connector given case context.
    Automatically falls back from /{entity_id} to ?user_id=... collection queries when
    only user_id (or transaction_id) is available on the investigation trigger.
    """
    s_key = spec["service_key"]
    method = (spec.get("http_method") or "GET").upper()
    endpoint = spec.get("endpoint_path") or ""
    query_params: Dict[str, str] = {}
    json_body: Any = spec.get("sample_payload")
    skip_reason: Optional[str] = None

    if s_key == "USER_SERVICE":
        target_u = user_id or merchant_id
        if not target_u:
            skip_reason = "No user_id or merchant_id provided"
        elif "{user_id}" in endpoint:
            endpoint = endpoint.replace("{user_id}", target_u)
        else:
            query_params["user_id"] = target_u

    elif s_key == "ORDER_SERVICE":
        if order_id:
            if "{order_id}" in endpoint:
                endpoint = endpoint.replace("{order_id}", order_id)
            else:
                query_params["order_id"] = order_id
        elif user_id:
            endpoint = endpoint.replace("/{order_id}", "").replace("{order_id}", "")
            query_params["user_id"] = user_id
        else:
            skip_reason = "No order_id or user_id provided"

    elif s_key == "PAYMENT_SERVICE":
        if transaction_id:
            if "{payment_id}" in endpoint:
                endpoint = endpoint.replace("{payment_id}", transaction_id)
            else:
                query_params["payment_id"] = transaction_id
        elif user_id:
            endpoint = endpoint.replace("/{payment_id}", "").replace("{payment_id}", "")
            query_params["user_id"] = user_id
        elif order_id:
            endpoint = endpoint.replace("/{payment_id}", "").replace("{payment_id}", "")
            query_params["order_id"] = order_id
        else:
            skip_reason = "No transaction_id, user_id, or order_id provided"

    elif s_key == "CHARGEBACK_SERVICE":
        endpoint = endpoint.replace("/{chargeback_id}", "").replace("{chargeback_id}", "")
        if transaction_id:
            query_params["payment_id"] = transaction_id
        elif user_id:
            query_params["user_id"] = user_id
        else:
            skip_reason = "No transaction_id or user_id provided"

    elif s_key == "REFUND_SERVICE":
        endpoint = endpoint.replace("/{refund_id}", "").replace("{refund_id}", "")
        if user_id:
            query_params["user_id"] = user_id
        elif transaction_id:
            query_params["payment_id"] = transaction_id
        elif order_id:
            query_params["order_id"] = order_id
        else:
            skip_reason = "No user_id, transaction_id, or order_id provided"

    else:
        # Custom / third-party connector
        replacements = {
            "user_id": user_id,
            "transaction_id": transaction_id,
            "payment_id": transaction_id,
            "order_id": order_id,
            "merchant_id": merchant_id,
        }
        embedded_keys = set()
        for k, v in replacements.items():
            placeholder = f"{{{k}}}"
            if placeholder in endpoint:
                if v:
                    endpoint = endpoint.replace(placeholder, str(v))
                    embedded_keys.add(k)
                else:
                    endpoint = endpoint.replace(f"/{placeholder}", "").replace(placeholder, "")
        # Clean up any leftover unknown path placeholders
        endpoint = re.sub(r"/\{[^}]+\}", "", endpoint)

        context_payload = {
            k: v for k, v in {
                "user_id": user_id,
                "transaction_id": transaction_id,
                "order_id": order_id,
                "merchant_id": merchant_id,
            }.items() if v is not None
        }
        if method in ("GET", "DELETE"):
            for k, v in context_payload.items():
                if k not in embedded_keys:
                    query_params[k] = str(v)
        elif method in ("POST", "PUT", "PATCH"):
            if isinstance(json_body, dict):
                merged = dict(json_body)
                for k, v in context_payload.items():
                    merged.setdefault(k, v)
                json_body = merged
            elif json_body is None and context_payload:
                json_body = context_payload

    local_path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    base_url = (spec.get("base_url") or "").strip()
    target_url = f"{base_url.rstrip('/')}/{local_path.lstrip('/')}" if base_url else local_path

    return {
        "method": method,
        "local_path": local_path,
        "target_url": target_url,
        "query_params": query_params,
        "json_body": json_body,
        "headers": _resolve_headers(spec),
        "skip_reason": skip_reason,
    }


def _normalize_http_response(
    s_key: str,
    target_table: str,
    status_code: int,
    resp_body: Any,
    lookup_ctx: Dict[str, Optional[str]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Extracts domain records and normalized CaseEvidence descriptor dicts from an HTTP response.
    Returns (records_list, evidence_descriptors).
    """
    # 404 on internal microservices directory simply means 0 matching records for this user/entity
    if status_code == 404 and s_key in CORE_SERVICE_KEYS:
        return [], []

    records: List[Dict[str, Any]] = []
    evidence_descriptors: List[Dict[str, Any]] = []

    if s_key == "USER_SERVICE":
        if isinstance(resp_body, dict):
            if resp_body.get("user"):
                records = [resp_body["user"]]
            elif isinstance(resp_body.get("users"), list):
                records = resp_body["users"]
        for u in records:
            payload_hash = hashlib.sha256(json.dumps(u, sort_keys=True, default=str).encode()).hexdigest()
            evidence_descriptors.append({
                "evidence_type": "USER_PROFILE",
                "source_system": f"USER_SERVICE [{target_table}]",
                "source_reference": u.get("user_id") or lookup_ctx.get("user_id") or "N/A",
                "retrieval_status": "COLLECTED",
                "normalized_payload": u,
                "content_hash": payload_hash,
            })

    elif s_key == "ORDER_SERVICE":
        if isinstance(resp_body, dict):
            if resp_body.get("order"):
                records = [resp_body["order"]]
            elif isinstance(resp_body.get("orders"), list):
                records = resp_body["orders"][:10]
        for o in records:
            payload_hash = hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()
            evidence_descriptors.append({
                "evidence_type": "ORDER_DETAILS",
                "source_system": f"ORDER_SERVICE [{target_table}]",
                "source_reference": o.get("order_id") or "N/A",
                "retrieval_status": "COLLECTED",
                "normalized_payload": o,
                "content_hash": payload_hash,
            })

    elif s_key == "PAYMENT_SERVICE":
        if isinstance(resp_body, dict):
            if resp_body.get("payment"):
                records = [resp_body["payment"]]
            elif isinstance(resp_body.get("payments"), list):
                records = resp_body["payments"][:10]
        for p in records:
            payload_hash = hashlib.sha256(json.dumps(p, sort_keys=True, default=str).encode()).hexdigest()
            evidence_descriptors.append({
                "evidence_type": "PAYMENT_RECORD",
                "source_system": f"PAYMENT_SERVICE [{target_table}]",
                "source_reference": p.get("payment_id") or "N/A",
                "retrieval_status": "COLLECTED",
                "normalized_payload": p,
                "content_hash": payload_hash,
            })

    elif s_key == "CHARGEBACK_SERVICE":
        if isinstance(resp_body, dict):
            if resp_body.get("chargeback"):
                records = [resp_body["chargeback"]]
            elif isinstance(resp_body.get("chargebacks"), list):
                records = resp_body["chargebacks"][:10]
        for c in records:
            payload_hash = hashlib.sha256(json.dumps(c, sort_keys=True, default=str).encode()).hexdigest()
            evidence_descriptors.append({
                "evidence_type": "CHARGEBACK_HISTORY",
                "source_system": f"CHARGEBACK_SERVICE [{target_table}]",
                "source_reference": c.get("chargeback_id") or "N/A",
                "retrieval_status": "COLLECTED",
                "normalized_payload": c,
                "content_hash": payload_hash,
            })

    elif s_key == "REFUND_SERVICE":
        if isinstance(resp_body, dict):
            if resp_body.get("refund"):
                records = [resp_body["refund"]]
            elif isinstance(resp_body.get("refunds"), list):
                records = resp_body["refunds"][:10]
        for r in records:
            payload_hash = hashlib.sha256(json.dumps(r, sort_keys=True, default=str).encode()).hexdigest()
            evidence_descriptors.append({
                "evidence_type": "REFUND_HISTORY",
                "source_system": f"REFUND_SERVICE [{target_table}]",
                "source_reference": r.get("refund_id") or "N/A",
                "retrieval_status": "COLLECTED",
                "normalized_payload": r,
                "content_hash": payload_hash,
            })

    else:
        payload = resp_body if isinstance(resp_body, (dict, list)) else {"raw_response": resp_body}
        records = [payload] if isinstance(payload, dict) else list(payload)
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        evidence_descriptors.append({
            "evidence_type": f"{s_key}_RECORD",
            "source_system": s_key,
            "source_reference": (
                lookup_ctx.get("user_id")
                or lookup_ctx.get("transaction_id")
                or lookup_ctx.get("order_id")
                or "N/A"
            ),
            "retrieval_status": "COLLECTED",
            "normalized_payload": payload,
            "content_hash": payload_hash,
        })

    return records, evidence_descriptors


def _execute_http_connector_worker(
    app: Any,
    spec: Dict[str, Any],
    lookup_ctx: Dict[str, Optional[str]],
) -> Dict[str, Any]:
    """
    Worker executed inside ThreadPoolExecutor for a single active microservice connector.
    Creates no cross-thread ORM mutations; returns plain serializable dicts.
    """
    s_key = spec["service_key"]
    s_name = spec["service_name"]
    target_table = _target_table_for_service(s_key)
    start_t = time.time()

    resolved = _resolve_connector_http_target(
        spec,
        user_id=lookup_ctx.get("user_id"),
        transaction_id=lookup_ctx.get("transaction_id"),
        order_id=lookup_ctx.get("order_id"),
        merchant_id=lookup_ctx.get("merchant_id"),
    )

    if resolved["skip_reason"]:
        latency_ms = int((time.time() - start_t) * 1000)
        return {
            "service_key": s_key,
            "service_name": s_name,
            "target_table": target_table,
            "status": "COLLECTED",
            "status_code": 204,
            "execution_mode": "SKIPPED_NO_KEY",
            "records": [],
            "evidence_descriptors": [],
            "records_count": 0,
            "latency_ms": latency_ms,
            "error": None,
            "log_line": (
                f"  {COLOR_GREEN}[✓ ACTIVE]{COLOR_RESET}   {COLOR_BOLD}{s_key:<20}{COLOR_RESET} ➔ "
                f"{COLOR_GREEN}HTTP {resolved['local_path']}{COLOR_RESET} (0 matching records) [NO_KEY • {latency_ms}ms]"
            ),
        }

    def _run_http() -> Tuple[int, Any, str]:
        if spec.get("is_mock_enabled"):
            return 200, (spec.get("sample_response") or {"status": "ok", "mock": True}), "MOCK_SIMULATION"

        base_url = spec.get("base_url") or ""
        local_path = resolved["local_path"]
        is_local_base = (not base_url) or ("localhost" in base_url) or ("127.0.0.1" in base_url)
        is_internal = (
            local_path.startswith("/api/v1/services")
            and is_local_base
            and not Config.MICROSERVICE_FORCE_NETWORK_HTTP
        )

        if is_internal and app is not None:
            client = app.test_client()
            client_kwargs: Dict[str, Any] = {
                "method": resolved["method"],
                "path": local_path,
                "query_string": resolved["query_params"] or None,
                "headers": resolved["headers"],
            }
            if resolved["method"] in ("POST", "PUT", "PATCH") and resolved["json_body"] is not None:
                client_kwargs["json"] = resolved["json_body"]
            resp = client.open(**client_kwargs)
            body = resp.get_json(silent=True)
            if body is None:
                body = resp.get_data(as_text=True)
            return resp.status_code, body, "LIVE_DATABASE_SERVICE"

        # External / real network HTTP dispatch via httpx
        timeout_sec = max(0.5, (spec.get("timeout_ms") or 5000) / 1000.0)
        max_retries = min(max(0, int(spec.get("retry_count") or 0)), 3)
        last_exc: Optional[Exception] = None

        with httpx.Client(timeout=timeout_sec) as http_client:
            for attempt in range(max_retries + 1):
                try:
                    req_kwargs: Dict[str, Any] = {
                        "method": resolved["method"],
                        "url": resolved["target_url"],
                        "params": resolved["query_params"] or None,
                        "headers": resolved["headers"],
                    }
                    if resolved["method"] in ("POST", "PUT", "PATCH") and resolved["json_body"] is not None:
                        req_kwargs["json"] = resolved["json_body"]
                    resp = http_client.request(**req_kwargs)
                    try:
                        body = resp.json()
                    except Exception:
                        body = resp.text
                    if resp.status_code >= 500 and attempt < max_retries:
                        continue
                    return resp.status_code, body, "LIVE_NETWORK"
                except httpx.RequestError as exc:
                    last_exc = exc
                    if attempt >= max_retries:
                        raise
            if last_exc:
                raise last_exc
        raise RuntimeError(f"Unexpected HTTP dispatch termination for {s_key}")

    try:
        if app is not None:
            with app.app_context():
                try:
                    status_code, resp_body, exec_mode = _run_http()
                finally:
                    db.session.remove()
        else:
            status_code, resp_body, exec_mode = _run_http()

        latency_ms = max(1, int((time.time() - start_t) * 1000))

        # Non-404 >=400 HTTP error on external/internal API
        if status_code >= 400 and not (status_code == 404 and s_key in CORE_SERVICE_KEYS):
            err_msg = f"HTTP {status_code}: {str(resp_body)[:200]}"
            return {
                "service_key": s_key,
                "service_name": s_name,
                "target_table": target_table,
                "status": "ERROR",
                "status_code": status_code,
                "execution_mode": exec_mode,
                "records": [],
                "evidence_descriptors": [{
                    "evidence_type": f"{s_key}_ERROR",
                    "source_system": f"{s_key} [{target_table}]",
                    "source_reference": lookup_ctx.get("user_id") or lookup_ctx.get("transaction_id") or "N/A",
                    "retrieval_status": "FAILED",
                    "normalized_payload": {"error": err_msg, "status_code": status_code, "target_url": resolved["target_url"]},
                    "content_hash": None,
                }],
                "records_count": 0,
                "latency_ms": latency_ms,
                "error": err_msg,
                "log_line": (
                    f"  {COLOR_YELLOW}[! ERROR]{COLOR_RESET}    {COLOR_BOLD}{s_key:<20}{COLOR_RESET} ➔ "
                    f"{COLOR_RED}{err_msg}{COLOR_RESET} [{latency_ms}ms]"
                ),
            }

        records, evidence_descriptors = _normalize_http_response(
            s_key=s_key,
            target_table=target_table,
            status_code=status_code,
            resp_body=resp_body,
            lookup_ctx=lookup_ctx,
        )
        rec_count = len(records)
        status_str = f"{rec_count} records" if rec_count > 0 else "0 matching records"
        return {
            "service_key": s_key,
            "service_name": s_name,
            "target_table": target_table,
            "status": "COLLECTED",
            "status_code": status_code,
            "execution_mode": exec_mode,
            "records": records,
            "evidence_descriptors": evidence_descriptors,
            "records_count": rec_count,
            "latency_ms": latency_ms,
            "error": None,
            "log_line": (
                f"  {COLOR_GREEN}[✓ ACTIVE]{COLOR_RESET}   {COLOR_BOLD}{s_key:<20}{COLOR_RESET} ➔ "
                f"{COLOR_GREEN}{resolved['method']} {resolved['local_path']} ({target_table}){COLOR_RESET} "
                f"({status_str}) [{status_code} • {latency_ms}ms • {exec_mode}]"
            ),
        }

    except Exception as exc:
        latency_ms = max(1, int((time.time() - start_t) * 1000))
        err_msg = str(exc)
        return {
            "service_key": s_key,
            "service_name": s_name,
            "target_table": target_table,
            "status": "ERROR",
            "status_code": 504,
            "execution_mode": "ERROR",
            "records": [],
            "evidence_descriptors": [{
                "evidence_type": f"{s_key}_ERROR",
                "source_system": f"{s_key} [{target_table}]",
                "source_reference": lookup_ctx.get("user_id") or lookup_ctx.get("transaction_id") or "N/A",
                "retrieval_status": "FAILED",
                "normalized_payload": {"error": err_msg, "target_url": resolved["target_url"]},
                "content_hash": None,
            }],
            "records_count": 0,
            "latency_ms": latency_ms,
            "error": err_msg,
            "log_line": (
                f"  {COLOR_YELLOW}[! ERROR]{COLOR_RESET}    {COLOR_BOLD}{s_key:<20}{COLOR_RESET} ➔ "
                f"{COLOR_RED}Failed: {err_msg}{COLOR_RESET} [{latency_ms}ms]"
            ),
        }


class MicroserviceDispatcher:
    """Dynamic dispatcher for parallel HTTP microservice evidence collection & runtime gating."""

    @staticmethod
    def get_connector(service_key: str) -> Optional[MicroserviceApiRegistry]:
        """Fetches connector configuration by service_key."""
        try:
            return MicroserviceApiRegistry.query.filter_by(service_key=service_key).first()
        except Exception as e:
            logger.warning(f"Failed to lookup connector {service_key}: {e}")
            return None

    @classmethod
    def is_service_active(cls, service_key: str) -> bool:
        """
        Returns True if the microservice is registered AND active (is_active == True).
        If connector is found and disabled, returns False.
        """
        conn = cls.get_connector(service_key)
        return bool(conn and conn.is_active)

    @staticmethod
    def get_all_connectors_status() -> Dict[str, Dict[str, Any]]:
        """Returns map of all registered connectors with active status and mapped tables."""
        try:
            connectors = MicroserviceApiRegistry.query.order_by(MicroserviceApiRegistry.service_key.asc()).all()
            status_map = {}
            for c in connectors:
                status_map[c.service_key] = {
                    "id": c.id,
                    "service_name": c.service_name,
                    "service_category": c.service_category,
                    "endpoint_path": c.endpoint_path,
                    "is_active": c.is_active,
                    "target_table": _target_table_for_service(c.service_key),
                }
            return status_map
        except Exception as e:
            logger.warning(f"Failed to load connectors status: {e}")
            return {}

    @staticmethod
    def _load_connector_specs() -> List[Dict[str, Any]]:
        """Loads registered connector specs sorted by service_key, or defaults if empty."""
        try:
            connectors = MicroserviceApiRegistry.query.order_by(MicroserviceApiRegistry.service_key.asc()).all()
        except Exception as e:
            logger.warning(f"Connector registry query failed, using defaults: {e}")
            connectors = []

        if connectors:
            return [_serialize_connector_spec(c) for c in connectors]
        return [dict(s) for s in DEFAULT_CORE_SPECS]

    @classmethod
    def fetch_domain_snapshot_parallel(
        cls,
        user_id: Optional[str] = None,
        transaction_id: Optional[str] = None,
        order_id: Optional[str] = None,
        merchant_id: Optional[str] = None,
        case_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fires HTTP calls to all active registered microservices IN PARALLEL for one target user/case,
        blocks at a synchronization barrier until all complete (or timeout), and returns a structured
        snapshot containing normalized evidence descriptors, raw records by service, and telemetry.
        """
        specs = cls._load_connector_specs()
        lookup_ctx = {
            "user_id": user_id,
            "transaction_id": transaction_id,
            "order_id": order_id,
            "merchant_id": merchant_id,
        }

        try:
            app = current_app._get_current_object()
        except RuntimeError:
            app = None

        active_specs = [s for s in specs if s.get("is_active", True)]
        disabled_specs = [s for s in specs if not s.get("is_active", True)]

        summary: Dict[str, Any] = {
            "active_sources": [],
            "bypassed_sources": [],
            "telemetry": [],
        }
        evidence_descriptors: List[Dict[str, Any]] = []
        records_by_service: Dict[str, List[Dict[str, Any]]] = {}
        service_active: Dict[str, bool] = {s["service_key"]: bool(s.get("is_active", True)) for s in specs}
        log_lines: List[str] = []

        # Disabled connectors are recorded immediately without thread dispatch
        for spec in disabled_specs:
            s_key = spec["service_key"]
            s_name = spec["service_name"]
            target_table = _target_table_for_service(s_key)
            records_by_service[s_key] = []
            log_lines.append(
                f"  {COLOR_RED}[✗ DISABLED]{COLOR_RESET} {COLOR_BOLD}{s_key:<20}{COLOR_RESET} ➔ "
                f"{COLOR_DIM}BYPASSED (Admin Policy: OFF){COLOR_RESET}"
            )
            summary["bypassed_sources"].append(f"{s_key} [{target_table}] (Admin Policy: OFF)")
            summary["telemetry"].append({
                "service_key": s_key,
                "service_name": s_name,
                "status": "DISABLED",
                "target_table": target_table,
                "bypassed": True,
            })
            evidence_descriptors.append({
                "evidence_type": f"{s_key}_AUDIT",
                "source_system": f"{s_key} [{target_table}]",
                "source_reference": "BYPASSED_BY_CONFIG",
                "retrieval_status": "SKIPPED",
                "normalized_payload": {
                    "service_key": s_key,
                    "status": "DISABLED",
                    "note": f"{s_name} was bypassed during investigation because its Admin Console toggle is OFF.",
                },
                "content_hash": None,
            })

        # Parallel fan-out across all active connectors with barrier wait
        worker_results_by_key: Dict[str, Dict[str, Any]] = {}
        wall_start = time.time()

        if active_specs:
            max_workers = max(1, min(len(active_specs), Config.MICROSERVICE_MAX_WORKERS))
            barrier_timeout = getattr(Config, "MICROSERVICE_BARRIER_TIMEOUT_SECONDS", 15.0)
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="ms_dispatch",
            ) as executor:
                future_to_spec = {
                    executor.submit(_execute_http_connector_worker, app, spec, lookup_ctx): spec
                    for spec in active_specs
                }
                done, not_done = concurrent.futures.wait(
                    future_to_spec.keys(),
                    timeout=barrier_timeout,
                    return_when=concurrent.futures.ALL_COMPLETED,
                )

                for fut in done:
                    spec = future_to_spec[fut]
                    s_key = spec["service_key"]
                    try:
                        worker_results_by_key[s_key] = fut.result()
                    except Exception as exc:
                        target_table = _target_table_for_service(s_key)
                        worker_results_by_key[s_key] = {
                            "service_key": s_key,
                            "service_name": spec["service_name"],
                            "target_table": target_table,
                            "status": "ERROR",
                            "status_code": 500,
                            "execution_mode": "ERROR",
                            "records": [],
                            "evidence_descriptors": [{
                                "evidence_type": f"{s_key}_ERROR",
                                "source_system": f"{s_key} [{target_table}]",
                                "source_reference": user_id or transaction_id or "N/A",
                                "retrieval_status": "FAILED",
                                "normalized_payload": {"error": str(exc)},
                                "content_hash": None,
                            }],
                            "records_count": 0,
                            "latency_ms": int((time.time() - wall_start) * 1000),
                            "error": str(exc),
                            "log_line": (
                                f"  {COLOR_YELLOW}[! ERROR]{COLOR_RESET}    {COLOR_BOLD}{s_key:<20}{COLOR_RESET} ➔ "
                                f"{COLOR_RED}Worker exception: {exc}{COLOR_RESET}"
                            ),
                        }

                for fut in not_done:
                    fut.cancel()
                    spec = future_to_spec[fut]
                    s_key = spec["service_key"]
                    target_table = _target_table_for_service(s_key)
                    err_msg = f"Microservice barrier timeout after {barrier_timeout}s"
                    worker_results_by_key[s_key] = {
                        "service_key": s_key,
                        "service_name": spec["service_name"],
                        "target_table": target_table,
                        "status": "ERROR",
                        "status_code": 504,
                        "execution_mode": "TIMEOUT",
                        "records": [],
                        "evidence_descriptors": [{
                            "evidence_type": f"{s_key}_ERROR",
                            "source_system": f"{s_key} [{target_table}]",
                            "source_reference": user_id or transaction_id or "N/A",
                            "retrieval_status": "FAILED",
                            "normalized_payload": {"error": err_msg},
                            "content_hash": None,
                        }],
                        "records_count": 0,
                        "latency_ms": int(barrier_timeout * 1000),
                        "error": err_msg,
                        "log_line": (
                            f"  {COLOR_YELLOW}[! TIMEOUT]{COLOR_RESET}  {COLOR_BOLD}{s_key:<20}{COLOR_RESET} ➔ "
                            f"{COLOR_RED}{err_msg}{COLOR_RESET}"
                        ),
                    }

        total_wall_ms = int((time.time() - wall_start) * 1000)

        # Merge results in deterministic spec order
        for spec in active_specs:
            s_key = spec["service_key"]
            res = worker_results_by_key[s_key]
            target_table = res["target_table"]
            records_by_service[s_key] = res.get("records", [])
            evidence_descriptors.extend(res.get("evidence_descriptors", []))
            log_lines.append(res["log_line"])

            if res["status"] == "COLLECTED":
                rec_count = res["records_count"]
                status_str = f"{rec_count} records" if rec_count > 0 else "0 matching records"
                summary["active_sources"].append(f"{s_key} [{target_table}] ({status_str})")
                summary["telemetry"].append({
                    "service_key": s_key,
                    "service_name": res["service_name"],
                    "status": "COLLECTED",
                    "target_table": target_table,
                    "records_count": rec_count,
                    "latency_ms": res["latency_ms"],
                    "status_code": res.get("status_code"),
                    "execution_mode": res.get("execution_mode"),
                })
            else:
                summary["telemetry"].append({
                    "service_key": s_key,
                    "service_name": res["service_name"],
                    "status": "ERROR",
                    "target_table": target_table,
                    "error": res.get("error"),
                    "latency_ms": res["latency_ms"],
                    "status_code": res.get("status_code"),
                    "execution_mode": res.get("execution_mode"),
                })

        # Clean, non-interleaved terminal summary
        label_str = case_label or (f"User: {user_id}" if user_id else "N/A")
        print(f"\n{COLOR_BOLD}{COLOR_CYAN}================================================================================{COLOR_RESET}")
        print(
            f"{COLOR_BOLD}{COLOR_CYAN}📡 [AGENT EVIDENCE PIPELINE] Parallel HTTP Dispatch ({label_str}) • "
            f"{len(active_specs)} active in {total_wall_ms}ms{COLOR_RESET}"
        )
        print(f"{COLOR_BOLD}{COLOR_CYAN}================================================================================{COLOR_RESET}")
        for line in log_lines:
            print(line)
        print(f"{COLOR_BOLD}{COLOR_CYAN}================================================================================{COLOR_RESET}\n")

        return {
            "evidence_descriptors": evidence_descriptors,
            "summary": summary,
            "records_by_service": records_by_service,
            "service_active": service_active,
            "wall_time_ms": total_wall_ms,
        }

    @classmethod
    def dispatch_case_evidence(
        cls,
        case_id: str,
        user_id: Optional[str] = None,
        transaction_id: Optional[str] = None,
        order_id: Optional[str] = None,
        merchant_id: Optional[str] = None,
        prefetched_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[CaseEvidence], Dict[str, Any]]:
        """
        Orchestrates parallel HTTP evidence collection across all registered active microservices
        (or persists a pre-fetched parallel snapshot), generates CaseEvidence items, and commits once.
        """
        now = datetime.now(timezone.utc)
        snapshot = prefetched_snapshot or cls.fetch_domain_snapshot_parallel(
            user_id=user_id,
            transaction_id=transaction_id,
            order_id=order_id,
            merchant_id=merchant_id,
            case_label=f"Case: {case_id[:8]}...",
        )

        evidence_items: List[CaseEvidence] = []
        for desc in snapshot.get("evidence_descriptors", []):
            evidence_items.append(
                CaseEvidence(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    evidence_type=desc["evidence_type"],
                    source_system=desc["source_system"],
                    source_reference=desc.get("source_reference"),
                    retrieval_status=desc["retrieval_status"],
                    retrieved_at=now,
                    normalized_payload=desc.get("normalized_payload"),
                    content_hash=desc.get("content_hash"),
                )
            )

        try:
            if evidence_items:
                db.session.add_all(evidence_items)
                db.session.commit()
        except Exception as commit_err:
            db.session.rollback()
            logger.debug(f"Evidence session commit note: {commit_err}")

        return evidence_items, snapshot.get("summary", {"active_sources": [], "bypassed_sources": [], "telemetry": []})
