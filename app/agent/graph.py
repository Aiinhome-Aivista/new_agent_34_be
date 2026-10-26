from langgraph.graph import StateGraph, START, END
from sqlalchemy.orm import Session
from app.agent.state import InvestigationState
from app.agent.nodes import (
    intake_and_plan_node,
    collect_evidence_node,
    detect_gaps_node,
    retrieve_policy_node,
    synthesize_findings_node,
)
from app.gateway.router import DecisionGateway

def build_investigation_graph(db: Session):
    workflow = StateGraph(InvestigationState)

    # Wrap node functions with db session
    async def _intake_step(state: InvestigationState):
        return await intake_and_plan_node(state, db)

    async def _collect_step(state: InvestigationState):
        return await collect_evidence_node(state, db)

    async def _gaps_step(state: InvestigationState):
        return await detect_gaps_node(state, db)

    async def _policy_step(state: InvestigationState):
        return await retrieve_policy_node(state, db)

    async def _synth_step(state: InvestigationState):
        return await synthesize_findings_node(state, db)

    async def _gateway_step(state: InvestigationState):
        decision_mode = state.get("decision_mode", "ADVISOR")
        recommended_action = state.get("recommendation", "NO_ACTION")
        confidence = state.get("qualitative_confidence", "MEDIUM")
        
        # Payment amount check
        payment = state.get("payment") or {}
        amount = float(payment.get("amount", 0.0))

        route, rationale = DecisionGateway.evaluate_route(
            decision_mode=decision_mode,
            recommended_action=recommended_action,
            qualitative_confidence=confidence,
            amount=amount
        )
        return {
            "gateway_route": route,
            "gateway_rationale": rationale
        }

    # Add nodes
    workflow.add_node("intake_and_plan", _intake_step)
    workflow.add_node("collect_evidence", _collect_step)
    workflow.add_node("detect_gaps", _gaps_step)
    workflow.add_node("retrieve_policy", _policy_step)
    workflow.add_node("synthesize_findings", _synth_step)
    workflow.add_node("route_gateway", _gateway_step)

    # Add edges
    workflow.add_edge(START, "intake_and_plan")
    workflow.add_edge("intake_and_plan", "collect_evidence")
    workflow.add_edge("collect_evidence", "detect_gaps")
    workflow.add_edge("detect_gaps", "retrieve_policy")
    workflow.add_edge("retrieve_policy", "synthesize_findings")
    workflow.add_edge("synthesize_findings", "route_gateway")
    workflow.add_edge("route_gateway", END)

    return workflow.compile()
