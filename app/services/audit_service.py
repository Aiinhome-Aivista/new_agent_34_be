import hashlib
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from backend.app.extensions import db
from backend.app.models.governance import AuditEvent

class AuditService:
    """Manages creation and integrity verification of audit logs."""

    @staticmethod
    def record_event(
        event_type: str,
        actor_type: str,
        correlation_id: str,
        case_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditEvent:
        """Persists a new structured audit record with a deterministic hash."""
        now = datetime.now(timezone.utc)
        sanitized_details = details or {}
        
        # Calculate event fingerprint
        payload_str = f"{case_id}:{actor_type}:{event_type}:{now.isoformat()}:{json.dumps(sanitized_details, sort_keys=True)}"
        event_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

        event = AuditEvent(
            case_id=case_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            event_timestamp=now,
            correlation_id=correlation_id,
            details=sanitized_details,
            event_hash=event_hash
        )
        db.session.add(event)
        db.session.commit()
        return event
