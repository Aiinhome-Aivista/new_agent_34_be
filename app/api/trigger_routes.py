import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.database import get_db, SessionLocal
from app.models.platform import InvestigationCase, AuditEvent, InvestigationRun, EvidenceRecord, InvestigationFinding, InvestigationRecommendation
from app.schemas.triggers import ExternalTriggerPayload, IngestTriggerResponse
from app.agent.graph import build_investigation_graph

router = APIRouter(prefix="/triggers", tags=["Trigger Intake"])

async def _execute_investigation_background(case_id: str, trigger_dict: dict):
    """Executes the LangGraph investigation in the background."""
    db = SessionLocal()
    try:
        case = db.query(InvestigationCase).filter(InvestigationCase.case_id == case_id).first()
        if not case:
            return

        run_id = str(uuid.uuid4())
        run = InvestigationRun(
            run_id=run_id,
            case_id=case_id,
            run_status="RUNNING",
            agent_version="1.0.0",
            model_name="qwen2.5:7b",
            started_at=datetime.utcnow()
        )
        db.add(run)
        case.status = "INVESTIGATING"
        db.commit()

        # Build and invoke LangGraph graph
        graph = build_investigation_graph(db)
        initial_state = {
            "case_id": case_id,
            "case_number": case.case_number,
            "trigger": trigger_dict,
            "user_id": case.user_id,
            "merchant_id": case.merchant_id,
            "order_id": case.order_id,
            "payment_id": case.payment_id,
            "decision_mode": case.decision_mode
        }

        final_state = await graph.ainvoke(initial_state)

        # Record evidence into DB
        for ev in final_state.get("evidence_records", []):
            ev_record = EvidenceRecord(
                evidence_id=str(uuid.uuid4()),
                case_id=case_id,
                run_id=run_id,
                source_type=ev.get("source_type", "UNKNOWN"),
                record_identifier=ev.get("record_identifier", "REC"),
                summary=ev.get("summary", ""),
                evidence_payload=ev.get("payload", {}),
                is_counter_signal=ev.get("is_counter_signal", False),
                collected_at=datetime.utcnow()
            )
            db.add(ev_record)

        # Record finding
        finding_id = str(uuid.uuid4())
        finding = InvestigationFinding(
            finding_id=finding_id,
            case_id=case_id,
            run_id=run_id,
            assessment=final_state.get("assessment", "INCONCLUSIVE"),
            qualitative_confidence=final_state.get("qualitative_confidence", "MEDIUM"),
            summary=final_state.get("summary", ""),
            risk_indicators=final_state.get("risk_indicators", []),
            counter_signals=final_state.get("counter_signals", []),
            missing_evidence=final_state.get("missing_evidence", []),
            policy_references=final_state.get("policy_references", []),
            created_at=datetime.utcnow()
        )
        db.add(finding)

        # Record recommendation
        rec_id = str(uuid.uuid4())
        rec = InvestigationRecommendation(
            recommendation_id=rec_id,
            case_id=case_id,
            finding_id=finding_id,
            recommended_action=final_state.get("recommendation", "NO_ACTION"),
            rationale=final_state.get("recommendation_rationale", ""),
            human_review_required=final_state.get("human_review_required", True),
            auto_eligible=final_state.get("auto_eligible", False),
            suggested_target_type=final_state.get("suggested_target_type", "USER"),
            suggested_target_id=final_state.get("suggested_target_id", case.user_id or "UNKNOWN"),
            created_at=datetime.utcnow()
        )
        db.add(rec)

        # Update run & case status
        run.run_status = "COMPLETED"
        run.completed_at = datetime.utcnow()
        
        route = final_state.get("gateway_route", "HUMAN_REVIEW")
        if route == "AUTO_ACTION":
            case.status = "AUTO_ACTION_PENDING"
        elif route == "ESCALATE":
            case.status = "ESCALATED"
        else:
            case.status = "AWAITING_REVIEW"

        # Audit Event
        audit = AuditEvent(
            event_id=str(uuid.uuid4()),
            case_id=case_id,
            actor_id="agent_34_svc",
            actor_type="AGENT",
            event_type="INVESTIGATION_COMPLETED",
            event_description=f"Agent 34 completed investigation. Route: {route}, Recommendation: {rec.recommended_action}",
            event_payload={
                "run_id": run_id,
                "assessment": finding.assessment,
                "confidence": finding.qualitative_confidence,
                "route": route
            }
        )
        db.add(audit)
        db.commit()

    except Exception as e:
        db.rollback()
        # Mark failure
        if 'run' in locals() and run:
            run.run_status = "FAILED"
            run.error_message = str(e)
            db.commit()
    finally:
        db.close()

@router.post("/ingest", response_model=IngestTriggerResponse)
def ingest_trigger(
    payload: ExternalTriggerPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    # Check for existing case if external case_id supplied
    if payload.case_id:
        existing = db.query(InvestigationCase).filter(InvestigationCase.case_id == payload.case_id).first()
        if existing:
            return IngestTriggerResponse(
                status="EXISTING",
                message="Case already exists with this identifier",
                case_id=existing.case_id,
                case_number=existing.case_number,
                is_new=False
            )

    # Generate new case number
    case_count = db.query(InvestigationCase).count() + 1
    case_number = f"CASE-2026-{case_count:04d}"
    new_case_id = payload.case_id or str(uuid.uuid4())

    new_case = InvestigationCase(
        case_id=new_case_id,
        case_number=case_number,
        trigger_type=payload.trigger_type,
        trigger_source=payload.trigger_source,
        trigger_reason=payload.trigger_reason,
        priority=payload.priority,
        status="INTAKE",
        entity_type=payload.entity_type or "TRANSACTION",
        user_id=payload.user_id,
        merchant_id=payload.merchant_id,
        order_id=payload.order_id,
        payment_id=payload.payment_id,
        decision_mode=payload.decision_mode or "ADVISOR"
    )
    db.add(new_case)

    # Audit Intake Event
    audit = AuditEvent(
        event_id=str(uuid.uuid4()),
        case_id=new_case_id,
        actor_id=payload.trigger_source,
        actor_type="SYSTEM",
        event_type="CASE_INTAKE",
        event_description=f"External trigger received: {payload.trigger_reason}",
        event_payload=payload.model_dump()
    )
    db.add(audit)
    db.commit()

    # Enqueue investigation run
    background_tasks.add_task(
        _execute_investigation_background,
        new_case_id,
        payload.model_dump()
    )

    return IngestTriggerResponse(
        status="ACCEPTED",
        message="Trigger accepted and queued for autonomous agent investigation",
        case_id=new_case_id,
        case_number=case_number,
        is_new=True
    )
