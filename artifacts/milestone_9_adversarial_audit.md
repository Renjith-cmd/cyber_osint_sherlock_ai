# Sherlock AI — Milestone 9 Adversarial Correctness & Security Audit

**Audit Date:** October 12, 2026  
**Auditor:** Senior ML Engineer & Investigation Systems Architect  
**Repository:** `/home/renjith-cmd/Documents/sherlock-ai-1/entity_resolution_graph_osint/`  
**Target Milestone:** Milestone 9 — Document Ingestion, Named Entity Recognition & Evidence-Grounded Relation Extraction  
**Environment:** Linux (Python 3.14.7, pytest 9.1.1, pydantic 2.11.0a0)  
**Safety Mandate:** Read-only first, zero-commit, zero-push, preservation of all Milestones 7–9 tracked and untracked work.

---

## Executive Audit Summary

This adversarial audit evaluated the Milestone 9 document ingestion, NER, and relation extraction subsystems under rigorous stress, boundary, and negative conditions. 

The baseline implementation demonstrated sound foundational architecture, including strict separation of raw source bytes from normalized text, deterministic character offsets, preservation of repeated mentions, and integration into Milestone 8 `Evidence` and `Claim` models defaulting strictly to `ReviewStatus.UNREVIEWED`.

However, the adversarial audit uncovered **four substantive correctness limitations** in the initial baseline:
1. **Linguistic Inflection Blind Spots in Relation Extraction:** The initial predicate patterns only matched specific morphological forms (e.g. `owns`, `owned`), failing to extract negated or gerund forms such as `does not own` or `denies owning`.
2. **Whole-Sentence Negation Leakage Across Coordinate Clauses:** Negation cues were initially computed at the whole-sentence level rather than scoped to the active clause, causing compound sentences (e.g. *"Alice does not work for X, but Bob works for Y"*) to falsely negate the second, unrelated clause.
3. **Correlative Conjunction Negation Misclassification:** Constructive additive phrasing such as *"Wayne Enterprises not only owns X but also operates it"* was incorrectly flagged as negated due to the presence of the token `"not"`.
4. **Character Set Boundaries in NER:** The initial rule-based NER regular expressions were restricted to ASCII `[A-Z][a-z]+`, failing on international names with accented characters (e.g. *Dr. René François*, *Angela Müller*).

All four issues were resolved with minimal, targeted modifications, and 7 new dedicated adversarial regression tests were added. The complete test suite now passes with **232 passing tests** (201 regression tests + 31 Milestone 9 unit/integration/adversarial tests) in 3.13s.

---

## 1. Audit A: Negation, Attribution, and Epistemic Qualifiers

### 1.1 Evaluation of the 10 Mandatory Audit Cases

Each case was executed against the real extraction pipeline and investigated down to emitted `EntityMention`, `ExtractedRelationCandidate`, `Evidence`, and `Claim` objects:

| # | Test Case Input | Extracted Predicate | `is_negated` | `is_allegation` | `attribution_source` | `uncertainty_flag` | Evidence Polarity | Claim Review Status & Evidence Routing |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | *"Wayne Enterprises owns Globex Corporation."* | `OWNS` | `False` | `False` | `None` | `False` | `SUPPORTING` | `UNREVIEWED` \| `supporting_evidence_ids` |
| **2** | *"Wayne Enterprises does not own Globex Corporation."* | `OWNS` | `True` | `False` | `None` | `False` | `CONTRADICTING` | `UNREVIEWED` \| `contradicting_evidence_ids` |
| **3** | *"The report alleges that Wayne Enterprises owns Globex Corporation."* | `OWNS` | `False` | `True` | `"The report alleges that"` | `False` | `SUPPORTING` | `UNREVIEWED` \| `supporting_evidence_ids` |
| **4** | *"Wayne Enterprises denies owning Globex Corporation."* | `OWNS` | `True` | `False` | `None` | `False` | `CONTRADICTING` | `UNREVIEWED` \| `contradicting_evidence_ids` |
| **5** | *"It is unclear whether Wayne Enterprises owns Globex Corporation."* | `OWNS` | `False` | `False` | `None` | `True` | `SUPPORTING` | `UNREVIEWED` \| `supporting_evidence_ids` |
| **6** | *"Wayne Enterprises does not own Globex Corporation, according to the report."* | `OWNS` | `True` | `True` | `"according to the report"` | `False` | `CONTRADICTING` | `UNREVIEWED` \| `contradicting_evidence_ids` |
| **7** | *"Wayne Enterprises owns no shares in Globex Corporation."* | `OWNS` | `True` | `False` | `None` | `False` | `CONTRADICTING` | `UNREVIEWED` \| `contradicting_evidence_ids` |
| **8** | *"Wayne Enterprises not only owns Globex Corporation but also operates it."* | `OWNS` | `False` | `False` | `None` | `False` | `SUPPORTING` | `UNREVIEWED` \| `supporting_evidence_ids` |
| **9** | *"The report did not establish that Wayne Enterprises owns Globex Corporation."* | `OWNS` | `True` | `False` | `None` | `False` | `CONTRADICTING` | `UNREVIEWED` \| `contradicting_evidence_ids` |
| **10** | *"Wayne Enterprises owns Globex Corporation. However, Wayne Enterprises denies owning Globex Corporation."* | `OWNS` (x2) | Sent 1: `False`<br>Sent 2: `True` | `False` | `None` | `False` | Sent 1: `SUPPORTING`<br>Sent 2: `CONTRADICTING` | Emits 2 distinct `Claim` objects: Claim 1 with `supporting_evidence_ids`, Claim 2 with `contradicting_evidence_ids`. Neither claim overwrites the other. |

### 1.2 Coordinate Clause Negation Isolation

- **Adversarial Scenario:** A compound sentence with coordinate clauses separated by punctuation/conjunction:
  > *"Alice Smith does not work for Cyberdyne Systems, but Dr. John Watson works for Sherlock Security."*
- **Baseline Failure Observed:** Prior to the fix, the sentence-level negation check flagged both `Alice Smith -> Cyberdyne Systems` and `Dr. John Watson -> Sherlock Security` as negated. Furthermore, a spurious candidate was generated across the clause boundary linking `Alice Smith -> Sherlock Security`.
- **Targeted Fix Applied:**
  1. Implemented clause-boundary detection in `_detect_predicate`: If subject and object are separated by coordinating clause boundaries (`,\s*but`, `,\s*however`, `,\s*whereas`, `,\s*while`, `;\s*`), predicate detection returns `None`, rejecting cross-clause spurious linking.
  2. Implemented `_evaluate_pair_qualifiers`: Scopes negation, attribution, and uncertainty checks strictly to the clause enclosing the specific entity pair.
- **Verified Behavior:**
  - Candidate 1: `Alice Smith` $\to$ `Cyberdyne Systems` (`is_negated: True`).
  - Candidate 2: `Dr. John Watson` $\to$ `Sherlock Security` (`is_negated: False`).
  - Candidate count is exactly 2 (zero cross-clause candidates emitted).

---

## 2. Audit B: Provenance, Offsets, and Ingestion Robustness

### 2.1 Character Offsets & Normalization Bounds

- **Invariant Tested:** For every extracted mention and relation evidence span, does `document.normalized_text[start:end]` equal the exact recorded surface string?
- **Finding:** Verified 100% across ASCII, accented Unicode names, emojis, and multiline texts.
- **Critical Distinction:** Offsets are defined strictly relative to `document.normalized_text`. If source bytes contain Windows CRLF (`\r\n`), `TextDocumentParser` normalizes `\r\n` to `\n`. Offsets therefore refer to the normalized representation, not raw byte indices. This is explicitly documented in the technical report.

### 2.2 Accented International Names & Emojis

- **Finding:** Initial NER regular expressions used `[A-Z][a-z]+`, which failed on international accented names such as *Dr. René François* or *Angela Müller*.
- **Fix:** Enhanced name patterns to support Latin-1 supplement character classes (`[A-Z\xc0-\xd6\xd8-\xde]` and `[a-z\xdf-\xf6\xf8-\xff]`).
- **Emoji Test:** Preceding emojis (e.g. `🔍 Investigator Sherlock Holmes arrived at 221B Baker Street. 🚀`) preserve exact offset alignment without offset drift.

### 2.3 Malformed, Empty, and Nested Documents

- **Empty / Whitespace-Only Documents:** Initial parser returned an empty `IngestedDocument(char_count=0)`. In strict compliance with Section 3 (*"No silent conversion of failed parses into empty successful documents"*), `TextDocumentParser` now raises `DocumentParsingError("Document text is empty or contains no extractable characters.")`.
- **Nested JSON Traversal:** `JsonDocumentParser` now includes recursive traversal (`_extract_recursive_texts`) allowing nested structures (e.g. `{"status": 200, "response": {"data": {"article": "..."}}}`) to be extracted seamlessly.
- **Non-String JSON Fields:** Handled safely; non-string values under text keys are ignored, and if no valid string text is discovered, `DocumentParsingError` is raised.

---

## 3. Audit C: Entity Identity & Graph Integration

### 3.1 Distinction Between Mentions and Resolved Entities

- **Audit Requirement:** Verify that repeated mentions of the same name are not automatically merged into the same real-world entity merely because their surface text matches.
- **Verified Behavior:**
  - In a document containing `"Dr. Watson visited London. Later, Dr. Watson arrived in Tokyo."`, two distinct `EntityMention` objects are created with unique mention IDs: `men_doc_..._0_...` and `men_doc_..._1_...`.
  - In `_resolve_entity_reference`: Unresolved mentions are registered as provisional entities using their mention ID: `unresolved_men_doc_..._0_...` and `unresolved_men_doc_..._1_...`.
  - They are **not** collapsed into a single entity. Merging can only occur through Milestone 1–7 entity resolution (blocking, pairwise comparison, and constraint-aware clustering).

### 3.2 Human Review Preservation & Referential Integrity

- **Audit Requirement:** Reprocessing a document must not overwrite prior human retractions, rejections, or corrections.
- **Verified Behavior:**
  1. A document is ingested and an unreviewed claim is registered.
  2. An analyst calls `update_claim_status(claim_id, ReviewStatus.RETRACTED, rationale="Contractor, not employee", corrected_by="analyst_jane")`.
  3. The identical document is re-ingested.
  4. The pipeline detects that `existing_claim.review_status == ReviewStatus.RETRACTED`, retains the retracted claim, logs it in `preserved_reviewed_claims`, and does not revert the status to `UNREVIEWED`.
  5. Referential integrity: Every claim references valid existing evidence in the store and valid entity participant IDs.

---

## 4. Audit D: Evaluation Harness Validity

### 4.1 Denominator and Metric Integrity

- **Exact Match:** Requires identical `start_char`, `end_char`, and matching `EntityType`.
- **Lenient Match:** Credits non-zero token overlap.
- **Denominators:**
  - $\text{Exact Precision} = \frac{\text{Exact Matches}}{\text{Total Predictions}}$
  - $\text{Exact Recall} = \frac{\text{Exact Matches}}{\text{Total Gold Entities}}$
  - $\text{Exact F1} = \frac{2 \times P \times R}{P + R}$
  - Duplicate predictions cannot inflate true positives because `matched_gold_indices` and `matched_pred_indices` track one-to-one assignments.

### 4.2 In-Memory Mutation Verification

To verify that the evaluation harness is sensitive to errors, in-memory mutation checks were executed:

| Mutation Experiment | Baseline Metric | Mutated Metric | Metric Decreased? |
| :--- | :--- | :--- | :--- |
| **Drop 1 Gold Mention Prediction (False Negative)** | Exact F1 = 95.24% | Exact F1 = 83.33% | **Yes** (Confirmed) |
| **Invert All Negation Predictions** | Negation Acc = 100.00% | Negation Acc = 0.00% | **Yes** (Confirmed) |
| **Inject Artificial False Positive Relation** | Precision = 100.00% | Precision = 45.45% | **Yes** (Confirmed) |

### 4.3 Representativeness Disclosure

- **Crucial Architectural Note:** The synthetic fixture suite consists of 6 curated documents and 5 gold relations. 
- **Epistemic Assessment:** This suite serves as a **functional unit regression harness**, not an open-domain benchmark. Achieving 100% precision and recall on 5 curated synthetic relations does **not** indicate production-grade open-domain NLP performance. The documentation clearly labels this as a deterministic baseline.

---

## 5. Audit E: CLI and Operational Behavior

### 5.1 Command-Line Execution & Exit Codes

| CLI Invocation | Exit Code | Verified Output & Behavior |
| :--- | :--- | :--- |
| `python -m src.core.document_cli --sample` | `0` | Emits formatted human investigation dossier with clear epistemic disclaimer. |
| `python -m src.core.document_cli --sample --json` | `0` | Emits valid, serializable JSON containing document, mentions, candidates, evidence, and claims. |
| `python -m src.core.document_cli --evaluate` | `0` | Executes synthetic benchmark and prints exact metric table. |
| `python -m src.core.document_cli /nonexistent/file.txt` | `1` | Prints clear stderr message: `Error: File not found: '/nonexistent/file.txt'`. |
| PDF ingestion without `pypdf` | `2` | Catches `ExtractionCapabilityError` and returns code 2 without crashing or downloading packages. |

### 5.2 Security and Offline Operation

- **No Data Leakage:** Error messages report file limits and parsing failure reasons without dumping full document byte contents.
- **Zero External Network Calls:** The entire suite operates strictly offline with zero external model weight downloads or network queries.

---

## 6. Minimal Fixes Made & Regression Tests Added

1. **`src/core/document_ingestion.py`:**
   - Enforced non-empty check in `TextDocumentParser` (raises `DocumentParsingError` on empty/whitespace input).
   - Added `_extract_recursive_texts` in `JsonDocumentParser` for nested key extraction.
2. **`src/core/ner.py`:**
   - Added Latin-1 supplement character classes (`[A-Z\xc0-\xd6\xd8-\xde]` and `[a-z\xdf-\xf6\xf8-\xff]`) to person name patterns.
3. **`src/core/relation_extraction.py`:**
   - Added verb inflections (`own`, `owning`, `work for`, `working for`, etc.).
   - Added noun phrase negation (`no shares`, `no stake`, `no ownership`).
   - Added `"not only"` exclusion in negation check.
   - Added clause-delimiter boundary check in `_detect_predicate` to prevent cross-clause spurious relations.
   - Added `_evaluate_pair_qualifiers` for clause-scoped negation/attribution evaluation.
4. **`tests/test_document_pipeline.py`:**
   - Added `TestAdversarialRobustness` class containing 7 new tests:
     - `test_audit_a_10_adversarial_cases`
     - `test_audit_a_clause_level_negation_isolation`
     - `test_audit_b_unicode_and_emoji_offsets`
     - `test_audit_b_empty_and_whitespace_documents_rejected`
     - `test_audit_b_nested_json_extraction`
     - `test_audit_c_unresolved_participants_remain_separate`
     - `test_audit_d_mutation_checks`

---

## 7. Full Regression Suite & Git Status Verification

### 7.1 Test Suite Output
```bash
.venv/bin/pytest tests/
```
```text
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/renjith-cmd/Documents/sherlock-ai-1/entity_resolution_graph_osint
configfile: pytest.ini
collecting ... collected 232 items                                                            

tests/test_benchmark.py ...................                              [  8%]
tests/test_blocking.py ........................                          [ 18%]
tests/test_clustering.py ......................                          [ 28%]
tests/test_comparison.py .................                               [ 35%]
tests/test_dataset_integrity.py .....                                    [ 37%]
tests/test_datasets.py ............                                      [ 42%]
tests/test_decision.py ........................                          [ 53%]
tests/test_document_pipeline.py ...............................          [ 66%]
tests/test_evaluation.py .............                                   [ 71%]
tests/test_investigation_graph.py ...........................            [ 83%]
tests/test_models.py .........................                           [ 94%]
tests/test_normalization.py .............                                [100%]

============================= 232 passed in 3.13s ==============================
```

### 7.2 Git Check & Status
```bash
git diff --check
# Exit code 0 (clean formatting, no trailing whitespace)
```
```bash
git status --short
```
```text
 M artifacts/benchmarks/benchmark_results.json
 M artifacts/benchmarks/real_world/milestone_7_production_evaluation.md
 M artifacts/benchmarks/real_world/milestone_7_results.json
 M src/core/__init__.py
 M src/core/benchmark.py
 M src/core/document_ingestion.py
 M src/core/models.py
 M src/core/ner.py
 M src/core/relation_extraction.py
 M tests/test_clustering.py
 M tests/test_document_pipeline.py
?? artifacts/milestone_8_evidence_provenance_relationship_graph_report.md
?? artifacts/milestone_9_adversarial_audit.md
?? artifacts/milestone_9_document_extraction_report.md
?? src/core/document_cli.py
?? src/core/document_evaluation.py
?? src/core/document_pipeline.py
?? src/core/investigation_demo.py
?? src/core/investigation_graph.py
?? src/core/investigation_lifecycle.py
?? src/core/investigation_service.py
?? tests/test_investigation_graph.py
```

---

## 8. Final Audit Verdict

Based on formal execution, mutation testing, adversarial case analysis, and regression verification:

### **ACCEPTED FOR RESEARCH PROTOTYPE**

**Rationale:**
1. The document-to-evidence pipeline strictly implements the epistemic safeguards of Sherlock AI: automated extraction defaults to `ReviewStatus.UNREVIEWED`, evidence spans are strictly grounded, and prior human review decisions are preserved across re-ingestion.
2. The 10 adversarial negation and attribution constructions are verified and tested.
3. Coordinate clause isolation prevents negation leakage across sentence clauses.
4. Character offsets are proven 100% faithful to normalized source text across ASCII, accented Unicode, and emojis.
5. All 232 regression and adversarial tests pass cleanly without errors or performance degradation.
