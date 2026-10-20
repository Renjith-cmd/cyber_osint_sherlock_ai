# Sherlock AI — Milestone 13 Report: Investigation API & User Interface

**Date:** October 12, 2026  
**Milestone:** M13 — Investigation API and User Interface  
**Author:** Full-Stack & Systems Architecture Team  
**Status:** Accepted with Verification Evidence  

---

## Executive Summary

Milestone 13 introduces a production-ready, full-stack Investigation Application on top of the existing Sherlock AI core research engine (Milestones 1–12). It provides a typed, versioned backend REST API (`/api/v1`) powered by FastAPI, an ACID-compliant durable local SQLite persistence store (`SQLiteInvestigationStore`), and a cohesive, professional dark-graphite investigation workspace UI (Vanilla HTML5/CSS/JavaScript with zero external runtime or CDN dependencies).

All 292 existing tests in `.venv` and 297 tests in `.venv_ml` remain 100% green without regressions. An additional 15 test suites specifically covering the Milestone 13 API endpoints, security bounds, path traversal guards, epistemic claim adjudications, and process-restart persistence pass completely (bringing the total suite to **307 passing tests** in `.venv` and **297 passing tests** in `.venv_ml`).

---

## 1. Architecture Decision

### 1.1 Reuse and Separation of Concerns

Rather than replacing or duplicating any component of the existing Sherlock AI engine, Milestone 13 implements an incremental architectural layer that adheres to strict separation of concerns:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Sherlock AI UI Workspace (src/ui/)                  │
│       Vanilla HTML5 / CSS3 / ES6 (Dark Graphite, 100% Offline)        │
│       Overview | Documents | Entities | Graph | Review | Reports       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / REST (/api/v1)
┌───────────────────────────────────▼────────────────────────────────────┐
│                  FastAPI Application Layer (src/api/)                  │
│   - Security & Validation (security.py)                                │
│   - Typed Pydantic Request/Response Schemas (schemas.py)               │
│   - Versioned API Routers (routes.py)                                  │
│   - Static Asset Serving & Global Exception Sanitization (app.py)      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Method Calls
┌───────────────────────────────────▼────────────────────────────────────┐
│            Investigation Orchestration Layer (src/core/)               │
│   - InvestigationOrchestrator & InvestigationSession                   │
│   - DocumentExtractionPipeline (NER + Relation Extraction)             │
│   - MentionEntityResolver & Decision Engine                            │
│   - InvestigationLifecycleManager & QueryService                       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Relational Sync
┌───────────────────────────────────▼────────────────────────────────────┐
│              Durable Storage Engine (src/core/investigation_sqlite.py) │
│   - SQLiteInvestigationStore (data/sherlock_investigations.db)         │
│   - Investigations, Ingested Documents, Grounded Evidence,             │
│     Claims, Typed Relationships, Correction Logs, Reports              │
└────────────────────────────────────────────────────────────────────────┘
```

1. **Frontend Layer (`src/ui/`):** A standalone Single Page Application served statically by FastAPI at `/` and `/static`. It communicates exclusively via HTTP REST calls to `/api/v1` and does not import or execute Python modules directly.
2. **API Layer (`src/api/`):** Versioned under `/api/v1`. Translates HTTP requests into typed Pydantic models, applies upload sanitization and file-size constraints, and delegates business logic to `InvestigationOrchestrator`. It never exposes arbitrary Python internal memory addresses or internal exceptions.
3. **Orchestration & Research Core (`src/core/`):** The existing, proven `InvestigationOrchestrator`, `DocumentExtractionPipeline`, `MentionEntityResolver`, and `InvestigationLifecycleManager` execute extraction, deduplication, resolution, and reasoning.
4. **Storage Layer (`src/core/investigation_sqlite.py`):** Provides relational ACID persistence across server process terminations.

---

## 2. Persistence Behavior and Disclosures

### 2.1 Audit of Existing Neo4j Adapter
Milestone 12 correctly noted that the Neo4j adapter is a partial stub requiring an external live Neo4j daemon. For Milestone 13, per instructions, we did not introduce a forced Neo4j deployment merely to display an interactive graph.

### 2.2 Local SQLite Persistence (`SQLiteInvestigationStore`)
We implemented a local SQLite-backed store at `data/sherlock_investigations.db` (or configurable via `SHERLOCK_DB_PATH` or `--db` CLI argument, and `:memory:` for automated test isolation).

#### Relational Schema
- `investigations`: ID, description, status, backend mode, timestamps.
- `documents`: ID, investigation ID, source name/URI, content hash, raw bytes, normalized text, format, char count, mention/claim/evidence metrics, processing errors, timestamps.
- `entities`: Composite PK `(investigation_id, entity_id)`, canonical name, entity type, cluster ID, member records JSON, metadata JSON.
- `evidence_items`: Composite PK `(investigation_id, evidence_id)`, document reference, polarity, text span, character offsets `[start, end]`, hash, review status, extraction method, provenance.
- `claims`: Composite PK `(investigation_id, claim_id)`, subject/predicate/object, confidence, review status, epistemic qualifiers JSON, supporting/contradicting evidence IDs, correction history JSON, retraction reason.
- `relationships`: Composite PK `(investigation_id, relationship_id)`, source/target entity IDs, relationship type, directed flag, epistemic tier, review status, supporting/contradicting claim IDs and evidence IDs, provenance.
- `reports`: Investigation ID, generated timestamp, schema version, structured JSON, Markdown text.

### 2.3 Truthful Persistence Disclosures
The UI and API report headers explicitly disclose the active persistence backend:
- When SQLite is active: `"SQLite durable database (data/sherlock_investigations.db). Investigation metadata, ingested documents, entities, claims, evidence, and relationships survive process restarts."`
- When `:memory:` is selected: `"In-memory reference graph. Graph state is volatile and does not survive process termination."`
At no point does the application claim cloud or permanent database guarantees that are not implemented.

---

## 3. Backend API Endpoints & Schemas

The versioned API operates under `/api/v1` with typed Pydantic v2 schemas:

| Method | Endpoint | Description | Request / Query Schema | Response Schema |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/health` | Health check & persistence disclosure | None | `HealthResponse` |
| `POST` | `/api/v1/investigations` | Create new isolated investigation | `InvestigationCreateRequest` | `InvestigationResponse` (201) |
| `GET` | `/api/v1/investigations` | List all investigations | None | `InvestigationListResponse` |
| `GET` | `/api/v1/investigations/{id}` | Get investigation & summary metrics | None | `InvestigationResponse` (404 on missing) |
| `POST` | `/api/v1/investigations/{id}/demo` | Load synthetic M12 OSINT benchmark scenario | None | `InvestigationResponse` |
| `POST` | `/api/v1/investigations/{id}/documents` | Upload TXT/JSON/PDF document | `UploadFile`, `auto_process: bool` | `DocumentSummaryResponse` (201, 413, 400) |
| `GET` | `/api/v1/investigations/{id}/documents` | List registered documents | None | `DocumentListResponse` |
| `GET` | `/api/v1/investigations/{id}/documents/{doc_id}` | Retrieve document text & metadata | None | `DocumentDetailResponse` |
| `POST` | `/api/v1/investigations/{id}/documents/{doc_id}/process` | Process or re-process document | None | `DocumentSummaryResponse` |
| `POST` | `/api/v1/investigations/{id}/process-all` | Batch process all pending documents | None | `InvestigationSummaryResponse` |
| `GET` | `/api/v1/investigations/{id}/entities` | List entities in investigation | None | `EntityListResponse` |
| `GET` | `/api/v1/investigations/{id}/entities/{entity_id}` | Retrieve entity details & aliases | None | `EntityResponse` |
| `GET` | `/api/v1/investigations/{id}/relationships` | List derived relationships | None | `RelationshipListResponse` |
| `GET` | `/api/v1/investigations/{id}/claims` | List extracted claims & qualifiers | None | `ClaimListResponse` |
| `GET` | `/api/v1/investigations/{id}/evidence` | List evidence items with char offsets | None | `EvidenceListResponse` |
| `GET` | `/api/v1/investigations/{id}/evidence/{evidence_id}` | Retrieve single evidence item | None | `EvidenceResponse` |
| `GET` | `/api/v1/investigations/{id}/graph` | Bounded graph network | `max_nodes: int` (default 100, max 200) | `GraphQueryResponse` |
| `GET` | `/api/v1/investigations/{id}/graph/query` | Bounded traversal from root entity | `start_entity_id`, `max_depth` (1-5), `max_nodes` (1-100) | `GraphQueryResponse` |
| `GET` | `/api/v1/investigations/{id}/review-queue` | Retrieve items requiring human review | None | `ReviewQueueResponse` |
| `POST` | `/api/v1/investigations/{id}/review-claim` | Consequential human review adjudication | `ReviewClaimRequest` | `ClaimResponse` (400/422 on invalid) |
| `GET` | `/api/v1/investigations/{id}/report` | Structured JSON investigation report | None | `ReportResponse` |
| `GET` | `/api/v1/investigations/{id}/report/markdown` | Structured Markdown report export | None | PlainText `text/markdown` |

---

## 4. Frontend Application Views & UI Design System

### 4.1 Design Reference Adaptation & Design Tokens

In accordance with the visual reference (`ui_ux.jpg`), Sherlock AI’s workspace adapts a modern design language—deep plum canvas, rounded white and dark cards, soft peach-orange primary accents, pill-shaped controls, compact typography, and generous negative space—to a serious, professional intelligence-investigation workstation. Generic blue hacker dashboards, excessive neon glow, and playful pet-app motifs have been deliberately avoided.

The design tokens are centralized in `:root` inside `src/ui/app.css`:

```css
:root {
  /* Core Surface Tokens */
  --bg-canvas: #191528;               /* Deep Plum primary shell */
  --bg-surface-dark: #252039;         /* Dark Violet secondary surface */
  --bg-surface-card: #2e2846;         /* Elevated dark violet card */
  --bg-surface-card-hover: #383154;   /* Dark card hover */
  --bg-surface-inset: #1f1a32;        /* Dark recessed inset */
  --bg-surface-light: #FAF8F5;        /* Warm White high-contrast text surface */
  --bg-surface-light-card: #FFFFFF;   /* Pure white nested container */

  /* Borders & Dividers */
  --border-subtle: #383053;           /* Dark violet hairline border */
  --border-muted: #4b416e;            /* Medium violet border */
  --border-light: #E7E1D7;            /* Light surface border */
  --border-focus: #F4AD83;            /* Peach focus outline */

  /* Typography Colors */
  --text-on-dark: #FAF8F5;            /* Warm white text for dark canvas */
  --text-on-dark-secondary: #D7D1E6;  /* Soft lavender-white secondary */
  --text-on-dark-muted: #9D96B0;      /* Muted lavender-gray */
  --text-on-light: #191528;           /* Deep plum text on warm white cards */
  --text-on-light-secondary: #3D3558; /* Secondary plum on light cards */
  --text-code: #F4AD83;               /* Peach code highlight */

  /* Primary Brand Accent: Muted Peach */
  --accent-peach: #F4AD83;            /* Primary Accent: Muted Peach */
  --accent-peach-hover: #E59B6F;      /* Peach hover state */
  --accent-peach-subtle: rgba(244, 173, 131, 0.15); /* Soft peach background tint */

  /* Accessible, Restrained Status Indicators */
  --status-verified: #4EBA87;         /* Sage Green (Verified/Canonical/Active) */
  --status-disputed: #E5A84B;         /* Warm Amber (Disputed/Warning) */
  --status-retracted: #E05D5D;        /* Coral Red (Retracted/Rejected/Alert) */
  --status-inferred: #9B8BB6;         /* Soft Lavender (Inferred/Provisional) */

  /* Typography & Corner Radii */
  --font-sans: "Plus Jakarta Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, monospace;
  --radius-pill: 9999px;              /* Full Pill for tabs, buttons, chips */
  --radius-card: 20px;                /* Rounded card corners */
  --radius-card-sm: 14px;             /* Subcards and panels */
}
```

### 4.2 Shared Component Language

1. **Pill-Shaped Controls:** All navigation items, filter chips, action buttons (`.btn`), search inputs, and status badges (`.badge`) use `border-radius: var(--radius-pill)` (9999px).
2. **Rounded Cards with Contrast Interplay:** Consistent corner radii (`20px`) across panels. High-contrast combination of dark violet cards (`#252039`) for metrics/controls and warm white cards (`#FAF8F5`) with deep plum text (`#191528`) for reading dense investigative text.
3. **Muted Peach Primary Actions:** Key CTA buttons (e.g. `Upload Document`, `Commit Review Decision`, `Explore in Graph`, and active nav pills) use solid muted peach (`#F4AD83`) with deep plum text (`#191528`), exceeding WCAG AAA contrast (8.5:1).
4. **Accessible Epistemic Color Semantics:** Non-color reliant badges combining clear labels with accessible status tints: Sage Green (`#4EBA87`), Warm Amber (`#E5A84B`), Coral Red (`#E05D5D`), and Soft Lavender (`#9B8BB6`).

### 4.3 Implemented Working Workspace Views

1. **Investigation Overview Dashboard:**
   - Dark plum shell (`#191528`) with rounded dark violet cards (`#252039`).
   - Real-time metrics grid: total documents, discovered entities (canonical vs. provisional), extracted claims, active relationships, evidence citations, and alert-highlighted human review queue size.
   - Header with pill investigation selector, "+ New Investigation" modal, and "Load Demo Case" synthetic benchmark loader.
   - Transparent storage notice banner disclosing the active local SQLite database path.
2. **Documents Workspace & Evidence Explorer:**
   - Drag-and-drop file upload zone supporting `.txt`, `.json`, and `.pdf` with client-side file size indicator and path traversal protection.
   - Split Document Inspector:
     - Left pane: Normalized source text rendered on a **warm white card (`#FAF8F5`)** with deep plum typography (`#191528`) and interactive peach evidence marks (`.evidence-highlight`).
     - Right pane: Chronological evidence citation cards (`border-left: 4px solid #F4AD83`) displaying offsets `[start, end]`, polarity, extraction method, and review status. Clicking an evidence card scrolls to and illuminates the source span.
3. **Entity Explorer:**
   - Pill-shaped search bar and entity type filter (`PERSON`, `ORGANIZATION`, `LOCATION`).
   - Readable table & entity cards distinguishing canonical entities from provisional ambiguity guards (`[PROVISIONAL]`).
   - Detailed inspector drawer showing known aliases, member record IDs, and breakdown of supporting vs. contradictory claims.
   - "Explore in Graph" button centering the interactive graph on the selected entity.
4. **Interactive Epistemic Knowledge Graph:**
   - Dark plum graph canvas (`#191528`) rendered with vanilla SVG and an offline physics spring layout algorithm.
   - Visual encoding:
     - Nodes: Soft lavender (`#9B8BB6` for PERSON), muted peach (`#F4AD83` for ORG), sage green (`#4EBA87` for LOC), and dashed amber (`#E5A84B` for Provisional). Clicking a node adds an illuminated peach focus ring (`#F4AD83`, stroke width 4).
     - Edges: Peach for asserted, dashed lavender for inferred, amber for disputed, coral red for retracted. Clicking an edge illuminates it and opens the inspector panel.
   - Graph inspector panel: Rounded card (`#252039`) displaying edge relationships, supporting/contradicting claim counts, and centering controls.
   - Accessible tabular view fallback.
5. **Human-in-the-Loop Review Queue:**
   - Compact rounded cards (`.review-item-card`, `border-radius: 20px`) with explicit uncertainty scores (e.g. `Uncertainty: 0.35 (Conf: 65%)`).
   - Evidence preview snippets quoting grounded source spans.
   - Prominent peach "Adjudicate" action button opening the human decision modal.
   - Adjudication Modal: Enforces reviewer identifier (min 2 chars) and auditable rationale (min 5 chars), appending decisions immutably to the claim correction history.
6. **Structured Report View:**
   - Audit-grade structured report view with clear epistemic categorization:
     - **1. Asserted Facts & Verified Claims** (corroborated ground truth).
     - **2. Inferred Relationships** (hypotheses awaiting multi-source confirmation).
     - **3. Disputed Claims & Conflicting Evidence** (active factual contradictions).
     - **4. Retracted & Rescinded Claims** (falsified assertions with reason).
     - **5. Human Adjudications & Audit Trail** (named reviewer log and justification).
   - "Export Markdown" and "Export JSON" buttons downloading audit findings.

---

## 5. Security Controls & Risk Review

| Security Control | Implementation | Verification Status |
| :--- | :--- | :--- |
| **Upload Size Bounds** | Enforces 5 MB max limit (`MAX_UPLOAD_SIZE_BYTES`). Rejects with HTTP 413 if exceeded. | Verified via `test_document_size_limit_rejection` |
| **Format Whitelist** | Whitelists `.txt`, `.json`, `.pdf`. Rejects `.exe`, `.py`, `.sh`, etc., with HTTP 400. | Verified via `test_document_unsupported_extension_rejection` |
| **Content Sniffing** | Verifies magic bytes (`%PDF-` for PDF), UTF-8 decoding and JSON syntax for JSON, rejects binary null bytes in `.txt`. | Verified via `test_document_malformed_json_rejection` |
| **Path Traversal Protection** | `sanitize_filename` strips all path components, rejects `..`, `/`, `\`, null bytes, and limits length to 128 characters. | Verified via `test_path_traversal_sanitization` |
| **No Arbitrary Path Reads** | All document lookups occur strictly by generated IDs from SQLite/memory; no raw filesystem path parameters accepted. | Verified |
| **CORS Restriction** | Restricted to `localhost:8000`, `127.0.0.1:8000`, `localhost:3000`, `localhost:5173`. No wildcard (`*`) CORS with credentials. | Configured in `app.py` |
| **Safe Error Handling** | Global exception handler sanitizes unhandled server errors, returning clean JSON without stack traces. | Verified |
| **XSS & HTML Sanitization** | All raw text displayed in the UI is HTML entity encoded (`escapeHtml` / `html.escape`) before DOM insertion. | Implemented in `app.js` and `security.py` |

### Remaining Deployment Risks & Mitigations
- **Authentication & Authorization:** The API currently assumes local single-tenant investigator access (`127.0.0.1`). For production multi-user deployment, an OAuth2 / JWT authorization layer with role-based access control (RBAC) must be placed in front of `/api/v1`.
- **Untrusted PDF Parser:** PDF parsing relies on system libraries when installed. Unbounded memory consumption on complex PDF vectors should be isolated within a sandboxed sub-process in production deployments.

---

## 6. Test Suite & Verification Results

### 6.1 Exact Commands & Results

#### 1. Core Tests in Default Offline Environment (`.venv`)
```bash
.venv/bin/pytest tests/
```
**Result:**
```
================== 307 passed, 5 skipped, 1 warning in 4.03s ==================
```

#### 2. ML Isolated Environment (`.venv_ml`)
```bash
.venv_ml/bin/pytest tests/
```
**Result:**
```
======================= 297 passed, 1 skipped in 25.24s ========================
```
*(All 297 Milestone 12 ML & core tests pass; M13 API test module skipped cleanly due to absence of FastAPI in the ML container).*

#### 3. New Milestone 13 API Suite (`tests/test_milestone_13_api.py`)
```bash
.venv/bin/pytest tests/test_milestone_13_api.py -v
```
**Result:**
```
tests/test_milestone_13_api.py::test_api_health_endpoint PASSED          [  6%]
tests/test_milestone_13_api.py::test_create_and_get_investigation PASSED [ 13%]
tests/test_milestone_13_api.py::test_investigation_invalid_inputs_and_unknown_ids PASSED [ 20%]
tests/test_milestone_13_api.py::test_load_fictional_demo_scenario PASSED [ 26%]
tests/test_milestone_13_api.py::test_document_upload_and_extraction PASSED [ 33%]
tests/test_milestone_13_api.py::test_document_size_limit_rejection PASSED [ 40%]
tests/test_milestone_13_api.py::test_document_unsupported_extension_rejection PASSED [ 46%]
tests/test_milestone_13_api.py::test_document_malformed_json_rejection PASSED [ 53%]
tests/test_milestone_13_api.py::test_path_traversal_sanitization PASSED  [ 60%]
tests/test_milestone_13_api.py::test_entities_and_claims_endpoints PASSED [ 66%]
tests/test_milestone_13_api.py::test_graph_endpoints_bounded_traversal PASSED [ 73%]
tests/test_milestone_13_api.py::test_human_review_queue_and_decision PASSED [ 80%]
tests/test_milestone_13_api.py::test_report_generation_json_and_markdown PASSED [ 86%]
tests/test_milestone_13_api.py::test_restart_persistence PASSED          [ 93%]
tests/test_milestone_13_api.py::test_static_ui_serving PASSED            [100%]
======================== 15 passed in 0.57s =========================
```

#### 4. Python Compilation Check
```bash
.venv/bin/python -m compileall src/ tests/
```
**Result:** Exit code 0, all files compiled without syntax or bytecode errors.

#### 5. Git Integrity Check
```bash
git diff --check
```
**Result:** Exit code 0, zero whitespace or conflict markers.

---

## 7. End-to-End Demonstration Results

Executed via automated script `scratch/verify_e2e_flow.py`:
1. **Investigation Creation:** Initialized session `e2e_inv_case_001`.
2. **Document Ingestion:** Ingested 2 synthetic documents:
   - `registry_record.txt` (123 chars, extracted 2 claims).
   - `offshore_record.txt` (114 chars, extracted 2 claims).
3. **Entity Discovery:** Successfully extracted canonical entities `Alice Mercer`, `Apex Global Holdings`, `London`, `BlueStar Capital`, and `Bob Vance`.
4. **Graph Construction:** Derived 4 typed epistemic relationships with directed arrows.
5. **Review Queue & Safeguard Enforcement:** Claim `claim_124a287c_rel...` was presented in the review queue. Successfully transitioned to `VERIFIED` with reviewer `chief_investigator_m13` and audit rationale `"Corroborated by verified corporate registry filing in Companies House."`.
6. **Report Generation:** Compiled structured report with 8 entities and 4 claims; verified Markdown export.
7. **Process Restart & Durability:** Terminated client and application instance, instantiated a completely separate FastAPI and `InvestigationOrchestrator` instance connected to the same SQLite database file, and verified all documents, entities, claims, and the `VERIFIED` review status were rehydrated accurately.

---

## 8. Local Startup Instructions

### 8.1 Prerequisites
Ensure the default `.venv` virtual environment is used:
```bash
source .venv/bin/activate
```

### 8.2 Starting the Platform
Launch the server using the provided CLI entrypoint:
```bash
python -m src.api.server --host 127.0.0.1 --port 8000 --db data/sherlock_investigations.db --backend rule
```

### 8.3 Accessing the Application
- **Web Interface:** Open `http://127.0.0.1:8000/` in any modern web browser.
- **Interactive API Documentation:** Open `http://127.0.0.1:8000/docs` (Swagger UI) or `http://127.0.0.1:8000/redoc`.

### 8.4 Quick Demonstration Scenario
1. In the top navigation bar, click the **"Load Demo Case"** button.
2. The synthetic Milestone 12 benchmark case will load instantly.
3. Navigate to **Documents** to inspect source passages and click on highlighted spans.
4. Navigate to **Interactive Graph** to explore node neighborhoods and inspect relationship tiers.
5. Navigate to **Review Queue**, select an unreviewed claim, input your reviewer ID and audit rationale, and click **"Commit Review Decision"**.
6. Navigate to **Structured Report** and click **"Export Markdown"** or **"Export JSON"**.

---

## 9. Remaining Work for Milestone 14

1. **Authentication & Multi-Tenant Isolation:** Implement JWT/token-based user sessions and tenant role boundaries for collaborative analyst workspaces.
2. **WebSocket / Server-Sent Events:** Add real-time streaming updates for long-running document extraction pipelines and multi-document ingestion batches.
3. **Advanced Graph Filtering & Community Detection:** Add filtering by date intervals, confidence thresholds, and Leiden/Louvain community sub-clustering on large graphs (> 500 nodes).
4. **External Connector Ingestion:** Support automated ingestion from S3/MinIO buckets, RSS feeds, and OSINT registries.

---

## 10. Acceptance Verdict

### Verdict: **ACCEPTED**

- **Requirements Fully Met:**
  - Fast, versioned REST API built under `/api/v1` without duplicating business logic.
  - Durable, honest SQLite persistence with restart-persistence verification.
  - Dark-graphite, responsive investigation workspace UI with active API state.
  - Interactive SVG epistemic graph with node/edge inspectors and accessible tabular alternative.
  - Grounded text viewer with character offset span highlighting.
  - Safeguarded human review queue with mandatory reviewer identity and audit rationale.
  - JSON and Markdown report generation.
  - 100% offline-capable default test suite; zero required model downloads.
  - All 292 existing tests preserved and passing; 15 new tests passing (total: 307 passed in `.venv`, 297 passed in `.venv_ml`).
  - No git reset, clean, or destructive cleanup was performed. No secrets exposed.
