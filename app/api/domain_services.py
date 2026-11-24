import uuid
import logging
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from app.extensions import db
from app.models.source_domain import MUser, MOrder, MPayment, MChargeback

logger = logging.getLogger("fraud_agent.api.domain_services")
domain_services_bp = Blueprint("domain_services", __name__)


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# 1. User Profile & KYC Service (USER_PROFILE_SERVICE)
# ============================================================================

@domain_services_bp.route("/users/<user_id>", methods=["GET"])
def get_user_profile(user_id):
    """
    Core Banking Customer 360 & KYC Service endpoint.
    Retrieves full customer profile, KYC tier, risk metrics, and account status.
    """
    user = MUser.query.filter(
        (MUser.user_id == user_id) |
        (MUser.external_user_id == user_id) |
        (MUser.email == user_id)
    ).first()

    if not user:
        return jsonify({
            "error": "Not Found",
            "message": f"User '{user_id}' was not found in Master User Directory."
        }), 404

    payload = user.to_dict()
    payload["service_origin"] = "USER_PROFILE_SERVICE"
    payload["queried_at"] = utc_now_iso()
    return jsonify(payload), 200


# ============================================================================
# 2. Payment Gateway Switch & Clearing (PAYMENT_GATEWAY_SERVICE)
# ============================================================================

@domain_services_bp.route("/payments/<payment_id>", methods=["GET"])
def get_payment_details(payment_id):
    """
    Payment Gateway Switch & Clearing endpoint.
    Retrieves transaction processor state, 3D-Secure flags, amounts, and card metadata.
    """
    payment = MPayment.query.filter(
        (MPayment.payment_id == payment_id) |
        (MPayment.gateway_transaction_id == payment_id)
    ).first()

    if not payment:
        return jsonify({
            "error": "Not Found",
            "message": f"Payment '{payment_id}' was not found in Gateway Clearing Ledger."
        }), 404

    payload = payment.to_dict()
    payload["service_origin"] = "PAYMENT_GATEWAY_SERVICE"
    payload["queried_at"] = utc_now_iso()
    return jsonify(payload), 200


# ============================================================================
# 3. Order & Fulfillment Service (ORDER_FULFILLMENT_SERVICE)
# ============================================================================

@domain_services_bp.route("/orders/<order_id>", methods=["GET"])
def get_order_details(order_id):
    """
    Order & Fulfillment Service endpoint.
    Retrieves order items, billing/shipping geography, device fingerprints, and merchant data.
    """
    order = MOrder.query.filter(
        (MOrder.order_id == order_id) |
        (MOrder.merchant_order_id == order_id)
    ).first()

    if not order:
        return jsonify({
            "error": "Not Found",
            "message": f"Order '{order_id}' was not found in Fulfillment Ledger."
        }), 404

    payload = order.to_dict()
    payload["service_origin"] = "ORDER_FULFILLMENT_SERVICE"
    payload["queried_at"] = utc_now_iso()
    return jsonify(payload), 200


# ============================================================================
# 4. Chargeback & Dispute Ledger (DISPUTE_LEDGER_SERVICE)
# ============================================================================

@domain_services_bp.route("/disputes/summary/<user_id>", methods=["GET"])
def get_dispute_summary(user_id):
    """
    Chargeback & Dispute Ledger Service endpoint.
    Returns historical dispute filings, fraud indicators, and chargeback totals for a customer.
    """
    # Query chargebacks linked to payments made by this user
    cbs = (
        MChargeback.query
        .join(MPayment, MChargeback.payment_id == MPayment.payment_id)
        .filter(MPayment.user_id == user_id)
        .all()
    )

    # Fallback check if user_id was directly an order_id or payment_id
    if not cbs:
        cbs = MChargeback.query.filter(
            (MChargeback.payment_id == user_id) |
            (MChargeback.order_id == user_id)
        ).all()

    total_amount = float(sum(cb.amount for cb in cbs)) if cbs else 0.0

    return jsonify({
        "service_origin": "DISPUTE_LEDGER_SERVICE",
        "user_id": user_id,
        "dispute_count": len(cbs),
        "total_disputed_amount": total_amount,
        "has_active_disputes": any(cb.chargeback_status in ("OPEN", "UNDER_REVIEW") for cb in cbs),
        "chargebacks": [cb.to_dict() for cb in cbs],
        "queried_at": utc_now_iso()
    }), 200


# ============================================================================
# 5. Downstream Account Enforcement (ACCOUNT_ENFORCEMENT_SERVICE)
# ============================================================================

@domain_services_bp.route("/accounts/<user_id>/status", methods=["PUT"])
def update_account_status(user_id):
    """
    Downstream Account Enforcement endpoint.
    Applies real-time protective enforcement: lock user, activate account, or suspend digital access.
    """
    user = MUser.query.filter_by(user_id=user_id).first()
    if not user:
        return jsonify({
            "error": "Not Found",
            "message": f"User '{user_id}' was not found in Core Account Directory."
        }), 404

    data = request.get_json(silent=True) or {}
    raw_status = (data.get("status") or data.get("action") or "").strip().upper()
    action_map = {
        "LOCK_USER": "LOCKED",
        "BLOCK_USER": "BLOCKED",
        "UNLOCK_USER": "ACTIVE",
        "SUSPEND_USER": "SUSPENDED"
    }
    new_status = action_map.get(raw_status, raw_status)
    reason = data.get("reason", "Administrative Enforcement").strip()
    idempotency_key = data.get("idempotency_key")

    valid_statuses = {"ACTIVE", "BLOCKED", "SUSPENDED", "LOCKED"}
    if new_status not in valid_statuses:
        return jsonify({
            "error": "Bad Request",
            "message": f"Invalid status '{new_status}'. Allowed values: {sorted(list(valid_statuses))}"
        }), 400

    prev_status = user.status
    user.status = new_status
    user.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    logger.info(f"[Enforcement] User {user_id} status changed: {prev_status} -> {new_status} (Reason: {reason})")

    return jsonify({
        "service_origin": "ACCOUNT_ENFORCEMENT_SERVICE",
        "user_id": user.user_id,
        "previous_status": prev_status,
        "new_status": user.status,
        "reason": reason,
        "idempotency_key": idempotency_key,
        "enforcement_reference": f"ENF-{uuid.uuid4().hex[:10].upper()}",
        "updated_at": utc_now_iso()
    }), 200
