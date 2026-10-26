import pytest
from app.database import SessionLocal
from app.models.transactional import User, Order, Payment, Chargeback
from app.models.platform import InvestigationCase, PolicyDocument
from app.tools.read_tools import EvidenceCollectorTools
from app.gateway.router import DecisionGateway
from app.auth.security import create_access_token, decode_access_token, verify_password

def test_database_connection_and_base_tables():
    db = SessionLocal()
    try:
        users = db.query(User).all()
        assert len(users) >= 4, "Users table should contain seeded users"

        orders = db.query(Order).all()
        assert len(orders) >= 4, "Orders table should contain seeded orders"

        payments = db.query(Payment).all()
        assert len(payments) >= 4, "Payments table should contain seeded payments"

        chargebacks = db.query(Chargeback).all()
        assert len(chargebacks) >= 2, "Chargebacks table should contain seeded chargebacks"
    finally:
        db.close()

def test_merchant_identifier_verification_and_unresolved_gap():
    db = SessionLocal()
    try:
        tools = EvidenceCollectorTools(db)
        # Test an unmapped merchant ID per Section 6 of Blueprint
        res = tools.get_merchant_profile("MER-91822")
        assert res["status"] == "UNRESOLVED_MERCHANT_RELATIONSHIP"
        assert res["gap_recorded"] is True
        assert "not mapped" in res["message"]
    finally:
        db.close()

def test_decision_gateway_advisor_mode():
    route, rationale = DecisionGateway.evaluate_route(
        decision_mode="ADVISOR",
        recommended_action="TEMPORARY_RESTRICTION",
        qualitative_confidence="HIGH",
        amount=78500.0
    )
    assert route == "HUMAN_REVIEW"
    assert "Advisor Mode" in rationale

def test_decision_gateway_high_value_escalation():
    route, rationale = DecisionGateway.evaluate_route(
        decision_mode="POLICY_CONTROLLED",
        recommended_action="MONITOR",
        qualitative_confidence="HIGH",
        amount=150000.0
    )
    assert route == "ESCALATE"
    assert "₹100,000 threshold" in rationale

def test_jwt_security_tokens():
    token = create_access_token(data={"sub": "priya.investigator", "role": "INVESTIGATOR"})
    payload = decode_access_token(token)
    assert payload["sub"] == "priya.investigator"
    assert payload["role"] == "INVESTIGATOR"
