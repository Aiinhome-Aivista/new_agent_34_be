import logging
from flask import Blueprint, request, jsonify
from app.models.source_domain import MUser, MOrder, MPayment, MChargeback, MRefund

logger = logging.getLogger("fraud_agent.api.microservices")
microservices_bp = Blueprint("microservices", __name__)

# ============================================================================
# 1. User / Customer 360 Microservice API (m_users)
# ============================================================================

@microservices_bp.route("/users/<user_id>", methods=["GET"])
@microservices_bp.route("/users", methods=["GET"])
def get_user_service(user_id=None):
    """
    Microservice endpoint for User / Customer 360 data.
    Fetches live record directly from m_users table.
    """
    target_id = user_id or request.args.get("user_id")
    if not target_id:
        # Return sample recent users if no specific ID requested
        limit = min(int(request.args.get("limit", 10)), 50)
        users = MUser.query.order_by(MUser.created_at.desc()).limit(limit).all()
        return jsonify({
            "service": "USER_SERVICE",
            "source_table": "m_users",
            "count": len(users),
            "users": [u.to_dict() for u in users]
        }), 200

    user = MUser.query.filter(
        (MUser.user_id == target_id) | (MUser.external_user_id == target_id)
    ).first()

    if not user:
        return jsonify({
            "error": "Not Found",
            "message": f"User '{target_id}' not found in m_users directory",
            "service": "USER_SERVICE",
            "source_table": "m_users"
        }), 404

    return jsonify({
        "service": "USER_SERVICE",
        "source_table": "m_users",
        "user": user.to_dict()
    }), 200


# ============================================================================
# 2. Order & Fulfillment Microservice API (m_orders)
# ============================================================================

@microservices_bp.route("/orders/<order_id>", methods=["GET"])
@microservices_bp.route("/orders", methods=["GET"])
def get_order_service(order_id=None):
    """
    Microservice endpoint for Order & Commerce data.
    Fetches live record directly from m_orders table.
    """
    target_id = order_id or request.args.get("order_id")
    user_id = request.args.get("user_id")

    if not target_id:
        query = MOrder.query
        if user_id:
            query = query.filter_by(user_id=user_id)
        limit = min(int(request.args.get("limit", 10)), 50)
        orders = query.order_by(MOrder.created_at.desc()).limit(limit).all()
        return jsonify({
            "service": "ORDER_SERVICE",
            "source_table": "m_orders",
            "count": len(orders),
            "orders": [o.to_dict() for o in orders]
        }), 200

    order = MOrder.query.filter(
        (MOrder.order_id == target_id) | (MOrder.merchant_order_id == target_id)
    ).first()

    if not order:
        return jsonify({
            "error": "Not Found",
            "message": f"Order '{target_id}' not found in m_orders directory",
            "service": "ORDER_SERVICE",
            "source_table": "m_orders"
        }), 404

    return jsonify({
        "service": "ORDER_SERVICE",
        "source_table": "m_orders",
        "order": order.to_dict()
    }), 200


# ============================================================================
# 3. Payment Gateway Microservice API (m_payments)
# ============================================================================

@microservices_bp.route("/payments/<payment_id>", methods=["GET"])
@microservices_bp.route("/payments", methods=["GET"])
def get_payment_service(payment_id=None):
    """
    Microservice endpoint for Payment Gateway data.
    Fetches live record directly from m_payments table.
    """
    target_id = payment_id or request.args.get("payment_id")
    user_id = request.args.get("user_id")
    order_id = request.args.get("order_id")

    if not target_id:
        query = MPayment.query
        if user_id:
            query = query.filter_by(user_id=user_id)
        if order_id:
            query = query.filter_by(order_id=order_id)
        limit = min(int(request.args.get("limit", 10)), 50)
        payments = query.order_by(MPayment.initiated_at.desc()).limit(limit).all()
        return jsonify({
            "service": "PAYMENT_SERVICE",
            "source_table": "m_payments",
            "count": len(payments),
            "payments": [p.to_dict() for p in payments]
        }), 200

    payment = MPayment.query.filter(
        (MPayment.payment_id == target_id) | (MPayment.gateway_transaction_id == target_id)
    ).first()

    if not payment:
        return jsonify({
            "error": "Not Found",
            "message": f"Payment '{target_id}' not found in m_payments directory",
            "service": "PAYMENT_SERVICE",
            "source_table": "m_payments"
        }), 404

    return jsonify({
        "service": "PAYMENT_SERVICE",
        "source_table": "m_payments",
        "payment": payment.to_dict()
    }), 200


# ============================================================================
# 4. Chargeback & Dispute Microservice API (m_chargebacks)
# ============================================================================

@microservices_bp.route("/chargebacks/<chargeback_id>", methods=["GET"])
@microservices_bp.route("/chargebacks", methods=["GET"])
def get_chargeback_service(chargeback_id=None):
    """
    Microservice endpoint for Chargeback & Dispute Ledger data.
    Fetches live record directly from m_chargebacks table.
    """
    target_id = chargeback_id or request.args.get("chargeback_id")
    user_id = request.args.get("user_id")
    payment_id = request.args.get("payment_id")

    if not target_id:
        query = MChargeback.query
        if payment_id:
            query = query.filter_by(payment_id=payment_id)
        elif user_id:
            query = query.join(MPayment, MChargeback.payment_id == MPayment.payment_id).filter(MPayment.user_id == user_id)
        limit = min(int(request.args.get("limit", 10)), 50)
        chargebacks = query.order_by(MChargeback.received_at.desc()).limit(limit).all()
        return jsonify({
            "service": "CHARGEBACK_SERVICE",
            "source_table": "m_chargebacks",
            "count": len(chargebacks),
            "chargebacks": [c.to_dict() for c in chargebacks]
        }), 200

    chargeback = MChargeback.query.filter(
        (MChargeback.chargeback_id == target_id) | (MChargeback.processor_case_id == target_id)
    ).first()

    if not chargeback:
        return jsonify({
            "error": "Not Found",
            "message": f"Chargeback '{target_id}' not found in m_chargebacks directory",
            "service": "CHARGEBACK_SERVICE",
            "source_table": "m_chargebacks"
        }), 404

    return jsonify({
        "service": "CHARGEBACK_SERVICE",
        "source_table": "m_chargebacks",
        "chargeback": chargeback.to_dict()
    }), 200


# ============================================================================
# 5. Refund & Return Microservice API (m_refunds)
# ============================================================================

@microservices_bp.route("/refunds/<refund_id>", methods=["GET"])
@microservices_bp.route("/refunds", methods=["GET"])
def get_refund_service(refund_id=None):
    """
    Microservice endpoint for User Refund & Return Ledger data.
    Fetches live record directly from m_refunds table.
    """
    target_id = refund_id or request.args.get("refund_id")
    user_id = request.args.get("user_id")
    payment_id = request.args.get("payment_id")
    order_id = request.args.get("order_id")

    if not target_id:
        query = MRefund.query
        if user_id:
            query = query.filter_by(user_id=user_id)
        if payment_id:
            query = query.filter_by(payment_id=payment_id)
        if order_id:
            query = query.filter_by(order_id=order_id)
        limit = min(int(request.args.get("limit", 10)), 50)
        refunds = query.order_by(MRefund.requested_at.desc()).limit(limit).all()
        return jsonify({
            "service": "REFUND_SERVICE",
            "source_table": "m_refunds",
            "count": len(refunds),
            "refunds": [r.to_dict() for r in refunds]
        }), 200

    refund = MRefund.query.filter_by(refund_id=target_id).first()
    if not refund:
        return jsonify({
            "error": "Not Found",
            "message": f"Refund '{target_id}' not found in m_refunds directory",
            "service": "REFUND_SERVICE",
            "source_table": "m_refunds"
        }), 404

    return jsonify({
        "service": "REFUND_SERVICE",
        "source_table": "m_refunds",
        "refund": refund.to_dict()
    }), 200
