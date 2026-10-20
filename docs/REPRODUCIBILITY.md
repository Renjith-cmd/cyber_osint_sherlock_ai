# Sherlock AI — Reproducibility & Evaluation Guide

This guide documents the exact environment specifications, verified execution commands, determinism guarantees, and benchmark interpretation guidelines for the Sherlock AI research prototype.

---

## 1. Environment Specifications

Sherlock AI has been verified across two isolated Python virtual environments on Linux:

| Specification | Standard Environment (`.venv`) | Machine Learning Environment (`.venv_ml`) |
| :--- | :--- | :--- |
| **Operating System** | Linux x86_64 (Linux 6.8.0 kernel) | Linux x86_64 (Linux 6.8.0 kernel) |
| **Python Version** | 3.14.7 | 3.11.14 |
| **Primary Frameworks** | Pydantic 2.14, FastAPI 0.115, Starlette 0.46, SQLite3 | Pydantic 2.14, PyTorch, Transformers, Sentence-Transformers |
| **Test Runner** | Pytest 9.1.1 (pluggy 1.6.0) | Pytest 9.1.1 (pluggy 1.6.0) |
| **Role in Prototype** | Core logic, SQLite persistence, REST API, Web UI, CLI | Deep learning NER, embeddings, and cross-encoder evaluation |

---

## 2. Full Regression Test Suites

### 2.1 Running the Standard Regression Suite (`.venv`)
Execute all tests in the standard environment:
```bash
.venv/bin/pytest tests/
```

**Independently Observed Output:**
- **Exit Code:** `0`
- **Total Tests Collected:** 366
- **Passed:** **361**
- **Failed:** **0**
- **Skipped:** **5**
- **Duration:** ~4–6 seconds

#### Skipped Tests Explanation (5 tests)
All 5 skips occur in `tests/test_milestone_11_real_model_evaluation.py`:
- `test_cross_encoder_real_eval`
- `test_bi_encoder_real_eval`
- `test_full_hybrid_ensemble_evaluation`
- `test_model_card_and_run_config_metadata`
- `test_production_latency_and_memory_footprint`

**Reason:** These tests evaluate pre-trained neural cross-encoders and bi-encoders. They dynamically skip when `torch` or `transformers` is not present in the runtime environment.

---

### 2.2 Running the Machine Learning Regression Suite (`.venv_ml`)
Execute all tests in the machine learning environment:
```bash
.venv_ml/bin/pytest tests/
```

**Independently Observed Output:**
- **Exit Code:** `0`
- **Total Tests Collected:** 352
- **Passed:** **341**
- **Failed:** **0**
- **Skipped:** **11**
- **Duration:** ~20–25 seconds

#### Skipped Tests Explanation (11 tests)
- 10 tests in `tests/test_milestone_14_hardening.py` conditionally skip because `fastapi` and `starlette` are omitted from the ML environment to minimize dependency bloat.
- 1 test in `tests/test_milestone_14_hardening.py` conditionally skips due to optional `psutil`.
- All deep learning model tests in `test_milestone_11_real_model_evaluation.py` run and pass.

---

### 2.3 Running the Milestone 15 Targeted Test Suite
Execute the cross-document resolution, epistemic tiers, and reversibility test suite:
```bash
.venv/bin/pytest tests/test_milestone_15_cross_document.py -v
```

**Independently Observed Output:**
- **Exit Code:** `0`
- **Passed:** **16** (100% pass rate)
- **Duration:** ~0.14 seconds

---

### 2.4 Static Bytecode Compilation & Patch Hygiene
Verify that all source files compile cleanly without syntax errors:
```bash
.venv/bin/python -m compileall -q src tests scripts
git diff --check
```
Both commands must exit with code `0`.

---

## 3. Verified Execution Entry Points

### 3.1 Document Extraction CLI Demo (Safe, In-Memory)
Demonstrates document parsing, entity mention detection, relation candidate extraction, and claim grounding on sample text:
```bash
.venv/bin/python -m src.core.document_cli --sample
```
- **Exit Code:** `0`
- **Output:** Outputs a complete forensic dossier with character offsets, grounded evidence spans, and epistemic notices. Zero external network calls or file mutations.

### 3.2 End-to-End Multi-Document Investigation Demo
Demonstrates multi-document ingestion, variant resolution, allegation modeling, claim retraction, bounded graph queries, and report generation:
```bash
.venv/bin/python -m src.core.investigation_demo
```
- **Exit Code:** `0`
- **Output:** Processes synthetic memos (`memo_alpha_101.txt` and `field_dispatch_beta_102.txt`), tests idempotency, executes a human retraction, and outputs a structured Markdown investigation report.

### 3.3 Investigation API & Web UI Server
Start the FastAPI server and dark-graphite web workspace:
```bash
.venv/bin/python -m src.api.server --host 127.0.0.1 --port 8000
```
- **Default Binding:** `127.0.0.1:8000` (Strict local loopback).
- **Web Workspace:** `http://127.0.0.1:8000/`
- **Swagger Documentation:** `http://127.0.0.1:8000/docs`
- **OpenAPI Schema:** `http://127.0.0.1:8000/openapi.json`

---

## 4. Benchmark Harness & Metric Interpretation

### 4.1 Benchmark Artifacts & Lineage

The repository contains historical benchmark runs and a Milestone 15 benchmark harness:

1. **Milestone 15 Cross-Document Benchmark:**
   - **Script:** `scripts/benchmark_milestone_15.py`
   - **Output:** `artifacts/benchmarks/milestone_15/cross_document_benchmark_results.json`
   - **Dataset:** 10 targeted synthetic candidate pairs covering 6 match/non-match archetypes, plus 5 syndicated identical wire statements and SQLite lifecycle operations.
   - **Determinism:** 100% deterministic rule evaluations (no random seed required).
2. **Milestone 7 Real-World Restaurant Benchmark:**
   - **Script:** `src/core/benchmark.py`
   - **Output:** `artifacts/benchmarks/real_world/milestone_7_results.json`
   - **Dataset:** Zagat-Fodor's restaurant listings (864 records, 112 true matching pairs, 752 canonical entities).
3. **Milestone 14 Pipeline & Persistence Benchmark:**
   - **Script:** `benchmarks_m14_phase2.py`
   - **Output:** `artifacts/benchmarks/milestone_14_phase2_benchmarks.json`
   - **Measures:** Latency, RSS memory high-water mark, and SQLite PRAGMA integrity check across synthetic text sizes.

> [!WARNING]
> **Safety Rule on Benchmark Execution:**
> Never re-run benchmark scripts if doing so would overwrite existing historical benchmark JSON files. If re-running a benchmark is essential for independent replication, always specify a custom, unique output path.

---

### 4.2 Critical Benchmark Interpretation & Limitations

1. **Synthetic Fixtures are Smoke Tests, Not Real-World Proof:**
   - The 10-pair evaluation in `cross_document_benchmark_results.json` achieves 1.0000 Precision and Recall.
   - **Interpretation:** This fixture serves strictly as a **functional decision-boundary smoke test** to verify that algorithmic edge cases (homonyms, conflicting tax IDs, shared org sub-tokens, review queue routing) behave as designed. It must **not** be presented as empirical evidence of real-world accuracy across unstructured OSINT text.
2. **Heuristic Scores are Not Probabilities:**
   - Scores produced by `CrossDocumentEntityResolver` (e.g. `0.9729`, `0.8500`) are deterministic, rule-weighted similarity measures combining Jaro-Winkler string distance, token overlap, and contextual attribute modifiers.
   - **Interpretation:** These scores are **not calibrated Bayesian probabilities**. They must not be interpreted as the probability that two entities are identical in the real world.
3. **Zagat-Fodor's Domain Specificity:**
   - Historical benchmarks on `Restaurant.csv` demonstrate high reduction ratios (>99.9%) and high candidate recall on structured commercial directory listings.
   - **Interpretation:** High performance on commercial business directories does not imply equivalent performance on noisy, unstructured text containing complex geopolitical entities or human intelligence reports.

---

## 5. Security & Isolation Guidelines

- **Database Isolation:** When running tests or experiments, always use temporary database files (e.g. `tempfile.TemporaryDirectory()`) or specify `--db data/demo_test.db`. Never execute write operations against operational data stores.
- **Remote Binding Restrictions:** Sherlock AI refuses binding to non-loopback addresses (`0.0.0.0` or external IPs) unless `--allow-remote` is explicitly passed AND an API token of $\ge 16$ characters is supplied via `--api-token` or `SHERLOCK_API_TOKEN`.
- **Single-Tenant Assumption:** The current prototype operates under a single-tenant model with no multi-user session segregation or role-based access control (RBAC). Do not expose the service on public networks.
