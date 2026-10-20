# Sherlock AI — Milestone 8 Technical Report
## Evidence Provenance, Relationship Modeling & Investigation Graph

**Status:** Completed & Formally Verified  
**Date:** October 12, 2026  
**Environment:** Linux (Python 3.14.7, pytest 9.1.1, pydantic 2.11.0a0)  
**Test Suite Baseline:** 201 passing tests (174 regression + 27 Milestone 8 invariant tests) in 3.33s  

---

### Executive Summary

Milestone 8 introduces the **Evidence Provenance, Relationship Modeling, and Investigation Graph Layer** for Sherlock AI. 

In intelligence analysis and OSINT investigations, raw records and factual statements must never be conflated with established facts. For example, if two records mention the same person, or an unverified leak document alleges that a person owns a corporation, the system must not silently merge entities or treat allegations as ground truth. Milestone 8 establishes a mathematically disciplined, epistemically stratified investigation graph where:
1. **Raw records** remain immutable observations.
2. **Resolved entities** maintain reversible cluster memberships derived from entity resolution decisions.
3. **Evidence items** capture verifiable provenance (source URIs, publication timestamps, text spans, offsets, content hashes).
4. **Claims** represent extracted assertions independently of entities and evidence, with explicit extraction methods, review statuses, and confidence semantics.
5. **Relationships** link entities through supporting claims while preserving contradictory evidence, review states, and epistemic tiers (`ASSERTED`, `INFERRED`, `HUMAN_VERIFIED`).
6. **Investigation queries** execute cycle-safe, bounded graph traversals that produce verifiable, human-readable explainability traces back to root sources.

---

### 1. Architecture & Design Decisions

#### 1.1 Architectural Separation of Concerns

```
+---------------------------------------------------------------------------------------------------+
|                                  SHERLOCK AI ARCHITECTURE STACK                                    |
+---------------------------------------------------------------------------------------------------+
|  [Layer 5: Investigation & Explainability]                                                        |
|  - InvestigationQueryService: Bounded BFS/DFS traversal, cycle protection                         |
|  - RelationshipExplanation & Markdown Audit Reports                                               |
+---------------------------------------------------------------------------------------------------+
|  [Layer 4: Investigation Lifecycle & Reversibility]                                               |
|  - InvestigationLifecycleManager: Ingestion -> Extraction -> Derivation -> Review -> Rebuild       |
|  - Re-clustering synchronization without mutating historical claims or evidence                   |
+---------------------------------------------------------------------------------------------------+
|  [Layer 3: Graph Storage & Indexing]                                                              |
|  - BaseInvestigationGraphStore (Abstract Protocol Interface)                                     |
|  - InMemoryInvestigationGraphStore (Deterministic In-Memory reference implementation)             |
|  - Neo4jInvestigationGraphAdapter (Offline-safe driver bridge)                                     |
+---------------------------------------------------------------------------------------------------+
|  [Layer 2: Domain Data Contracts (src/core/models.py)]                                            |
|  - ImmutableBaseModel: Deep immutability via MappingProxyType, tuple, frozenset                   |
|  - Enums: ReviewStatus, RelationshipEpistemicTier, ConfidenceSemantics                            |
|  - Models: Record, EntityCluster, InvestigationEntity, Evidence, Claim, ClaimCorrection, Rel.     |
+---------------------------------------------------------------------------------------------------+
|  [Layer 1: Identity & Entity Resolution Engine (Milestones 1-7)]                                  |
|  - Normalization, Candidate Blocking, Pairwise Comparison, Decision Engine, Clusterer              |
+---------------------------------------------------------------------------------------------------+
```

#### 1.2 Key Architectural Decisions

1. **Epistemic Layering (Separation of Identity vs Allegation):**
   - *Problem:* Traditional graph databases frequently merge entities when relationships are extracted (e.g., merging "Alice Vance" and "Dr. E. Vance" because both are listed as directors), or treat extracted edges as verified facts.
   - *Design Decision:* Entity identity resolution is strictly segregated from relational extraction. Entity memberships derive solely from pairwise comparison rules and transitive clustering (Milestones 1–7). Relationships are derived views over extracted claims and do not feed back into identity merging.

2. **Claim & Evidence Decoupling:**
   - *Design Decision:* Claims (`Claim`) are first-class immutable records containing subject, predicate, object, qualifiers, and validity intervals. Evidence (`Evidence`) represents atomic pieces of source material. A single claim can be supported by multiple pieces of evidence from disparate sources, and multiple claims can refer to the same evidence.

3. **Multi-Source Support & Non-Destructive Contradiction Modeling:**
   - *Design Decision:* When contradictory claims emerge (e.g., Claim A asserts ownership while Claim B asserts divestment), the system does not silently discard earlier claims or overwrite the graph state. Both claims and their underlying evidence remain linked to the relationship, transitioning its status to `DISPUTED` and exposing both sides in the investigation audit trail.

4. **Audit History & Reversible Correction Lifecycle:**
   - *Design Decision:* Claims and relationships are immutable. When an analyst reviews, supersedes, or retracts a claim, the system generates a `ClaimCorrection` record detailing the reviewer, timestamp, previous status, new status, and justification rationale. Dependent relationships automatically recalculate their review state.

5. **Storage Abstraction & Offline Execution:**
   - *Design Decision:* To ensure zero test infrastructure dependencies, `BaseInvestigationGraphStore` defines the storage protocol. `InMemoryInvestigationGraphStore` provides deterministic, indexed, in-memory operations for all tests and local processing. `Neo4jInvestigationGraphAdapter` is provided as an adapter bridge with graceful offline checks.

---

### 2. Data Models & Core Invariants

All models inherit from `ImmutableBaseModel`, guaranteeing deep freeze via `MappingProxyType`, `tuple`, and `frozenset`.

#### 2.1 Enums

- **`ReviewStatus`**: `UNREVIEWED`, `VERIFIED`, `DISPUTED`, `REJECTED`, `SUPERSEDED`, `RETRACTED`.
- **`RelationshipEpistemicTier`**:
  - `ASSERTED`: Directly asserted by a source document or claim.
  - `INFERRED`: Derived algorithmically (e.g., transitive corporate ownership, co-location inference).
  - `HUMAN_VERIFIED`: Confirmed and adjudicated by a human intelligence analyst.
- **`ConfidenceSemantics`**:
  - `HEURISTIC_SCORE`: Rule-based matching score, not a probability.
  - `UNCALIBRATED_MODEL`: Raw machine learning or NLP model output.
  - `CALIBRATED_PROBABILITY`: Empirically validated statistical probability.
  - `HUMAN_AFFIRMED`: Confidence assigned by an analyst.

#### 2.2 Model Schema & Invariants

| Model | Key Fields | Invariants & Validation Rules |
| :--- | :--- | :--- |
| **`Evidence`** | `evidence_id`, `evidence_type`, `polarity`, `content`, `source_uri`, `publication_time`, `text_span`, `content_hash`, `provenance`, `strength` | `evidence_id`, `evidence_type` must be non-empty strings. `provenance` is mandatory. `strength` bounded in $[0.0, 1.0]$. Bidirectional syncing for `source_id`/`source_reference`. |
| **`Claim`** | `claim_id`, `subject_id`, `predicate`, `object_id`, `supporting_evidence_ids`, `contradicting_evidence_ids`, `review_status`, `confidence`, `correction_history` | `confidence` bounded in $[0.0, 1.0]$. When `SUPERSEDED`, `superseded_by_claim_id` is mandatory. When `RETRACTED`, `retraction_reason` is mandatory. |
| **`ClaimCorrection`** | `correction_id`, `corrected_at`, `corrected_by`, `previous_status`, `new_status`, `rationale`, `previous_claim_id`, `replacement_claim_id` | Audit record of status changes; rationale and author are required. |
| **`Relationship`** | `relationship_id`, `source_entity_id`, `target_entity_id`, `relationship_type`, `epistemic_tier`, `supporting_claim_ids`, `supporting_evidence_ids`, `contradicting_claim_ids`, `review_status` | Source and target entities must exist in store before relationship can be added (prevents dangling references). |
| **`InvestigationEntity`** | `entity_id`, `entity_type`, `canonical_name`, `member_record_ids`, `cluster_id`, `metadata` | Can represent a resolved cluster or a provisional unresolved mention. |

---

### 3. Evidence Lifecycle

The lifecycle follows a deterministic 9-stage sequence:

```mermaid
flowchart TD
    S1[1. Ingest Record / Source] --> S2[2. Validate & Normalize Metadata]
    S2 --> S3[3. Extract Claim]
    S3 --> S4[4. Link Supporting Evidence]
    S4 --> S5[5. Resolve Participants to Entities]
    S5 --> S6[6. Derive Typed Relationship]
    S6 --> S7[7. Review / Dispute / Retract]
    S7 --> S8[8. Re-cluster & Rebuild Graph Views]
    S8 --> S9[9. Produce Explainable Investigation Report]
```

1. **Ingest Record / Evidence:** Raw record is stored immutably without altering fields.
2. **Normalize Metadata:** Normalizes URIs, hashes, and attributes while preserving raw data.
3. **Extract Claim:** Extracts subject, predicate, object, and temporal intervals with an explicitly documented method (e.g., `sec_parser_v3`, `relation_extractor_v2`).
4. **Link Evidence:** Verifies that referenced evidence items exist and links them to the claim.
5. **Resolve Participants:** Maps subject and object to existing entity clusters. If an entity is unknown or ambiguous, registers a provisional entity with `unresolved=True`, preserving reference integrity without hallucinating merges.
6. **Derive Relationship:** Instantiates a `Relationship` linking entities with epistemic tier `ASSERTED`. If multiple claims support the relationship, aggregates them.
7. **Review & Dispute:** Analysts can review claims. If contradictory claims are ingested, both sides are retained, and the relationship enters `DISPUTED` status.
8. **Re-clustering Rebuild:** If entity resolution splits or merges clusters, the derived relationship endpoints are updated to reflect the new clusters without deleting historical claims or altering raw evidence.
9. **Investigation Report:** Generates a structured narrative and path trace highlighting verified vs unreviewed vs disputed claims.

---

### 4. Deterministic Investigation Demonstration

The test fixture in `src/core/investigation_demo.py` executes a full lifecycle demonstration using fictional records:

#### 4.1 Fictional Scenario Setup
- **Source Record 1 (`rec_fict_corp_01`):** "Aperture Holdings Inc." from Delaware Corporate Registry.
- **Source Record 2 (`rec_fict_sec_02`):** "Aperture Holdings Incorporated" from SEC EDGAR.
- **Source Record 3 (`rec_fict_person_01`):** "Dr. Elena Vance" from Academic Registry.
- **Resolution:** Entity clustering resolves Records 1 & 2 into `cluster_fict_aperture_holdings`. Record 3 forms `cluster_fict_elena_vance`.

#### 4.2 Ingestion & Claim Extraction
- **Evidence 1 (`ev_fict_leak_2023`):** Leaked memo alleging: *"Dr. Elena Vance holds 52% controlling interest in Aperture Holdings Inc."* (URI: `https://fictional-leaks.example.org/docs/cascade_memo_2023.pdf`, Content Hash: `2a1ef9dfb032...`).
- **Claim 1 (`cl_fict_vance_ownership`):** `cluster_fict_elena_vance` —[`BENEFICIAL_OWNER_OF`]—> `cluster_fict_aperture_holdings`.
- **Relationship (`rel_fict_vance_owns_aperture`):** Epistemic tier `ASSERTED`, Review status `UNREVIEWED`.

#### 4.3 Initial Investigation Query Output

```markdown
# Sherlock AI Investigation Report
**Root Entity ID:** `cluster_fict_elena_vance`
**Traversal Constraints:** Max Depth = 2, Max Nodes = 50
**Discovered Scope:** 2 Entities, 1 Relationships, 1 Claims, 1 Evidence Items.

## Summary Metrics
- **Disputed Claims:** 0
- **Unreviewed Claims:** 1
- **Unsupported Relationships:** 0

## Entities
- **`cluster_fict_aperture_holdings`** [ORGANIZATION]: Aperture Holdings Inc. (records: ('rec_fict_corp_01', 'rec_fict_sec_02'))
- **`cluster_fict_elena_vance`** [PERSON] (ROOT): Dr. Elena Vance (records: ('rec_fict_person_01',))

## Relationships & Evidence Provenance
### Relationship `rel_fict_vance_owns_aperture`: `cluster_fict_elena_vance` —[BENEFICIAL_OWNER_OF]—> `cluster_fict_aperture_holdings`
- **Epistemic Tier:** `ASSERTED`
- **Review Status:** `UNREVIEWED`
- **Explanation:** [ASSERTED] Entity `cluster_fict_elena_vance` is linked to `cluster_fict_aperture_holdings` via BENEFICIAL_OWNER_OF. Supported by claims: [`cl_fict_vance_ownership`] and evidence: [`ev_fict_leak_2023`].
- **Supporting Evidence:** `ev_fict_leak_2023`
```

#### 4.4 Ingestion of Contradictory Evidence & Dispute Modeling
- **Evidence 2 (`ev_fict_audit_2024`):** Audited SEC 10-K filing stating: *"Dr. Elena Vance divested 100% equity stake in Aperture Holdings on 2024-01-10."*
- **Contradicting Claim (`cl_fict_vance_divested`):** `NOT_BENEFICIAL_OWNER_OF`.
- **Resulting Investigation Query Output:**
  ```markdown
  ### Relationship `rel_fict_vance_owns_aperture`: `cluster_fict_elena_vance` —[BENEFICIAL_OWNER_OF]—> `cluster_fict_aperture_holdings`
  - **Epistemic Tier:** `ASSERTED`
  - **Review Status:** `DISPUTED`
  - **Explanation:** [ASSERTED] Entity `cluster_fict_elena_vance` is linked to `cluster_fict_aperture_holdings` via BENEFICIAL_OWNER_OF. Supported by claims: [`cl_fict_vance_ownership`] and evidence: [`ev_fict_leak_2023`]. CONTRADICTION DETECTED: Disputed by claims: [`cl_fict_vance_divested`], evidence: [`ev_fict_audit_2024`].
  - **Supporting Evidence:** `ev_fict_leak_2023`
  - **Contradicting Evidence:** `ev_fict_audit_2024`
  ```

#### 4.5 Human Review, Retraction & Reversibility
- **Action:** Analyst reviews the audited SEC filing and retracts `cl_fict_vance_ownership` with rationale: *"2024 SEC 10-K filing confirms total divestment; 2023 memo is superseded."*
- **Resulting Investigation Query Output:**
  ```markdown
  ### Relationship `rel_fict_vance_owns_aperture`: `cluster_fict_elena_vance` —[BENEFICIAL_OWNER_OF]—> `cluster_fict_aperture_holdings`
  - **Epistemic Tier:** `ASSERTED`
  - **Review Status:** `RETRACTED`
  - **Explanation:** [ASSERTED] Entity `cluster_fict_elena_vance` is linked to `cluster_fict_aperture_holdings` via BENEFICIAL_OWNER_OF. Supported by claims: [`cl_fict_vance_ownership`] and evidence: [`ev_fict_leak_2023`]. CONTRADICTION DETECTED: Disputed by claims: [`cl_fict_vance_divested`], evidence: [`ev_fict_audit_2024`]. STATUS ALERT: Relationship has been marked RETRACTED.
  - **Supporting Evidence:** `ev_fict_leak_2023`
  - **Contradicting Evidence:** `ev_fict_audit_2024`
  ```

---

### 5. Verification & Test Execution Results

The test suite was run using `.venv/bin/pytest` covering all 201 tests:

```
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/renjith-cmd/Documents/sherlock-ai-1/entity_resolution_graph_osint
configfile: pytest.ini
testpaths: tests
collected 201 items

tests/test_benchmark.py ...................                              [  9%]
tests/test_blocking.py ........................                          [ 21%]
tests/test_clustering.py ......................                          [ 32%]
tests/test_comparison.py .................                               [ 40%]
tests/test_dataset_integrity.py .....                                    [ 43%]
tests/test_datasets.py ............                                      [ 49%]
tests/test_decision.py ........................                          [ 61%]
tests/test_evaluation.py .............                                   [ 67%]
tests/test_investigation_graph.py ...........................            [ 81%]
tests/test_models.py .........................                           [ 93%]
tests/test_normalization.py .............                                [100%]

============================= 201 passed in 3.33s ==============================
```

#### Breakdown of Milestone 8 Test Cases (`tests/test_investigation_graph.py` - 27 Tests)

1. `test_model_validation_empty_ids`: Validates rejection of empty/whitespace IDs.
2. `test_confidence_bounds`: Verifies upper and lower confidence bounds ($[0.0, 1.0]$).
3. `test_dangling_entity_reference_prevention`: Verifies that relationships pointing to non-existent entity IDs raise `ValueError`.
4. `test_missing_evidence_in_claim_extraction`: Verifies that extracting a claim referencing non-existent evidence IDs raises `ValueError`.
5. `test_stable_ids_and_immutability`: Verifies `ImmutableBaseModel` immutability and serialization.
6. `test_evidence_to_claim_to_relationship_provenance`: Verifies multi-hop provenance tracing from relationship to evidence text span.
7. `test_multiple_sources_supporting_relationship`: Verifies multiple independent sources supporting a single relationship.
8. `test_contradictory_claims_and_evidence`: Verifies non-destructive preservation of contradicting claims and transition to `DISPUTED`.
9. `test_missing_provenance_warning`: Verifies that relationships lacking evidence are flagged with `[WARNING: LACKS_PROVENANCE]`.
10. `test_epistemic_tiers`: Verifies separation between `ASSERTED`, `INFERRED`, and `HUMAN_VERIFIED`.
11. `test_unresolved_entity_references_preserved`: Verifies that unknown entities are preserved as provisional without false merges.
12. `test_er_distinct_from_factual_verification`: Verifies that entities sharing a relationship are never merged solely on that basis.
13. `test_traversal_cycle_handling_and_depth_limits`: Verifies cycle safety and termination on cyclic graphs (A -> B -> C -> A).
14. `test_query_determinism`: Verifies 100% deterministic ordering across consecutive queries.
15. `test_corrections_and_retractions`: Verifies claim retraction, audit history logging, and cascading relationship status updates.
16. `test_superseded_claim_validation`: Verifies mandatory `superseded_by_claim_id` validation.
17. `test_reclustering_updates_derived_relationships`: Verifies that entity resolution re-clustering re-maps relationships without stale references.
18. `test_source_record_immutability`: Verifies raw record immutability.
19. `test_neo4j_adapter_offline_graceful_handling`: Verifies offline safety of Neo4j adapter.
20. `test_investigation_demo_executes_deterministically`: Verifies complete end-to-end execution of the fictional investigation demo.
21. `test_retraction_not_undone_by_reingestion_or_rebuild`: Verifies that rerunning automated ingestion or graph rebuilding cannot silently undo a human retraction.
22. `test_claim_reinstatement_and_correction_cycle`: Verifies that explicitly reinstating a claim recalculates relationship status and reflects in queries.
23. `test_relationship_not_simultaneously_retracted_and_disputed`: Verifies semantic consistency: a retracted relationship is marked RETRACTED with historical contradiction notes, not simultaneously labeled an active open dispute.
24. `test_store_mutation_referential_integrity_all_paths`: Verifies that direct `store.add_claim` and `store.add_relationship` calls enforce all entity, claim, and evidence integrity checks.
25. `test_nested_structures_immutability_shared_reference_protection`: Verifies that mutating external dictionaries or lists passed to metadata cannot mutate model state.
26. `test_branching_graph_traversal_node_and_depth_limits`: Verifies that node and depth limits are strictly enforced under dense branching graphs without dangling edges.
27. `test_neo4j_adapter_reported_as_incomplete_placeholder`: Verifies that `Neo4jInvestigationGraphAdapter` is clearly documented as an offline placeholder and raises `NotImplementedError`.

---

### 6. Audit of Pre-Existing Milestone 7 Modifications

The working tree retains 5 files modified during the prior Milestone 7 Final Acceptance Audit:
1. `tests/test_clustering.py`: Contains `test_ritz_carlton_graph_clustering_cascade_and_reversibility`, testing non-transitive split preservation and reversibility on sub-venue collisions.
2. `src/core/benchmark.py`: Contains updated report generator sections 9 and 10 documenting the subcorpus isolated blocking diagnostic and production scope disclaimers.
3. `artifacts/benchmarks/real_world/milestone_7_production_evaluation.md`: Generated from the audited benchmark script during Milestone 7.
4. `artifacts/benchmarks/real_world/milestone_7_results.json`: Reconciled metrics and subcorpus isolated blocking diagnostic from Milestone 7.
5. `artifacts/benchmarks/benchmark_results.json`: Generated by `src/core/benchmark.py` execution; preserved without modification to historical baselines.

None of these files were reverted or discarded; all existing tests in `test_clustering.py` continue to pass without regression.

### 7. Scope Boundaries & Deferred Capabilities

In strict accordance with the Milestone 8 specifications:
- **Full NER and relation extraction ML models:** Deferred to Milestone 9. Claims currently consume explicit extraction metadata.
- **Automated Web Scraping:** Deferred to Milestone 10. Evidence items model OSINT source references without live network calls.
- **Live Neo4j Cluster Deployment:** The interface adapter is implemented as an offline placeholder; live deployment is deferred until infrastructure is provisioned.
- **Automated LLM Adjudication:** Factual verification and claim adjudication require explicit human reviewer credentials or rule-based updates; no uncalibrated AI scoring is permitted to fabricate identity or factual links.

---

### 8. Acceptance Criteria Verification

| Acceptance Criterion | Status | Evidence |
| :--- | :--- | :--- |
| **1. Architecture reused appropriately** | **PASSED** | Built on top of `ImmutableBaseModel`, `EntityCluster`, and `Record` in `src/core/`. |
| **2. Separate Evidence, Claims, Relationships** | **PASSED** | Distinct data models linked by explicit ID references. |
| **3. Explainable investigation queries** | **PASSED** | `InvestigationQueryService` returns paths and narrative provenance traces. |
| **4. Non-destructive conflict & corrections** | **PASSED** | Both sides preserved in `DISPUTED` state; audit trail captured in `ClaimCorrection`. |
| **5. ER separate from factual verification** | **PASSED** | Co-occurrence in claims does not trigger identity merges. |
| **6. Offline testability** | **PASSED** | `InMemoryInvestigationGraphStore` executes 100% locally with zero external services. |
| **7. Existing tests intact & passing** | **PASSED** | All 174 Milestone 1–7 tests pass. |
| **8. New tests cover required invariants** | **PASSED** | 27 new tests cover all required failure modes, referential checks, and invariants. |
| **9. Documentation matches implementation**| **PASSED** | Technical report and demonstration verified against active code. |
| **10. Zero git commit / push** | **PASSED** | No commits or pushes performed. |
