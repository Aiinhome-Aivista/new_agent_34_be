import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agent.graph import execute_case_investigation, node_execute_fraud_rules
from app.agent.state import InvestigationState
from app.services.knowledgebase.rule_engine import RuleEvaluators


def _make_fr001_rule():
    return SimpleNamespace(
        id="FR-001",
        rule_name="User Identity Not Found",
        category="IDENTITY",
        severity="CRITICAL",
        weight=0.35,
        threshold_value=1.0,
        threshold_unit="exists_flag",
    )


def _fake_evidence(evidence_type: str, retrieval_status: str, payload: dict, source_reference: str = "REF"):
    data = {
        "id": f"ev-{evidence_type}",
        "evidence_type": evidence_type,
        "source_system": "USER_SERVICE [m_users]",
        "source_reference": source_reference,
        "retrieval_status": retrieval_status,
        "normalized_payload": payload,
    }
    return SimpleNamespace(
        evidence_type=evidence_type,
        source_reference=source_reference,
        retrieval_status=retrieval_status,
        to_dict=lambda: data,
    )


def test_investigation_state_declares_user_profile():
    assert "_user_profile" in InvestigationState.__annotations__


def test_langgraph_preserves_user_profile_and_passes_fr001():
    fake_case = SimpleNamespace(
        id="case-10029",
        trigger_type="TRANSACTION_INVESTIGATION",
        trigger_reason="Routine audit",
        priority="MEDIUM",
        transaction_id="PAY_8839210",
        user_id_ref="USR_10029",
        merchant_id_ref="MERCH_NORTH_01",
        status="RECEIVED",
        idempotency_key="idem-10029",
        completed_at=None,
    )
    collected = [
        _fake_evidence(
            "USER_PROFILE",
            "COLLECTED",
            {"user_id": "USR_10029", "status": "ACTIVE", "kyc_status": "VERIFIED"},
            "USR_10029",
        ),
    ]
    captured_evidence_ctx = {}

    def fake_rule_eval(ctx):
        captured_evidence_ctx.update(ctx)
        fr001 = RuleEvaluators.eval_user_identity_exists(_make_fr001_rule(), ctx)
        return {
            "triggered_rules": [fr001] if fr001["triggered"] else [],
            "passed_rules": [] if fr001["triggered"] else [fr001],
            "total_risk_score": 0.35 if fr001["triggered"] else 0.0,
            "highest_severity": "CRITICAL" if fr001["triggered"] else "NONE",
        }

    mock_case_query = MagicMock()
    mock_case_query.filter_by.return_value.first.return_value = fake_case
    mock_tok_query = MagicMock()
    mock_tok_query.filter_by.return_value.order_by.return_value.first.return_value = None

    with (
        patch("app.agent.graph.InvestigationCase") as mock_case_cls,
        patch("app.agent.graph.db") as mock_db,
        patch("app.agent.graph.EvidenceService.collect_evidence_for_case", return_value=collected),
        patch("app.models.investigation.EvidenceRequestToken") as mock_tok_cls,
        patch("app.agent.graph.GraphStoreService.get_entity_neighborhood", return_value={"risk_signals": []}),
        patch("app.agent.graph.GraphStoreService.get_historical_patterns", return_value=[]),
        patch("app.agent.graph.FraudRuleEngine.evaluate", side_effect=fake_rule_eval),
        patch("app.agent.graph.KBPolicyService.retrieve_active_policies", return_value={"passages": []}),
        patch(
            "app.agent.graph.LLMReasoningService.generate_investigation_reasoning",
            return_value={
                "assessment": "NOT_SUBSTANTIATED",
                "recommendation": "NO_ACTION",
                "explanation": "Verified customer with clean profile and no triggered fraud rules.",
                "confidence_label": "HIGH",
                "risk_indicators": [],
                "counter_signals": [],
                "model_name": "test-model",
            },
        ),
        patch("app.services.microservice_dispatcher.MicroserviceDispatcher.get_all_connectors_status", return_value={}),
        patch("app.agent.graph.DecisionGateway.evaluate_route", return_value={
            "route": "HUMAN_REVIEW",
            "reason": "test",
            "auto_action_eligible": False,
            "review_required": True,
        }),
        patch("app.agent.graph.AuditService.record_event"),
    ):
        mock_case_cls.query = mock_case_query
        mock_tok_cls.query = mock_tok_query
        mock_db.session = MagicMock()

        final_state = execute_case_investigation("case-10029")

    assert captured_evidence_ctx["user_profile"] == {
        "user_id": "USR_10029",
        "status": "ACTIVE",
        "kyc_status": "VERIFIED",
    }
    assert final_state["rule_evaluation_results"]["triggered_rules"] == []


def test_node_execute_fraud_rules_falls_back_to_evidence_items_for_user_profile():
    items = [
        _fake_evidence("USER_PROFILE", "COLLECTED", {"user_id": "USR_10029", "status": "ACTIVE"}).to_dict(),
    ]
    partial_state = {
        "user_id": "USR_10029",
        "merchant_id": None,
        "evidence_items": items,
        "case_id": "case-partial",
    }
    captured = {}

    def capture_eval(ctx):
        captured.update(ctx)
        return {"triggered_rules": [], "passed_rules": [], "total_risk_score": 0.0, "highest_severity": "NONE"}

    with patch("app.agent.graph.FraudRuleEngine.evaluate", side_effect=capture_eval):
        node_execute_fraud_rules(partial_state)

    assert captured["user_profile"] == {"user_id": "USR_10029", "status": "ACTIVE"}


def test_eval_user_identity_exists_handles_collected_and_missing():
    rule = _make_fr001_rule()

    # 1. Profile present directly
    res_direct = RuleEvaluators.eval_user_identity_exists(
        rule, {"user_id": "USR_10029", "user_profile": {"user_id": "USR_10029", "status": "ACTIVE"}}
    )
    assert res_direct["triggered"] is False

    # 2. Fallback to evidence_items COLLECTED
    res_ev = RuleEvaluators.eval_user_identity_exists(
        rule,
        {
            "user_id": "USR_10029",
            "user_profile": None,
            "evidence_items": [
                _fake_evidence("USER_PROFILE", "COLLECTED", {"user_id": "USR_10029", "status": "ACTIVE"}).to_dict()
            ],
        },
    )
    assert res_ev["triggered"] is False

    # 3. Genuinely missing user still triggers FR-001
    res_missing = RuleEvaluators.eval_user_identity_exists(
        rule,
        {
            "user_id": "USER_ALPHA",
            "user_profile": None,
            "evidence_items": [
                _fake_evidence("USER_PROFILE", "MISSING", {"reason": "Not found"}).to_dict()
            ],
        },
    )
    assert res_missing["triggered"] is True
