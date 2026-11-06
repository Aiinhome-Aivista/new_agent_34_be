import logging
from flask import Blueprint, request, jsonify
from app.extensions import db
from app.models.governance import AppNotification, AppUser
from app.models.investigation import InvestigationCase

logger = logging.getLogger("fraud_agent.notifications_api")
notifications_bp = Blueprint("notifications_bp", __name__)

@notifications_bp.route("", methods=["GET"])
def get_notifications():
    """
    Returns recent notifications tailored for the active persona / user.
    """
    role = request.args.get("role", "").strip()
    user_id = request.args.get("user_id", "").strip()
    limit = min(int(request.args.get("limit", 25)), 100)

    query = AppNotification.query

    # Role & user matching
    if role:
        # If user is ADMIN or SENIOR_INVESTIGATOR, they also get SENIOR_AND_ADMIN and ALL notifications
        if role in ["ADMIN", "SENIOR_INVESTIGATOR"]:
            query = query.filter(
                (AppNotification.recipient_role.in_([role, "SENIOR_AND_ADMIN", "ALL"])) |
                (AppNotification.recipient_role == None) |
                (AppNotification.recipient_user_id == user_id)
            )
        else:
            query = query.filter(
                (AppNotification.recipient_role.in_([role, "ALL"])) |
                (AppNotification.recipient_user_id == user_id)
            )
    elif user_id:
        query = query.filter(
            (AppNotification.recipient_user_id == user_id) |
            (AppNotification.recipient_role.in_(["ALL"]))
        )

    # Order newest first
    all_items = query.order_by(AppNotification.created_at.desc()).limit(limit).all()
    unread_count = query.filter(AppNotification.is_read == False).count()

    return jsonify({
        "items": [n.to_dict() for n in all_items],
        "unread_count": unread_count,
        "total": len(all_items)
    }), 200

@notifications_bp.route("/<notification_id>/read", methods=["POST"])
def mark_read(notification_id):
    """Marks a single notification as read."""
    notif = AppNotification.query.filter_by(id=notification_id).first()
    if not notif:
        return jsonify({"error": "Not Found", "message": "Notification not found"}), 404

    notif.is_read = True
    db.session.commit()
    return jsonify({"success": True, "id": notification_id, "is_read": True}), 200

@notifications_bp.route("/read-all", methods=["POST"])
def mark_all_read():
    """Marks all notifications for a role as read."""
    payload = request.get_json(silent=True) or {}
    role = payload.get("role", "").strip()
    user_id = payload.get("user_id", "").strip()

    query = AppNotification.query.filter(AppNotification.is_read == False)
    if role in ["ADMIN", "SENIOR_INVESTIGATOR"]:
        query = query.filter(AppNotification.recipient_role.in_([role, "SENIOR_AND_ADMIN", "ALL"]))
    elif role:
        query = query.filter(AppNotification.recipient_role.in_([role, "ALL"]))
    elif user_id:
        query = query.filter(AppNotification.recipient_user_id == user_id)

    updated_count = query.update({AppNotification.is_read: True}, synchronize_session=False)
    db.session.commit()

    return jsonify({"success": True, "marked_count": updated_count}), 200

@notifications_bp.route("/escalations/stats", methods=["GET"])
def get_escalation_stats():
    """Returns real-time escalation desk metrics for senior review."""
    escalated_cases = InvestigationCase.query.filter_by(status="ESCALATED").all()
    critical_count = sum(1 for c in escalated_cases if c.priority == "CRITICAL")
    high_count = sum(1 for c in escalated_cases if c.priority == "HIGH")

    return jsonify({
        "total_escalated": len(escalated_cases),
        "critical_escalations": critical_count,
        "high_escalations": high_count,
        "active_cases": [
            {
                "case_id": c.id,
                "user_id_ref": c.user_id_ref,
                "priority": c.priority,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in escalated_cases[:10]
        ]
    }), 200

