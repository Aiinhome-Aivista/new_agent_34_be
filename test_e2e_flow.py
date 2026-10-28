#!/usr/bin/env python3
"""
Comprehensive End-to-End Verification Test Script
Tests:
1. 4-column CSV template generation
2. Master table verification and batch ingestion
3. Decision Gateway: LOCK_USER -> m_users.status == BLOCKED
4. Decision Gateway: REQUEST_EVIDENCE -> EVIDENCE_REQUESTED
5. Evidence Upload & Lightbox file server
6. Decision Gateway: UNLOCK_USER -> m_users.status == ACTIVE
7. Tamper-evident Audit Events with user_id and SHA-256 hashes
"""

import io
import sys
import os
from pathlib import Path

# Force UTF-8 on Windows stdout
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

root_dir = str(Path(__file__).resolve().parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import create_app
from app.extensions import db
from app.models.source_domain import MUser, MOrder, MPayment, MChargeback
from app.models.governance import AuditEvent
from app.models.investigation import InvestigationCase, CaseEvidence
from app.services.ingest_service import IngestService

def run_tests():
    app = create_app()
    client = app.test_client()

    with app.app_context():
        print("\n========================================================")
        print("  [TEST SUITE] FRAUD INVESTIGATION AGENT - E2E")
        print("========================================================")

        # -----------------------------------------------------------
        # TEST 1: Template Download (4 columns)
        # -----------------------------------------------------------
        print("\n[TEST 1] Verifying 4-Column Template Generation...")
        res = client.get("/api/v1/ingest/template")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        csv_text = res.data.decode("utf-8")
        lines = csv_text.strip().split("\n")
        header = lines[0].strip()
        print(f"  Header: {header}")
        assert header == "user_id,user_name,email,reason", f"Invalid header: {header}"
        assert len(lines) >= 6, f"Expected at least 5 sample rows, got {len(lines) - 1}"
        print(f"  [PASS] Template correctly outputs 4 columns: user_id, user_name, email, reason ({len(lines)-1} sample rows).")

        # -----------------------------------------------------------
        # TEST 2: Batch Ingestion with Strict Master Verification
        # -----------------------------------------------------------
        print("\n[TEST 2] Testing Batch Ingestion with Master Table Verification...")
        sample_csv = IngestService.generate_sample_csv()
        data = {
            "file": (io.BytesIO(sample_csv.encode("utf-8")), "test_batch.csv"),
            "auto_investigate": "true"
        }
        res = client.post("/api/v1/ingest/upload", data=data, content_type="multipart/form-data")
        assert res.status_code == 200, f"Upload failed: {res.data}"
        json_data = res.get_json()
        print(f"  Message: {json_data.get('message')}")
        print(f"  Total Ingested: {json_data.get('ingested')}, Triggered Cases: {len(json_data.get('triggered_cases', []))}")
        assert json_data.get("ingested") >= 5, "Expected at least 5 rows ingested"
        assert len(json_data.get("triggered_cases")) >= 5, "Expected at least 5 triggered cases"
        print("  [PASS] Successfully verified users against m_users and triggered multi-modal cases.")

        # Pick a target case linked to USR_SYBIL_RING_01
        sybil_case_info = None
        for tc in json_data.get("triggered_cases", []):
            if tc.get("user_id") == "USR_SYBIL_RING_01":
                sybil_case_info = tc
                break
        if not sybil_case_info:
            sybil_case_info = json_data.get("triggered_cases")[0]

        target_case_id = sybil_case_info["case_id"]
        target_user_id = sybil_case_info["user_id"]
        print(f"  Selected target case: {target_case_id} for user: {target_user_id}")

        # -----------------------------------------------------------
        # TEST 3: Decision Gateway - Action: LOCK_USER
        # -----------------------------------------------------------
        print(f"\n[TEST 3] Testing Decision Gateway: LOCK_USER on {target_user_id}...")
        lock_payload = {
            "decision": "LOCK_USER",
            "reason": "Confirmed multi-account hardware cluster on emulator farm",
            "reviewer_id": "SUB_ANALYST_01",
            "policy_reference": "FRAUD_SOP_04_HUMAN_REVIEW"
        }
        res = client.post(f"/api/v1/investigations/{target_case_id}/decisions", json=lock_payload)
        assert res.status_code == 200, f"LOCK_USER failed: {res.data}"
        print(f"  Response: {res.get_json()}")

        # Verify m_users mutation
        m_user = MUser.query.filter_by(user_id=target_user_id).first()
        assert m_user is not None, f"m_users record for {target_user_id} not found"
        assert m_user.status == "BLOCKED", f"Expected m_user.status == 'BLOCKED', got '{m_user.status}'"
        print(f"  [PASS] Master table mutation verified: m_users.status for {target_user_id} is '{m_user.status}'")

        # Verify AuditEvent with user_id
        lock_audit = AuditEvent.query.filter_by(case_id=target_case_id, user_id=target_user_id).order_by(AuditEvent.event_timestamp.desc()).first()
        assert lock_audit is not None, f"Audit event for case {target_case_id} and user {target_user_id} not found"
        print(f"  [PASS] Audit trail logged: event_type={lock_audit.event_type}, user_id={lock_audit.user_id}, hash={lock_audit.event_hash[:16]}...")

        # -----------------------------------------------------------
        # TEST 4: Decision Gateway - Action: REQUEST_EVIDENCE
        # -----------------------------------------------------------
        print(f"\n[TEST 4] Testing Decision Gateway: REQUEST_EVIDENCE...")
        req_ev_payload = {
            "decision": "REQUEST_EVIDENCE",
            "reason": "Request government Aadhaar/Passport proof and original payment confirmation",
            "reviewer_id": "SUB_ANALYST_01",
            "policy_reference": "FRAUD_SOP_05_KYC_IDENTITY"
        }
        res = client.post(f"/api/v1/investigations/{target_case_id}/decisions", json=req_ev_payload)
        assert res.status_code == 200, f"REQUEST_EVIDENCE failed: {res.data}"
        case_obj = InvestigationCase.query.filter_by(id=target_case_id).first()
        assert case_obj.status == "EVIDENCE_REQUESTED", f"Expected case.status == 'EVIDENCE_REQUESTED', got '{case_obj.status}'"
        print(f"  [PASS] Case status updated to '{case_obj.status}', evidence upload portal activated.")

        # -----------------------------------------------------------
        # TEST 5: Evidence Upload & Lightbox File Server
        # -----------------------------------------------------------
        print("\n[TEST 5] Testing Evidence Document Upload & File Server...")
        dummy_image_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        upload_data = {
            "file": (io.BytesIO(dummy_image_data), "identity_card_proof.png"),
            "document_type": "IDENTITY_PROOF",
            "notes": "Customer submitted government identity card",
            "uploader_name": "Priya Sharma (Senior Investigator)"
        }
        res = client.post(f"/api/v1/investigations/{target_case_id}/evidence-upload", data=upload_data, content_type="multipart/form-data")
        assert res.status_code == 201, f"Evidence upload failed: {res.data}"
        up_json = res.get_json()
        print(f"  Upload Response: {up_json.get('message')}")
        evidence_rec = up_json.get("evidence")
        assert evidence_rec is not None, "Evidence item missing in response"
        stored_file_path = evidence_rec.get("normalized_payload", {}).get("file_path")
        print(f"  Evidence Preview Path: {stored_file_path}")

        # Test file serving endpoint
        file_res = client.get(stored_file_path)
        assert file_res.status_code == 200, f"Failed to serve uploaded evidence file: {file_res.status_code}"
        assert len(file_res.data) == len(dummy_image_data), "Served file size mismatch"
        print(f"  [PASS] Lightbox file server verified: {len(file_res.data)} bytes served with HTTP 200.")

        # Test verify document endpoint
        verify_payload = {
            "status": "VERIFIED",
            "notes": "Hologram and signature verified against national database",
            "analyst_name": "Priya Sharma"
        }
        res = client.post(f"/api/v1/investigations/{target_case_id}/evidence/{evidence_rec['id']}/verify", json=verify_payload)
        assert res.status_code == 200, f"Verify evidence failed: {res.data}"
        print("  [PASS] In-app lightbox document verification action verified.")

        # -----------------------------------------------------------
        # TEST 6: Decision Gateway - Action: UNLOCK_USER
        # -----------------------------------------------------------
        print(f"\n[TEST 6] Testing Decision Gateway: UNLOCK_USER on {target_user_id}...")
        unlock_payload = {
            "decision": "UNLOCK_USER",
            "reason": "Submitted KYC documents verified authentic. Reinstating account access.",
            "reviewer_id": "SUB_ANALYST_01",
            "policy_reference": "FRAUD_SOP_04_HUMAN_REVIEW"
        }
        res = client.post(f"/api/v1/investigations/{target_case_id}/decisions", json=unlock_payload)
        assert res.status_code == 200, f"UNLOCK_USER failed: {res.data}"
        case_obj = InvestigationCase.query.filter_by(id=target_case_id).first()
        assert case_obj.status == "RESOLVED", f"Expected case.status == 'RESOLVED', got '{case_obj.status}'"

        # Verify m_users status restored to ACTIVE
        m_user = MUser.query.filter_by(user_id=target_user_id).first()
        assert m_user.status == "ACTIVE", f"Expected m_user.status == 'ACTIVE', got '{m_user.status}'"
        print(f"  [PASS] Master table mutation verified: m_users.status restored to '{m_user.status}'")

        # Verify AuditEvent with user_id
        unlock_audit = AuditEvent.query.filter_by(case_id=target_case_id, user_id=target_user_id, event_type="UNLOCK_USER").first()
        assert unlock_audit is not None, f"Unlock audit event for user {target_user_id} not found"
        print(f"  [PASS] Audit trail logged: event_type={unlock_audit.event_type}, user_id={unlock_audit.user_id}, hash={unlock_audit.event_hash[:16]}...")

        # -----------------------------------------------------------
        # TEST 7: Full Audit History Verification
        # -----------------------------------------------------------
        print(f"\n[TEST 7] Verifying Audit History for case {target_case_id}...")
        res = client.get(f"/api/v1/audit?case_id={target_case_id}")
        assert res.status_code == 200
        case_audits = res.get_json().get('items', [])
        print(f"  Retrieved {len(case_audits)} audit trail entries.")
        for a in case_audits:
            print(f"    * [{a.get('event_type')}] User: {a.get('user_id')} | Actor: {a.get('actor_id')} | Hash: {a.get('event_hash')[:12]}...")
            assert a.get("event_hash") is not None, "Missing event hash"

        print("\n========================================================")
        print("  ALL END-TO-END VERIFICATION TESTS PASSED SUCCESSFULLY!")
        print("========================================================\n")

if __name__ == "__main__":
    run_tests()
