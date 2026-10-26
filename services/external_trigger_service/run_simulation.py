import sys
import json
from services.external_trigger_service.dispatcher import TriggerDispatcher

def main():
    print("==========================================================")
    print("  AGENT 34 - EXTERNAL MULTI-THREADED TRIGGER SIMULATOR")
    print("==========================================================")
    
    target = "http://localhost:5000/api/v1/investigations"
    if len(sys.argv) > 1:
        target = sys.argv[1]

    dispatcher = TriggerDispatcher(target_url=target)

    print(f"\n[1/2] Running Idempotency Concurrency Flood Test (10 threads, same key)...")
    flood_res = dispatcher.run_idempotency_flood_test(flood_count=10, concurrency=5)
    print(f"Result: {'PASS' if flood_res['pass'] else 'FAIL'}")
    print(f"  - Cases Created (Expect exactly 1): {flood_res['cases_created (expected 1)']}")
    print(f"  - Duplicate Handled: {flood_res['duplicate_handled']}")
    print(f"  - Total Duration: {flood_res['total_duration_seconds']:.2f}s")

    print(f"\n[2/2] Running Burst Concurrency Load Test (20 requests, 5 parallel workers)...")
    burst_res = dispatcher.run_burst_test(num_requests=20, concurrency=5)
    print(f"  - Successful: {burst_res['successful_requests']}/{burst_res['total_requests']}")
    print(f"  - Avg Latency: {burst_res['average_latency']:.3f}s")
    print(f"  - Total Duration: {burst_res['total_duration_seconds']:.2f}s")
    print("\nSimulation Complete.\n")

if __name__ == "__main__":
    main()
