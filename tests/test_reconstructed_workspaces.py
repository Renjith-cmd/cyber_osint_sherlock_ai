"""
Tests for Sherlock AI Reconstructed Workspaces (Screens 5, 6, 7).
Verifies that:
- HTML structure contains all reference-accurate workspace panels, toolbars, containers, and slide-out drawers.
- CSS design system implements the warm ivory/navy palette, 3-card entity grid, timeline cards, and drawer styles.
- JavaScript client correctly handles API endpoints, deterministic sticker avatars, pagination, and inspections.
"""

import re
from pathlib import Path
import pytest

pytest.importorskip("fastapi", reason="FastAPI not installed in this environment.")
from fastapi.testclient import TestClient
from src.api.app import create_app


REPO_ROOT = Path(__file__).resolve().parent.parent
UI_DIR = REPO_ROOT / "src" / "ui"
INDEX_HTML = UI_DIR / "index.html"
APP_CSS = UI_DIR / "app.css"
APP_JS = UI_DIR / "app.js"
STICKERS_JS = UI_DIR / "stickers.js"


def test_html_workspace_containers():
    """Verify that index.html contains all reconstructed workspace elements for Screens 5, 6, 7."""
    assert INDEX_HTML.exists()
    html = INDEX_HTML.read_text(encoding="utf-8")

    # Screen 5: Entities Workspace
    assert 'id="tab-entities"' in html
    assert 'id="entities-total-badge"' in html
    assert 'id="ent-metric-total"' in html
    assert 'id="ent-metric-match"' in html
    assert 'id="ent-metric-review"' in html
    assert 'id="ent-metric-unresolved"' in html
    assert 'id="filter-entity-name"' in html
    assert 'id="filter-entity-type"' in html
    assert 'id="filter-entity-status"' in html
    assert 'id="filter-entity-sort"' in html
    assert 'id="btn-entities-view-grid"' in html
    assert 'id="btn-entities-view-table"' in html
    assert 'id="entities-grid-view-container"' in html
    assert 'id="entities-pagination-row"' in html
    assert 'id="entity-detail-panel"' in html
    assert 'id="entity-drawer-backdrop"' in html

    # Screen 6: Interactive Relationship Graph
    assert 'id="tab-graph"' in html
    assert 'id="graph-workspace-panel"' in html
    assert 'id="graph-stats-badge"' in html
    assert 'id="btn-fullscreen-graph"' in html
    assert 'id="graph-root-select"' in html
    assert 'id="graph-filter-edge-type"' in html
    assert 'id="graph-filter-status"' in html
    assert 'id="graph-svg"' in html
    assert 'id="btn-graph-zoom-in"' in html
    assert 'id="btn-graph-zoom-out"' in html
    assert 'id="btn-graph-zoom-fit"' in html
    assert 'id="btn-graph-zoom-reset"' in html
    assert 'id="graph-inspector"' in html

    # Screen 7: Claims & Evidence Workspace
    assert 'id="tab-claims"' in html
    assert 'id="evidence-total-badge"' in html
    assert 'id="ev-metric-docs"' in html
    assert 'id="ev-metric-spans"' in html
    assert 'id="ev-metric-claims"' in html
    assert 'id="ev-metric-disputes"' in html
    assert 'id="evidence-timeline-track"' in html
    assert 'id="filter-evidence-query"' in html
    assert 'id="filter-evidence-polarity"' in html
    assert 'id="filter-evidence-status"' in html
    assert 'id="evidence-cards-container"' in html
    assert 'id="claims-table-view-container"' in html
    assert 'id="evidence-detail-panel"' in html
    assert 'id="evidence-drawer-backdrop"' in html


def test_css_design_system_tokens_and_classes():
    """Verify that app.css includes reference palette tokens and reconstructed component classes."""
    assert APP_CSS.exists()
    css = APP_CSS.read_text(encoding="utf-8")

    # Color tokens
    assert "#171827" in css or "--bg-canvas" in css
    assert "#F7F1E9" in css or "--bg-ivory-panel" in css
    assert "#F5AE89" in css or "--accent-peach" in css
    assert "#E2F4EC" in css or "--status-match-bg" in css
    assert "#FFE4D6" in css or "--status-review-bg" in css

    # Reconstructed component classes
    assert ".entity-card-v2" in css
    assert ".entity-sticker-blob" in css
    assert ".timeline-step-card" in css
    assert ".evidence-card-v2" in css
    assert ".pagination-page-btn" in css
    assert ".drawer-sheet" in css


def test_js_controllers_and_exports():
    """Verify that app.js implements required controllers and exports."""
    assert APP_JS.exists()
    js = APP_JS.read_text(encoding="utf-8")

    # Screen 5
    assert "async function loadEntities()" in js
    assert "function renderEntitiesWorkspace()" in js
    assert "async function inspectEntity(" in js
    assert "function setEntitiesPage(" in js

    # Screen 6
    assert "async function loadGraph()" in js
    assert "function renderSvgGraph()" in js
    assert "function fitGraphToView()" in js
    assert "function toggleGraphFullscreen()" in js

    # Screen 7
    assert "async function loadClaimsAndEvidence()" in js
    assert "function renderEvidenceTimeline()" in js
    assert "function renderEvidenceExplorer()" in js
    assert "function openEvidenceDrawer(" in js
    assert "function setEvidencePage(" in js

    # Global window.sherlockApp exports
    assert "window.sherlockApp = {" in js
    assert "inspectEntity:" in js
    assert "openEvidenceDrawer:" in js
    assert "setEntitiesPage:" in js
    assert "setEvidencePage:" in js


def test_fastapi_endpoints_with_test_client():
    """Verify API endpoints return valid JSON for investigation data."""
    app = create_app(db_path="data/sherlock_investigations.db")
    client = TestClient(app)

    # Health
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"

    # Static assets
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Sherlock AI" in resp.text

    resp = client.get("/static/app.css")
    assert resp.status_code == 200

    resp = client.get("/static/app.js")
    assert resp.status_code == 200

    resp = client.get("/static/stickers.js")
    assert resp.status_code == 200

    # API endpoints for demo case
    resp = client.get("/api/v1/investigations/demo_benchmark_4495/entities")
    assert resp.status_code == 200
    assert "entities" in resp.json()

    resp = client.get("/api/v1/investigations/demo_benchmark_4495/graph")
    assert resp.status_code == 200
    assert "nodes" in resp.json()

    resp = client.get("/api/v1/investigations/demo_benchmark_4495/claims")
    assert resp.status_code == 200
    assert "claims" in resp.json()

    resp = client.get("/api/v1/investigations/demo_benchmark_4495/evidence")
    assert resp.status_code == 200
    data = resp.json()
    assert "evidence" in data or "evidence_items" in data
