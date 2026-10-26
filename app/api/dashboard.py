from flask import Blueprint, jsonify
from app.services.dashboard_service import DashboardService

dashboard_bp = Blueprint("dashboard", __name__)

@dashboard_bp.route("/summary", methods=["GET"])
def get_dashboard_summary():
    """Returns genuine aggregate case metrics computed directly from MySQL."""
    metrics = DashboardService.get_summary_metrics()
    return jsonify(metrics), 200
