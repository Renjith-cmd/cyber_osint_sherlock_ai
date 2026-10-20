# 🛰️ Sherlock AI — Entity Resolution & Evidence-Grounded Investigation Platform

[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.14-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests Passing](https://img.shields.io/badge/tests-361%20passed%20%7C%205%20skipped-brightgreen.svg)](tests/)
[![Architecture](https://img.shields.io/badge/Architecture-Forensic%20Integrity-blueviolet.svg)](docs/ARCHITECTURE.md)
[![Reproducibility](https://img.shields.io/badge/Reproducibility-Verified-success.svg)](docs/REPRODUCIBILITY.md)

An audit-grade, research-prototype intelligence and entity resolution system. Designed to transform unstructured investigative reports, regulatory documents, and news feeds into a structured, evidence-grounded knowledge graph with **strict epistemic tracking, non-destructive reversibility, and verifiable provenance**.

---

> [!IMPORTANT]
> **Responsible Research Prototype Disclaimer**
> Sherlock AI is an experimental research system developed for evaluating conservative entity resolution algorithms, epistemic provenance modeling, and graph-theoretic link analysis. It is **not** an operational intelligence platform, and it must **not** be used as the sole basis for legal, law-enforcement, financial, or personnel adjudications without independent human corroboration.

---

## 1. Project Overview & Problem Statement

In automated open-source intelligence (OSINT) and complex data investigations, conventional entity resolution and knowledge graph systems suffer from four critical failure modes:

1. **Hallucinatory Identity Merges:** Heuristic or embedding-based linkers frequently merge distinct individuals who share common names (homonyms) or conflate separate corporate subsidiaries that share root tokens.
2. **Ungrounded Graph Assertions:** Extracted relationships are often presented as ground truth without linking back to exact verbatim text spans, document hashes, or extraction methodologies.
3. **Corroboration Inflation (The Echo-Chamber Effect):** When syndicated news wires, press releases, or repetitive reports reprint the identical sentence across multiple outlets, conventional algorithms count each reprint as independent corroboration, artificially inflating confidence.
4. **Irreversible Graph Corruption:** Automated graph merges are typically destructive one-way operations: once two entities are combined, separating them or correcting errors requires rebuilding the entire database.

### The Sherlock AI Solution
Sherlock AI resolves these challenges through an audit-grade architectural pipeline:
- **Immutable Empirical Observations:** Raw payloads cannot be mutated by downstream processing.
- **Three-Tier Outcome Model:** Pairwise comparisons strictly output `MATCH`, `NON_MATCH`, or `REVIEW`. Ambiguous candidates or uncorroborated high similarities are quarantined into a human review queue.
- **Hard Constraints & Cascade Prevention:** Explicit non-match constraints prevent automated or manual merges between declared distinct entities, blocking transitive collapse ($A \approx B$, $B \approx C$, $A \not\approx C$).
- **Epistemic Relationship Tiers:** Relationships explicitly record epistemic tiers (`ASSERTED`, `DENIED`, `QUOTED`, `INFERRED`, `DISPUTED`, `HUMAN_VERIFIED`).
- **Anti-Corroboration Content Hashing:** Repeated statements sharing identical normalized text hashes increment duplicate counters rather than independent source counts.
- **Fully Reversible Lifecycle:** Every merge can be inspected, split back into distinct entities, or reversed completely with automatic non-match constraint generation.

---

## 2. Key Capabilities & End-to-End Workflow

```text
[ Unstructured Documents / Files ]
               │
               ▼
   1. Ingestion & Content Hashing (SHA-256)
               │
               ▼
   2. NER & Grounded Relation Candidate Extraction
               │
               ▼
   3. Candidate Generation & Blocking (Multi-rule index pruning)
               │
               ▼
   4. Conservative Cross-Document Entity Resolution [MATCH | NON_MATCH | REVIEW]
               │
               ▼
   5. Evidence-Grounded Claims & Epistemic Derivations (ASSERTED vs QUOTED vs DISPUTED)
               │
               ▼
   6. Anti-Corroboration Duplicate Suppression (Shared content hashes)
               │
               ▼
   7. Durable Relational Persistence (SQLite WAL Mode)
               │
               ▼
   8. Investigation Workspace & Human-in-the-Loop Review (Web UI / REST API)
```

1. **Autonomous Document Ingestion:** Validates text, PDF, JSON, and HTML formats, generates SHA-256 digests, and guarantees idempotent re-processing.
2. **Deterministic Extraction:** Rule-based and optional neural extractors extract entity mentions with exact character spans `(start_char, end_char)`.
3. **Candidate Generation (Blocking):** Slashes the $O(N^2)$ Cartesian comparison space by $>99.9\%$ using multi-rule blocking (Exact Name, Name Tokens, Order-Invariant Fingerprints, Acronyms, Soundex, and Structured Identifiers).
4. **Conservative Resolution Engine:** Uses Jaro-Winkler surface similarity, token sort metrics, reliable identifier matching (tax IDs, LEI, CRN), and contextual attribute comparisons.
5. **Epistemic Derivation:** Distinguishes affirmative claims from explicit negations (`DENIED`) and reported allegations (`QUOTED`). Merging affirmative and negative claims marks the relationship as `DISPUTED`.
6. **Reversible Split & Merge:** Analysts can approve merge proposals, split mis-clustered composite entities, or reverse prior merges with complete record restoration.

---

## 3. Architecture & Major Components

```text
entity_resolution_graph_osint/
├── src/
│   ├── core/                        # Core algorithmic foundation
│   │   ├── models.py                # Immutable domain models (Record, Claim, Evidence, Relationship)
│   │   ├── blocking.py              # Candidate generation & multi-rule blocking strategies
│   │   ├── comparison.py            # Pairwise comparators & feature similarity scoring
│   │   ├── cross_document_resolver.py # Cross-doc ER, constraints, review queue, reversibility
│   │   ├── document_ingestion.py    # Document ingestion, format parsers, content hashing
│   │   ├── document_pipeline.py     # Extraction pipeline & intra-doc mention resolution
│   │   ├── investigation_lifecycle.py# Evidence grounding, epistemic tiers, dispute modeling
│   │   ├── investigation_sqlite.py  # SQLite WAL persistence with relational schema
│   │   ├── investigation_service.py # Investigation session orchestrator & report generation
│   │   ├── investigation_demo.py    # End-to-end multi-document deterministic demo
│   │   ├── document_cli.py          # Document extraction CLI
│   │   └── ner.py                   # Rule and model-backed NER extractors
│   ├── api/                         # FastAPI REST Service & Security Layer
│   │   ├── app.py                   # Application factory, CORS, static UI mounting
│   │   ├── server.py                # Server entry point with loopback binding enforcement
│   │   ├── routes.py                # REST endpoints for investigations, review, and resolution
│   │   ├── schemas.py               # Pydantic request/response schemas
│   │   └── security.py              # Constant-time token verification & input sanitization
│   └── ui/                          # Mobile-first warm cream & deep navy-purple UI (HTML5/CSS3/Vanilla JS)
│       ├── index.html               # 9-screen investigation workspace
│       ├── app.js                   # Mobile-first SPA controller & API client
│       └── app.css                  # Rounded design system & responsive styling
├── data/                            # Local benchmark manifests and SQLite databases
├── docs/                            # Deep architectural and reproducibility documentation
│   ├── ARCHITECTURE.md              # Technical design, data flow, and invariants
│   └── REPRODUCIBILITY.md           # Reproduction steps, test results, and seed specs
├── scripts/                         # Benchmark harnesses
│   └── benchmark_milestone_15.py    # Milestone 15 cross-document benchmark harness
├── tests/                           # Complete test suite (366 test cases)
└── requirements.txt                 # Runtime dependencies
```

---

## 4. Prerequisites & Environment Setup (Linux)

### 4.1 System Requirements
- **Operating System:** Linux (Ubuntu 22.04 LTS, Debian 12, or compatible x86_64 distribution).
- **Python:** Python 3.10 to 3.14 (Tested on Python 3.14.7 in `.venv` and Python 3.11.14 in `.venv_ml`).
- **Hardware Profile:** Runs entirely in CPU memory (Baseline process RSS: ~39 MB). Optional GPU acceleration supported for deep learning models if PyTorch is installed.

### 4.2 Setup Instructions

```bash
# 1. Clone the repository
git clone https://github.com/Arnav8452/entity_resolution_graph_osint.git
cd entity_resolution_graph_osint

# 2. Create and activate a standard virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install core dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5. Verified Execution Commands

All commands below have been independently verified on Linux and exit with code `0`.

### 5.1 Run the Full Test Regression Suite
```bash
# Standard environment test run (361 passed, 5 skipped)
.venv/bin/pytest tests/

# Targeted Milestone 15 suite (16 passed in 0.14s)
.venv/bin/pytest tests/test_milestone_15_cross_document.py -v
```

### 5.2 Static Bytecode Compilation Check
```bash
.venv/bin/python -m compileall -q src tests scripts
git diff --check
```

### 5.3 Run the Document Extraction CLI (Safe In-Memory Demo)
Extracts mentions, grounded relation candidates, and claims from synthetic text:
```bash
.venv/bin/python -m src.core.document_cli --sample
```

### 5.4 Run the Multi-Document Investigation Demo
Executes a multi-document investigation with cross-document resolution, epistemic derivation, idempotency validation, and structured report generation:
```bash
.venv/bin/python -m src.core.investigation_demo
```

### 5.5 Start the Investigation Server & Web Interface
Starts the FastAPI application and serves the redesigned mobile-first warm cream and deep navy-purple workspace:
```bash
.venv/bin/python -m src.api.server --host 127.0.0.1 --port 8000
```
- **Web Interface:** Open `http://127.0.0.1:8000/` in your browser.
- **Interactive Swagger Documentation:** Open `http://127.0.0.1:8000/docs`.
- **OpenAPI Schema:** `http://127.0.0.1:8000/openapi.json`.
- **Available Screens (9 Integrated Views):**
  1. *Dashboard:* Active case summary, metric pills, epistemic disclaimers, and quick actions.
  2. *Investigations:* List, search, create cases, and load synthetic demo scenarios.
  3. *Document Intake:* Upload dropzone (.txt, .json, .pdf), extraction triggers, and split text/offset viewer.
  4. *Entity Resolution:* Cross-document pairwise candidate proposals, score inspection, approval merges, and non-match constraints.
  5. *Entity Profile:* Canonical/provisional entities, member mention records, cluster properties, and split reversibility.
  6. *Relationship Graph:* Interactive SVG network with epistemic tier coloring, radial focus, depth controls, and node/edge inspector.
  7. *Claims & Evidence:* Epistemic claim registry with qualifiers (allegations, negations), verbatim citations, and human review adjudication.
  8. *Investigation Report:* Deterministic dossier compiler with Markdown and JSON export.
  9. *System Status:* Real-time API health, version, SQLite storage path, and offline safety rules.

### 5.6 Deploy the Investigation UI/API to Vercel
The repository includes a Vercel Python function entrypoint at `api/index.py` and `vercel.json`. The Vercel dependency profile is intentionally lightweight; install `requirements-full.txt` for the optional scraper, ML, Neo4j, and Streamlit surfaces when running the full repository locally.

Deploy this repository as a Vercel project and enable Vercel Deployment Protection for the deployment. The Vercel entrypoint relies on that upstream protection and does not require a second API bearer token in the browser. `SHERLOCK_API_TOKEN` remains available for a separately exposed/self-hosted API; do not expose an unprotected deployment publicly.

**Persistence limitation:** the default Vercel database path is `/tmp/sherlock_investigations.db`. Vercel function filesystems are ephemeral and separate between instances, so SQLite data is not durable or shared across invocations. Use this deployment only for a stateless/demo preview unless the application is configured with a durable external persistence backend. Vercel deployment has not been tested with the optional ML backend.

---

## 6. Fictional-Data End-to-End Walkthrough

To see Sherlock AI operate across multiple documents without mutating any database:

1. Run `.venv/bin/python -m src.core.investigation_demo`.
2. The demo initializes session `inv_project_blackthorn_2026` in memory.
3. **Document Alpha (`memo_alpha_101.txt`)** is ingested:
   - Identifies mentions: `Dr. John Watson`, `Sherlock Security`, `London`, `Wayne Enterprises`, `Globex Corporation`.
   - Extracts relations: `(Dr. John Watson) ==[WORKS_FOR]==> (Sherlock Security)`, `(Wayne Enterprises) ==[OWNS]==> (Globex Corporation) [ALLEGATION]`.
4. **Document Beta (`field_dispatch_beta_102.txt`)** is ingested:
   - Identifies mentions: `Dr. John Watson`, `Sherlock Security Ltd`, `Alice Smith`, `Cyberdyne Systems`, `Marcus Vance`.
   - Resolves `Sherlock Security Ltd` to canonical entity `ent_sherlock_security`.
   - Evaluates `Alice Smith does not work for Cyberdyne Systems` as an explicit denial (`polarity="NEGATIVE"`).
   - Identifies `Marcus Vance` as an unlinked entity and safely assigns `UNRESOLVED_NO_CANDIDATES` rather than forcing a false merge.
5. **Idempotency Guarantee:** Re-submitting Document Alpha detects identical content hashes and marks the processing as `SKIPPED_DUPLICATE` without creating duplicate claims.
6. **Epistemic Adjudication:** An investigator reviews the hearsay allegation that Wayne Enterprises owns Globex Corporation, updating the claim to `RETRACTED`. The active relationship status automatically cascades to `RETRACTED`.
7. **Report Generation:** Produces a structured Markdown dossier detailing document registries, resolved entities, unresolved ambiguity guards, and evidential claims.

---

## 7. Test Results & Skipped-Test Explanations

| Environment | Command | Total Collected | Passed | Skipped | Failed | Duration |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Standard (`.venv`)** | `.venv/bin/pytest tests/` | 366 | **361** | **5** | **0** | 5.41s |
| **Machine Learning (`.venv_ml`)** | `.venv_ml/bin/pytest tests/` | 352 | **341** | **11** | **0** | 20.59s |
| **Milestone 15 Targeted** | `.venv/bin/pytest tests/test_milestone_15_cross_document.py` | 16 | **16** | **0** | **0** | 0.14s |

### Transparent Skipped-Test Explanations
- **5 Skips in `.venv`:** Occur exclusively in `tests/test_milestone_11_real_model_evaluation.py`. These tests evaluate neural bi-encoders and cross-encoders that require heavy optional dependencies (`torch`, `transformers`). In standard lightweight environments, they skip dynamically without failure.
- **11 Skips in `.venv_ml`:** 10 REST API tests in `tests/test_milestone_14_hardening.py` skip because FastAPI is omitted from the dedicated ML training environment; 1 test skips due to optional `psutil`.

---

## 8. Benchmark Interpretation & Methodological Safeguards

### 8.1 Empirical Benchmark Profiles
Sherlock AI includes two distinct benchmark suites:
1. **Decision-Boundary Functional Smoke Test (`scripts/benchmark_milestone_15.py`):**
   - Evaluates 10 synthetic candidate pairs targeting specific edge cases: homonyms with conflicting ages, organizations with shared prefixes but distinct sub-tokens, conflicting registration numbers, matching LEI codes, and uncorroborated surface similarities.
   - Outputs: `artifacts/benchmarks/milestone_15/cross_document_benchmark_results.json`.
   - **Methodological Safeguard:** This fixture is a **functional smoke test** to verify boundary decision logic. It is **not** an empirical proof of real-world accuracy across open-domain web data.
2. **Real-World Restaurant Benchmark (`src/core/benchmark.py`):**
   - Evaluates the standard Zagat-Fodor's benchmark (`Restaurant.csv`, 864 records, 112 true matching pairs).
   - Demonstrates candidate reduction ratio $>99.9\%$ and candidate recall $>95\%$ across baseline comparators.
   - Outputs: `artifacts/benchmarks/real_world/milestone_7_results.json`.

### 8.2 Heuristic Scores vs. Probabilities
Confidence scores emitted by `CrossDocumentEntityResolver` (e.g. `0.9729`, `0.8500`) are deterministic, rule-weighted similarity measures combining Jaro-Winkler string distance, token overlap, and contextual attribute modifiers. **They are not calibrated Bayesian probabilities** and must not be interpreted as mathematical likelihoods of real-world identity.

---

## 9. Security, Privacy & Boundary Guarantees

- **Loopback Enforcement:** `src/api/server.py` enforces local loopback binding (`127.0.0.1`, `localhost`) by default. Binding to `0.0.0.0` or external network interfaces is strictly prohibited unless `--allow-remote` is passed AND an authentication token of at least 16 characters is supplied.
- **Single-Operator Isolation:** Sherlock AI operates as a single-tenant investigation workspace. It does not provide multi-user role-based access control (RBAC), multi-tenant data segregation, or end-user session encryption.
- **Zero External Telemetry:** All document ingestion, text parsing, entity resolution, and report generation execute 100% locally on the host machine. No telemetry, analytics, or scraped payloads are transmitted to external servers.

---

## 10. Licensing & Provenance Notes

- **Core Codebase:** Distributed under the **MIT License**.
- **Test Fixtures & Synthetic Data:** All test cases in `tests/`, `src/core/document_cli.py`, and `src/core/investigation_demo.py` consist of 100% synthetic fictional data released under **CC0 1.0 Universal / Public Domain**.
- **Zagat-Fodor's Dataset (`data/Restaurant.csv`):** Curated in CRAN package `restaurant` v0.1.0 under **CC0 1.0 Universal** (Tejada et al., 2001; Chen, Shrivastava, Steorts, 2018). Raw data represents commercial business listings (restaurant names, addresses, cuisine) with zero personally identifiable information (PII).
- **Core Dependencies:**
  - `pydantic`: MIT
  - `fastapi` & `starlette`: MIT / BSD
  - `sqlite3`: Public Domain
  - `jellyfish`: MIT
  - `python-dateutil`: Apache 2.0 / BSD

---

## 11. Known Limitations & Research Boundaries

1. **Nickname Dictionary Dependency:** Heuristic Jaro-Winkler similarity reliably identifies spelling and transliteration variants (e.g. "Robert Vance" $\leftrightarrow$ "Robert H. Vance", "Dmitry" $\leftrightarrow$ "Dmitrii"). Highly irregular short nicknames (e.g. "Peggy" for "Margaret") require secondary identifiers or route conservatively to `REVIEW`.
2. **Negation Scope Resolution:** Complex linguistic negations across compound sentences (e.g. *"Neither Alice nor Bob, despite rumors to the contrary, was associated with the firm"*) require neural parsing; rule-based extraction operates over sentence-level syntactic patterns.
3. **Graph Query Scale in SQLite:** Bounded traversals in SQLite WAL mode are optimized for sub-millisecond latencies across hundreds of entities. Graph traversals exceeding 50,000 nodes should be mirrored to a graph database (e.g. Neo4j) for heavy multi-hop graph algorithms.

---

## 12. Troubleshooting & FAQ

### Port 8000 is already in use
```bash
.venv/bin/python -m src.api.server --port 8080
```

### ModuleNotFoundError: No module named 'src'
Always execute Python modules from the repository root directory using the `-m` flag:
```bash
.venv/bin/python -m src.core.investigation_demo
```

### SQLite Database Locked
Ensure that external database inspection tools (such as DB Browser for SQLite) do not hold exclusive transaction locks while the API server is actively processing documents. Sherlock AI configures WAL mode to allow concurrent readers.

---

## 13. Documentation & Further Reading

- [Architecture Guide (`docs/ARCHITECTURE.md`)](docs/ARCHITECTURE.md) — Comprehensive data flow, model immutability, epistemic tiers, and component specifications.
- [Reproducibility Guide (`docs/REPRODUCIBILITY.md`)](docs/REPRODUCIBILITY.md) — Environment setups, verified commands, seeds, test counts, and benchmark reproduction guidelines.
- [Milestone 15 Final Verification Report (`artifacts/milestone_15_report.md`)](artifacts/milestone_15_report.md) — Acceptance audit findings, regression logs, and implementation verification.