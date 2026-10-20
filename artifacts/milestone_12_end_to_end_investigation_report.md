# SHERLOCK AI — MILESTONE 12 ACCEPTANCE REPORT
## End-to-End Investigation Engine Integration

**Date:** 2026-10-12  
**Author:** Senior Software Architect, Entity-Resolution Engineer & Test Engineer  
**Repository:** `/home/renjith-cmd/Documents/sherlock-ai-1/entity_resolution_graph_osint/`  
**Git HEAD:** `e245940` (Milestones 1–11 intact, zero destructive operations)  
**Report Schema Version:** `v1.2.0`  
**Target Environments:** Python 3.14.7 default `.venv` (100% offline-capable) & `.venv_ml` (isolated ML environment)

---

## Executive Summary

Milestone 12 unifies Sherlock AI's core capabilities—document ingestion, named entity recognition (NER), grounded relation extraction (RE), pairwise entity resolution (ER), evidence lifecycle management, graph traversal, and epistemic auditing—into a single, reproducible, and deterministic **End-to-End Investigation Engine**.

Prior milestones built high-quality components in isolation (M1–7: Pairwise ER & Clustering; M8: Evidence & Claim Graph Lifecycle; M9: Document Ingestion, Rules NER & RE; M10–11: Model-Backed Extraction & Pretrained Transformer Evaluation). However, the system lacked a unified orchestration service capable of coordinating batch document ingestion, incrementally updating the entity resolution store, tracing multi-document evidence chains, enforcing review protections across re-ingestion, and generating deterministic structured investigation reports.

Milestone 12 delivers this orchestration layer through `InvestigationOrchestrator`, `InvestigationSession`, and `InvestigationReport` in `src/core/investigation_service.py`, supported by an offline demonstration in `src/core/investigation_demo.py`, extended CLI entry points in `src/core/document_cli.py`, and 14 comprehensive tests in `tests/test_milestone_12_investigation_orchestration.py`.

All 292 default tests pass in `.venv` in 3.73 seconds with zero network downloads, and all 297 tests pass in `.venv_ml` in 22.49 seconds.

---

## 1. Original Architecture and Identified Gaps

### 1.1 Existing Architecture Prior to Milestone 12
Before Milestone 12, the repository possessed strong individual subsystems:
1. **Document Ingestion (`src/core/document_ingestion.py`):** Canonical text normalization, parser registry (TXT, JSON, PDF), content-addressable SHA-256 hashing.
2. **Extraction Engine (`src/core/ner.py`, `src/core/relation_extraction.py`):** Rule baseline, model-backed adapters, hybrid extractors producing `EntityMention` and `ExtractedRelationCandidate` with exact text spans.
3. **Pipeline Adapter (`src/core/document_pipeline.py`):** Connected document ingestion, NER, and RE into `Evidence` and `Claim` models with provisional entity placeholders.
4. **Mention-Entity Resolution (`src/core/mention_entity_resolution.py`):** Evaluated mentions against known records using candidate blocking, pairwise comparison, and explainable match decisions (`RESOLVED_MATCH`, `UNRESOLVED_NO_CANDIDATES`, `UNRESOLVED_INSUFFICIENT_EVIDENCE`, `CONFIRMED_NON_MATCH`).
5. **Investigation Graph & Lifecycle (`src/core/investigation_graph.py`, `src/core/investigation_lifecycle.py`):** Enforced referential integrity, status cascading on claim review, bounded cycle-safe traversals, and in-memory graph operations.
6. **Query & Explainability (`src/core/investigation_service.py`):** Generated `RelationshipExplanation` and `InvestigationResult` for bounded graph subgraphs.

### 1.2 Gaps Identified Before Milestone 12
Despite these components, several critical integration gaps prevented a true end-to-end investigation workflow:
- **No Unified Investigation Orchestrator:** Callers had to manually instantiate store, lifecycle manager, query service, mention resolver, and extraction pipeline, and coordinate their lifecycles.
- **Fragmented Multi-Document Ingestion:** Re-ingesting documents or processing multi-document batches lacked a centralized session tracker monitoring per-document status (`PENDING`, `COMPLETED`, `SKIPPED_DUPLICATE`, `FAILED`).
- **Resolver-Store Desynchronization:** As entities were added or discovered in an investigation, there was no automated synchronization mechanism to index newly established entities into `MentionEntityResolver` for cross-document resolution.
- **Partial Failure Invisibility:** An error during one document's processing could silently abort an entire batch or falsely leave an investigation marked as completed.
- **Absence of Audit-Grade Investigation Report:** The system could print subgraphs for single entities, but lacked an investigation-level structured report capturing document hashes, unresolved entity queues, human review requirements, retractions, and epistemic notices.

---

## 2. Integration Design and Files Changed

### 2.1 Component Architecture & Responsibilities

```
                                      +------------------------------------+
                                      |     InvestigationOrchestrator      |
                                      +-----------------+------------------+
                                                        |
                                          manages 1..*  |
                                                        v
                                      +------------------------------------+
                                      |        InvestigationSession        |
                                      |  - investigation_id                |
                                      |  - session status & registry       |
                                      |  - processed_hashes (idempotency)  |
                                      +--------+--------+--------+---------+
                                               |        |        |
         +-------------------------------------+        |        +-------------------------------------+
         |                                              |                                              |
         v                                              v                                              v
+-------------------------------+              +--------------------+              +------------------------------------+
|  DocumentExtractionPipeline   |              | BaseGraphStore     |              |    InvestigationQueryService       |
|  - DocumentIngestionService   | <----------> | (InMemory reference| <----------> |  - Cycle-safe bounded traversal    |
|  - Deterministic Rule NER     |  registers   |  graph store)      |   queries    |  - RelationshipExplanation builder |
|  - Grounded RelationExtractor |   entities   +--------------------+              +------------------------------------+
|  - MentionEntityResolver      |   & claims            ^
+-------------------------------+                       |
         |                                              |
         +----------------------------------------------+
            uses lifecycle manager for claim review,
            contradiction tracking, & status cascade
```

### 2.2 Files Modified and Created

| File | Change Type | Purpose |
| :--- | :--- | :--- |
| `src/core/investigation_service.py` | Enhanced | Added `InvestigationStatus`, `DocumentProcessingStatus`, `DocumentProcessingRecord`, `InvestigationSummary`, `InvestigationReport`, `InvestigationSession`, and `InvestigationOrchestrator`. Preserved 100% backward compatibility for `RelationshipExplanation`, `InvestigationResult`, and `InvestigationQueryService`. |
| `src/core/investigation_demo.py` | Enhanced | Added `run_end_to_end_investigation_demo()` executing a 9-stage synthetic offline scenario. Preserved existing Milestone 8 demo. Added standalone executable script support. |
| `src/core/document_cli.py` | Enhanced | Added `--demo-investigation` and `--report-output` flags to run the end-to-end investigation engine from the CLI. |
| `tests/test_milestone_12_investigation_orchestration.py` | Created | 14 comprehensive unit and integration tests covering multi-document processing, cross-document resolution, idempotency, Unicode offsets, dangling reference protection, ambiguity routing, negation/allegations, retractions, cycle safety, and partial failure recovery. |
| `artifacts/milestone_12_end_to_end_investigation_report.md` | Created | Comprehensive Milestone 12 acceptance report. |

---

## 3. End-to-End Data Flow

The integrated pipeline executes the complete 9-stage investigation lifecycle:

```
[Raw Document Bytes]
         |
         v
1. Document Ingestion & Source Registration (SHA-256 content hashing, UTF-8 normalization)
         |
         v
2. Named Entity Recognition (Extracts EntityMention with char offsets, honorifics, ORG/LOC/DATE/MONEY rules)
         |
         v
3. Grounded Relation Extraction (Extracts ExtractedRelationCandidate with exact sentence span validation)
         |
         v
4. Mention-to-Entity Resolution:
   - Queries MentionEntityResolver against known records and investigation entities.
   - If MATCH: links mention to canonical entity_id.
   - If UNRESOLVED (no candidates or review band): registers explicit provisional entity `unresolved_{mention_id}`.
   - Ambiguity Guard: multiple distinct matches route to REVIEW without forced merge.
         |
         v
5. Evidence & Claim Construction:
   - Evidence object created with exact char offsets, text span, and SHA-256 hash.
   - Claim object created with epistemic qualifiers (negation, allegation, uncertainty).
   - Invariant: automated extractions default to ReviewStatus.UNREVIEWED.
         |
         v
6. Graph Store Registration & Relationship Derivation:
   - Referential integrity verified (preventing dangling references).
   - Typed relationships derived with epistemic tiers (ASSERTED, INFERRED, HUMAN_VERIFIED).
   - Multi-document evidence aggregated into supporting_evidence_ids.
         |
         v
7. Epistemic Adjudication & Lifecycle:
   - Human review (VERIFIED, RETRACTED, REJECTED, SUPERSEDED).
   - Status updates cascade automatically to dependent relationships.
   - Correction history and provenance preserved permanently.
         |
         v
8. Cycle-Safe Bounded Query Traversal:
   - Traverses bounded subgraphs from root entities (max_depth, max_nodes).
   - Distinguishes active disputes from historical contradictions.
         |
         v
9. Structured Investigation Report Generation:
   - Generates deterministic JSON and Markdown reports.
   - Strict read-only operation; zero mutation of investigation state.
```

---

## 4. Demo Scenario and Output

### 4.1 Fictional Scenario Description
The synthetic demonstration scenario involves two confidential intelligence documents concerning a fictional corporate security network:
- **Document 1 (`memo_alpha_101.txt`):**
  - Mentions `Dr. John Watson` working for `Sherlock Security`.
  - Mentions `Sherlock Security` located in `London`.
  - Mentions unverified allegation: `The report alleges that Wayne Enterprises owns Globex Corporation.`
- **Document 2 (`field_dispatch_beta_102.txt`):**
  - Mentions `Dr. John Watson` working for variant name `Sherlock Security Ltd`.
  - Mentions explicit denial: `Alice Smith does not work for Cyberdyne Systems.`
  - Mentions unknown individual: `Marcus Vance was spotted near the docklands warehouse.`

### 4.2 Step-by-Step Execution Verification

```bash
.venv/bin/python -m src.core.document_cli --demo-investigation
```

#### Step 1: Investigation Session Creation
- Initialized investigation session `inv_project_blackthorn_2026`.
- Storage: isolated `InMemoryInvestigationGraphStore`.
- Initial status: `InvestigationStatus.CREATED`.

#### Step 2: Intelligence Baseline Registration
- Registered canonical entities:
  - `ent_dr_watson` (`Dr. John Watson`, PERSON, alias `John Watson`).
  - `ent_sherlock_security` (`Sherlock Security`, ORGANIZATION, alias `Sherlock Security Ltd`).

#### Step 3 & 4: Multi-Document Ingestion & Extraction
- **Document Alpha (`memo_alpha_101.txt`):** Ingested 220 characters; extracted 8 mentions, 3 claims, 3 evidence items.
- **Document Beta (`field_dispatch_beta_102.txt`):** Ingested 224 characters; extracted 7 mentions, 2 claims, 2 evidence items.

#### Step 5: Cross-Document Entity Resolution
- `Dr. John Watson` in Doc 1 and Doc 2 matched `ent_dr_watson`.
- `Sherlock Security` in Doc 1 and `Sherlock Security Ltd` in Doc 2 matched `ent_sherlock_security`.
- Grounded relationship `rel_ent_dr_watson_WORKS_FOR_ent_sherlock_security` derived with multi-evidence support from **both** documents:
  - `ev_08f08cef...` (Document 1, offsets 69–112)
  - `ev_dc19beb8...` (Document 2, offsets 72–119)
- `Marcus Vance` had zero candidate matches; explicitly retained as `UNRESOLVED_NO_CANDIDATES` without false non-match or forced merge.

#### Step 6: Idempotent Duplicate Ingestion Guarantee
- Document Alpha was re-submitted with identical bytes.
- Content hash `08f08cef4007...` detected.
- Status returned: `DocumentProcessingStatus.SKIPPED_DUPLICATE`.
- Total claims before and after remained identical (5 claims); **zero duplicates created**.

#### Step 7: Bounded Query & Evidence Provenance
- Query from root entity `ent_dr_watson` (max_depth=2, max_nodes=10).
- Returned subgraph of 3 entities and 2 relationships with exact evidence IDs, text spans, and source offsets.

#### Step 8: Epistemic Adjudication & Retraction
- Allegation claim `Wayne Enterprises owns Globex Corporation` reviewed.
- Status updated: `ReviewStatus.RETRACTED` with rationale: *"Official corporate registry filings confirm Globex is independent. Memo allegation was hearsay."*
- Cascaded relationship `rel_..._OWNS_...` status automatically updated to `RETRACTED` (Inactive).
- Audit log entry appended to `correction_history`.

#### Step 9: Structured Investigation Report Generation
- Report generated deterministically in Markdown and JSON formats.

```
================================================================================
DEMONSTRATION COMPLETED: ALL 9 WORKFLOW STAGES VERIFIED
================================================================================
```

---

## 5. Idempotency and Lifecycle Guarantees Actually Tested

| Invariant / Guarantee | Verification Mechanism | Test Name | Result |
| :--- | :--- | :--- | :--- |
| **Document Hash Deduplication** | SHA-256 hash detection returns `SKIPPED_DUPLICATE` | `test_idempotent_reingestion_no_duplicates` | **PASSED** |
| **No Duplicate Claims/Evidence** | Graph claim and evidence counts remain unchanged on re-ingestion | `test_idempotent_reingestion_no_duplicates` | **PASSED** |
| **Human Review Preservation** | Re-ingesting a document does not reset reviewed, verified, or retracted claims | `test_idempotency_preserves_human_review` | **PASSED** |
| **Status Cascade on Retraction** | Retracting a supporting claim automatically transitions the relationship to `RETRACTED` | `test_retraction_and_cascade_lifecycle` | **PASSED** |
| **Audit Log Provenance** | `ClaimCorrection` records previous status, rationale, timestamp, and reviewer | `test_retraction_and_cascade_lifecycle` | **PASSED** |
| **Historical vs Active Disputes** | Inactive retracted relationships are not reported as current active disputes | `test_retraction_and_cascade_lifecycle` | **PASSED** |
| **Raw Content Immutability** | Ingested document normalized text and attributes cannot be mutated | `test_raw_ingested_document_immutability` | **PASSED** |
| **Partial Failure Recovery** | Corrupted document marks status `FAILED` without failing valid documents | `test_partial_processing_failure_visibility_and_retry` | **PASSED** |

---

## 6. Provenance and Safety Checks

### 6.1 Source-Span Integrity
- Every extracted `Evidence` item is strictly checked against the exact source text of the ingested document.
- In `test_source_span_integrity_and_unicode_offsets`, text containing accents and non-ASCII characters (`René François`, `Zürich`) was ingested. The extracted span `text[start:end]` was verified to match `ev.text_span` character-for-character.
- If offsets are invalid or do not match the expected substring, candidate grounding is rejected.

### 6.2 Referential Integrity (No Dangling References)
- The graph store prevents dangling references:
  - Claims cannot reference nonexistent evidence IDs (`ValueError`).
  - Claims cannot reference unregistered subject/object entities unless flagged as unresolved provisional entities (`ValueError`).
  - Relationships cannot connect unregistered entities (`ValueError`).
  - Verified in `test_referential_integrity_no_dangling_entities`.

### 6.3 Entity Resolution Safety
- **No Confirmed Non-Match from Candidate Absence:** A mention with no blocking candidates is marked `UNRESOLVED_NO_CANDIDATES`, preserving candidate absence distinct from confirmed non-match.
- **Ambiguity Routing:** When a mention matches multiple distinct known records, `MentionEntityResolver` routes the decision to `DecisionType.REVIEW` (`UNRESOLVED_INSUFFICIENT_EVIDENCE`), refusing to perform an automatic forced merge. Verified in `test_conflicting_match_decisions_route_to_review`.
- **Model Confidence != Identity Probability:** Extractor model confidence scores are recorded as heuristic metadata and are never used as match decision thresholds.

---

## 7. Test and Compilation Results

### 7.1 Python Compilation Check
```bash
.venv/bin/python -m compileall src/ tests/
```
**Result:** Exit code 0. Zero syntax or compilation errors across `src/` and `tests/`.

### 7.2 Git Diff Check
```bash
git diff --check
```
**Result:** Exit code 0. Clean formatting, no whitespace or merge marker issues.

### 7.3 Milestone 12 Targeted Integration Suite
```bash
.venv/bin/pytest tests/test_milestone_12_investigation_orchestration.py -v
```
**Result:**
```
tests/test_milestone_12_investigation_orchestration.py::TestInvestigationOrchestrationEndToEnd::test_single_document_successful_processing PASSED [  7%]
tests/test_milestone_12_investigation_orchestration.py::TestInvestigationOrchestrationEndToEnd::test_multi_document_cross_references PASSED [ 14%]
tests/test_milestone_12_investigation_orchestration.py::TestInvestigationOrchestrationEndToEnd::test_idempotent_reingestion_no_duplicates PASSED [ 21%]
tests/test_milestone_12_investigation_orchestration.py::TestInvestigationOrchestrationEndToEnd::test_idempotency_preserves_human_review PASSED [ 28%]
tests/test_milestone_12_investigation_orchestration.py::TestInvestigationOrchestrationEndToEnd::test_source_span_integrity_and_unicode_offsets PASSED [ 35%]
tests/test_milestone_12_investigation_orchestration.py::TestInvestigationOrchestrationEndToEnd::test_no_candidate_unresolved_behavior PASSED [ 42%]
tests/test_milestone_12_investigation_orchestration.py::TestInvestigationOrchestrationEndToEnd::test_conflicting_match_decisions_route_to_review PASSED [ 50%]
tests/test_milestone_12_investigation_orchestration.py::TestInvestigationOrchestrationEndToEnd::test_negation_and_allegations_epistemic_qualifiers PASSED [ 57%]
tests/test_milestone_12_investigation_orchestration.py::TestInvestigationOrchestrationEndToEnd::test_retraction_and_cascade_lifecycle PASSED [ 64%]
tests/test_milestone_12_investigation_orchestration.py::TestInvestigationOrchestrationEndToEnd::test_cycle_safe_graph_traversal_and_bounds PASSED [ 71%]
tests/test_milestone_12_investigation_orchestration.py::TestInvestigationOrchestrationEndToEnd::test_partial_processing_failure_visibility_and_retry PASSED [ 78%]
tests/test_milestone_12_investigation_orchestration.py::TestInvestigationOrchestrationEndToEnd::test_report_determinism_and_provenance PASSED [ 85%]
tests/test_milestone_12_investigation_orchestration.py::TestInvestigationOrchestrationEndToEnd::test_referential_integrity_no_dangling_entities PASSED [ 92%]
tests/test_milestone_12_investigation_orchestration.py::TestInvestigationOrchestrationEndToEnd::test_raw_ingested_document_immutability PASSED [100%]

============================== 14 passed in 0.12s ==============================
```

### 7.4 Full Default Environment Test Suite (`.venv`)
```bash
.venv/bin/pytest tests/
```
**Result:**
```
======================== 292 passed, 5 skipped in 3.73s ========================
```
*(The 5 skipped tests are model-backed integration tests that gracefully skip when heavy transformers are not installed in the offline environment).*

### 7.5 ML Environment Test Suite (`.venv_ml`)
```bash
.venv_ml/bin/pytest tests/
```
**Result:**
```
============================= 297 passed in 22.49s =============================
```
*(All 297 tests pass, including real BERT transformer inference and comparative benchmarks).*

### 7.6 Demonstration Idempotency Verification
The demonstration was executed twice consecutively via `.venv/bin/python src/core/investigation_demo.py`. Both runs produced identical outputs, identical entity clusters, identical relationship subgraphs, and identical metrics:
- Total Documents: 2
- Total Claims: 5 (1 Retracted)
- Total Relationships: 3 (2 Active, 1 Retracted)
- Total Evidence Spans: 5
- Human Review Queue Items: 15

---

## 8. Persistence and Performance Limitations

1. **In-Memory Volatility:**
   - The current graph persistence implementation is `InMemoryInvestigationGraphStore`.
   - All investigations, sessions, entities, claims, and audit logs reside strictly in Python process heap memory.
   - **Data does not survive process termination.**
   - The report explicitly includes a prominent disclaimer: *"In-memory reference graph. Graph state is volatile and does not survive process termination. External durable persistence is not enabled in this prototype."*
2. **Neo4j Adapter Status:**
   - The `Neo4jInvestigationGraphAdapter` is a research bridge and is not connected to a live production database instance in this milestone.
3. **Memory Scalability:**
   - Because documents, text spans, and mention resolutions are held in memory, processing dossiers exceeding hundreds of megabytes in a single session may require database-backed pagination.

---

## 9. Remaining Risks and Follow-Up Work

1. **Durable Database Backend (Milestone 13+):**
   - Implement production-grade transactional persistence (e.g. Postgres + pgvector or Neo4j Aura) with ACID guarantees and disk durability.
2. **Automated Cross-Document Coreference Resolution:**
   - Enhance the pipeline to resolve pronominal and nominal anaphoric references across document boundaries (e.g. "he", "the CEO", "the suspect").
3. **Interactive Human-in-the-Loop Adjudication Interface:**
   - Provide an investigator UI or REST API allowing analysts to inspect the review queue, merge or split provisional entities, and adjudicate disputes interactively.

---

## 10. Final Acceptance Verdict

### ACCEPTED (Unconditional)

**Summary of Acceptance Criteria Met:**
- [x] **Workspace Protection:** No git commits, no git pushes, no destructive operations (`reset`, `clean`, `rebase`), zero work discarded.
- [x] **Offline Capability:** Default `.venv` runs 100% offline without Hugging Face downloads; 292 tests pass in 3.73s.
- [x] **Full Compatibility:** `.venv_ml` passes all 297 tests in 22.49s.
- [x] **Single Orchestrator:** `InvestigationOrchestrator` integrates document ingestion, NER, relation extraction, mention resolution, graph reasoning, and reporting.
- [x] **Epistemic Discipline:** Distinguishes source assertions, inferences, contradictions, and human reviews. Automated claims default to `UNREVIEWED`.
- [x] **Idempotency:** Re-ingesting documents deduplicates cleanly via SHA-256 hashes without duplicating claims or erasing human reviews.
- [x] **Provenance Integrity:** Text offsets validated against exact source text; no dangling entity or evidence references.
- [x] **Entity Resolution Safety:** Preserves `UNRESOLVED_NO_CANDIDATES`, routes ambiguous matches to `REVIEW`, refuses ungrounded merges.
- [x] **Synthetic Demo:** Fully functional, offline, 9-stage fictional demonstration verified twice with reproducible outputs.
- [x] **CLI Integration:** Documented `--demo-investigation` and `--report-output` command-line flags.
- [x] **Regression Free:** Zero regressions across all pre-existing tests.
