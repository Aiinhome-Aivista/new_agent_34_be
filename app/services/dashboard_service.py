import logging
from sqlalchemy import func
from app.extensions import db
from app.models.investigation import InvestigationCase
from app.models.governance import ActionRequest, AuditEvent

logger = logging.getLogger("fraud_agent.dashboard_service")

class DashboardService:
    """Computes genuine real-time statistics from persisted MySQL records."""

    @staticmethod
    def get_summary_metrics():
        """Aggregates persisted case counts, status distributions, and recent events."""
        total_cases = db.session.query(func.count(InvestigationCase.id)).scalar() or 0
        
        # Breakdown by status
        status_rows = db.session.query(
            InvestigationCase.status,
            func.count(InvestigationCase.id)
        ).group_by(InvestigationCase.status).all()
        status_counts = {status: count for status, count in status_rows}

        # Breakdown by priority
        priority_rows = db.session.query(
            InvestigationCase.priority,
            func.count(InvestigationCase.id)
        ).group_by(InvestigationCase.priority).all()
        priority_counts = {priority: count for priority, count in priority_rows}

        # Completed actions count
        total_actions = db.session.query(func.count(ActionRequest.id)).filter(
            ActionRequest.execution_status == "COMPLETED"
        ).scalar() or 0

        # Pending human reviews
        pending_review_count = status_counts.get("REQUIRES_REVIEW", 0)

        # Recent real audit activity
        recent_events = AuditEvent.query.order_by(AuditEvent.event_timestamp.desc()).limit(8).all()
        activity = [e.to_dict() for e in recent_events]

        return {
            "total_investigations": total_cases,
            "pending_review_count": pending_review_count,
            "actions_executed_count": total_actions,
            "status_distribution": status_counts,
            "priority_distribution": priority_counts,
            "recent_activity": activity,
            "is_empty": total_cases == 0
        }
