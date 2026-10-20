# Sherlock AI — Milestone 15 Initial Architecture & Baseline Audit

**Audit Date:** October 12, 2026  
**Auditor:** Senior Entity-Resolution Engineer, Knowledge-Graph Architect, and Adversarial Test Engineer  
**Scope:** Milestone 15 Phase 0 — Baseline Verification & Cross-Document Architecture Mapping  
**Repository:** `/home/renjith-cmd/Documents/sherlock-ai-1/entity_resolution_graph_osint/`  
**Status:** Audit Complete — No Blockers Identified; Proceeding to Phase 1  

---

## 1. Repository Safety & Environment Baseline

### 1.1 Git Hygiene & Preservation Status
- **Current Head Commit:** `e245940 (HEAD -> main) feat(core): implement Milestone 7 production-grade entity resolution, multi-policy evaluation, and leakage-free benchmarking`
- **Tracked Modifications:** Pre-existing milestone modifications preserved in `src/core/__init__.py`, `src/core/benchmark.py`, `src/core/models.py`, `tests/test_clustering.py`, and benchmark reports.
- **Untracked Artifacts:** All Milestone 8–14 artifacts and tests are preserved intact. Zero resets, rebases, stashes, cleans, or commits executed.
- **Static Compilation:** `.venv/bin/python -m compileall -q src tests` exited with code `0`.
- **Patch Formatting:** `git diff --check` exited with code `0` (clean, zero trailing whitespace defects).

### 1.2 Baseline Test Suites Execution
| Environment | Execution Command | Exit Code | Passed | Skipped | Failed | Total | Duration |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Standard (`.venv`)** | `.venv/bin/pytest tests/` | `0` | **345** | **5** | **0** | 350 | 4.25s |
| **Machine Learning (`.venv_ml`)** | `.venv_ml/bin/pytest tests/` | `0` | **325** | **11** | **0** | 336 | 20.51s |

#### Skipped Test Rationale
- **5 tests in `.venv`:** Dynamically skip tests in `tests/test_milestone_11_real_model_evaluation.py` requiring optional `torch` and `transformers`.
- **11 tests in `.venv_ml`:** 10 REST API tests in `tests/test_milestone_14_hardening.py` skip cleanly because `fastapi`/`starlette` is omitted from the ML environment; 1 test skips due to optional `psutil`. All SQLite, graph, and core algorithms pass 100%.

---

## 2. End-to-End Investigation Workflow Mapping

The existing Sherlock AI investigation lifecycle connects ingestion, extraction, resolution, epistemic modeling, and persistence across nine distinct modules:

```
[Raw Document / File]
        │
        ▼
[DocumentIngestionService] ─── Normalized text, SHA-256 hash, format validation
        │
        ▼
[DocumentExtractionPipeline]
  ├── NER Extractor (Rule / Model) ─────── List[EntityMention]
  ├── Grounded Relation Extractor ──────── List[ExtractedRelationCandidate]
  └── MentionEntityResolver ────────────── List[MentionResolutionResult]
        │
        ▼
[InvestigationLifecycleManager]
  ├── Ingest Evidence ──────────────────── Evidence items with char offsets
  ├── Register Claims ──────────────────── Claims linked to evidence
  └── Derive Relationships ─────────────── Typed directed relationships
        │
        ▼
[InvestigationSession / InMemoryInvestigationGraphStore]
  └── In-memory graph state: entities, claims, evidence, relationships
        │
        ▼
[SQLiteInvestigationStore]
  └── Atomic multi-table persistence via sync_session() with WAL mode
```

---

## 3. Canonical Identifiers Specification

The system enforces deterministic, collision-safe identifier conventions:

1. **Document Identifier:** `doc_{content_hash[:16]}`
   - Formed from SHA-256 digest of raw bytes.
2. **Mention Identifier:** `men_{doc_prefix}_{start_char}_{end_char}`
   - Uniquely identifies a surface span within a specific document.
3. **Evidence Identifier:** `ev_{doc_hash_prefix}_{candidate_id}`
   - Links verbatim text span with exact character offsets `(start_char, end_char)`.
4. **Claim Identifier:** `claim_{doc_hash_prefix}_{candidate_id}`
   - Encapsulates subject reference, predicate, object reference, and supporting/contradicting evidence.
5. **Entity Identifier:**
   - Pre-existing / Canonical: `ent_{uuid}` or user-specified ID.
   - Provisional Unresolved: `unresolved_{mention_id}` created by `_resolve_entity_reference()` when mention resolution does not find a confident match.
6. **Relationship Identifier:** `rel_{subject_id}_{predicate}_{object_id}`
   - Joins subject and object entities with epistemic tier (`ASSERTED`, `INFERRED`, `VERIFIED`).

---

## 4. Current State of Cross-Document Entity Resolution

### 4.1 How Mentions Are Currently Resolved
In `src/core/document_pipeline.py`:
1. When a document is ingested, `ner_extractor` generates `EntityMention` instances.
2. The mentions are passed to `MentionEntityResolver.resolve_mentions()`.
3. `MentionEntityResolver` checks `self.known_records`.
4. However, in `InvestigationSession.sync_store_entities_to_resolver()`:
   ```python
   for ent in self.store.list_entities():
       if not ent.metadata.get("provisional"):
           if ent.entity_id not in self.resolver.known_records:
               # register as known record...
   ```
5. Any mention that did not match an existing non-provisional entity is registered in `self.store` as:
   ```python
   provisional_id = f"unresolved_{mention.mention_id}"
   self.lifecycle_manager.register_unresolved_entity(
       mention_id=provisional_id,
       raw_name=raw_name,
       entity_type=mention.entity_type,
   )  # ent.metadata = {"provisional": True, "unresolved": True}
   ```

### 4.2 Architectural Defect & Cross-Document Limitation
Because provisional entities have `metadata["provisional"] = True`, they are **never** synced to `resolver.known_records`. As a result:
- When Document A introduces "Alice Mercer" (CEO of Apex Global), it becomes `unresolved_men_docA_0_12`.
- When Document B introduces "Alice Mercer" (Director of Apex Global), `resolver.known_records` still has zero records.
- Document B's mention becomes `unresolved_men_docB_0_12`.
- **Mentions across different documents never resolve to each other automatically.**
- There is currently no cross-document mention clustering engine that can evaluate all mentions in an investigation across documents, block them, compare contextual attributes, generate explainable match decisions, propose entity clusters, and allow analyst review or reversal.

---

## 5. Lifecycle, Re-Ingestion, and Claim Retraction Analysis

### 5.1 Re-Ingestion & Idempotency
- When an identical document is re-ingested (matching `content_hash`), `process_document()` detects it via `session.processed_hashes` and returns `DocumentProcessingStatus.SKIPPED_DUPLICATE` without mutating graph state.
- When re-processing is forced (`force_reprocess=True`), the pipeline extracts claims again, but checks:
  ```python
  if existing_claim and existing_claim.review_status in (
      ReviewStatus.RETRACTED, ReviewStatus.REJECTED,
      ReviewStatus.VERIFIED, ReviewStatus.SUPERSEDED
  ):
      claims.append(existing_claim)
      preserved_reviewed_claims.append(claim_id)
      continue
  ```
  Human review decisions on claims are preserved.

### 5.2 Claim Retraction & Contradiction
- In `InvestigationLifecycleManager.review_claim()`:
  - Transitioning a claim to `RETRACTED` updates the claim's status.
  - In `InvestigationLifecycleManager.record_contradiction()`:
    - Adding a contradicting claim against an existing relationship transitions the relationship's review status to `DISPUTED` and populates `contradicting_claim_ids` and `contradicting_evidence_ids`.
- In `InvestigationLifecycleManager.recluster_and_rebuild()`:
  - Calling `rebuild_derived_graph(clusters, record_to_cluster_map)` re-maps relationship endpoints to new cluster IDs without deleting claims or evidence.

---

## 6. Required Milestone 15 Capabilities & Implementation Plan

### Phase 1: Cross-Document Entity Resolution Engine
1. **`CrossDocumentEntityResolver`:**
   - Dedicated service that collects all mentions (both resolved and provisional) across all documents in an investigation session.
   - Deterministic candidate generation across documents utilizing:
     - Surface text and normalized name similarity (Jaro-Winkler, Levenshtein, Token Sort).
     - Entity type compatibility (strict matching; cross-type matching forbidden).
     - Contextual attributes: co-occurring organizations, locations, titles, temporal tags.
     - Document co-occurrence signal (distinguishing intra-document coreference from cross-document duplication).
     - Verified match history and explicit non-match constraints.
   - Conservative Pairwise Decision Engine:
     - `MATCH`, `NON_MATCH`, `REVIEW`.
     - Explicit decision breakdown: positive evidence, negative evidence, missing info, hard constraints, and human-readable explanation.
     - High name similarity alone without corroboration or with conflicting context routes to `REVIEW`.
   - Reversible Merge & Split Architecture:
     - Reversible clustering (`EntityCluster`).
     - Explicit merge action, merge reversal, entity split action.
     - Preserving human review decisions and non-match constraints across re-clustering.

### Phase 2: Evidence-Grounded Relationship Resolution
1. Enhance relationship derivation:
   - Explicit provenance tracking on every relationship: source document, exact text span, content hash, extraction method.
   - Epistemic classification:
     - `SOURCE_ASSERTED` (direct affirmative statement).
     - `SOURCE_DENIED` (explicit negation).
     - `SOURCE_QUOTED` (attributed quote / allegation).
     - `MODEL_INFERRED` (heuristic or graph-derived).
     - `DISPUTED` (conflicting reports across sources).
     - `HUMAN_VERIFIED` (adjudicated by analyst).
   - Duplicate Evidence De-biasing:
     - Detect identical source statements / identical content hashes so duplicated documents do not falsely inflate corroboration counts.

### Phase 3: Explainable Investigation Reporting
1. Extend `InvestigationReportGenerator`:
   - Document inventory and processing audit.
   - Entity profiles with cross-document mention clusters and aliases.
   - Proposed identity links with traceable evidence and review queues.
   - Relationship inventory categorized by epistemic status.
   - Contradiction and uncertainty analysis.
   - Limitations and reproducibility summary.

### Phase 4: Adversarial Regression Testing
1. Dedicated test suite `tests/test_milestone_15_cross_document.py` covering:
   - Same name, different person; different name/spelling, same person.
   - Organization name variations vs distinct corporate entities.
   - Missing attributes (must not assume agreement).
   - Conflicting identifiers (must prevent merge).
   - Transitive merge cascade prevention.
   - Merge reversal and entity splitting.
   - Duplicate statement deduplication.
   - Negation scope and quoted statements.
   - Persistence and API endpoint verification.

### Phase 5: Benchmark & Quality Evaluation
1. Fictional multi-document cross-entity evaluation dataset with ground truth.
2. Generate benchmark results in `artifacts/benchmarks/milestone_15/`.

---

## 7. Audit Verdict

**Verdict:** **NO BLOCKERS DETECTED — PROCEED WITH PHASE 1 IMPLEMENTATION.**  
The repository architecture cleanly isolates data models, stores, lifecycles, and engines, providing the exact extension points needed to implement cross-document resolution without breaking existing functionality.
