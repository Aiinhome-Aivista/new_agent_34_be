from flask import Blueprint, jsonify, request
from app.models.governance import AuditEvent
from app.models.investigation import InvestigationCase

audit_bp = Blueprint("audit", __name__)

@audit_bp.route("", methods=["GET"])
def list_audit_events():
    """
    Lists audit events for compliance inspections.
    Supports cross-case historical precedents by user_id so investigators
    can inspect prior enforcement actions (LOCK_USER, EVIDENCE_REQUESTED, etc.)
    taken against the same customer across past cases.
    """
    case_id = request.args.get("case_id")
    user_id = request.args.get("user_id")
    include_precedents = request.args.get("include_precedents", "true").lower() in ["true", "1", "yes"]

    target_user_id = user_id
    current_case = None
    if case_id:
        current_case = InvestigationCase.query.filter_by(id=case_id).first()
        if current_case and current_case.user_id_ref and not target_user_id:
            target_user_id = current_case.user_id_ref

    query = AuditEvent.query
    if case_id and not include_precedents:
        query = query.filter_by(case_id=case_id)
    elif case_id and target_user_id:
        # Cross-case query: Fetch events for current case OR for this target user across previous cases
        query = query.filter(
            (AuditEvent.case_id == case_id) | (AuditEvent.user_id == target_user_id)
        )
    elif target_user_id:
        query = query.filter_by(user_id=target_user_id)
    elif case_id:
        query = query.filter_by(case_id=case_id)

    events = query.order_by(AuditEvent.event_timestamp.desc()).limit(200).all()

    items = []
    current_count = 0
    precedent_count = 0

    for e in events:
        item = e.to_dict()
        is_current = (e.case_id == case_id) if case_id else True
        item["is_current_case"] = is_current
        cid_short = f"#{e.case_id[:8]}" if e.case_id else ""
        item["case_label"] = "Current Case" if is_current else f"Previous Case {cid_short}".strip()
        if is_current:
            current_count += 1
        else:
            precedent_count += 1
        items.append(item)

    return jsonify({
        "items": items,
        "total": len(items),
        "current_case_count": current_count,
        "precedent_count": precedent_count,
        "target_user_id": target_user_id
    }), 200
