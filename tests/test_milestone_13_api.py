"""
Comprehensive Test Suite for Sherlock AI Milestone 13: Investigation API and User Interface.

Tests:
1. API Health and Schema Validation.
2. Investigation Lifecycle (Create, List, Retrieve, Demo Scenario).
3. Document Uploads, Format Validation, and Processing.
4. Security Safeguards (Upload Size Limits, Path Traversal, Unsupported Formats, Malformed JSON).
5. Entity Explorer and Bounded Graph Neighborhood Traversal.
6. Claims, Epistemic Evidence Spans, and Offsets.
7. Human-in-the-Loop Review Queue and Safeguarded Adjudications.
8. Deterministic Structured Reports (JSON and Markdown).
9. Durable SQLite Restart Persistence (Verifies state survives process termination).
10. UI Static Assets & Root HTML Endpoint.
"""

import io
import os
import tempfile
import pytest
pytest.importorskip("fastapi", reason="FastAPI not installed in this environment.")
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.core.investigation_service import InvestigationOrchestrator
from src.core.investigation_sqlite import SQLiteInvestigationStore
from src.core.models import ReviewStatus


@pytest.fixture
def temp_db_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_sherlock.db")
        yield db_path


@pytest.fixture
def test_client(temp_db_dir):
    app = create_app(db_path=temp_db_dir, backend_mode="rule")
    with TestClient(app) as client:
        yield client, temp_db_dir


# =============================================================================
# 1. Health & System Disclosure Tests
# =============================================================================

def test_api_health_endpoint(test_client):
    client, db_path = test_client
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "v1.0.0"
    assert data["backend_mode"] == "rule"
    assert data["persistence_backend"] == "sqlite"
    assert data["persistence_db_path"] == db_path
    assert "timestamp" in data


# =============================================================================
# 2. Investigation Lifecycle Tests
# =============================================================================

def test_create_and_get_investigation(test_client):
    client, _ = test_client
    inv_id = "inv_test_01"
    create_payload = {
        "investigation_id": inv_id,
        "description": "Test investigation for financial OSINT.",
        "backend_mode": "rule",
    }
    resp = client.post("/api/v1/investigations", json=create_payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["investigation_id"] == inv_id
    assert data["description"] == create_payload["description"]
    assert data["status"] == "CREATED"
    assert data["backend_mode"] == "rule"
    assert data["summary"]["total_documents"] == 0

    # Retrieve investigation
    get_resp = client.get(f"/api/v1/investigations/{inv_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["investigation_id"] == inv_id

    # List investigations
    list_resp = client.get("/api/v1/investigations")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    assert any(i["investigation_id"] == inv_id for i in list_data["investigations"])


def test_investigation_invalid_inputs_and_unknown_ids(test_client):
    client, _ = test_client
    # Unknown ID returns 404
    resp = client.get("/api/v1/investigations/non_existent_id")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()

    # Invalid ID with forbidden characters returns 422
    resp_invalid = client.post("/api/v1/investigations", json={"investigation_id": "inv/bad/id!", "backend_mode": "rule"})
    assert resp_invalid.status_code == 422


def test_load_fictional_demo_scenario(test_client):
    client, _ = test_client
    inv_id = "inv_demo_case"
    resp = client.post(f"/api/v1/investigations/{inv_id}/demo")
    assert resp.status_code == 200
    data = resp.json()
    assert data["investigation_id"] == inv_id
    summary = data["summary"]
    assert summary["total_documents"] == 2
    assert summary["completed_documents"] == 2
    assert summary["total_entities"] > 0
    assert summary["total_claims"] > 0


# =============================================================================
# 3. Document Ingestion & Security Tests
# =============================================================================

def test_document_upload_and_extraction(test_client):
    client, _ = test_client
    inv_id = "inv_doc_test"
    client.post("/api/v1/investigations", json={"investigation_id": inv_id})

    doc_text = "Acme Corp is located in Berlin. John Smith is director of Acme Corp."
    file_bytes = doc_text.encode("utf-8")

    files = {"file": ("report.txt", io.BytesIO(file_bytes), "text/plain")}
    data = {"auto_process": "true"}

    upload_resp = client.post(f"/api/v1/investigations/{inv_id}/documents", files=files, data=data)
    assert upload_resp.status_code == 201
    doc_data = upload_resp.json()
    assert doc_data["status"] == "COMPLETED"
    assert doc_data["source_name"] == "report.txt"
    assert doc_data["char_count"] == len(doc_text)
    assert doc_data["mention_count"] > 0
    assert doc_data["claim_count"] > 0

    # Retrieve document detail
    detail_resp = client.get(f"/api/v1/investigations/{inv_id}/documents/{doc_data['document_id']}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["text_content"] == doc_text


def test_document_size_limit_rejection(test_client):
    client, _ = test_client
    inv_id = "inv_oversize_test"
    client.post("/api/v1/investigations", json={"investigation_id": inv_id})

    # Create oversized payload: 6 MB (> 5 MB limit)
    oversized_bytes = b"A" * (6 * 1024 * 1024)
    files = {"file": ("large_file.txt", io.BytesIO(oversized_bytes), "text/plain")}

    resp = client.post(f"/api/v1/investigations/{inv_id}/documents", files=files)
    assert resp.status_code == 413
    assert "exceeds maximum allowed limit" in resp.json()["detail"].lower()


def test_document_unsupported_extension_rejection(test_client):
    client, _ = test_client
    inv_id = "inv_ext_test"
    client.post("/api/v1/investigations", json={"investigation_id": inv_id})

    files = {"file": ("malicious_payload.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")}
    resp = client.post(f"/api/v1/investigations/{inv_id}/documents", files=files)
    assert resp.status_code == 400
    assert "unsupported document format" in resp.json()["detail"].lower()


def test_document_malformed_json_rejection(test_client):
    client, _ = test_client
    inv_id = "inv_json_test"
    client.post("/api/v1/investigations", json={"investigation_id": inv_id})

    malformed_json = b"{'key': unquoted_value"
    files = {"file": ("bad_schema.json", io.BytesIO(malformed_json), "application/json")}
    resp = client.post(f"/api/v1/investigations/{inv_id}/documents", files=files)
    assert resp.status_code == 400
    assert "invalid json" in resp.json()["detail"].lower()


def test_path_traversal_sanitization(test_client):
    client, _ = test_client
    inv_id = "inv_traversal_test"
    client.post("/api/v1/investigations", json={"investigation_id": inv_id})

    content = b"Safe report text content."
    # Path traversal in filename
    files = {"file": ("../../../../etc/passwd.txt", io.BytesIO(content), "text/plain")}
    resp = client.post(f"/api/v1/investigations/{inv_id}/documents", files=files)
    # Sanitization either rejects traversal or strips path safely
    if resp.status_code == 201:
        assert "/" not in resp.json()["source_name"]
        assert ".." not in resp.json()["source_name"]
    else:
        assert resp.status_code == 400


# =============================================================================
# 4. Entities, Claims, Evidence, and Graph Endpoints
# =============================================================================

def test_entities_and_claims_endpoints(test_client):
    client, _ = test_client
    inv_id = "inv_entities_test"
    client.post(f"/api/v1/investigations/{inv_id}/demo")

    # List entities
    ent_resp = client.get(f"/api/v1/investigations/{inv_id}/entities")
    assert ent_resp.status_code == 200
    entities = ent_resp.json()["entities"]
    assert len(entities) > 0
    first_ent = entities[0]

    # Get single entity
    single_ent_resp = client.get(f"/api/v1/investigations/{inv_id}/entities/{first_ent['entity_id']}")
    assert single_ent_resp.status_code == 200
    assert single_ent_resp.json()["entity_id"] == first_ent["entity_id"]

    # List claims
    claims_resp = client.get(f"/api/v1/investigations/{inv_id}/claims")
    assert claims_resp.status_code == 200
    claims = claims_resp.json()["claims"]
    assert len(claims) > 0

    # List evidence
    ev_resp = client.get(f"/api/v1/investigations/{inv_id}/evidence")
    assert ev_resp.status_code == 200
    evidence_list = ev_resp.json()["evidence"]
    assert len(evidence_list) > 0
    assert "start_char" in evidence_list[0]
    assert "end_char" in evidence_list[0]


def test_graph_endpoints_bounded_traversal(test_client):
    client, _ = test_client
    inv_id = "inv_graph_test"
    client.post(f"/api/v1/investigations/{inv_id}/demo")

    # Entire graph
    g_resp = client.get(f"/api/v1/investigations/{inv_id}/graph?max_nodes=30")
    assert g_resp.status_code == 200
    g_data = g_resp.json()
    assert len(g_data["nodes"]) > 0
    assert len(g_data["edges"]) > 0

    # Query from root entity
    root_id = g_data["nodes"][0]["id"]
    q_resp = client.get(f"/api/v1/investigations/{inv_id}/graph/query?start_entity_id={root_id}&max_depth=2&max_nodes=20")
    assert q_resp.status_code == 200
    q_data = q_resp.json()
    assert q_data["root_entity_id"] == root_id
    assert len(q_data["nodes"]) > 0


# =============================================================================
# 5. Human Review Queue & Consequential Adjudication
# =============================================================================

def test_human_review_queue_and_decision(test_client):
    client, _ = test_client
    inv_id = "inv_review_test"
    client.post(f"/api/v1/investigations/{inv_id}/demo")

    # Retrieve review queue
    q_resp = client.get(f"/api/v1/investigations/{inv_id}/review-queue")
    assert q_resp.status_code == 200
    items = q_resp.json()["items"]
    assert len(items) > 0

    # Pick an item that is a claim
    claim_item = next((item for item in items if item.get("claim_details")), None)
    assert claim_item is not None
    target_claim_id = claim_item["item_id"]

    # Rejection check: Missing reviewer ID or short rationale
    bad_req = {
        "claim_id": target_claim_id,
        "new_status": "VERIFIED",
        "reviewer": "a",  # too short
        "rationale": "ok",  # too short
    }
    bad_resp = client.post(f"/api/v1/investigations/{inv_id}/review-claim", json=bad_req)
    assert bad_resp.status_code == 422

    # Successful review decision
    good_req = {
        "claim_id": target_claim_id,
        "new_status": "VERIFIED",
        "reviewer": "analyst_alice",
        "rationale": "Verified against official company register disclosures.",
    }
    good_resp = client.post(f"/api/v1/investigations/{inv_id}/review-claim", json=good_req)
    assert good_resp.status_code == 200
    updated = good_resp.json()
    assert updated["claim_id"] == target_claim_id
    assert updated["review_status"] == "VERIFIED"
    assert len(updated["correction_history"]) == 1
    assert updated["correction_history"][0]["corrected_by"] == "analyst_alice"


# =============================================================================
# 6. Structured Report Endpoints
# =============================================================================

def test_report_generation_json_and_markdown(test_client):
    client, _ = test_client
    inv_id = "inv_report_test"
    client.post(f"/api/v1/investigations/{inv_id}/demo")

    # JSON report
    resp_json = client.get(f"/api/v1/investigations/{inv_id}/report")
    assert resp_json.status_code == 200
    rep_data = resp_json.json()
    assert rep_data["investigation_id"] == inv_id
    assert "report_schema_version" in rep_data
    assert "persistence_notice" in rep_data
    assert "metrics" in rep_data
    assert "raw_json" in rep_data

    # Markdown export
    resp_md = client.get(f"/api/v1/investigations/{inv_id}/report/markdown")
    assert resp_md.status_code == 200
    assert "text/markdown" in resp_md.headers.get("content-type", "")
    assert "# Sherlock AI Investigation Report" in resp_md.text


# =============================================================================
# 7. Restart Persistence Verification (Durable Local SQLite)
# =============================================================================

def test_restart_persistence(temp_db_dir):
    """
    Test that investigation metadata, ingested documents, entities, claims,
    and review decisions survive complete server process restart.
    """
    inv_id = "inv_restart_verify"

    # --- Phase 1: Initialize first process instance and write data ---
    app1 = create_app(db_path=temp_db_dir, backend_mode="rule")
    with TestClient(app1) as client1:
        # Create investigation
        c_resp = client1.post(
            "/api/v1/investigations",
            json={"investigation_id": inv_id, "description": "Persistent audit trial case."},
        )
        assert c_resp.status_code == 201

        # Upload and process document
        doc_text = "Alice Mercer serves as CEO of Apex Global Holdings. Apex Global Holdings is located in London."
        files = {"file": ("acquisition.txt", io.BytesIO(doc_text.encode("utf-8")), "text/plain")}
        u_resp = client1.post(f"/api/v1/investigations/{inv_id}/documents", files=files, data={"auto_process": "true"})
        assert u_resp.status_code == 201

        # Review a claim
        claims_resp = client1.get(f"/api/v1/investigations/{inv_id}/claims")
        claims = claims_resp.json()["claims"]
        assert len(claims) > 0
        target_claim = claims[0]["claim_id"]

        rev_resp = client1.post(
            f"/api/v1/investigations/{inv_id}/review-claim",
            json={
                "claim_id": target_claim,
                "new_status": "VERIFIED",
                "reviewer": "senior_investigator",
                "rationale": "Cross-verified with merger registry filings.",
            },
        )
        assert rev_resp.status_code == 200

        # Generate report
        rep_resp = client1.get(f"/api/v1/investigations/{inv_id}/report")
        assert rep_resp.status_code == 200

    # --- Phase 2: Simulate process termination & start brand new instance ---
    # Create completely new app and client pointing to the exact same DB file
    app2 = create_app(db_path=temp_db_dir, backend_mode="rule")
    with TestClient(app2) as client2:
        # Verify investigation exists
        inv_resp = client2.get(f"/api/v1/investigations/{inv_id}")
        assert inv_resp.status_code == 200
        inv_data = inv_resp.json()
        assert inv_data["investigation_id"] == inv_id
        assert inv_data["description"] == "Persistent audit trial case."
        assert inv_data["summary"]["total_documents"] >= 1
        assert inv_data["summary"]["total_entities"] >= 1
        assert inv_data["summary"]["verified_claims"] >= 1

        # Verify document text and metadata intact
        docs_resp = client2.get(f"/api/v1/investigations/{inv_id}/documents")
        assert docs_resp.status_code == 200
        docs = docs_resp.json()["documents"]
        assert len(docs) >= 1
        doc_id = docs[0]["document_id"]

        doc_detail = client2.get(f"/api/v1/investigations/{inv_id}/documents/{doc_id}").json()
        assert doc_detail["text_content"] == doc_text

        # Verify claim review audit trail preserved
        claims2 = client2.get(f"/api/v1/investigations/{inv_id}/claims").json()["claims"]
        matching_claim = next(c for c in claims2 if c["claim_id"] == target_claim)
        assert matching_claim["review_status"] == "VERIFIED"
        assert len(matching_claim["correction_history"]) == 1
        assert matching_claim["correction_history"][0]["corrected_by"] == "senior_investigator"

        # Verify stored report retrieved intact
        report2 = client2.get(f"/api/v1/investigations/{inv_id}/report").json()
        assert report2["investigation_id"] == inv_id
        assert report2["persistence_backend"] == "sqlite"


# =============================================================================
# 8. Static UI Serving Tests
# =============================================================================

def test_static_ui_serving(test_client):
    client, _ = test_client
    # Root HTML
    resp_root = client.get("/")
    assert resp_root.status_code == 200
    assert "text/html" in resp_root.headers.get("content-type", "")
    assert "Sherlock AI" in resp_root.text

    # Static CSS
    resp_css = client.get("/static/app.css")
    assert resp_css.status_code == 200
    assert "text/css" in resp_css.headers.get("content-type", "")

    # Static JS
    resp_js = client.get("/static/app.js")
    assert resp_js.status_code == 200
