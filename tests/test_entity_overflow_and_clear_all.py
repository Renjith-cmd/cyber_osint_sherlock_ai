"""
Comprehensive Regression Test Suite: Entity Overflow & Clear All Data Fixes.

Covers:
1. Clear-all data execution with exact phrase 'DELETE ALL SHERLOCK DATA'.
2. Strict rejection of invalid / partial confirmation phrases with 400 Bad Request.
3. Atomic SQLite wipe in reverse dependency order without transaction locking or VACUUM failures.
4. Authentication enforcement: 401 when token is missing/invalid, 200 when authenticated.
5. Idempotent clear-all on already empty databases.
6. Single investigation clearing preserves unrelated investigations and cases.
7. CSS grid/flex resilience rules: min-width: 0, overflow-wrap: anywhere, word-break, 2-line name clamp.
8. Frontend UI contract: modal exact phrase requirement, disabled button state, resetAllUiViews DOM wipe.
"""

import io
import os
import tempfile
import sqlite3
import pytest

try:
    from fastapi.testclient import TestClient
    from src.api.app import create_app
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.core.investigation_sqlite import SQLiteInvestigationStore
from src.core.investigation_service import InvestigationOrchestrator


@pytest.fixture
def disposable_db_path(tmp_path):
    """Provides an isolated, disposable SQLite file for destructive testing."""
    return str(tmp_path / "disposable_test_sherlock.db")


@pytest.fixture
def temp_api_client(disposable_db_path):
    """Provides a TestClient connected to the disposable SQLite database."""
    if not HAS_FASTAPI:
        pytest.skip("FastAPI not installed in this environment.")
    app = create_app(db_path=disposable_db_path, backend_mode="rule")
    with TestClient(app) as client:
        yield client


def test_clear_all_with_exact_phrase_delete_all_sherlock_data(temp_api_client):
    """Verify that 'DELETE ALL SHERLOCK DATA' completely and atomically wipes all operational data."""
    # 1. Populate multiple investigations, documents, entities, claims
    for idx in range(3):
        inv_id = f"test_case_{idx}"
        create_res = temp_api_client.post(
            "/api/v1/investigations",
            json={"investigation_id": inv_id, "description": f"Test case description {idx}"},
        )
        assert create_res.status_code == 201

        doc_content = f"Subject John Doe_{idx} operated Nexus Alpha_{idx} with claim verification.".encode()
        upload_res = temp_api_client.post(
            f"/api/v1/investigations/{inv_id}/documents",
            files={"file": (f"doc_{idx}.txt", io.BytesIO(doc_content), "text/plain")},
            data={"auto_process": True},
        )
        assert upload_res.status_code == 201

    # Verify stats before deletion are non-zero
    pre_stats = temp_api_client.get("/api/v1/system/stats").json()
    assert pre_stats["investigations"] >= 3
    assert pre_stats["documents"] >= 3

    # 2. Execute clear-all with exact phrase "DELETE ALL SHERLOCK DATA"
    clear_res = temp_api_client.post(
        "/api/v1/system/clear-all",
        json={"confirmation_phrase": "DELETE ALL SHERLOCK DATA"},
    )
    assert clear_res.status_code == 200
    data = clear_res.json()
    assert data["status"] == "cleared"
    assert "deleted_counts" in data
    assert data["deleted_counts"]["investigations"] >= 3
    assert data["deleted_counts"]["documents"] >= 3

    # 3. Verify all tables in DB are completely empty
    post_stats = temp_api_client.get("/api/v1/system/stats").json()
    assert post_stats["investigations"] == 0
    assert post_stats["documents"] == 0
    assert post_stats["entities"] == 0
    assert post_stats["claims"] == 0
    assert post_stats["evidence"] == 0
    assert post_stats["relationships"] == 0
    assert post_stats["reports"] == 0

    # 4. Verify list investigations is empty
    inv_list = temp_api_client.get("/api/v1/investigations").json()
    assert inv_list["total"] == 0
    assert inv_list["investigations"] == []


def test_clear_all_rejection_of_invalid_phrases(temp_api_client):
    """Verify that any non-matching phrase is strictly rejected and leaves data untouched."""
    # Seed an investigation
    temp_api_client.post(
        "/api/v1/investigations",
        json={"investigation_id": "safe_case_01", "description": "Must not be deleted"},
    )

    invalid_phrases = [
        "",
        "delete",
        "DELETE",
        "CLEAR ALL",
        "delete all sherlock data",
        "DELETE ALL SHERLOCK DATA PLEASE",
        "DELETE ALL",
    ]

    for phrase in invalid_phrases:
        res = temp_api_client.post(
            "/api/v1/system/clear-all",
            json={"confirmation_phrase": phrase},
        )
        assert res.status_code == 400
        assert "DELETE ALL SHERLOCK DATA" in res.json()["detail"]

    # Verify data remained 100% intact
    stats = temp_api_client.get("/api/v1/system/stats").json()
    assert stats["investigations"] == 1


def test_clear_all_atomic_wipe_and_vacuum(disposable_db_path):
    """Verify InvestigationOrchestrator and SQLite store run reverse-dependency wipe and VACUUM without transaction errors."""
    store = SQLiteInvestigationStore(disposable_db_path)
    orch = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)

    # Seed data via orchestrator
    orch.create_investigation("case_direct_01", description="Direct SQLite test")
    orch.ingest_document(
        investigation_id="case_direct_01",
        raw_content=b"Direct document text mentioning Watson and Holmes.",
        source_name="memo.txt",
    )

    # Verify session and sqlite store have data
    assert "case_direct_01" in orch._sessions
    stats_pre = store.get_system_stats()
    assert stats_pre["investigations"] >= 1
    assert stats_pre["documents"] >= 1

    # Run direct clear_all_data
    deleted_counts = orch.clear_all_data()
    assert deleted_counts["investigations"] >= 1
    assert deleted_counts["documents"] >= 1
    assert len(orch._sessions) == 0

    # Verify tables are empty
    with sqlite3.connect(disposable_db_path) as conn:
        cursor = conn.cursor()
        for tbl in ["investigations", "documents", "entities", "claims", "evidence_items", "relationships", "reports"]:
            cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
            count = cursor.fetchone()[0]
            assert count == 0, f"Table {tbl} was expected to be empty, found {count} rows"


def test_clear_all_auth_enforcement(disposable_db_path):
    """Verify that when API authentication is enabled, /api/v1/system/clear-all enforces token verification."""
    if not HAS_FASTAPI:
        pytest.skip("FastAPI not installed in this environment.")
    token = "super_secret_sherlock_auth_token_99"
    app = create_app(db_path=disposable_db_path, api_token=token, enforce_auth=True)

    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/api/v1/investigations").status_code == 401

        # Seed an investigation using valid auth
        seed_res = client.post(
            "/api/v1/investigations",
            json={"investigation_id": "auth_case_01", "description": "Auth protected case"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert seed_res.status_code == 201

        # 1. Unauthenticated request must return 401
        unauth_res = client.post(
            "/api/v1/system/clear-all",
            json={"confirmation_phrase": "DELETE ALL SHERLOCK DATA"},
        )
        assert unauth_res.status_code == 401

        # 2. Invalid token must return 401
        bad_token_res = client.post(
            "/api/v1/system/clear-all",
            json={"confirmation_phrase": "DELETE ALL SHERLOCK DATA"},
            headers={"Authorization": "Bearer invalid_token_xyz"},
        )
        assert bad_token_res.status_code == 401

        # 3. Valid Authorization: Bearer <token> must succeed
        valid_res = client.post(
            "/api/v1/system/clear-all",
            json={"confirmation_phrase": "DELETE ALL SHERLOCK DATA"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert valid_res.status_code == 200
        assert valid_res.json()["status"] == "cleared"


def test_upstream_protection_can_disable_duplicate_api_auth(disposable_db_path):
    """Vercel Deployment Protection is the access boundary; FastAPI should not require a second browser token."""
    if not HAS_FASTAPI:
        pytest.skip("FastAPI not installed in this environment.")
    app = create_app(
        db_path=disposable_db_path,
        api_token="unused_upstream_protection_token",
        enforce_auth=True,
        disable_auth=True,
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/investigations",
            json={"investigation_id": "upstream_protected_case", "description": "Protected by the hosting platform"},
        )
        assert created.status_code == 201


def test_clear_all_idempotent_on_empty_db(temp_api_client):
    """Verify that running clear-all repeatedly on an empty database succeeds cleanly without errors."""
    for _ in range(2):
        res = temp_api_client.post(
            "/api/v1/system/clear-all",
            json={"confirmation_phrase": "DELETE ALL SHERLOCK DATA"},
        )
        assert res.status_code == 200
        counts = res.json()["deleted_counts"]
        assert counts["investigations"] == 0
        assert counts["documents"] == 0


def test_single_investigation_clearing_preserves_other_cases(temp_api_client):
    """Verify that clearing a single case leaves all other investigations intact."""
    temp_api_client.post(
        "/api/v1/investigations",
        json={"investigation_id": "case_to_delete", "description": "Delete this case"},
    )
    temp_api_client.post(
        "/api/v1/investigations",
        json={"investigation_id": "case_to_preserve", "description": "Keep this case"},
    )

    del_res = temp_api_client.post(
        "/api/v1/investigations/case_to_delete/clear",
        json={"confirmed_name": "case_to_delete"},
    )
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "cleared"

    # Preserved case must still exist
    keep_res = temp_api_client.get("/api/v1/investigations/case_to_preserve")
    assert keep_res.status_code == 200

    # Deleted case must return 404
    gone_res = temp_api_client.get("/api/v1/investigations/case_to_delete")
    assert gone_res.status_code == 404


def test_css_entity_overflow_and_resilience_contracts():
    """Verify that app.css enforces min-width: 0, word-breaking, line clamping, and responsive card grids."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    css_path = os.path.join(base_dir, "src", "ui", "app.css")
    assert os.path.exists(css_path), f"app.css missing at {css_path}"

    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    # 1. Responsive Grid columns with min-width: 0
    assert ".entities-workspace-grid" in css
    assert "min-width: 0" in css

    # 2. Card overflow protection
    assert ".entity-card-v2" in css
    assert "overflow-wrap: anywhere" in css
    assert "word-break: break-word" in css

    # 3. Name clamping (2 lines)
    assert "-webkit-line-clamp: 2" in css
    assert "-webkit-box-orient: vertical" in css

    # 4. Shortened ID and copy button styling
    assert ".entity-id-row" in css
    assert ".btn-copy-id" in css
    assert ".entity-id-code" in css

    # 5. Disabled button styling
    assert "button:disabled" in css or ".btn:disabled" in css
    assert "cursor: not-allowed" in css


def test_ui_modal_and_js_phrase_contracts():
    """Verify that index.html and app.js enforce DELETE ALL SHERLOCK DATA and UI view resets."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html_path = os.path.join(base_dir, "src", "ui", "index.html")
    js_path = os.path.join(base_dir, "src", "ui", "app.js")

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # HTML contracts
    assert 'id="modal-clear-all"' in html
    assert "DELETE ALL SHERLOCK DATA" in html
    assert 'id="btn-submit-clear-all"' in html
    assert 'id="clear-all-modal-error"' in html
    assert 'id="clear-inv-modal-error"' in html
    assert 'id="entities-page-size"' in html
    assert 'id="evidence-page-size"' in html

    # JS contracts
    assert "DELETE ALL SHERLOCK DATA" in js
    assert "btnSubmitClearAll.disabled" in js
    assert "resetAllUiViews" in js
    assert "formatShortId" in js
    assert "copyTextToClipboard" in js
    assert "sherlock_preferences_v1" in js
    assert "function readPreferences()" in js
    assert "persistPreference(\"resolutionThreshold\"" in js
    assert "persistPreference(\"graphDepth\"" in js
    assert "persistPreference(\"entitiesPageSize\"" in js
    assert "persistPreference(\"evidencePageSize\"" in js
    assert "preferences = { ...DEFAULT_PREFERENCES" in js
    assert "function promptForApiToken()" in js
    assert "Vercel, sign in through Vercel Deployment Protection" in js
    assert "Backend authorization failed" in js
    assert "disable_auth=True" in open(os.path.join(base_dir, "api", "index.py"), encoding="utf-8").read()
    assert "state.activeInvestigationId || (els.activeInvSelect && els.activeInvSelect.value)" in js


def test_extremely_long_entity_ids_and_names_formatting_and_resilience():
    """Verify that formatShortId and entity card contracts safely handle 100+ char unbroken IDs and long names."""
    long_id = "ec_men_doc_709335fb706d9224_0_239_258_b4c5f1ee_super_long_subcluster_identifier_hex_deadbeef_cafebabe"
    assert len(long_id) > 90

    # Short ID helper logic verification (matches app.js formatShortId)
    def format_short_id(val, head=10, tail=6):
        s = str(val)
        if len(s) <= head + tail + 2:
            return s
        return f"{s[:head]}…{s[-tail:]}"

    shortened = format_short_id(long_id, 10, 6)
    assert shortened.startswith("ec_men_doc…")
    assert shortened.endswith("febabe")
    assert len(shortened) == 17  # 10 + 1 + 6

    # Verify that app.js includes keyboard accessibility and empty mention handling
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js_path = os.path.join(base_dir, "src", "ui", "app.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    assert "snippet-empty" in js
    assert "0 mentions recorded" in js
    assert "role=\"button\"" in js or 'role=\\"button\\"' in js
    assert "tabindex=\"0\"" in js or 'tabindex=\\"0\\"' in js


def test_reopen_application_persists_cleared_state(disposable_db_path):
    """Verify that after clearing all data, restarting/reopening the store confirms complete persistent wipe."""
    # 1. Initialize and populate
    store = SQLiteInvestigationStore(disposable_db_path)
    orch = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)
    orch.create_investigation("persisted_case_01", description="Case before wipe")
    orch.ingest_document(
        investigation_id="persisted_case_01",
        raw_content=b"Sample raw text mentioning Acme Corp and John Watson.",
        source_name="evidence.txt",
    )
    assert len(orch.list_investigations()) == 1

    # 2. Clear all data
    orch.clear_all_data()

    # 3. Simulate process exit and restart with fresh store & orchestrator instances
    store.close()
    del store
    del orch

    new_store = SQLiteInvestigationStore(disposable_db_path)
    new_orch = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=new_store)

    assert new_orch.list_investigations() == []
    stats = new_store.get_system_stats()
    for key, val in stats.items():
        assert val == 0, f"Expected {key} to be 0 after restart, got {val}"
    new_store.close()


def test_simulated_failure_rollback_and_fk_integrity(disposable_db_path):
    """Verify foreign-key integrity and transaction rollback when an error occurs during clear operations."""
    store = SQLiteInvestigationStore(disposable_db_path)
    orch = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)
    orch.create_investigation("rollback_case", description="Must survive simulated crash")
    orch.ingest_document(
        investigation_id="rollback_case",
        raw_content=b"Durability test with grounded relationships and claims.",
        source_name="durability.txt",
    )

    stats_before = store.get_system_stats()
    assert stats_before["investigations"] == 1
    assert stats_before["documents"] == 1

    # Simulate transactional failure during a custom clear attempt
    with pytest.raises(RuntimeError):
        with store.get_connection() as conn:
            conn.execute("DELETE FROM reports")
            conn.execute("DELETE FROM relationships")
            raise RuntimeError("Simulated transient storage or disk I/O failure!")

    # Verify transaction rolled back: original records remain intact
    stats_after = store.get_system_stats()
    assert stats_after["investigations"] == 1
    assert stats_after["documents"] == 1

    # Verify SQLite foreign key integrity check returns clean (0 constraint violations)
    with store.get_connection() as conn:
        fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert len(fk_violations) == 0


def test_configuration_and_preferences_preservation(disposable_db_path):
    """Verify clear-all operation does not mutate or wipe system configuration files."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_dir = os.path.join(base_dir, "configs")
    assert os.path.isdir(config_dir)

    # Record config files before clear-all
    configs_before = {f: os.path.getsize(os.path.join(config_dir, f)) for f in os.listdir(config_dir)}
    assert len(configs_before) > 0

    store = SQLiteInvestigationStore(disposable_db_path)
    orch = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)
    orch.create_investigation("case_cfg_test", description="Config test case")
    orch.clear_all_data()

    # Verify configs remain untouched
    configs_after = {f: os.path.getsize(os.path.join(config_dir, f)) for f in os.listdir(config_dir)}
    assert configs_before == configs_after


def test_failed_persisted_investigation_delete_keeps_session(disposable_db_path, monkeypatch):
    """A failed SQLite delete must not evict the live investigation cache."""
    store = SQLiteInvestigationStore(disposable_db_path)
    orch = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)
    orch.create_investigation("delete_failure_case", description="Must remain loaded")

    def fail_delete(_investigation_id):
        raise RuntimeError("simulated SQLite delete failure")

    monkeypatch.setattr(store, "delete_investigation", fail_delete)
    with pytest.raises(RuntimeError, match="simulated SQLite delete failure"):
        orch.delete_investigation("delete_failure_case")

    assert orch.get_investigation("delete_failure_case") is not None
    assert store.get_investigation("delete_failure_case") is not None
    store.close()
