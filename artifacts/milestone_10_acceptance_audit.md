# SHERLOCK AI — MILESTONE 10 TARGETED ACCEPTANCE AUDIT REPORT

**Audit Date**: 2026-10-12  
**Target Repository**: `/home/renjith-cmd/Documents/sherlock-ai-1/entity_resolution_graph_osint/`  
**Current HEAD**: `e245940` (`feat(core): implement Milestone 7 production-grade entity resolution, multi-policy evaluation, and leakage-free benchmarking`)  
**Auditor**: Sherlock AI Senior Assurance & ML Verification Agent  
**Audit Scope**: Milestone 10 Model-Backed NER, Relation Extraction & Entity-Resolution Integration  
**Final Verdict**: **CONDITIONALLY ACCEPTED** (Accepted with explicit epistemic disclaimers and offline mock safeguards; blocked from full production ML deployment until live model weights and neural inference dependencies are provisioned in runtime environment).

---

## Executive Summary

A targeted correctness and evaluation audit was conducted across the newly integrated Milestone 10 components. The audit verified backend selection, model adapter interfaces, entity-resolution decision semantics, negation and attribution reconciliation in hybrid pipelines, relation grounding integrity, and benchmark reporting provenance.

Prior to this audit, the implementation contained several critical epistemic vulnerabilities:
1. **Mock Silently Masquerading as ML**: When `--backend ml` was selected in an environment without `transformers`, the pipeline silently substituted regex heuristic mocks without raising an error or clearly warning the user.
2. **False Negation on Unlinked Mentions**: Mentions with zero blocking candidates erroneously returned `DecisionType.NON_MATCH`, creating false negative evidence rather than preserving unlinked/unresolved epistemic status.
3. **Flawed Negation Semantics**: Unproven claims (e.g., *"did not establish that X owns Y"*) were incorrectly classified as affirmative negation (`is_negated=True`), conflating absence of evidence with evidence of absence.
4. **Mock Execution Timing Presented as Neural Latency**: Benchmark outputs reported sub-millisecond CPU regex execution times alongside ML accuracy figures without disclosing the simulation methodology.

All identified vulnerabilities have been corrected and verified via 21 targeted acceptance regression tests and the full 272-test suite.

---

## 1. Audit Findings Ranked by Severity

| ID | Category | Severity | Summary | Affected Files | Status |
|---|---|---|---|---|---|
| **FINDING-01** | Mock vs Real Inference | **CRITICAL** | `backend="ml"` silently fell back to mock regex inference when `transformers` was uninstalled, generating simulated benchmark scores without error. | `src/core/ner.py`<br>`src/core/relation_extraction.py`<br>`src/core/document_cli.py` | **FIXED & VERIFIED** |
| **FINDING-02** | Entity Resolution Semantics | **CRITICAL** | Mentions with no candidate matches generated `DecisionType.NON_MATCH`, fabricating negative evidence instead of declaring an unresolved state. | `src/core/mention_entity_resolution.py`<br>`src/core/document_evaluation.py` | **FIXED & VERIFIED** |
| **FINDING-03** | Negation & Epistemic Polarity | **MAJOR** | Phrasing like *"did not establish that X owns Y"* was classified as affirmative negation (`is_negated=True`), violating epistemic integrity. | `src/core/relation_extraction.py`<br>`tests/test_document_pipeline.py` | **FIXED & VERIFIED** |
| **FINDING-04** | Benchmark Provenance & Metrics | **MAJOR** | Benchmark and CLI reports did not explicitly distinguish CPU mock timings from real GPU/CPU transformer inference, risking misattribution. | `src/core/document_evaluation.py`<br>`src/core/document_cli.py` | **FIXED & VERIFIED** |
| **FINDING-05** | Hybrid Disagreement Handling | **MODERATE** | Polarity conflicts between rule and model backends did not mandate human review in metadata or mark polarity disagreements. | `src/core/relation_extraction.py`<br>`src/core/document_pipeline.py` | **FIXED & VERIFIED** |
| **FINDING-06** | Relation Grounding Validation | **MODERATE** | Extracted relations whose evidence offsets or mention references mismatched the source document text were not rejected early in pipeline. | `src/core/document_pipeline.py` | **FIXED & VERIFIED** |
| **FINDING-07** | Reviewed Claim Protection | **MINOR** | Claims updated by human review (e.g. `RETRACTED` or `VERIFIED`) were susceptible to automated overwriting on subsequent document re-processing. | `src/core/document_pipeline.py` | **FIXED & VERIFIED** |

---

## 2. Detailed Findings, Reproduction & Fixes Applied

### Finding 1: Mock Silently Masquerading as Real ML (CRITICAL)
- **Reproduction**:
  Running `python -m src.core.document_cli --evaluate --backend ml` in a Python virtual environment without `transformers` installed succeeded without warning and returned synthetic accuracy numbers.
- **Root Cause**:
  `ModelBackedNERExtractor` and `ModelBackedRelationExtractor` automatically caught `ImportError` and defaulted to `MockTransformerNERBackend` without requiring an explicit mock flag or raising `MLModelUnavailableError`.
- **Fix Applied**:
  1. Added `@property is_mock -> bool` to all backend classes (`False` for live/HF, `True` for mock).
  2. Added `use_mock_backend: bool = False` flag to extractor constructors. If `use_mock_backend=False` and dependencies or model weights are missing, `MLModelUnavailableError` is immediately raised.
  3. Added explicit `--backend mock_ml` to the CLI. When `--backend ml` is passed without `transformers`, the CLI exits with code 1 and outputs a clear dependency error.
  4. Added `is_mock_simulation: bool = True` and epistemic warning metadata to every mention produced by the mock backend.

### Finding 2: Lack of Candidates Erroneously Represented as Confirmed Non-Match (CRITICAL)
- **Reproduction**:
  Resolving a mention like `"Xanadu Robotics"` against a database containing only `"Bruce Wayne"` yielded `DecisionType.NON_MATCH`, implying proof that the mention cannot be any known entity.
- **Root Cause**:
  In `src/core/mention_entity_resolution.py`, when candidate blocking returned an empty list, the method defaulted to:
  ```python
  return MentionResolutionResult(
      decision_type=DecisionType.NON_MATCH,
      is_resolved=False,
      ...
  )
  ```
- **Fix Applied**:
  1. Introduced explicit `MentionResolutionStatus` enum with distinct states:
     - `RESOLVED_MATCH`: Candidate verified and linked.
     - `UNRESOLVED_NO_CANDIDATES`: No candidate found in known database; epistemic status is open/unlinked (NOT non-match).
     - `UNRESOLVED_INSUFFICIENT_EVIDENCE`: Candidates exist but similarity score is below match threshold and above non-match cutoff (routes to `REVIEW`).
     - `CONFIRMED_NON_MATCH`: High candidate similarity but fatal contradiction (e.g. conflicting tax IDs or explicit exclusion constraint).
  2. For zero candidates, `decision_type` is set to `None` and `resolution_status = MentionResolutionStatus.UNRESOLVED_NO_CANDIDATES`.
  3. Document evaluation reports track `unresolved_no_candidates` distinctly from `true_non_matches`.

### Finding 3: "Did Not Establish" Treated as Affirmative Negation (MAJOR)
- **Reproduction**:
  Ingesting *"The report did not establish that Wayne Enterprises owns Globex Corporation."* produced `ExtractedRelationCandidate(is_negated=True)`.
- **Root Cause**:
  The regex `\bdid not\b` matched inside `"did not establish that"`, triggering affirmative negation. However, lack of establishment indicates epistemic uncertainty or allegation, not proof of falsity.
- **Fix Applied**:
  1. Defined `RE_UNESTABLISHED` regex matching phrases like `did not establish that`, `failed to confirm that`, `unproven whether`.
  2. In `DeterministicRuleRelationExtractor` and `MockRelationNLIBackend`, matches against `RE_UNESTABLISHED` strip the carrier phrase from negative polarity scanning and set `uncertainty_flag = True`, `is_allegation = True`, and `is_negated = False`.
  3. Updated Milestone 9 adversarial suite regression assertion to reflect the corrected epistemic semantics.

### Finding 4: Benchmark Integrity & Provenance Disclosures (MAJOR)
- **Reproduction**:
  `--benchmark-compare` displayed columns labeled `ML`, showing execution speeds of 2–3 ms and 100% relation F1 without indicating that the figures were from offline CPU regex simulation.
- **Root Cause**:
  The benchmark runner used mock adapters but labeled output columns generically as `ML` without epistemic notices.
- **Fix Applied**:
  1. Renamed column to `Mock ML (Sim)` in both text tables and terminal displays.
  2. Added fields `ml_backend_type="mock_simulation"`, `is_mock_ml_simulation=True`, and `epistemic_disclaimer` to `MultiBackendComparativeReport`.
  3. Footnotes explicitly disclose:
     > *"ML performance figures represent offline heuristic/mock simulation for pipeline validation. Latency and memory reflect CPU regular-expression processing, NOT neural network inference. Do not interpret as measured transformer model accuracy or latency."*

### Finding 5: Hybrid Disagreement Reconciliation & Polarity Preservation (MODERATE)
- **Reproduction**:
  When rule and ML backends disagreed on negation polarity or predicate type, one backend arbitrarily overwrote the other without routing to human review.
- **Fix Applied**:
  1. Updated `HybridRelationExtractor._reconcile_relations()`:
     - When one backend asserts negation and the other does not, **negation is strictly preserved** (`is_negated=True`), and the claim is flagged with `requires_human_review=True` and `polarity_conflict=True`.
     - When backends disagree on predicate type, the candidate is flagged with `requires_human_review=True` and `disagreement_type="predicate_conflict"`.
  2. Provenance metadata records `backends_executed` (`["rule", "mock_ml"]` or `["rule", "ml"]`).

### Finding 6: Relation Grounding & Span Offset Validation (MODERATE)
- **Reproduction**:
  Candidates with corrupted offsets or nonexistent mention IDs could be passed to `process_ingested_document()` and converted into claims.
- **Fix Applied**:
  1. Enforced strict character slice verification: `doc.normalized_text[cand.evidence_start_char:cand.evidence_end_char] == cand.evidence_span`.
  2. Verified that `subject_mention_id` and `object_mention_id` exist in the document's validated mention set.
  3. Reject and discard ungrounded candidates before claim synthesis.

### Finding 7: Protection of Human-Reviewed Claims (MINOR)
- **Reproduction**:
  Re-ingesting a document could overwrite an existing claim in `InvestigationStore` even if an analyst had set its status to `RETRACTED` or `VERIFIED`.
- **Fix Applied**:
  `DocumentExtractionPipeline` checks `store.get_claim(claim_id)`. If an existing claim has `review_status` in `[VERIFIED, REJECTED, RETRACTED, SUPERSEDED]`, the automated pipeline preserves the analyst's verdict and adds the claim ID to `preserved_reviewed_claims`.

---

## 3. Mock versus Real Inference Status

| Component | Status | Model ID / Engine | Hardware / Execution | Provenance Disclosure |
|---|---|---|---|---|
| **Deterministic Rule NER** | Real (Deterministic) | Compiled RegEx Patterns | CPU | `extraction_method="rule"` |
| **Deterministic Rule RE** | Real (Deterministic) | Compiled RegEx & Clause Segmenter | CPU | `extraction_method="rule"` |
| **HuggingFace NER Backend** | Unloaded (Offline) | `dslim/bert-base-NER` | PyTorch / HF (Not installed) | Raises `MLModelUnavailableError` |
| **Mock Transformer NER** | **Simulated Mock** | Rule-mimicking regex fixture | CPU Heuristic | Flagged `is_mock_simulation=True` |
| **HuggingFace Relation Backend**| Unloaded (Offline) | `roberta-large-mnli` | PyTorch / HF (Not installed) | Raises `MLModelUnavailableError` |
| **Mock Relation NLI Backend** | **Simulated Mock** | Rule-mimicking regex fixture | CPU Heuristic | Flagged `is_mock_simulation=True` |
| **Hybrid Extractor** | **Hybrid** | Rule + Mock ML (Offline) | CPU Heuristic | Discloses `backends_executed` |
| **Entity Resolution Engine** | Real (Deterministic) | Jaro-Winkler + Attribute Matcher | CPU | `extraction_method="sherlock_er_v1"` |

---

## 4. Test Execution & Reproduction Results

### A. Acceptance Audit Regression Suite (21 tests)
Command:
```bash
.venv/bin/pytest tests/test_milestone_10_acceptance_audit.py -v
```
Output:
```
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0 -- /home/renjith-cmd/Documents/sherlock-ai-1/entity_resolution_graph_osint/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/renjith-cmd/Documents/sherlock-ai-1/entity_resolution_graph_osint
configfile: pytest.ini
collecting ... collected 21 items                                                             

tests/test_milestone_10_acceptance_audit.py::TestAuditAMockVsRealInference::test_mock_backends_flagged_as_mock PASSED [  4%]
tests/test_milestone_10_acceptance_audit.py::TestAuditAMockVsRealInference::test_live_ml_backend_raises_error_when_dependencies_missing PASSED [  9%]
tests/test_milestone_10_acceptance_audit.py::TestAuditAMockVsRealInference::test_live_relation_backend_raises_error_when_dependencies_missing PASSED [ 14%]
tests/test_milestone_10_acceptance_audit.py::TestAuditAMockVsRealInference::test_pipeline_ml_mode_raises_error_on_missing_live_dependencies PASSED [ 19%]
tests/test_milestone_10_acceptance_audit.py::TestAuditAMockVsRealInference::test_mock_outputs_contain_epistemic_simulation_warning PASSED [ 23%]
tests/test_milestone_10_acceptance_audit.py::TestAuditAMockVsRealInference::test_hybrid_mode_reports_actual_executed_backends PASSED [ 28%]
tests/test_milestone_10_acceptance_audit.py::TestAuditBEntityResolutionSemantics::test_scenario_1_no_candidates_found PASSED [ 33%]
tests/test_milestone_10_acceptance_audit.py::TestAuditBEntityResolutionSemantics::test_scenario_2_candidate_exists_but_insufficient_evidence PASSED [ 38%]
tests/test_milestone_10_acceptance_audit.py::TestAuditBEntityResolutionSemantics::test_scenario_3_confirmed_explicit_non_match PASSED [ 42%]
tests/test_milestone_10_acceptance_audit.py::TestAuditBEntityResolutionSemantics::test_scenario_4_valid_match_supported PASSED [ 47%]
tests/test_milestone_10_acceptance_audit.py::TestAuditBEntityResolutionSemantics::test_scenario_5_exact_name_collision_with_conflicting_identifiers PASSED [ 52%]
tests/test_milestone_10_acceptance_audit.py::TestAuditBEntityResolutionSemantics::test_scenario_6_explicit_non_match_constraint_prevents_clustering PASSED [ 57%]
tests/test_milestone_10_acceptance_audit.py::TestAuditCHybridNegationAndDisagreement::test_unestablished_phrasing_is_not_affirmative_negation PASSED [ 61%]
tests/test_milestone_10_acceptance_audit.py::TestAuditCHybridNegationAndDisagreement::test_mock_relation_unestablished_phrasing PASSED [ 66%]
tests/test_milestone_10_acceptance_audit.py::TestAuditCHybridNegationAndDisagreement::test_hybrid_polarity_conflict_preserves_negation_and_routes_to_review PASSED [ 71%]
tests/test_milestone_10_acceptance_audit.py::TestAuditCHybridNegationAndDisagreement::test_hybrid_predicate_conflict_routes_to_review PASSED [ 76%]
tests/test_milestone_10_acceptance_audit.py::TestAuditDRelationGrounding::test_ungrounded_mentions_are_rejected PASSED [ 80%]
tests/test_milestone_10_acceptance_audit.py::TestAuditDRelationGrounding::test_mismatched_evidence_offsets_are_rejected PASSED [ 85%]
tests/test_milestone_10_acceptance_audit.py::TestAuditDRelationGrounding::test_human_reviewed_claims_are_protected_from_overwrite PASSED [ 90%]
tests/test_milestone_10_acceptance_audit.py::TestAuditEBenchmarkIntegrity::test_comparative_benchmark_report_contains_mock_disclosures PASSED [ 95%]
tests/test_milestone_10_acceptance_audit.py::TestAuditEBenchmarkIntegrity::test_entity_resolution_report_tracks_unresolved_no_candidates PASSED [100%]

============================== 21 passed in 0.19s ==============================
```

### B. Full Test Suite (272 tests)
Command:
```bash
.venv/bin/pytest tests/
```
Output:
```
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/renjith-cmd/Documents/sherlock-ai-1/entity_resolution_graph_osint
configfile: pytest.ini
collecting ... collected 272 items                                                            

tests/test_benchmark.py ...................                              [  6%]
tests/test_blocking.py ........................                          [ 15%]
tests/test_clustering.py ......................                          [ 23%]
tests/test_comparison.py .................                               [ 30%]
tests/test_dataset_integrity.py .....                                    [ 31%]
tests/test_datasets.py ............                                      [ 36%]
tests/test_decision.py ........................                          [ 45%]
tests/test_document_pipeline.py ...............................          [ 56%]
tests/test_evaluation.py .............                                   [ 61%]
tests/test_investigation_graph.py ...........................            [ 71%]
tests/test_milestone_10_acceptance_audit.py .....................        [ 79%]
tests/test_milestone_10_ml_integration.py ...................            [ 86%]
tests/test_models.py .........................                           [ 95%]
tests/test_normalization.py .............                                [100%]

============================= 272 passed in 3.14s ==============================
```

### C. Live Backend Error Verification
Command:
```bash
.venv/bin/python -m src.core.document_cli --evaluate --backend ml
```
Output:
```
ERROR: Live 'ml' backend requires 'transformers' library and local model weights.
Cannot perform live ML evaluation in offline environment without dependencies.
Use '--backend mock_ml' or '--benchmark-compare' for deterministic offline simulation.
```
*(Process exited with return code 1, confirming strict prevention of silent fallback).*

### D. Benchmark Disclosure Verification
Command:
```bash
.venv/bin/python -m src.core.document_cli --benchmark-compare
```
Output:
```
=================================================================
   SHERLOCK AI - MULTI-BACKEND COMPARATIVE BENCHMARK (M10)       
=================================================================
Partition:  synthetic_regression_test
Provenance: Offline deterministic simulation (not live transformer weights)

--- NER PERFORMANCE COMPARISON ---
Metric                 Rule         Mock ML (Sim)    Hybrid      
------------------------------------------------------------------
Exact-Span F1           95.24%       85.00%*          95.24%
Exact Precision         95.24%       89.47%*          95.24%
Exact Recall            95.24%       80.95%*          95.24%
Latency (ms)             6.54 ms      2.25 ms*         7.01 ms

--- RELATION EXTRACTION COMPARISON ---
Metric                 Rule         Mock ML (Sim)    Hybrid      
------------------------------------------------------------------
Relation F1            100.00%      100.00%*         100.00%
Negation Acc           100.00%      100.00%*         100.00%
Attribution Acc        100.00%      100.00%*         100.00%
Latency (ms)             5.65 ms      3.29 ms*         8.59 ms

--- ENTITY RESOLUTION INTEGRATION ---
Total Mentions:           5
True Matches:             4
False Merges:             0
Unresolved (No Cands):    1
Candidate Recall:         100.00%
Review Rate:              0.00%
Pairwise F1:              100.00%
------------------------------------------------------------------
* NOTE: Mock ML columns reflect offline simulated regex engines.
  Latency and memory measure CPU regex execution, NOT transformer neural inference.
  ML performance figures represent offline heuristic/mock simulation for pipeline validation. Latency and memory reflect CPU regular-expression processing, NOT neural network inference. Do not interpret as measured transformer model accuracy or latency.
=================================================================
```

---

## 5. Repository Safety & Integrity Audit

1. **Git Status & Diff Verification**:
   - `git diff --check` exited with code 0 (zero whitespace or formatting errors).
   - Zero commits, pushes, resets, cleans, rebases, or amends executed.
   - Pre-existing untracked files and modifications from Milestones 7–9 remain strictly intact:
     - `artifacts/benchmarks/benchmark_results.json`
     - `artifacts/benchmarks/real_world/milestone_7_production_evaluation.md`
     - `artifacts/benchmarks/real_world/milestone_7_results.json`
     - `src/core/__init__.py`
     - `src/core/benchmark.py`
     - `src/core/models.py`
     - `tests/test_clustering.py`
     - Untracked artifacts from Milestones 8 and 9.

---

## 6. Remaining Limitations & Blockers

1. **Missing Runtime ML Dependencies**:
   - `transformers` and `torch` packages are not installed in the local `.venv`.
   - Local weights for `dslim/bert-base-NER` and `roberta-large-mnli` are not downloaded.
   - **Remediation**: In an online staging or GPU environment, run `pip install torch transformers` and cache model weights under a local model directory. The pipeline is architected to seamlessly activate `HuggingFaceNERBackend` and `HuggingFaceRelationNLIBackend` once dependencies are present.
2. **Synthetic Dataset Size**:
   - The current extraction benchmark fixture evaluates 21 entity mentions and 5 relations. While sufficient for deterministic unit/regression validation, it does not constitute statistically significant evaluation of neural generalizability.
   - **Remediation**: Benchmark on standard OSINT/NER datasets (e.g. CoNLL-2003, Few-Shot RE) once live model infrastructure is deployed.

---

## 7. Acceptance Recommendation

**Verdict: CONDITIONALLY ACCEPTED**

- **Why Accepted**:
  The architecture correctly separates deterministic rule extraction, model adapters, and hybrid reconciliation. The critical epistemic flaws (masquerading mocks, false non-match on zero candidates, incorrect negative finding polarity, ungrounded relation creation) are fully corrected, guarded by regression tests, and verifiable in an offline environment without external downloads.
- **Condition for Production ML Deployment**:
  Deployment of live neural models requires provisioning `torch` and `transformers` in the execution environment and running empirical benchmarking with real pretrained weights. Until then, only `backend="rule"` and explicitly labeled `backend="mock_ml"` simulations may be executed.
