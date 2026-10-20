"""
Unit & Integration Tests for Report Generation, Safe Data Management, and Resolution Scale.

Tests:
1. System Stats endpoint (/api/v1/system/stats).
2. Report generation for empty and populated investigations.
3. Report downloads in Markdown, JSON, and HTML formats.
4. Investigation isolation during single-investigation deletion.
5. Deletion confirmation requirements (name mismatch rejection).
6. System-wide data clearing (/api/v1/system/clear-all) with confirmation phrase guard.
7. Candidate similarity threshold boundary validation on cross-document resolution.
"""

import io
import os
import tempfile
import pytest

pytest.importorskip("fastapi", reason="FastAPI not installed.")
from fastapi.testclient import TestClient

from src.api.app import create_app


@pytest.fixture
def temp_client():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_repair.db")
        app = create_app(db_path=db_path, backend_mode="rule")
        with TestClient(app) as client:
            yield client


def test_system_stats_initial(temp_client):
    resp = temp_client.get("/api/v1/system/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "investigations" in data
    assert "documents" in data
    assert "entities" in data
    assert "evidence" in data
    assert "claims" in data
    assert "relationships" in data
    assert "reports" in data


def test_report_generation_and_downloads(temp_client):
    # Create investigation
    inv_id = "test_rep_download_01"
    res = temp_client.post("/api/v1/investigations", json={"investigation_id": inv_id, "description": "Report test"})
    assert res.status_code == 201

    # Ingest document
    doc_content = b"John Watson is an investigator at 221B Baker St. Nexus Holdings acquired Apex Corp."
    upload_res = temp_client.post(
        f"/api/v1/investigations/{inv_id}/documents",
        files={"file": ("memo.txt", io.BytesIO(doc_content), "text/plain")},
        data={"auto_process": True},
    )
    assert upload_res.status_code == 201

    # 1. JSON Report
    rep_res = temp_client.get(f"/api/v1/investigations/{inv_id}/report")
    assert rep_res.status_code == 200
    rep_data = rep_res.json()
    assert rep_data["investigation_id"] == inv_id
    assert "raw_json" in rep_data
    assert "markdown_report" in rep_data
    assert "## Executive Summary" in rep_data["markdown_report"]
    assert "## Key Findings" in rep_data["markdown_report"]
    assert "## Entity Directory" in rep_data["markdown_report"]
    assert "## Timeline" in rep_data["markdown_report"]
    assert "## Relationships" in rep_data["markdown_report"]
    assert "## Limitations and Methodology" in rep_data["markdown_report"]
    assert "John Watson" in rep_data["markdown_report"]
    assert "Nexus Holdings" in rep_data["markdown_report"]
    assert "ec_men_doc_" not in rep_data["markdown_report"]
    assert rep_data["raw_json"]["evidence_items"]

    graph = temp_client.get(f"/api/v1/investigations/{inv_id}/graph").json()
    assert graph["edges"]
    edge = graph["edges"][0]
    assert edge["source_label"] in {"John Watson", "Nexus Holdings", "Apex Corp", "221B Baker St"}
    assert edge["supporting_claim_ids"]
    assert edge["supporting_evidence"]
    assert "John Watson" not in edge["source"]

    # 2. Markdown Download
    md_dl = temp_client.get(f"/api/v1/investigations/{inv_id}/report/download?format=markdown")
    assert md_dl.status_code == 200
    assert "text/markdown" in md_dl.headers["content-type"]
    assert "attachment;" in md_dl.headers["content-disposition"]
    assert f"sherlock_report_{inv_id}_" in md_dl.headers["content-disposition"]
    assert "# Sherlock AI Investigation Report" in md_dl.text

    # 3. JSON Download
    json_dl = temp_client.get(f"/api/v1/investigations/{inv_id}/report/download?format=json")
    assert json_dl.status_code == 200
    assert "application/json" in json_dl.headers["content-type"]
    assert "attachment;" in json_dl.headers["content-disposition"]
    assert json_dl.json()["investigation_id"] == inv_id

    # 4. HTML Download
    html_dl = temp_client.get(f"/api/v1/investigations/{inv_id}/report/download?format=html")
    assert html_dl.status_code == 200
    assert "text/html" in html_dl.headers["content-type"]
    assert "attachment;" in html_dl.headers["content-disposition"]
    assert "<!DOCTYPE html>" in html_dl.text
    assert "Print / Save as PDF" in html_dl.text
    assert inv_id in html_dl.text


def test_empty_investigation_report(temp_client):
    inv_id = "test_rep_empty"
    temp_client.post("/api/v1/investigations", json={"investigation_id": inv_id, "description": "Empty test"})
    rep_res = temp_client.get(f"/api/v1/investigations/{inv_id}/report")
    assert rep_res.status_code == 200
    data = rep_res.json()
    assert data["investigation_id"] == inv_id
    assert "No documents registered" in data["markdown_report"]


def test_delete_single_investigation_and_isolation(temp_client):
    # Create two investigations
    inv_a = "case_alpha"
    inv_b = "case_beta"
    temp_client.post("/api/v1/investigations", json={"investigation_id": inv_a, "description": "Case Alpha"})
    temp_client.post("/api/v1/investigations", json={"investigation_id": inv_b, "description": "Case Beta"})

    # Ingest document into Case Alpha
    temp_client.post(
        f"/api/v1/investigations/{inv_a}/documents",
        files={"file": ("alpha_doc.txt", io.BytesIO(b"John Watson founded Nexus Holdings in London."), "text/plain")},
        data={"auto_process": True},
    )

    # Ingest document into Case Beta
    temp_client.post(
        f"/api/v1/investigations/{inv_b}/documents",
        files={"file": ("beta_doc.txt", io.BytesIO(b"Alice Mercer founded Apex Corporation in Berlin."), "text/plain")},
        data={"auto_process": True},
    )
    temp_client.get(f"/api/v1/investigations/{inv_a}/report")

    # Check stats before deletion
    stats = temp_client.get("/api/v1/system/stats").json()
    assert stats["investigations"] >= 2
    assert stats["documents"] >= 2

    # Rejection if confirmation name does not match
    bad_del = temp_client.delete(f"/api/v1/investigations/{inv_a}?confirmed_name=wrong_name")
    assert bad_del.status_code == 400

    # Successful deletion of Case Alpha with correct confirmation
    good_del = temp_client.delete(f"/api/v1/investigations/{inv_a}?confirmed_name={inv_a}")
    assert good_del.status_code == 200
    del_data = good_del.json()
    assert del_data["status"] == "cleared"
    assert del_data["investigation_id"] == inv_a
    assert del_data["deleted_counts"]["investigations"] == 1
    assert del_data["deleted_counts"]["documents"] >= 1
    assert del_data["deleted_counts"]["entities"] >= 1
    assert del_data["deleted_counts"]["claims"] >= 1
    assert del_data["deleted_counts"]["evidence"] >= 1
    assert del_data["deleted_counts"]["relationships"] >= 1
    assert del_data["deleted_counts"]["reports"] >= 1

    # Verify Case Alpha is gone
    check_a = temp_client.get(f"/api/v1/investigations/{inv_a}")
    assert check_a.status_code == 404

    # Verify Case Beta is intact (Investigation Isolation)
    check_b = temp_client.get(f"/api/v1/investigations/{inv_b}")
    assert check_b.status_code == 200
    docs_b = temp_client.get(f"/api/v1/investigations/{inv_b}/documents").json()
    assert docs_b["total"] == 1


def test_clear_investigation_post_endpoint(temp_client):
    inv_id = "case_post_clear"
    temp_client.post("/api/v1/investigations", json={"investigation_id": inv_id, "description": "Post clear"})

    # Reject mismatch
    bad_req = temp_client.post(f"/api/v1/investigations/{inv_id}/clear", json={"confirmed_name": "different_id"})
    assert bad_req.status_code == 400

    # Accept match
    good_req = temp_client.post(f"/api/v1/investigations/{inv_id}/clear", json={"confirmed_name": inv_id})
    assert good_req.status_code == 200
    assert good_req.json()["status"] == "cleared"


def test_clear_all_data(temp_client):
    # Populate data
    for i in range(2):
        cid = f"clear_all_case_{i}"
        temp_client.post("/api/v1/investigations", json={"investigation_id": cid, "description": "Clear all test"})
        temp_client.post(
            f"/api/v1/investigations/{cid}/documents",
            files={"file": (f"doc_{i}.txt", io.BytesIO(f"Content for case {i}".encode()), "text/plain")},
            data={"auto_process": True},
        )

    # Rejection if confirmation phrase is wrong
    bad_clear = temp_client.post("/api/v1/system/clear-all", json={"confirmation_phrase": "delete please"})
    assert bad_clear.status_code == 400

    # Successful clear with exact phrase
    good_clear = temp_client.post("/api/v1/system/clear-all", json={"confirmation_phrase": "CLEAR ALL DATA"})
    assert good_clear.status_code == 200
    res = good_clear.json()
    assert res["status"] == "cleared"
    assert res["deleted_counts"]["investigations"] >= 2

    # Check stats are reset
    stats = temp_client.get("/api/v1/system/stats").json()
    assert stats["investigations"] == 0
    assert stats["documents"] == 0
    assert stats["entities"] == 0
    assert stats["evidence"] == 0
    assert stats["claims"] == 0
    assert stats["relationships"] == 0


def test_cross_document_resolution_threshold_validation(temp_client):
    inv_id = "test_threshold_bounds"
    temp_client.post("/api/v1/investigations", json={"investigation_id": inv_id, "description": "Threshold test"})

    # Out of range low
    res_low = temp_client.post(f"/api/v1/investigations/{inv_id}/cross-document-resolution?threshold=0.05")
    assert res_low.status_code == 400
    assert "out of allowed range" in res_low.json()["detail"]

    # Out of range high
    res_high = temp_client.post(f"/api/v1/investigations/{inv_id}/cross-document-resolution?threshold=1.5")
    assert res_high.status_code == 400
    assert "out of allowed range" in res_high.json()["detail"]

    # Valid threshold
    res_valid = temp_client.post(f"/api/v1/investigations/{inv_id}/cross-document-resolution?threshold=0.60")
    assert res_valid.status_code == 200
    assert "total_decisions" in res_valid.json()
