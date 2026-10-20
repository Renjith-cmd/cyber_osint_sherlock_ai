# Sherlock AI — Release Preparation Phase 2: Final Demonstration Report

**Document Version:** `v1.0.0`  
**Date:** `2026-10-12`  
**Repository:** `/home/renjith-cmd/Documents/sherlock-ai-1/entity_resolution_graph_osint`  
**Evaluator Status:** `READY FOR EVALUATION`  
**Test Environments:** `.venv` (Python 3.14.7, FastAPI, Starlette), `.venv_ml` (Python 3.14.7, PyTorch, Transformers)  
**Safety Protocol:** Zero commits, zero pushes, zero package installations, zero benchmark mutations, 100% fictional synthetic data.

---

## 1. Executive Summary & Verdict

Phase 2 of release preparation establishes a polished, fully reproducible, deterministic end-to-end demonstration of the Sherlock AI research prototype. The demonstration exercises all nine core capabilities outlined in the project specification using three synthetic source documents, operating entirely in-memory with strict source provenance, conservative pairwise entity resolution, homonym disambiguation, identifier conflict handling, relationship evidence grounding, contradiction modeling, source attribution, duplicate suppression, and structured investigation reporting.

### Final Verdict

```
================================================================================
VERDICT: READY FOR EVALUATION
================================================================================
- Deterministic 9-stage demonstration executed cleanly via single-command CLI.
- Verified byte-for-byte output determinism across repeated executions (excluding dynamic UTC timestamp).
- 100% test pass rate across both project virtual environments:
  * .venv:    361 passed, 5 skipped, 4 warnings (4.24s)
  * .venv_ml: 341 passed, 11 skipped (21.80s)
- All historical benchmark datasets, reports, and working tree modifications preserved intact.
- Zero commits, pushes, cleans, resets, or external network dependencies introduced.
================================================================================
```

---

## 2. One-Command Demonstration Invocation

Evaluators can reproduce the entire end-to-end investigation scenario using either of the following single-command invocations:

### Primary Invocation (Recommended)

```bash
.venv/bin/python -m src.core.investigation_demo
```

### Alternative CLI Invocation

```bash
.venv/bin/python -m src.core.document_cli --demo-release
```

### Formatted Output Flags

```bash
# Export the full markdown investigation report to a specified file
.venv/bin/python -m src.core.investigation_demo --output /tmp/sherlock_report.md

# Emit machine-readable structured JSON output
.venv/bin/python -m src.core.investigation_demo --json

# Run in dedicated ML environment (.venv_ml)
.venv_ml/bin/python -m src.core.investigation_demo
```

### Web UI Inspection (Optional)

The prototype also provides a full-stack, dark-graphite web workspace:
```bash
# Start the FastAPI server on localhost:8000
.venv/bin/python -m src.api.server
# Open browser at: http://127.0.0.1:8000/
```

---

## 3. Demonstration Scenario & Numbered Stages

The demonstration scenario processes three synthetic documents and executes nine sequential stages:

### Fictional Documents Ingested

1. **`memo_nexus_201.txt` (Internal Memorandum Alpha-201):**
   * *Content:* Dr. John Watson works for Sherlock Security in London. Corporate registry NL-1001 indicates Nexus Holdings operates in London and owns Apex Corp. Elena Rostova is associated with Acorn Holdings.
2. **`wire_nexus_202.txt` (Regulatory Wire Beta-202):**
   * *Content:* Dr. John Watson works for Sherlock Security Ltd in London. Corporate registry NL-8899 indicates Nexus Holdings operates in Dublin. A media report alleges that Wayne Enterprises owns Globex Corporation. Elena Rostova is associated with Acorn Holdings.
3. **`dispatch_field_203.txt` (Field Dispatch Gamma-203):**
   * *Content:* Dr. John Watson, a 72-year-old botanist at London Arboretum, published research on flora. Official corporate records confirm Nexus Holdings does not own Apex Corp. Alice Smith does not work for Cyberdyne Systems. Marcus Vance was observed near the docklands warehouse.

### Detailed Stage Walkthrough

| Stage | Title | Decision Authority | Verification Criteria & Observed Engine Output |
| :--- | :--- | :--- | :--- |
| **Stage 1** | **Multi-Document Ingestion & Content Deduplication** | **Automatic** | Ingested `memo_nexus_201.txt`, `wire_nexus_202.txt`, and `dispatch_field_203.txt`. Re-ingesting Doc 1 yielded `DocumentProcessingStatus.SKIPPED_DUPLICATE` with zero duplicate claims. |
| **Stage 2** | **Entity & Evidence Extraction with Strict Provenance** | **Automatic** | Extracted 31 mentions, 13 claims, and 13 grounded evidence items. Each item includes `[start_char:end_char]`, sentence index, source URI, and SHA-256 hash. |
| **Stage 3** | **Cross-Document Entity Resolution (Corroborated Match)** | **Automatic** | Pairwise comparison between Watson in Doc 1 (Sherlock Security) and Doc 2 (Sherlock Security Ltd) resolved to `DecisionType.MATCH` (Score: 0.99) via corroborating corporate and location context. |
| **Stage 4** | **Homonym Disambiguation (Conservative Abstention)** | **Automatic** | Watson in Doc 3 (72-year-old botanist at London Arboretum) evaluated against investigator Watson. Policy detected distinct role/age context and lack of shared corporate affiliation; automatically routed to `DecisionType.REVIEW` (Score: 0.85) without false merging. |
| **Stage 5** | **Identifier Conflict & Explicit NON_MATCH Constraint** | **Reviewer-Supplied** | Nexus Holdings in Doc 1 (NL-1001) vs Doc 2 (NL-8899). Analyst registered an explicit non-match constraint via `add_non_match_constraint`. Engine enforced `DecisionType.NON_MATCH`. Reversibility demonstrated via `split_entity`. |
| **Stage 6** | **Evidence-Grounded Relationship Derivation & Graph Traversal** | **Automatic** | Derived `Dr. John Watson --[WORKS_FOR]--> Sherlock Security`. Bounded traversal (`query_entity`) from Watson root discovered 3 entities and 4 relationships with complete evidence provenance explanations. |
| **Stage 7** | **Contradictory Evidence & Dispute Modeling** | **Extraction: Automatic<br>Dispute Linkage: Reviewer-Supplied** | Pipeline automatically extracted positive assertion (Doc 1: Nexus Holdings owns Apex Corp) and negative assertion (Doc 3: does not own, `is_negated=True`). Crucially, the engine does NOT automatically mark existing relationships as DISPUTED upon ingesting negative claims. Reviewer adjudicates and links the contradiction via `record_contradiction`, transitioning the relationship to `ReviewStatus.DISPUTED` / `RelationshipEpistemicTier.DISPUTED`. |
| **Stage 8** | **Source Attribution & Duplicate-Content Suppression** | **Attribution: Automatic<br>Retraction: Reviewer-Supplied** | Extracted quoted allegation ("The report alleges that...") with `is_allegation=True`. Reviewer retracted unverified claim via `review_claim(..., new_status=ReviewStatus.RETRACTED)`. Duplicate statements preserved single unique source hash. |
| **Stage 9** | **Comprehensive Deterministic Investigation Reporting** | **Automatic** | Generated `InvestigationReport` (Schema `v1.5.0`) detailing 3 documents, 41 graph entities, 13 claims, 11 relationships, 31 unresolved mentions (e.g. `Marcus Vance`), and 4 epistemic research warnings. |

### 3.1 Decision Authority: Automatic vs. Reviewer-Supplied Actions

To ensure complete epistemic integrity, the demonstration strictly distinguishes between decisions computed automatically by the engine versus constraints or adjudications supplied by a human reviewer:

1. **Automatic Cross-Document Matches (Stage 3):**
   * Pairwise comparison between Dr. John Watson in Doc 1 and Doc 2 automatically evaluates to `DecisionType.MATCH` (Similarity Score: 0.99). The engine validates high name similarity corroborated by shared organizational ties (`Sherlock Security` / `Sherlock Security Ltd`) and location (`London`).
2. **Automatic Homonym Safeguards (Stage 4):**
   * Pairwise comparison between Dr. John Watson in Doc 1 (investigator) and Doc 3 (72-year-old botanist) automatically routes to `DecisionType.REVIEW` (Score: 0.85). The engine abstains from merging due to disjoint corporate affiliations and distinct contextual roles.
3. **Reviewer-Supplied Identifier Constraints (Stage 5):**
   * While Nexus Holdings shares high name similarity across Doc 1 and Doc 2, corporate registry numbers conflict (NL-1001 London vs NL-8899 Dublin). The reviewer registers an explicit non-match constraint via `orchestrator.add_non_match_constraint()`. The resolver subsequently enforces this as a hard constraint, producing `DecisionType.NON_MATCH`.
   * Similarly, the split of provisional entity clusters via `orchestrator.split_entity()` is a reviewer-initiated action demonstrating graph reversibility.
4. **Contradiction Modeling & Actual System Behavior (Stage 7):**
   * *Actual Pipeline Behavior:* When Doc 3 states *"Official audit records confirm Nexus Holdings does not own Apex Corp"*, the relation extraction pipeline automatically tags the claim with `is_negated=True` and status `UNREVIEWED`. It does **not** derive an unnegated relationship, nor does it automatically scan existing graph relationships to mark them as `DISPUTED`.
   * *Reviewer-Supplied Dispute:* Linking the negative claim to the preexisting positive relationship requires invoking the documented adjudicator interface `orchestrator.record_contradiction(investigation_id, relationship_id, contradicting_claim_id)`. Once invoked, the relationship status transitions to `ReviewStatus.DISPUTED` and its tier becomes `RelationshipEpistemicTier.DISPUTED`.
5. **Attribution & Retraction (Stage 8):**
   * Source attribution (`attribution_source='The report alleges that'`, `is_allegation=True`) is extracted automatically by the pipeline.
   * Retraction of the unverified claim is an explicit reviewer action invoking `orchestrator.review_claim(..., new_status=ReviewStatus.RETRACTED)`.

---

## 4. Determinism Comparison & Repeatability Audit

To verify repeatability, the demonstration was executed twice consecutively in isolated processes:

```bash
.venv/bin/python -m src.core.investigation_demo > /tmp/demo_run_1.txt
.venv/bin/python -m src.core.investigation_demo > /tmp/demo_run_2.txt
diff -u <(grep -v "Generated At" /tmp/demo_run_1.txt) <(grep -v "Generated At" /tmp/demo_run_2.txt)
```

### Determinism Audit Results

* **Diff Exit Code:** `0` (Zero differences detected).
* **Entity Identifiers:** 100% identical cluster hashes and entity IDs across runs.
* **Pairwise Decisions:** 100% identical decision types, scores, and positive/negative evidence lists.
* **Graph Subgraph Metrics:** Identical node and edge counts in bounded traversal.
* **Storage Isolation:** The demonstration executes strictly in-memory (`InMemoryInvestigationGraphStore`) without writing to or mutating any durable database tables or persistent files unless explicitly requested via `--output`.

---

## 5. Verification Commands and Exact Results

### 1. Code Quality & Formatting Checks

```bash
.venv/bin/python -m compileall -q src tests scripts
git diff --check
```
* **Exit Code:** `0`
* **Output:** Clean compilation; zero whitespace errors or lint issues.

### 2. Targeted Investigation & Cross-Document Regression Tests

```bash
.venv/bin/pytest tests/test_investigation_graph.py tests/test_milestone_12_investigation_orchestration.py tests/test_milestone_15_cross_document.py -v
```
* **Exit Code:** `0`
* **Result:** `57 passed in 0.16s`

### 3. Full Regression Suite in Standard Environment (`.venv`)

```bash
.venv/bin/pytest tests/
```
* **Exit Code:** `0`
* **Result:** `361 passed, 5 skipped, 4 warnings in 4.24s`
* **Skips Explanation:** 5 tests skipped cleanly: 1 optional psutil memory stress test, 4 conditional transformer model tests (dedicated to ML environment).
* **Warnings Explanation:** 4 deprecation warnings from upstream `starlette.testclient` and HTTP status code enum constants.

### 4. Full Regression Suite in ML Environment (`.venv_ml`)

```bash
.venv_ml/bin/pytest tests/
```
* **Exit Code:** `0`
* **Result:** `341 passed, 11 skipped in 21.80s`
* **Skips Explanation:** 10 REST API tests skipped cleanly because FastAPI is intentionally omitted from `.venv_ml` to prevent container bloat; 1 psutil test skipped.

---

## 6. Epistemic Limitations & Research Boundaries

The demonstration explicitly documents and prints the four foundational architectural principles and limitations of Sherlock AI:

1. **Extraction is NOT Verification:** Automated information extraction pipelines populate claims in the `UNREVIEWED` status by default. An automated extraction establishes only that a source made an assertion, not that the assertion is factually accurate.
2. **Persistence Boundary:** The default demonstration executes within an ephemeral in-memory graph (`InMemoryInvestigationGraphStore`). In this mode, graph state is volatile and terminates with the process. Durable multi-session persistence requires initializing the engine with `SQLiteInvestigationStore`.
3. **Relationship Semantics:** A relationship edge within the graph represents an asserted or inferred link between entities. It does not constitute proof of identity, legal wrongdoing, or criminal guilt.
4. **Conservative Matching Guard:** High string similarity alone is insufficient to trigger an automated identity merge. Without contextual corroboration (e.g. shared organizations, locations, or identifiers), candidate pairs are conservatively held in the human review queue.
5. **Neo4j Offline Adapter:** The `Neo4jInvestigationGraphAdapter` is an offline typed interface placeholder. Operational calls raise `NotImplementedError` by design to prevent unverified claims of production graph database support without an active Neo4j daemon.

---

## 7. Files Created or Modified

| File | Status | Description of Changes |
| :--- | :--- | :--- |
| `src/core/investigation_demo.py` | **Enhanced** | Added `run_release_demonstration()` implementing the complete 9-stage demonstration scenario. Added CLI argument parser supporting `--release` (default), `--legacy` (Milestone 12), `--milestone8`, `--json`, and `--output`. |
| `src/core/document_cli.py` | **Enhanced** | Added `--demo-release` flag allowing invocation of the Phase 2 release demonstration from the primary document CLI. |
| `artifacts/release_preparation_phase2_report.md` | **Created** | Comprehensive release demonstration report detailing stages, verification results, determinism analysis, and readiness verdict. |

---

## 8. Git Status & Safety Compliance Confirmation

A complete status check confirms strict compliance with all safety constraints:

```bash
git status --short
```

* **Tracked Modifications Preserved:**
  * `README.md`
  * `artifacts/benchmarks/benchmark_results.json`
  * `artifacts/benchmarks/real_world/milestone_7_production_evaluation.md`
  * `artifacts/benchmarks/real_world/milestone_7_results.json`
  * `src/core/__init__.py`
  * `src/core/benchmark.py`
  * `src/core/models.py`
  * `tests/test_clustering.py`
* **Safety Rules Maintained:**
  * Zero Git commits executed.
  * Zero Git pushes executed.
  * Zero resets, cleans, stashes, rebases, or amendments run.
  * Zero new packages or dependencies installed.
  * Zero historical benchmark files or reports overwritten.
  * Zero real-world personally identifiable information (PII) introduced; 100% fictional data.

---

## 9. Conclusion

Sherlock AI Release Preparation Phase 2 is complete. The system demonstrates robust, deterministic, evidence-grounded entity resolution and investigation capabilities in an easily verifiable single-command demonstration suitable for external technical evaluation.
