import sys
import time
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.microservice_dispatcher import (
    MicroserviceDispatcher,
    _resolve_connector_http_target,
    _normalize_http_response,
)
from app.services.ingest_service import IngestService


def _make_spec(
    service_key: str,
    endpoint_path: str,
    base_url: str = "http://localhost:3052",
    is_active: bool = True,
    is_mock_enabled: bool = False,
    http_method: str = "GET",
    auth_type: str = "NONE",
    auth_token_encrypted: str | None = None,
    sample_response: dict | None = None,
    retry_count: int = 0,
):
    return {
        "id": f"id-{service_key}",
        "service_key": service_key,
        "service_name": service_key.replace("_", " ").title(),
        "service_category": "IDENTITY",
        "http_method": http_method,
        "base_url": base_url,
        "endpoint_path": endpoint_path,
        "auth_type": auth_type,
        "auth_header_key": "Authorization",
        "auth_token_encrypted": auth_token_encrypted,
        "custom_headers": {},
        "sample_payload": None,
        "sample_response": sample_response,
        "timeout_ms": 3000,
        "retry_count": retry_count,
        "is_mock_enabled": is_mock_enabled,
        "is_active": is_active,
    }


def test_resolve_connector_http_target_user_only_fallbacks():
    # ORDER_SERVICE falls back from /{order_id} to ?user_id=USR_01
    order_res = _resolve_connector_http_target(
        _make_spec("ORDER_SERVICE", "/api/v1/services/orders/{order_id}"),
        user_id="USR_01",
    )
    assert order_res["local_path"] == "/api/v1/services/orders"
    assert order_res["query_params"] == {"user_id": "USR_01"}
    assert order_res["skip_reason"] is None

    # REFUND_SERVICE falls back from /{refund_id} to ?user_id=USR_01
    refund_res = _resolve_connector_http_target(
        _make_spec("REFUND_SERVICE", "/api/v1/services/refunds/{refund_id}"),
        user_id="USR_01",
    )
    assert refund_res["local_path"] == "/api/v1/services/refunds"
    assert refund_res["query_params"] == {"user_id": "USR_01"}

    # PAYMENT_SERVICE uses specific {payment_id} when transaction_id is provided
    pay_res = _resolve_connector_http_target(
        _make_spec("PAYMENT_SERVICE", "/api/v1/services/payments/{payment_id}"),
        user_id="USR_01",
        transaction_id="PAY_999",
    )
    assert pay_res["local_path"] == "/api/v1/services/payments/PAY_999"
    assert pay_res["query_params"] == {}

    # CHARGEBACK_SERVICE filters by payment_id when transaction_id is provided
    cb_res = _resolve_connector_http_target(
        _make_spec("CHARGEBACK_SERVICE", "/api/v1/services/chargebacks/{chargeback_id}"),
        user_id="USR_01",
        transaction_id="PAY_999",
    )
    assert cb_res["local_path"] == "/api/v1/services/chargebacks"
    assert cb_res["query_params"] == {"payment_id": "PAY_999"}


def test_parallel_dispatch_executes_concurrently_and_waits_for_barrier():
    specs = [
        _make_spec("USER_SERVICE", "/api/v1/services/users/{user_id}"),
        _make_spec("ORDER_SERVICE", "/api/v1/services/orders/{order_id}"),
        _make_spec("PAYMENT_SERVICE", "/api/v1/services/payments/{payment_id}"),
        _make_spec("CHARGEBACK_SERVICE", "/api/v1/services/chargebacks/{chargeback_id}"),
        _make_spec("REFUND_SERVICE", "/api/v1/services/refunds/{refund_id}"),
        _make_spec(
            "DEVICE_RISK_API",
            "/v1/risk/{user_id}",
            base_url="https://risk.example.com",
            auth_type="BEARER_TOKEN",
            auth_token_encrypted="secret-token",
        ),
        _make_spec("DISABLED_SVC", "/v1/disabled", is_active=False),
    ]

    active_threads = set()
    thread_lock = threading.Lock()

    def slow_worker(app, spec, lookup_ctx):
        with thread_lock:
            active_threads.add(threading.current_thread().name)
        time.sleep(0.25)
        s_key = spec["service_key"]
        return {
            "service_key": s_key,
            "service_name": spec["service_name"],
            "target_table": "external_api",
            "status": "COLLECTED",
            "status_code": 200,
            "execution_mode": "LIVE_NETWORK",
            "records": [{"id": f"rec-{s_key}"}],
            "evidence_descriptors": [{
                "evidence_type": f"{s_key}_RECORD",
                "source_system": s_key,
                "source_reference": lookup_ctx["user_id"],
                "retrieval_status": "COLLECTED",
                "normalized_payload": {"ok": True, "service": s_key},
                "content_hash": "abc",
            }],
            "records_count": 1,
            "latency_ms": 250,
            "error": None,
            "log_line": f"  [OK] {s_key}",
        }

    with (
        patch.object(MicroserviceDispatcher, "_load_connector_specs", return_value=specs),
        patch("app.services.microservice_dispatcher._execute_http_connector_worker", side_effect=slow_worker),
        patch("app.services.microservice_dispatcher.db") as mock_db,
    ):
        mock_db.session = MagicMock()
        t0 = time.perf_counter()
        evidence_items, summary = MicroserviceDispatcher.dispatch_case_evidence(
            case_id="case-parallel-1",
            user_id="USR_01",
        )
        elapsed = time.perf_counter() - t0

    # 6 active services * 0.25s sequential would be >= 1.50s; parallel must finish well under 0.9s
    assert elapsed < 0.9, f"Expected parallel execution under 0.9s, took {elapsed:.3f}s"
    assert len(active_threads) >= 2
    assert len(summary["active_sources"]) == 6
    assert len(summary["bypassed_sources"]) == 1
    assert len(evidence_items) == 7  # 6 collected + 1 skipped


def test_parallel_dispatch_isolates_partial_failures_and_executes_external_http():
    specs = [
        _make_spec(
            "MOCK_EXT",
            "/v1/mock/{user_id}",
            base_url="https://mock.example.com",
            is_mock_enabled=True,
            sample_response={"risk": "LOW"},
        ),
        _make_spec(
            "LIVE_EXT",
            "/v1/score/{user_id}",
            base_url="https://score.example.com",
            auth_type="BEARER_TOKEN",
            auth_token_encrypted="tok-123",
        ),
        _make_spec(
            "FAILING_EXT",
            "/v1/fail/{user_id}",
            base_url="https://down.example.com",
        ),
    ]

    captured_requests = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)

        def json(self):
            return self._payload

    class FakeHttpxClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, **kwargs):
            captured_requests.append(kwargs)
            if "down.example.com" in kwargs["url"]:
                return FakeResponse(503, {"error": "unavailable"})
            return FakeResponse(200, {"score": 88})

    with (
        patch.object(MicroserviceDispatcher, "_load_connector_specs", return_value=specs),
        patch("app.services.microservice_dispatcher.httpx.Client", FakeHttpxClient),
        patch("app.services.microservice_dispatcher.db") as mock_db,
    ):
        mock_db.session = MagicMock()
        evidence_items, summary = MicroserviceDispatcher.dispatch_case_evidence(
            case_id="case-partial-fail",
            user_id="USR_77",
        )

    statuses = {ev.source_system: ev.retrieval_status for ev in evidence_items}
    assert statuses["MOCK_EXT"] == "COLLECTED"
    assert statuses["LIVE_EXT"] == "COLLECTED"
    assert statuses["FAILING_EXT [external_api]"] == "FAILED"
    assert len(captured_requests) == 2
    live_req = next(r for r in captured_requests if "score.example.com" in r["url"])
    assert live_req["headers"]["Authorization"] == "Bearer tok-123"
    assert live_req["url"] == "https://score.example.com/v1/score/USR_77"
    assert any(t["service_key"] == "FAILING_EXT" and t["status"] == "ERROR" for t in summary["telemetry"])


def test_normalize_http_response_treats_core_404_as_empty():
    records, descriptors = _normalize_http_response(
        s_key="REFUND_SERVICE",
        target_table="m_refunds",
        status_code=404,
        resp_body={"error": "Not Found"},
        lookup_ctx={"user_id": "USR_01"},
    )
    assert records == []
    assert descriptors == []


def test_batch_ingest_fetches_parallel_once_per_user_in_strict_user_order():
    csv_bytes = (
        "user_id,user_name,email,reason\n"
        "USR_1,User One,u1@example.com,Check 1\n"
        "USR_2,User Two,u2@example.com,Check 2\n"
    ).encode("utf-8")

    timeline = []

    def fake_user_query(user_id):
        return SimpleNamespace(
            user_id=user_id,
            first_name=user_id,
            last_name="Test",
            email=f"{user_id.lower()}@example.com",
            status="ACTIVE",
            risk_level="LOW",
            risk_score=10.0,
            kyc_status="VERIFIED",
        )

    def fake_parallel_snapshot(user_id=None, **kwargs):
        timeline.append(("snapshot_start", user_id))
        return {
            "evidence_descriptors": [],
            "summary": {"active_sources": [], "bypassed_sources": [], "telemetry": []},
            "records_by_service": {
                "ORDER_SERVICE": [{"order_id": f"ORD_{user_id}", "merchant_id": "MERCH_1"}],
                "PAYMENT_SERVICE": [{"payment_id": f"PAY_{user_id}", "merchant_id": "MERCH_1"}],
                "CHARGEBACK_SERVICE": [],
                "REFUND_SERVICE": [{"refund_id": f"REF_{user_id}"}],
            },
            "service_active": {
                "ORDER_SERVICE": True,
                "PAYMENT_SERVICE": True,
                "CHARGEBACK_SERVICE": True,
                "REFUND_SERVICE": True,
            },
            "wall_time_ms": 12,
        }

    def fake_process_trigger(req):
        case = SimpleNamespace(
            id=f"case-{req.user_id}",
            status="RECEIVED",
            priority=req.priority,
            created_at=SimpleNamespace(isoformat=lambda: "2026-11-27T00:00:00Z"),
            recommendations=[SimpleNamespace(assessment="NOT_SUBSTANTIATED", recommendation_type="NO_ACTION", explanation="OK")],
        )
        return case, False

    def fake_execute_investigation(case_id, prefetched_snapshot=None, order_id=None):
        timeline.append(("investigate_done", case_id, prefetched_snapshot is not None))
        return {"status": "REQUIRES_REVIEW"}

    mock_muser_query = MagicMock()
    mock_muser_query.filter_by.side_effect = lambda **kw: SimpleNamespace(first=lambda: fake_user_query(kw["user_id"]))

    with (
        patch("app.services.ingest_service.MUser") as mock_muser_cls,
        patch("app.services.microservice_dispatcher.MicroserviceDispatcher.fetch_domain_snapshot_parallel", side_effect=fake_parallel_snapshot),
        patch("app.services.knowledgebase.graph_store.GraphStoreService.process_user_ingestion"),
        patch("app.services.knowledgebase.graph_store.GraphStoreService.process_order_ingestion"),
        patch("app.services.knowledgebase.graph_store.GraphStoreService.process_payment_ingestion"),
        patch("app.services.ingest_service.CaseService.process_trigger", side_effect=fake_process_trigger),
        patch("app.services.ingest_service.execute_case_investigation", side_effect=fake_execute_investigation),
        patch("app.services.ingest_service.db") as mock_db,
    ):
        mock_muser_cls.query = mock_muser_query
        mock_db.session = MagicMock()
        result = IngestService.parse_and_ingest(csv_bytes, "users.csv", auto_investigate=True)

    assert result["status"] == "SUCCESS"
    assert result["ingested"] == 2
    assert timeline == [
        ("snapshot_start", "USR_1"),
        ("investigate_done", "case-USR_1", True),
        ("snapshot_start", "USR_2"),
        ("investigate_done", "case-USR_2", True),
    ]


def test_internal_flask_test_client_parallel_execution():
    from flask import Flask
    from app.api.microservices import microservices_bp
    from app.services.microservice_dispatcher import _execute_http_connector_worker

    test_app = Flask(__name__)
    test_app.register_blueprint(microservices_bp, url_prefix="/api/v1/services")

    user_obj = SimpleNamespace(to_dict=lambda: {"user_id": "USR_42", "status": "ACTIVE"})
    order_obj = SimpleNamespace(to_dict=lambda: {"order_id": "ORD_42", "user_id": "USR_42"})
    refund_obj = SimpleNamespace(to_dict=lambda: {"refund_id": "REF_42", "user_id": "USR_42"})

    mock_user_q = MagicMock()
    mock_user_q.filter.return_value.first.return_value = user_obj
    mock_order_q = MagicMock()
    mock_order_q.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = [order_obj]
    mock_refund_q = MagicMock()
    mock_refund_q.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = [refund_obj]

    specs = [
        _make_spec("USER_SERVICE", "/api/v1/services/users/{user_id}"),
        _make_spec("ORDER_SERVICE", "/api/v1/services/orders/{order_id}"),
        _make_spec("REFUND_SERVICE", "/api/v1/services/refunds/{refund_id}"),
    ]

    with (
        test_app.app_context(),
        patch.object(MicroserviceDispatcher, "_load_connector_specs", return_value=specs),
        patch("app.api.microservices.MUser") as m_user,
        patch("app.api.microservices.MOrder") as m_order,
        patch("app.api.microservices.MRefund") as m_refund,
        patch("app.services.microservice_dispatcher.db") as mock_db,
    ):
        m_user.query = mock_user_q
        m_order.query = mock_order_q
        m_refund.query = mock_refund_q
        mock_db.session = MagicMock()

        evidence_items, summary = MicroserviceDispatcher.dispatch_case_evidence(
            case_id="case-internal-http",
            user_id="USR_42",
        )

    assert len(evidence_items) == 3
    by_type = {ev.evidence_type: ev for ev in evidence_items}
    assert by_type["USER_PROFILE"].source_reference == "USR_42"
    assert by_type["ORDER_DETAILS"].source_reference == "ORD_42"
    assert by_type["REFUND_HISTORY"].source_reference == "REF_42"
    assert all(t["execution_mode"] == "LIVE_DATABASE_SERVICE" for t in summary["telemetry"])
    assert mock_db.session.remove.call_count == 3
