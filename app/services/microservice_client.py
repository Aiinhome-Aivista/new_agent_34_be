import os
import logging
import requests
from typing import Optional, Dict, Any, List
from app.models.governance import MicroserviceApiRegistry
from app.models.source_domain import MUser, MOrder, MPayment, MChargeback

logger = logging.getLogger("fraud_agent.microservice_client")


class DomainRecord(dict):
    """Dictionary subclass supporting dot notation for attribute access."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            return None

    def __setattr__(self, name, value):
        self[name] = value


class MicroserviceClient:
    """
    Enterprise Microservice API Client Dispatcher.
    Routes data requests to registered microservice REST endpoints when LIVE_NETWORK is enabled,
    with automatic, zero-downtime fallback to local database queries.
    """

    @staticmethod
    def _dispatch_http(connector: MicroserviceApiRegistry, endpoint_path: str, method: str = "GET", payload: Optional[dict] = None) -> Optional[Dict[str, Any]]:
        """Executes HTTP request against connector base_url and endpoint."""
        target_url = f"{connector.base_url.rstrip('/')}/{endpoint_path.lstrip('/')}"
        headers = dict(connector.custom_headers or {})

        token = connector.auth_token_encrypted or ""
        if token.startswith("ENV:"):
            token = os.environ.get(token[4:], "")

        if connector.auth_type == "BEARER_TOKEN" and token:
            headers[connector.auth_header_key or "Authorization"] = f"Bearer {token}"
        elif connector.auth_type == "API_KEY" and token:
            headers[connector.auth_header_key or "X-API-KEY"] = token
        elif connector.auth_type == "CUSTOM_HEADER" and token:
            headers[connector.auth_header_key or "X-Custom-Auth"] = token

        timeout_sec = (connector.timeout_ms or 5000) / 1000.0

        for attempt in range(max(1, connector.retry_count or 1)):
            try:
                logger.debug(f"[MicroserviceClient] {method} {target_url} (attempt {attempt+1})")
                req_kwargs = {
                    "method": method,
                    "url": target_url,
                    "headers": headers,
                    "timeout": timeout_sec
                }
                if method in ("POST", "PUT", "PATCH") and payload is not None:
                    req_kwargs["json"] = payload

                resp = requests.request(**req_kwargs)
                if resp.status_code == 200:
                    data = resp.json()
                    data["_source"] = "LIVE_MICROSERVICE_API"
                    data["_connector"] = connector.service_key
                    data["_target_url"] = target_url
                    return DomainRecord(data)
                elif resp.status_code == 404:
                    logger.info(f"[MicroserviceClient] 404 Not Found from {target_url}")
                    return None
                else:
                    logger.warning(f"[MicroserviceClient] HTTP {resp.status_code} from {target_url}")
            except Exception as e:
                logger.warning(f"[MicroserviceClient] Attempt {attempt+1} failed for {target_url}: {e}")

        return None

    @classmethod
    def get_user(cls, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches user profile via USER_PROFILE_SERVICE API if live,
        falling back to local m_users table.
        """
        if not user_id:
            return None

        connector = MicroserviceApiRegistry.query.filter_by(service_key="USER_PROFILE_SERVICE").first()
        if connector and not connector.is_mock_enabled and connector.is_active:
            endpoint = (connector.endpoint_path or "/api/v1/users/{user_id}").replace("{user_id}", str(user_id))
            api_data = cls._dispatch_http(connector, endpoint, method="GET")
            if api_data:
                return api_data

        # Fallback to local DB
        user = MUser.query.filter(
            (MUser.user_id == user_id) |
            (MUser.external_user_id == user_id) |
            (MUser.email == user_id)
        ).first()

        if user:
            res = user.to_dict()
            res["_source"] = "LOCAL_DATABASE_FALLBACK"
            return DomainRecord(res)
        return None

    @classmethod
    def get_payment(cls, payment_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches payment transaction via PAYMENT_GATEWAY_SERVICE API if live,
        falling back to local m_payments table.
        """
        if not payment_id:
            return None

        connector = MicroserviceApiRegistry.query.filter_by(service_key="PAYMENT_GATEWAY_SERVICE").first()
        if connector and not connector.is_mock_enabled and connector.is_active:
            endpoint = (connector.endpoint_path or "/api/v1/payments/{payment_id}").replace("{payment_id}", str(payment_id))
            api_data = cls._dispatch_http(connector, endpoint, method="GET")
            if api_data:
                return api_data

        # Fallback to local DB
        payment = MPayment.query.filter(
            (MPayment.payment_id == payment_id) |
            (MPayment.gateway_transaction_id == payment_id)
        ).first()

        if payment:
            res = payment.to_dict()
            res["_source"] = "LOCAL_DATABASE_FALLBACK"
            return DomainRecord(res)
        return None

    @classmethod
    def get_order(cls, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches order fulfillment details via ORDER_FULFILLMENT_SERVICE API if live,
        falling back to local m_orders table.
        """
        if not order_id:
            return None

        connector = MicroserviceApiRegistry.query.filter_by(service_key="ORDER_FULFILLMENT_SERVICE").first()
        if connector and not connector.is_mock_enabled and connector.is_active:
            endpoint = (connector.endpoint_path or "/api/v1/orders/{order_id}").replace("{order_id}", str(order_id))
            api_data = cls._dispatch_http(connector, endpoint, method="GET")
            if api_data:
                return api_data

        # Fallback to local DB
        order = MOrder.query.filter(
            (MOrder.order_id == order_id) |
            (MOrder.merchant_order_id == order_id)
        ).first()

        if order:
            res = order.to_dict()
            res["_source"] = "LOCAL_DATABASE_FALLBACK"
            return DomainRecord(res)
        return None

    @classmethod
    def get_disputes(cls, user_id: str) -> List[Dict[str, Any]]:
        """
        Fetches dispute history via DISPUTE_LEDGER_SERVICE API if live,
        falling back to local m_chargebacks table.
        """
        if not user_id:
            return []

        connector = MicroserviceApiRegistry.query.filter_by(service_key="DISPUTE_LEDGER_SERVICE").first()
        if connector and not connector.is_mock_enabled and connector.is_active:
            endpoint = (connector.endpoint_path or "/api/v1/disputes/summary/{user_id}").replace("{user_id}", str(user_id))
            api_data = cls._dispatch_http(connector, endpoint, method="GET")
            if api_data and "chargebacks" in api_data:
                return api_data.get("chargebacks", [])

        # Fallback to local DB
        cbs = (
            MChargeback.query
            .join(MPayment, MChargeback.payment_id == MPayment.payment_id)
            .filter(MPayment.user_id == user_id)
            .all()
        )
        if not cbs:
            cbs = MChargeback.query.filter(
                (MChargeback.payment_id == user_id) |
                (MChargeback.order_id == user_id)
            ).all()

        return [cb.to_dict() for cb in cbs]

    @classmethod
    def enforce_account_status(cls, user_id: str, status: str, reason: str = "Enforcement", idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes protective enforcement via ACCOUNT_ENFORCEMENT_SERVICE API if live,
        falling back to updating local m_users table.
        """
        connector = MicroserviceApiRegistry.query.filter_by(service_key="ACCOUNT_ENFORCEMENT_SERVICE").first()
        payload = {
            "status": status,
            "reason": reason,
            "idempotency_key": idempotency_key
        }

        if connector and not connector.is_mock_enabled and connector.is_active:
            endpoint = (connector.endpoint_path or "/api/v1/accounts/{user_id}/status").replace("{user_id}", str(user_id))
            api_data = cls._dispatch_http(connector, endpoint, method="PUT", payload=payload)
            if api_data:
                return api_data

        # Fallback to local DB update
        user = MUser.query.filter_by(user_id=user_id).first()
        prev = user.status if user else "UNKNOWN"
        if user:
            user.status = status
            from app.extensions import db
            db.session.commit()

        return {
            "user_id": user_id,
            "previous_status": prev,
            "new_status": status,
            "reason": reason,
            "_source": "LOCAL_DATABASE_FALLBACK"
        }
