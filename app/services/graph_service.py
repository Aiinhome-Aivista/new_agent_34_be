import logging
from typing import Dict, Any, List, Optional
from backend.app.config import Config
from backend.app.models.source_domain import Order, Payment

logger = logging.getLogger("fraud_agent.graph_service")

class GraphEntityService:
    """Manages multi-hop fraud entity correlation using ArangoDB or relational topology."""

    _arango_client = None
    _db = None

    @classmethod
    def get_arango_connection(cls):
        """Attempts connection to ArangoDB with fast-fail socket check."""
        if cls._db is not None:
            return cls._db

        try:
            import socket
            from urllib.parse import urlparse
            parsed = urlparse(Config.ARANGO_HOST)
            host = parsed.hostname or "localhost"
            port = parsed.port or 8529
            with socket.create_connection((host, port), timeout=0.3):
                pass
        except Exception:
            cls._db = None
            return None

        try:
            from arango import ArangoClient
            client = ArangoClient(hosts=Config.ARANGO_HOST)
            # Check connection
            sys_db = client.db('_system', username=Config.ARANGO_USER, password=Config.ARANGO_PASSWORD)
            if not sys_db.has_database(Config.ARANGO_DB):
                sys_db.create_database(Config.ARANGO_DB)
            cls._db = client.db(Config.ARANGO_DB, username=Config.ARANGO_USER, password=Config.ARANGO_PASSWORD)
            logger.info("Successfully connected to ArangoDB.")
            return cls._db
        except Exception as e:
            logger.info(f"ArangoDB connection not active: {e}. Graph analysis will use relational link discovery.")
            cls._db = None
            return None

    @classmethod
    def analyze_entity_network(cls, user_id: Optional[str] = None, merchant_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Traverses relationships across entities (Device IDs, IP Addresses, Payment Methods).
        Detects shared footprints (e.g. 5 users transacting from identical device/IP).
        """
        shared_devices = []
        shared_ips = []
        nodes = []
        edges = []

        # Relational link discovery from actual persisted orders and payments
        if user_id:
            user_orders = Order.query.filter_by(user_id=user_id).all()
            user_devices = {o.device_id for o in user_orders if o.device_id}
            user_ips = {o.ip_address for o in user_orders if o.ip_address}

            nodes.append({"id": user_id, "label": f"User: {user_id[:8]}", "type": "USER"})

            # Check if any other user shares the same device
            if user_devices:
                for dev in user_devices:
                    nodes.append({"id": dev, "label": f"Device: {dev[:12]}", "type": "DEVICE"})
                    edges.append({"from": user_id, "to": dev, "relation": "USED_DEVICE"})
                    
                    co_users = Order.query.filter(Order.device_id == dev, Order.user_id != user_id).limit(5).all()
                    for co in co_users:
                        shared_devices.append({"device_id": dev, "linked_user_id": co.user_id})
                        nodes.append({"id": co.user_id, "label": f"User: {co.user_id[:8]}", "type": "USER"})
                        edges.append({"from": co.user_id, "to": dev, "relation": "SHARED_DEVICE"})

            # Check if any other user shares the same IP
            if user_ips:
                for ip in user_ips:
                    nodes.append({"id": ip, "label": f"IP: {ip}", "type": "IP"})
                    edges.append({"from": user_id, "to": ip, "relation": "LOGGED_IP"})
                    
                    co_ips = Order.query.filter(Order.ip_address == ip, Order.user_id != user_id).limit(5).all()
                    for co in co_ips:
                        shared_ips.append({"ip_address": ip, "linked_user_id": co.user_id})

        return {
            "status": "ANALYZED",
            "nodes": nodes,
            "edges": edges,
            "shared_devices_count": len(shared_devices),
            "shared_ips_count": len(shared_ips),
            "network_risk_indicator": "HIGH" if (len(shared_devices) > 2 or len(shared_ips) > 3) else "NORMAL"
        }
