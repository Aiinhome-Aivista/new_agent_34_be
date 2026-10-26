from flask import Blueprint, jsonify, request
from backend.app.models.governance import AuditEvent

audit_bp = Blueprint("audit", __name__)

@audit_bp.route("", methods=["GET"])
def list_audit_events():
    """Lists audit events for compliance inspections."""
    case_id = request.args.get("case_id")
    query = AuditEvent.query
    if case_id:
        query = query.filter_by(case_id=case_id)
    events = query.order_by(AuditEvent.event_timestamp.desc()).limit(100).all()
    return jsonify({
        "items": [e.to_dict() for e in events],
        "total": len(events)
    }), 200
