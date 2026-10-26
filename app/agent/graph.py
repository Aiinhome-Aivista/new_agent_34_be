import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any
from langgraph.graph import StateGraph, END

from app.extensions import db
from app.config import Config
from app.models.investigation import InvestigationCase, Recommendation, RecommendationEvidence
from app.schemas.recommendation import StructuredRecommendation
from app.agent.state import InvestigationState
from app.services.evidence_service import EvidenceService
from app.services.graph_service import GraphEntityService
from app.services.rag_service import PolicyRAGService
from app.services.decision_gateway import DecisionGateway
from app.services.audit_service import AuditService
from app.services.llm_provider import LLMReasoningService

logger = logging.getLogger("fraud_agent.workflow")

# -------------------------------------------------------------
# Workflow Node Implementations
# -------------------------------------------------------------

def node_validate_trigger(state: InvestigationState) -> Dict[str, Any]:
    """Validates trigger parameters and initiates investigation case state."""
    logger.info(f"Node: validate_trigger for case {state['case_id']}")
    case = InvestigationCase.query.filter_by(id=state["case_id"]).first()
    if case:
        case.status = "COLLECTING_EVIDENCE"
        db.session.commit()
    return {"status": "COLLECTING_EVIDENCE"}

def node_collect_evidence(state: InvestigationState) -> Dict[str, Any]:
    """Retrieves authorized read-only data across source systems."""
    logger.info(f"Node: collect_evidence for case {state['case_id']}")
    collected_models = EvidenceService.collect_evidence_for_case(
        case_id=state["case_id"],
        transaction_id=state.get("transaction_id"),
        user_id=state.get("user_id"),
        merchant_id=state.get("merchant_id")
    )
    
    items = []
    missing = []
    for item in collected_models:
        item_dict = item.to_dict()
        items.append(item_dict)
        if item.retrieval_status == "MISSING":
            missing.append(f"{item.evidence_type} ({item.source_reference})")

    return {
        "evidence_items": items,
        "missing_evidence": missing,
        "status": "UNDER_INVESTIGATION"
    }

def node_correlate_graph(state: InvestigationState) -> Dict[str, Any]:
    """Traverses relationship networks across users, devices, and payment instruments."""
    logger.info(f"Node: correlate_graph for case {state['case_id']}")
    graph_res = GraphEntityService.analyze_entity_network(
        user_id=state.get("user_id"),
        merchant_id=state.get("merchant_id")
    )
    return {"graph_analysis": graph_res}

def node_retrieve_policy(state: InvestigationState) -> Dict[str, Any]:
    """Queries ChromaDB policy index for applicable SOP clauses."""
    logger.info(f"Node: retrieve_policy for case {state['case_id']}")
    query_text = f"Fraud policy for {state.get('trigger_type', 'INVESTIGATION')} {state.get('trigger_reason', '')}"
    rag_res = PolicyRAGService.retrieve_policies(query=query_text, top_k=2)
    return {"retrieved_policies": rag_res.get("passages", [])}

def node_reason_llm(state: InvestigationState) -> Dict[str, Any]:
    """
    Synthesizes collected evidence, graph relationships, and policy excerpts
    into a structured assessment and recommendation using the configured LLM provider.
    """
    logger.info(f"Node: reason_llm for case {state['case_id']}")
    evidence_items = state.get("evidence_items", [])
    missing = state.get("missing_evidence", [])
    graph = state.get("graph_analysis", {})
    policies = state.get("retrieved_policies", [])

    case = InvestigationCase.query.filter_by(id=state["case_id"]).first()
    trigger_type = case.trigger_type if case else state.get("trigger_type", "INVESTIGATION")
    trigger_reason = case.trigger_reason if case else state.get("trigger_reason", "")
    priority = case.priority if case else "MEDIUM"

    llm_result = LLMReasoningService.generate_investigation_reasoning(
        case_id=state["case_id"],
        trigger_type=trigger_type,
        trigger_reason=trigger_reason,
        priority=priority,
        evidence_items=evidence_items,
        graph_analysis=graph,
        retrieved_policies=policies,
        missing_evidence=missing
    )

    return {
        "assessment": llm_result["assessment"],
        "recommendation": llm_result["recommendation"],
        "explanation": llm_result["explanation"],
        "confidence_label": llm_result["confidence_label"],
        "risk_indicators": llm_result["risk_indicators"],
        "counter_signals": llm_result["counter_signals"],
        "model_name": llm_result.get("model_name", "LLM-Engine")
    }

def node_validate_grounding(state: InvestigationState) -> Dict[str, Any]:
    """Ensures recommendation has valid schema and is backed by real evidence references."""
    logger.info(f"Node: validate_grounding for case {state['case_id']}")
    # Enforce Pydantic schema validation
    rec_schema = StructuredRecommendation(
        case_id=state["case_id"],
        assessment=state["assessment"],
        recommendation=state["recommendation"],
        explanation=state["explanation"],
        confidence_label=state["confidence_label"],
        risk_indicators=state["risk_indicators"],
        counter_signals=state["counter_signals"],
        missing_evidence=state.get("missing_evidence", []),
        policy_references=[p.get("document_key", "SOP") for p in state.get("retrieved_policies", [])],
        human_review_required=True,
        model_name=state.get("model_name", "LLM-Engine")
    )

    # Persist recommendation to MySQL
    rec = Recommendation(
        id=str(uuid.uuid4()),
        case_id=state["case_id"],
        assessment=rec_schema.assessment,
        recommendation_type=rec_schema.recommendation,
        explanation=rec_schema.explanation,
        confidence_label=rec_schema.confidence_label,
        human_review_required=rec_schema.human_review_required,
        model_name=rec_schema.model_name,
        prompt_version="1.0",
        policy_version="1.0",
        structured_result=rec_schema.model_dump()
    )
    db.session.add(rec)
    db.session.commit()

    return {"status": "RECOMMENDATION_PERSISTED"}

def node_route_decision(state: InvestigationState) -> Dict[str, Any]:
    """Applies deterministic Decision Gateway rules and updates case status."""
    logger.info(f"Node: route_decision for case {state['case_id']}")
    rec_obj = StructuredRecommendation(
        case_id=state["case_id"],
        assessment=state["assessment"],
        recommendation=state["recommendation"],
        explanation=state["explanation"],
        confidence_label=state["confidence_label"],
        risk_indicators=state["risk_indicators"],
        counter_signals=state["counter_signals"],
        missing_evidence=state.get("missing_evidence", []),
        policy_references=[],
        human_review_required=True,
        model_name=state.get("model_name", "LLM-Engine")
    )

    evidence_count = len(state.get("evidence_items", []))
    missing_count = len(state.get("missing_evidence", []))

    route_res = DecisionGateway.evaluate_route(
        recommendation=rec_obj,
        evidence_count=evidence_count,
        missing_evidence_count=missing_count
    )

    case = InvestigationCase.query.filter_by(id=state["case_id"]).first()
    final_status = "REQUIRES_REVIEW"
    if route_res["route"] == "ESCALATE":
        final_status = "ESCALATED"
    elif route_res["route"] == "AUTO_ACTION_ELIGIBLE":
        final_status = "ACTION_AUTHORIZED"

    if case:
        case.status = final_status
        case.completed_at = datetime.now(timezone.utc)
        db.session.commit()

    AuditService.record_event(
        event_type="RECOMMENDATION_GENERATED",
        actor_type="AGENT_WORKFLOW",
        correlation_id=case.idempotency_key if case else state["case_id"],
        case_id=state["case_id"],
        details={
            "assessment": state["assessment"],
            "recommendation": state["recommendation"],
            "route": route_res["route"],
            "status": final_status
        }
    )

    return {
        "gateway_route": route_res["route"],
        "gateway_reason": route_res["reason"],
        "auto_action_eligible": route_res["auto_action_eligible"],
        "review_required": route_res["review_required"],
        "status": final_status
    }

# -------------------------------------------------------------
# Graph Assembly
# -------------------------------------------------------------

def build_investigation_graph():
    """Builds and compiles the LangGraph investigation workflow."""
    workflow = StateGraph(InvestigationState)

    workflow.add_node("validate_trigger", node_validate_trigger)
    workflow.add_node("collect_evidence", node_collect_evidence)
    workflow.add_node("correlate_graph", node_correlate_graph)
    workflow.add_node("retrieve_policy", node_retrieve_policy)
    workflow.add_node("reason_llm", node_reason_llm)
    workflow.add_node("validate_grounding", node_validate_grounding)
    workflow.add_node("route_decision", node_route_decision)

    workflow.set_entry_point("validate_trigger")
    workflow.add_edge("validate_trigger", "collect_evidence")
    workflow.add_edge("collect_evidence", "correlate_graph")
    workflow.add_edge("correlate_graph", "retrieve_policy")
    workflow.add_edge("retrieve_policy", "reason_llm")
    workflow.add_edge("reason_llm", "validate_grounding")
    workflow.add_edge("validate_grounding", "route_decision")
    workflow.add_edge("route_decision", END)

    return workflow.compile()

# Global compiled instance
investigation_graph = build_investigation_graph()

def execute_case_investigation(case_id: str) -> Dict[str, Any]:
    """Helper to run the compiled graph on a case synchronously or via Celery."""
    case = InvestigationCase.query.filter_by(id=case_id).first()
    if not case:
        raise ValueError(f"Case {case_id} not found.")

    initial_state: InvestigationState = {
        "case_id": case.id,
        "trigger_type": case.trigger_type,
        "trigger_reason": case.trigger_reason,
        "priority": case.priority,
        "transaction_id": case.transaction_id,
        "user_id": case.user_id_ref,
        "merchant_id": case.merchant_id_ref,
        "evidence_items": [],
        "missing_evidence": [],
        "graph_analysis": {},
        "retrieved_policies": [],
        "assessment": None,
        "recommendation": None,
        "explanation": None,
        "confidence_label": None,
        "risk_indicators": [],
        "counter_signals": [],
        "gateway_route": None,
        "gateway_reason": None,
        "auto_action_eligible": False,
        "review_required": True,
        "status": case.status
    }

    return investigation_graph.invoke(initial_state)
