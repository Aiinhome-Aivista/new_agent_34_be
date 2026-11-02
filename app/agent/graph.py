"""
Phase 3: LangGraph Investigation Workflow — Parallel Intelligence Architecture
===============================================================================
Replaces the linear sequential pipeline with a fan-out / fan-in pattern:

  validate_trigger
       │
  collect_evidence (MySQL core data)
       │
       ├─────────────────────────────────────────────────────┐
       │                   │                  │              │
  retrieve_entity_graph  execute_fraud_rules  retrieve_policy_rag  retrieve_historical_intel
       │                   │                  │              │
       └─────────────────────────────────────────────────────┘
                                  │
                            reason_llm  (synthesis — receives all 4 intelligence streams)
                                  │
                         validate_grounding
                                  │
                          route_decision
                                  │
                                 END

The LLM node now receives:
  - graph_analysis: pre-computed entity relationships
  - rule_evaluation_results: deterministic triggered/passed rule set
  - retrieved_policies: version-filtered active ChromaDB passages
  - historical_patterns: past confirmed/false-positive case snapshots

This eliminates LLM arithmetic, hallucinatory SOP citations, and on-demand DB scans.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

from langgraph.graph import StateGraph, END

from app.extensions import db
from app.models.investigation import InvestigationCase, Recommendation
from app.schemas.recommendation import StructuredRecommendation
from app.agent.state import InvestigationState
from app.services.evidence_service import EvidenceService
from app.services.decision_gateway import DecisionGateway
from app.services.audit_service import AuditService
from app.services.llm_provider import LLMReasoningService
from app.services.knowledgebase.graph_store import GraphStoreService
from app.services.knowledgebase.rule_engine import FraudRuleEngine
from app.services.knowledgebase.policy_service import KBPolicyService

logger = logging.getLogger("fraud_agent.workflow")


# =============================================================================
# Node 1: validate_trigger (unchanged)
# =============================================================================

def node_validate_trigger(state: InvestigationState) -> Dict[str, Any]:
    """Validates trigger parameters and transitions case to COLLECTING_EVIDENCE."""
    logger.info(f"[Node:validate_trigger] case={state['case_id']}")
    case = InvestigationCase.query.filter_by(id=state["case_id"]).first()
    if case:
        case.status = "COLLECTING_EVIDENCE"
        db.session.commit()
    return {"status": "COLLECTING_EVIDENCE"}


# =============================================================================
# Node 2: collect_evidence — MySQL core evidence collection
# =============================================================================

def node_collect_evidence(state: InvestigationState) -> Dict[str, Any]:
    """
    Retrieves authorized read-only data from m_users, m_orders, m_payments, m_chargebacks.
    Builds a flat evidence_items list consumed by all parallel retrieval nodes.
    """
    logger.info(f"[Node:collect_evidence] case={state['case_id']}")
    collected_models = EvidenceService.collect_evidence_for_case(
        case_id=state["case_id"],
        transaction_id=state.get("transaction_id"),
        user_id=state.get("user_id"),
        merchant_id=state.get("merchant_id")
    )

    items = []
    missing = []
    user_profile = None

    for item in collected_models:
        item_dict = item.to_dict()
        items.append(item_dict)
        if item.retrieval_status == "MISSING":
            missing.append(f"{item.evidence_type} ({item.source_reference})")
        # Extract user profile for rule engine
        if item.evidence_type == "USER_PROFILE":
            if item.retrieval_status == "FOUND":
                user_profile = item_dict.get("content_json") or {}
            else:
                user_profile = None

    # Pull device_id from order evidence if available
    device_id = None
    for item in items:
        content = item.get("content_json") or {}
        if isinstance(content, dict) and content.get("device_id"):
            device_id = content["device_id"]
            break

    return {
        "evidence_items": items,
        "missing_evidence": missing,
        "status": "UNDER_INVESTIGATION",
        # Pass enriched context for downstream parallel nodes
        "_user_profile": user_profile,
        "_device_id": device_id,
    }


# =============================================================================
# Node 3a: retrieve_entity_graph — Layer 2 (Pre-computed Graph)
# =============================================================================

def node_retrieve_entity_graph(state: InvestigationState) -> Dict[str, Any]:
    """
    Traverses the pre-computed entity_relationships graph for the target user.
    Replaces legacy node_correlate_graph which performed expensive live DB scans.
    """
    logger.info(f"[Node:retrieve_entity_graph] case={state['case_id']}")
    graph_res = GraphStoreService.get_entity_neighborhood(
        user_id=state.get("user_id"),
        merchant_id=state.get("merchant_id")
    )
    return {"graph_analysis": graph_res}


# =============================================================================
# Node 3b: execute_fraud_rules — Layer 3 (Deterministic Rule Engine)
# =============================================================================

def node_execute_fraud_rules(state: InvestigationState) -> Dict[str, Any]:
    """
    Evaluates all active FraudRule records deterministically.
    LLM is never involved in threshold arithmetic.
    """
    logger.info(f"[Node:execute_fraud_rules] case={state['case_id']}")

    # Build evidence context dict for rule evaluators
    evidence_ctx = {
        "user_id": state.get("user_id"),
        "merchant_id": state.get("merchant_id"),
        "device_id": state.get("_device_id"),
        "user_profile": state.get("_user_profile"),
        "evidence_items": state.get("evidence_items", []),
    }

    rule_results = FraudRuleEngine.evaluate(evidence_ctx)
    return {"rule_evaluation_results": rule_results}


# =============================================================================
# Node 3c: retrieve_policy_rag — Layer 1 (Active Policy RAG)
# =============================================================================

def node_retrieve_policy_rag(state: InvestigationState) -> Dict[str, Any]:
    """
    Queries ChromaDB with version-filtering: only is_active=True policies returned.
    Prevents expired or superseded SOPs from being cited in reasoning.
    """
    logger.info(f"[Node:retrieve_policy_rag] case={state['case_id']}")

    trigger_type = state.get("trigger_type", "INVESTIGATION")
    trigger_reason = state.get("trigger_reason", "")
    query_text = f"Fraud investigation policy for {trigger_type}: {trigger_reason}"

    # Infer category from trigger type
    category_map = {
        "CHARGEBACK_SPIKE": "CHARGEBACK",
        "ACCOUNT_TAKEOVER": "ATO",
        "SYNTHETIC_IDENTITY": "SYNTHETIC_ID",
        "KYC_FAILURE": "KYC_AML",
    }
    category = category_map.get(trigger_type)

    rag_result = KBPolicyService.retrieve_active_policies(
        query_text=query_text,
        category=category,
        top_k=3
    )
    return {"retrieved_policies": rag_result.get("passages", [])}


# =============================================================================
# Node 3d: retrieve_historical_intel — Layer 4 (Historical Intelligence)
# =============================================================================

def node_retrieve_historical_intel(state: InvestigationState) -> Dict[str, Any]:
    """
    Retrieves recent analyst-confirmed case outcomes for the same user or merchant.
    Provides historical precedent context to the LLM synthesis node.
    """
    logger.info(f"[Node:retrieve_historical_intel] case={state['case_id']}")

    patterns = GraphStoreService.get_historical_patterns(
        user_id=state.get("user_id"),
        merchant_id=state.get("merchant_id"),
        limit=5
    )
    return {"historical_patterns": patterns}


# =============================================================================
# Node 4: reason_llm — Grounded Synthesis (receives all 4 intelligence streams)
# =============================================================================

def node_reason_llm(state: InvestigationState) -> Dict[str, Any]:
    """
    Synthesizes all 4 intelligence streams into a structured assessment.
    LLM is grounded by:
      - Explicit triggered/passed rule list (no arithmetic needed from LLM)
      - Version-filtered active policy passages
      - Pre-computed graph relationships
      - Historical case precedent
    """
    logger.info(f"[Node:reason_llm] case={state['case_id']}")

    case = InvestigationCase.query.filter_by(id=state["case_id"]).first()
    trigger_type = case.trigger_type if case else state.get("trigger_type", "INVESTIGATION")
    trigger_reason = case.trigger_reason if case else state.get("trigger_reason", "")
    priority = case.priority if case else "MEDIUM"

    llm_result = LLMReasoningService.generate_investigation_reasoning(
        case_id=state["case_id"],
        trigger_type=trigger_type,
        trigger_reason=trigger_reason,
        priority=priority,
        evidence_items=state.get("evidence_items", []),
        graph_analysis=state.get("graph_analysis", {}),
        retrieved_policies=state.get("retrieved_policies", []),
        missing_evidence=state.get("missing_evidence", []),
        # Phase 3 additions — grounding inputs
        rule_evaluation_results=state.get("rule_evaluation_results", {}),
        historical_patterns=state.get("historical_patterns", []),
    )

    return {
        "assessment": llm_result["assessment"],
        "recommendation": llm_result["recommendation"],
        "explanation": llm_result["explanation"],
        "confidence_label": llm_result["confidence_label"],
        "risk_indicators": llm_result["risk_indicators"],
        "counter_signals": llm_result["counter_signals"],
        "model_name": llm_result.get("model_name", "LLM-Engine"),
    }


# =============================================================================
# Node 5: validate_grounding — Schema validation & persistence
# =============================================================================

def node_validate_grounding(state: InvestigationState) -> Dict[str, Any]:
    """
    Validates recommendation against StructuredRecommendation Pydantic schema.
    Persists to MySQL recommendations table.
    Includes triggered rule IDs in policy_references for auditability.
    """
    logger.info(f"[Node:validate_grounding] case={state['case_id']}")

    # Collect policy references: active policy IDs + triggered rule IDs
    policy_refs = [p.get("document_id", "SOP") for p in state.get("retrieved_policies", [])]
    rule_results = state.get("rule_evaluation_results", {})
    triggered_rule_ids = [r["rule_id"] for r in rule_results.get("triggered_rules", [])]
    all_refs = list(set(policy_refs + triggered_rule_ids))

    rec_schema = StructuredRecommendation(
        case_id=state["case_id"],
        assessment=state["assessment"],
        recommendation=state["recommendation"],
        explanation=state["explanation"],
        confidence_label=state["confidence_label"],
        risk_indicators=state["risk_indicators"],
        counter_signals=state["counter_signals"],
        missing_evidence=state.get("missing_evidence", []),
        policy_references=all_refs,
        human_review_required=True,
        model_name=state.get("model_name", "LLM-Engine")
    )

    # Persist recommendation
    rec = Recommendation(
        id=str(uuid.uuid4()),
        case_id=state["case_id"],
        assessment=rec_schema.assessment,
        recommendation_type=rec_schema.recommendation,
        explanation=rec_schema.explanation,
        confidence_label=rec_schema.confidence_label,
        human_review_required=rec_schema.human_review_required,
        model_name=rec_schema.model_name,
        prompt_version="2.0",
        policy_version="1.0",
        structured_result=rec_schema.model_dump()
    )
    db.session.add(rec)
    db.session.commit()

    return {"status": "RECOMMENDATION_PERSISTED"}


# =============================================================================
# Node 6: route_decision — Decision gateway & audit trail
# =============================================================================

def node_route_decision(state: InvestigationState) -> Dict[str, Any]:
    """
    Routes case to ESCALATED / ACTION_AUTHORIZED / REQUIRES_REVIEW based on
    recommendation confidence and evidence completeness.
    Writes full audit event including rule_evaluation_results.
    """
    logger.info(f"[Node:route_decision] case={state['case_id']}")

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

    route_res = DecisionGateway.evaluate_route(
        recommendation=rec_obj,
        evidence_count=len(state.get("evidence_items", [])),
        missing_evidence_count=len(state.get("missing_evidence", []))
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

    # Full audit trail including rule engine results
    rule_results = state.get("rule_evaluation_results", {})
    AuditService.record_event(
        event_type="RECOMMENDATION_GENERATED",
        actor_type="AGENT_WORKFLOW",
        correlation_id=case.idempotency_key if case else state["case_id"],
        case_id=state["case_id"],
        details={
            "assessment": state["assessment"],
            "recommendation": state["recommendation"],
            "route": route_res["route"],
            "status": final_status,
            "triggered_rules": [r["rule_id"] for r in rule_results.get("triggered_rules", [])],
            "total_risk_score": rule_results.get("total_risk_score", 0.0),
            "highest_severity": rule_results.get("highest_severity", "NONE"),
        }
    )

    return {
        "gateway_route": route_res["route"],
        "gateway_reason": route_res["reason"],
        "auto_action_eligible": route_res["auto_action_eligible"],
        "review_required": route_res["review_required"],
        "status": final_status,
    }


# =============================================================================
# Graph Assembly — Parallel Fan-Out Architecture
# =============================================================================

def build_investigation_graph():
    """
    Builds and compiles the Phase 3 LangGraph workflow with parallel retrieval.
    """
    workflow = StateGraph(InvestigationState)

    # Register all nodes
    workflow.add_node("validate_trigger", node_validate_trigger)
    workflow.add_node("collect_evidence", node_collect_evidence)
    workflow.add_node("retrieve_entity_graph", node_retrieve_entity_graph)
    workflow.add_node("execute_fraud_rules", node_execute_fraud_rules)
    workflow.add_node("retrieve_policy_rag", node_retrieve_policy_rag)
    workflow.add_node("retrieve_historical_intel", node_retrieve_historical_intel)
    workflow.add_node("reason_llm", node_reason_llm)
    workflow.add_node("validate_grounding", node_validate_grounding)
    workflow.add_node("route_decision", node_route_decision)

    # Sequential entry
    workflow.set_entry_point("validate_trigger")
    workflow.add_edge("validate_trigger", "collect_evidence")

    # Unified 4-layer Knowledgebase Intelligence Retrieval Pipeline
    workflow.add_edge("collect_evidence", "retrieve_entity_graph")
    workflow.add_edge("retrieve_entity_graph", "execute_fraud_rules")
    workflow.add_edge("execute_fraud_rules", "retrieve_policy_rag")
    workflow.add_edge("retrieve_policy_rag", "retrieve_historical_intel")
    workflow.add_edge("retrieve_historical_intel", "reason_llm")

    # Sequential finale
    workflow.add_edge("reason_llm", "validate_grounding")
    workflow.add_edge("validate_grounding", "route_decision")
    workflow.add_edge("route_decision", END)

    return workflow.compile()


# Global compiled instance (singleton — loaded once at import time)
investigation_graph = build_investigation_graph()


# =============================================================================
# Public execution helper
# =============================================================================

def execute_case_investigation(case_id: str) -> Dict[str, Any]:
    """
    Runs the compiled investigation graph synchronously.
    Can be called directly or dispatched via Celery.
    """
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
        # Evidence
        "evidence_items": [],
        "missing_evidence": [],
        # Knowledgebase intelligence (populated by parallel nodes)
        "graph_analysis": {},
        "rule_evaluation_results": {},
        "retrieved_policies": [],
        "historical_patterns": [],
        # LLM synthesis
        "assessment": None,
        "recommendation": None,
        "explanation": None,
        "confidence_label": None,
        "risk_indicators": [],
        "counter_signals": [],
        "model_name": None,
        # Decision gateway
        "gateway_route": None,
        "gateway_reason": None,
        "auto_action_eligible": False,
        "review_required": True,
        "status": case.status,
        # Internal evidence enrichment (cleared after collect_evidence)
        "_user_profile": None,
        "_device_id": None,
    }

    return investigation_graph.invoke(initial_state)
