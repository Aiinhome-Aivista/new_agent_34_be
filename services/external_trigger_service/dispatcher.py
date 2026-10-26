import time
import requests
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any
from services.external_trigger_service.scenarios import generate_random_trigger_payload

logger = logging.getLogger("trigger_microservice.dispatcher")

class TriggerDispatcher:
    """Dispatches high-concurrency external fraud investigation signals."""

    def __init__(self, target_url: str = "http://localhost:5000/api/v1/investigations"):
        self.target_url = target_url

    def _send_single_trigger(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Sends one trigger request and measures latency and status code."""
        start_time = time.time()
        try:
            resp = requests.post(self.target_url, json=payload, timeout=10.0)
            elapsed = time.time() - start_time
            return {
                "status_code": resp.status_code,
                "latency_seconds": elapsed,
                "response": resp.json() if resp.status_code in [200, 201, 409] else resp.text,
                "idempotency_key": payload.get("idempotency_key"),
                "is_duplicate": resp.json().get("is_duplicate", False) if resp.status_code in [200, 201] else False
            }
        except Exception as e:
            elapsed = time.time() - start_time
            return {
                "status_code": 0,
                "latency_seconds": elapsed,
                "error": str(e),
                "idempotency_key": payload.get("idempotency_key")
            }

    def run_burst_test(self, num_requests: int = 20, concurrency: int = 5) -> Dict[str, Any]:
        """Fires distinct trigger requests across concurrent threads."""
        payloads = [generate_random_trigger_payload() for _ in range(num_requests)]
        results = []

        start_all = time.time()
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(self._send_single_trigger, p) for p in payloads]
            for future in as_completed(futures):
                results.append(future.result())
        total_time = time.time() - start_all

        successes = [r for r in results if r["status_code"] in [200, 201]]
        errors = [r for r in results if r["status_code"] not in [200, 201]]

        return {
            "test_type": "BURST_CONCURRENCY",
            "total_requests": num_requests,
            "concurrency_workers": concurrency,
            "total_duration_seconds": total_time,
            "successful_requests": len(successes),
            "error_requests": len(errors),
            "average_latency": sum(r["latency_seconds"] for r in results) / len(results) if results else 0,
            "results_sample": results[:5]
        }

    def run_idempotency_flood_test(self, flood_count: int = 10, concurrency: int = 5) -> Dict[str, Any]:
        """
        Sends identical idempotency_key simultaneously from multiple threads.
        Verifies that exactly ONE case is created, and all other threads receive 200/409 duplicate responses without error.
        """
        shared_key = f"flood_test_{int(time.time())}"
        payload = generate_random_trigger_payload(force_idempotency_key=shared_key)
        payloads = [payload.copy() for _ in range(flood_count)]

        results = []
        start_all = time.time()
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(self._send_single_trigger, p) for p in payloads]
            for future in as_completed(futures):
                results.append(future.result())
        total_time = time.time() - start_all

        created_count = sum(1 for r in results if r.get("status_code") == 201)
        duplicate_count = sum(1 for r in results if r.get("is_duplicate") is True or r.get("status_code") in [200, 409])

        return {
            "test_type": "IDEMPOTENCY_CONCURRENCY_FLOOD",
            "flood_count": flood_count,
            "concurrency": concurrency,
            "shared_idempotency_key": shared_key,
            "total_duration_seconds": total_time,
            "cases_created (expected 1)": created_count,
            "duplicate_handled": duplicate_count,
            "pass": created_count == 1,
            "results": results
        }
