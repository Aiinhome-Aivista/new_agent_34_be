"""
Phase 2: Entity Graph Store Service
=====================================
Manages Pipeline A: incremental upsert of entity nodes and relationships
as new users, orders, and payments are ingested.

During case investigation (Pipeline B), provides fast 2-hop traversal
without scanning full m_orders or m_payments tables.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy import text
from app.extensions import db
from app.models.knowledgebase import EntityNode, EntityRelationship

logger = logging.getLogger("fraud_agent.graph_store")

# Relation type constants
REL_USED_DEVICE = "USED_DEVICE"
REL_CONNECTED_FROM_IP = "CONNECTED_FROM_IP"
REL_PLACED_ORDER_AT = "PLACED_ORDER_AT"
REL_MADE_PAYMENT_VIA = "MADE_PAYMENT_VIA"
REL_SHARES_PAYMENT_METHOD = "SHARES_PAYMENT_METHOD"


class GraphStoreService:
    """
    Pipeline A: Incremental graph population.
    Pipeline B: Graph traversal for investigation intelligence.
    """

    # -----------------------------------------------------------------------
    # Pipeline A: Upsert helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def upsert_node(node_id: str, entity_type: str, display_label: str = None,
                    properties: Dict = None, risk_score: float = 0.0) -> None:
        """
        Insert or update an entity node. Safe to call repeatedly.
        """
        try:
            existing = EntityNode.query.get(node_id)
            if existing:
                # Update label and properties if provided
                if display_label:
                    existing.display_label = display_label
                if properties:
                    existing.properties_json = {**(existing.properties_json or {}), **properties}
                existing.updated_at = datetime.now(timezone.utc)
            else:
                node = EntityNode(
                    id=node_id,
                    entity_type=entity_type,
                    display_label=display_label,
                    properties_json=properties or {},
                    risk_score=risk_score,
                )
                db.session.add(node)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"[GraphStore] upsert_node failed for {node_id}: {e}")

    @staticmethod
    def upsert_relationship(source_id: str, source_type: str,
                             relation_type: str,
                             target_id: str, target_type: str,
                             properties: Dict = None) -> None:
        """
        Insert a new relationship edge or increment the weight counter if it already exists.
        """
        try:
            existing = EntityRelationship.query.filter_by(
                source_id=source_id,
                relation_type=relation_type,
                target_id=target_id
            ).first()

            if existing:
                existing.weight += 1
                existing.updated_at = datetime.now(timezone.utc)
                if properties:
                    existing.properties_json = {**(existing.properties_json or {}), **properties}
            else:
                rel = EntityRelationship(
                    source_id=source_id,
                    source_type=source_type,
                    relation_type=relation_type,
                    target_id=target_id,
                    target_type=target_type,
                    weight=1,
                    properties_json=properties or {},
                )
                db.session.add(rel)

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"[GraphStore] upsert_relationship failed {source_id}->{target_id}: {e}")

    @staticmethod
    def process_user_ingestion(user_id: str, email: str = None,
                                display_name: str = None, extra: Dict = None) -> None:
        """
        Called from ingest_service when a user record is processed.
        Creates/updates the USER entity node.
        """
        props = {"email": email} if email else {}
        if extra:
            props.update(extra)
        GraphStoreService.upsert_node(
            node_id=user_id,
            entity_type="USER",
            display_label=display_name or user_id,
            properties=props
        )
        logger.debug(f"[GraphStore] User node upserted: {user_id}")

    @staticmethod
    def process_order_ingestion(order: Dict[str, Any]) -> None:
        """
        Called from ingest_service when an order is processed.
        Creates device & IP nodes and links them to the user node.
        """
        user_id = order.get("user_id")
        device_id = order.get("device_id")
        ip_address = order.get("ip_address")
        merchant_id = order.get("merchant_id")
        order_id = order.get("order_id")

        if not user_id:
            return

        # Ensure user node exists
        GraphStoreService.upsert_node(user_id, "USER")

        # Device relationship
        if device_id:
            GraphStoreService.upsert_node(device_id, "DEVICE", display_label=f"Device:{device_id}")
            GraphStoreService.upsert_relationship(
                source_id=user_id, source_type="USER",
                relation_type=REL_USED_DEVICE,
                target_id=device_id, target_type="DEVICE",
                properties={"order_id": order_id}
            )

        # IP relationship
        if ip_address:
            GraphStoreService.upsert_node(ip_address, "IP_ADDRESS", display_label=ip_address)
            GraphStoreService.upsert_relationship(
                source_id=user_id, source_type="USER",
                relation_type=REL_CONNECTED_FROM_IP,
                target_id=ip_address, target_type="IP_ADDRESS",
                properties={"order_id": order_id}
            )

        # Merchant relationship
        if merchant_id:
            GraphStoreService.upsert_node(merchant_id, "MERCHANT", display_label=f"Merchant:{merchant_id}")
            GraphStoreService.upsert_relationship(
                source_id=user_id, source_type="USER",
                relation_type=REL_PLACED_ORDER_AT,
                target_id=merchant_id, target_type="MERCHANT",
                properties={"order_id": order_id}
            )

        logger.debug(f"[GraphStore] Order edges processed for user={user_id}, order={order_id}")

    @staticmethod
    def process_payment_ingestion(payment: Dict[str, Any]) -> None:
        """
        Called from ingest_service when a payment is processed.
        Links payment method and additional IP/device signals.
        """
        user_id = payment.get("user_id")
        device_id = payment.get("device_id")
        ip_address = payment.get("ip_address")
        payment_method = payment.get("payment_method")
        payment_id = payment.get("payment_id")

        if not user_id:
            return

        GraphStoreService.upsert_node(user_id, "USER")

        if device_id:
            GraphStoreService.upsert_node(device_id, "DEVICE")
            GraphStoreService.upsert_relationship(
                source_id=user_id, source_type="USER",
                relation_type=REL_USED_DEVICE,
                target_id=device_id, target_type="DEVICE",
                properties={"payment_id": payment_id}
            )

        if ip_address:
            GraphStoreService.upsert_node(ip_address, "IP_ADDRESS")
            GraphStoreService.upsert_relationship(
                source_id=user_id, source_type="USER",
                relation_type=REL_CONNECTED_FROM_IP,
                target_id=ip_address, target_type="IP_ADDRESS",
                properties={"payment_id": payment_id}
            )

        if payment_method:
            pm_node_id = f"PM:{payment_method}"
            GraphStoreService.upsert_node(pm_node_id, "PAYMENT_METHOD", display_label=payment_method)
            GraphStoreService.upsert_relationship(
                source_id=user_id, source_type="USER",
                relation_type=REL_MAKES_PAYMENT_VIA,
                target_id=pm_node_id, target_type="PAYMENT_METHOD",
                properties={"payment_id": payment_id}
            )

        logger.debug(f"[GraphStore] Payment edges processed for user={user_id}, payment={payment_id}")

    # -----------------------------------------------------------------------
    # Pipeline B: Graph Traversal for Investigation
    # -----------------------------------------------------------------------

    @staticmethod
    def get_entity_neighborhood(user_id: str, merchant_id: str = None) -> Dict[str, Any]:
        """
        2-hop neighborhood traversal for a user (and optionally merchant).
        Returns a structured graph analysis dict consumed by node_retrieve_entity_graph.

        Returns:
            {
                "user_node": {...} | None,
                "shared_devices": [{"device_id": ..., "shared_account_count": ..., "accounts": [...]}],
                "shared_ips": [{"ip": ..., "shared_account_count": ..., "accounts": [...]}],
                "merchant_connections": [...],
                "total_graph_risk_signals": int,
                "traversal_note": str,
            }
        """
        result = {
            "user_node": None,
            "shared_devices": [],
            "shared_ips": [],
            "merchant_connections": [],
            "total_graph_risk_signals": 0,
            "traversal_note": "",
        }

        if not user_id:
            result["traversal_note"] = "No user_id provided for graph traversal."
            return result

        # Load user node
        user_node = EntityNode.query.get(user_id)
        if user_node:
            result["user_node"] = user_node.to_dict()
        else:
            result["traversal_note"] = f"User node '{user_id}' not yet in entity graph."
            return result

        # Hop 1: Get all devices and IPs this user has used
        user_device_rels = EntityRelationship.query.filter_by(
            source_id=user_id, relation_type=REL_USED_DEVICE
        ).all()

        user_ip_rels = EntityRelationship.query.filter_by(
            source_id=user_id, relation_type=REL_CONNECTED_FROM_IP
        ).all()

        # Hop 2: Find other users sharing those same devices/IPs
        for rel in user_device_rels:
            device_id = rel.target_id
            # Find all users connected to this device
            sharing_users = EntityRelationship.query.filter(
                EntityRelationship.target_id == device_id,
                EntityRelationship.relation_type == REL_USED_DEVICE,
                EntityRelationship.source_id != user_id,  # Exclude current user
            ).all()

            if sharing_users:
                shared_account_ids = [r.source_id for r in sharing_users]
                result["shared_devices"].append({
                    "device_id": device_id,
                    "shared_account_count": len(shared_account_ids),
                    "accounts": shared_account_ids,
                })
                result["total_graph_risk_signals"] += len(shared_account_ids)

        for rel in user_ip_rels:
            ip_address = rel.target_id
            sharing_users = EntityRelationship.query.filter(
                EntityRelationship.target_id == ip_address,
                EntityRelationship.relation_type == REL_CONNECTED_FROM_IP,
                EntityRelationship.source_id != user_id,
            ).all()

            if sharing_users:
                shared_account_ids = [r.source_id for r in sharing_users]
                result["shared_ips"].append({
                    "ip_address": ip_address,
                    "shared_account_count": len(shared_account_ids),
                    "accounts": shared_account_ids,
                })
                result["total_graph_risk_signals"] += len(shared_account_ids)

        # Merchant connections (if provided)
        if merchant_id:
            merchant_users = EntityRelationship.query.filter(
                EntityRelationship.target_id == merchant_id,
                EntityRelationship.relation_type == REL_PLACED_ORDER_AT,
                EntityRelationship.source_id != user_id,
            ).limit(10).all()

            result["merchant_connections"] = [r.source_id for r in merchant_users]

        note_parts = []
        if result["shared_devices"]:
            note_parts.append(f"{len(result['shared_devices'])} shared device(s) detected")
        if result["shared_ips"]:
            note_parts.append(f"{len(result['shared_ips'])} shared IP(s) detected")
        if not note_parts:
            note_parts.append("No shared device or IP connections found")

        result["traversal_note"] = "; ".join(note_parts) + "."

        logger.info(
            f"[GraphStore] Traversal for user={user_id}: "
            f"devices={len(result['shared_devices'])}, IPs={len(result['shared_ips'])}, "
            f"risk_signals={result['total_graph_risk_signals']}"
        )
        return result

    @staticmethod
    def get_historical_patterns(user_id: str = None, merchant_id: str = None,
                                 limit: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve historical investigation snapshots for a user or merchant.
        Used by node_retrieve_historical_intel.
        """
        from app.models.knowledgebase import InvestigationHistorySnapshot

        query = InvestigationHistorySnapshot.query
        if user_id:
            query = query.filter_by(user_id=user_id)
        elif merchant_id:
            query = query.filter_by(merchant_id=merchant_id)
        else:
            return []

        snapshots = query.order_by(
            InvestigationHistorySnapshot.created_at.desc()
        ).limit(limit).all()

        return [s.to_dict() for s in snapshots]


# Constant alias fix
REL_MAKES_PAYMENT_VIA = REL_MADE_PAYMENT_VIA

