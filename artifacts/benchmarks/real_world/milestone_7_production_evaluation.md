# Sherlock AI — Milestone 7: Production-Grade Entity Resolution
## Reducing False Negatives Without Increasing False Merges (Consolidated Audit Report)

**Execution Timestamp**: 2026-10-12 02:51:47 UTC | **Seed**: `42` | **Total Runtime**: `6.2514s`
**Master Deterministic Metrics Fingerprint**: `77ee58698d7009f51d6b5d369369be3de497b5743cffe3bec23b7d066d411403`

---

## 1. Executive Summary & Baseline Reconciled Comparison

Milestone 7 delivers a production-grade pairwise comparison and decision architecture that dramatically reduces false negatives while enforcing strict safeguards against false merges:

| Metric (Strict Operational Mode) | Baseline Policy (M6) | Calibrated Evidence Policy (M7 Production) | Autonomous High-Precision Policy | Relative Gain |
| :--- | :---: | :---: | :---: | :---: |
| **Full Dataset True Positives (TP)** | 8 | **103** | 101 | **+95 TP (+1,187.5%)** |
| **Full Dataset False Positives (FP)** | 1 | **1** | 1 | **Zero FP increase (1 FP)** |
| **Full Dataset False Negatives (FN)** | 104 | **9** | 11 | **-91.35% reduction in FN (104 -> 9)** |
| **Operational Recall** | 7.14% | **91.96%** | 90.18% | **+84.82% absolute gain** |
| **Operational Precision** | 88.89% | **99.04%** | 99.02% | **+10.15% gain (99.04%)** |
| **Operational F1 Score** | 13.22% | **95.37%** | 94.39% | **+82.15% gain (95.37%)** |
| **Autonomous Match Precision** | 88.89% | **99.04%** | 99.02% | **99.04% precision** |
| **Clustering Pairwise F1** | 13.22% | **94.88%** | 93.90% | **+81.66% gain (94.88%)** |

> [!IMPORTANT]
> **Arithmetically Reconciled Baseline Verification**: On the full 864-record benchmark (372,816 total pairs, 6,797 candidate pairs, 112 true duplicates), the Milestone 6 baseline produced 9 MATCH decisions (8 TP, 1 FP), 5,178 NON_MATCH decisions (5,124 TN, 54 FN), and 1,610 REVIEW decisions (50 TP in review, 1,560 FP in review). Under strict operational evaluation where REVIEW is non-autonomous, the operational recall was only **7.14%** with **104 false negatives** (54 classified non-match + 50 routed to review). The production calibrated policy increases autonomous TP from 8 to **103**, reducing operational false negatives from 104 down to **9**.

---

## 2. Precise Evaluation Policy Definitions

To eliminate metric ambiguity, four explicit evaluation regimes are formally defined and separated:

### Regime A: Autonomous-Only Evaluation Policy
- **Core Rule**: Pairs routed to `REVIEW` are deferred to human investigation queues and **completely excluded** from autonomous binary scoring denominators.
- **Denominators**:
  - Autonomous Evaluated Pairs: `TP_match + FP_match + TN_non_match + FN_non_match`
  - Autonomous Precision = `TP_match / (TP_match + FP_match)`
  - Autonomous Recall = `TP_match / (TP_match + FN_non_match)`
  - Autonomous Specificity = `TN_non_match / (TN_non_match + FP_match)`
- **Critical Constraint**: Autonomous precision MUST NEVER be labeled as strict operational precision, because it omits positive pairs routed to review.

### Regime B: Strict Operational Evaluation Policy (Standard Production Baseline)
- **Core Rule**: In automated operations, any positive duplicate pair routed to `REVIEW` is an **unresolved duplicate** and incurs the documented operational cost of a **False Negative** (`FN_operational = Total_Positives - TP_match`).
- **Denominators**:
  - Operational Precision = `TP_match / (TP_match + FP_match)`
  - Operational Recall = `TP_match / Total_Ground_Truth_Positives`
  - Operational F1 = `2 * Prec * Rec / (Prec + Rec)`

### Regime C: Semi-Automated (Post-Review Adjudication) Policy
- **Core Rule**: Human investigators adjudicate all pairs routed to `REVIEW`. Under oracle review assumptions, true duplicates in review become verified matches (`TP_post = TP_match + TP_in_review`), while non-duplicates in review are rejected without incurring false merges (`FP_post = FP_match`).
- **Denominators**:
  - Post-Review Recall = `(TP_match + TP_in_review) / Total_Ground_Truth_Positives`
  - Review Duplicate Yield = `TP_in_review / Total_Review_Decisions`

### Regime D: Legacy CLI Evaluation Flags (`review_is_match` and `review_is_error`)
- **`review_is_match`**: Treats all `REVIEW` decisions as optimistic `MATCH` outcomes. This increases recall to 97.32%, but collapses precision to **6.81%** because 1,491 non-duplicate pairs in review are treated as false positives.
- **`review_is_error`** (default `True` in Milestone 6): Penalizes non-duplicate pairs routed to review as errors in the pairwise evaluator. Setting `--review-not-error` (`review_is_error=False`) treats review as non-error triage.

---

## 3. Partition Candidate-Count Reconciliation

### Discrepancy Investigation & Root-Cause Resolution
In earlier reporting, DEV (5,050 candidates), VAL (2,294 candidates), and TEST (1,829 candidates) summed to 9,173 candidates, appearing to contradict the full dataset candidate count of 6,797. The independent audit established the exact mathematical mechanism:

1. **Block-Size Cap Interaction (`max_block_size=50`)**:
   - In the full 864-record corpus, 9 high-frequency keys exceeded 50 records and were skipped: `city:new york` (250), `city:san francisco` (148), `city:atlanta` (120), `soundex:C100` (96), `city:new york city` (88), `token:cafe` (79), `city:los angeles` (74), `city:las vegas` (63), `soundex:T000` (53).
   - When candidate generation is run in isolation on smaller partition sub-corpora (e.g. VAL with 172 records), `city:new york` has only 39 records (<= 50), `city:atlanta` has 31 records (<= 50), `city:san francisco` has 28 records (<= 50). Because they do not exceed 50 in the sub-corpus, they were active and generated thousands of pairs within VAL and TEST that the global benchmark pruned!

2. **Canonical Partition-Restricted Global Candidates**:
   - Generating candidates globally once across all 864 records produces the canonical **6,797** candidate pairs.
   - Partitioning these canonical pairs by record membership yields mutually disjoint subsets that sum exactly to 6,797:

| Candidate Stream | Partition Membership | Candidate Pairs | Ground-Truth Positives | Candidate Recall | Notes |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **DEV Internal** | Both records in DEV | 2,490 | 67 / 67 | 100.0% | Internal DEV candidate pairs |
| **VAL Internal** | Both records in VAL | 298 | 22 / 22 | 100.0% | Internal VAL candidate pairs |
| **TEST Internal** | Both records in TEST | 291 | 23 / 23 | 100.0% | Internal TEST candidate pairs |
| **Cross-Partition** | Records in different partitions | 3,718 | 0 / 0 | N/A | Strictly 0 duplicate pairs (pure negatives) |
| **TOTAL GLOBAL** | Entire 864-record benchmark | **6,797** | **112 / 112** | **100.0%** | **2,490 + 298 + 291 + 3,718 = 6,797 (100% Reconciled)** |

> [!TIP]
> **Diagnostic Verification**: In both perspectives, Candidate Recall is strictly **100.0%** (all 112 true duplicates captured). Under the Calibrated Evidence policy, every extra pair generated by isolated sub-corpus blocking is classified as `NON_MATCH` or `REVIEW` (0 false positives).

---

## 4. Reconciled Full-Dataset Confusion Matrices & Cross-Tabulation

Derived from the single canonical list of 6,797 candidate decisions evaluated on the full 864-record dataset:

### Complete 3x2 Decision Cross-Tabulation Matrix

| Policy | Decision Type | Ground-Truth Duplicate (Pos) | Ground-Truth Non-Duplicate (Neg) | Row Total (Decisions) |
| :--- | :--- | :---: | :---: | :---: |
| **Baseline Policy (M6)** | MATCH | 8 (TP) | 1 (FP) | 9 |
| | REVIEW | 50 (TP in review) | 1,560 (FP in review) | 1,610 |
| | NON_MATCH | 54 (FN non-match) | 5,124 (TN non-match) | 5,178 |
| | **Column Total** | **112** | **6,685** | **6,797 (100% Reconciled)** |
| :--- | :--- | :---: | :---: | :---: |
| **Calibrated Evidence (M7 Prod)** | MATCH | **103 (TP)** | **1 (FP)** | **104** |
| | REVIEW | **6 (TP in review)** | **1,491 (FP in review)** | **1,497** |
| | NON_MATCH | **3 (FN non-match)** | **5,193 (TN non-match)** | **5,196** |
| | **Column Total** | **112** | **6,685** | **6,797 (100% Reconciled)** |
| :--- | :--- | :---: | :---: | :---: |
| **Autonomous High-Precision** | MATCH | 101 (TP) | 1 (FP) | 102 |
| | REVIEW | 8 (TP in review) | 2,236 (FP in review) | 2,244 |
| | NON_MATCH | 3 (FN non-match) | 4,448 (TN non-match) | 4,451 |
| | **Column Total** | **112** | **6,685** | **6,797 (100% Reconciled)** |

### Recomputed Metrics Breakdown (Calibrated Evidence Production Policy)
1. **Strict Operational Metrics**:
   - Operational TP = `103`
   - Operational FP = `1`
   - Operational FN = `112 - 103 = 9` (3 in NON_MATCH + 6 in REVIEW)
   - Operational Precision = `103 / (103 + 1) = 103 / 104 = 99.04%`
   - Operational Recall = `103 / 112 = 91.96%`
   - Operational F1 = `(2 * 0.9904 * 0.9196) / (0.9904 + 0.9196) = 95.37%`
2. **Autonomous Metrics (REVIEW Excluded)**:
   - Autonomous Evaluated Pairs = `104 + 5,196 = 5,300`
   - Autonomous Precision = `103 / 104 = 99.04%`
   - Autonomous Recall = `103 / (103 + 3) = 103 / 106 = 97.17%`
   - Autonomous F1 = `(2 * 0.9904 * 0.9717) / (0.9904 + 0.9717) = 98.10%`
   - Autonomous Specificity = `5,193 / (5,193 + 1) = 5,193 / 5,194 = 99.98%`
3. **Semi-Automated / Post-Review Metrics**:
   - Post-Review TP = `103 + 6 = 109`
   - Post-Review Recall = `109 / 112 = 97.32%`
   - Post-Review Precision = `109 / 110 = 99.09%`
   - Post-Review F1 = `98.20%`
   - Review Workload = `1,497 / 6,797 = 22.02%`
   - Review Duplicate Yield = `6 / 1,497 = 0.40%` (4 duplicate pairs per 1,000 reviewed)

---

## 5. Held-Out Test Protocol & Empirical Policy Selection

### Empirical Selection on Validation Partition (Zero Test Exposure)
Policy thresholds were finalized using DEV and VAL data prior to executing on the held-out test partition:

| Policy | Val Candidates | Val TP | Val FP | Val FN (Op) | Val Review | Operational Recall | Operational Precision | Operational F1 | Autonomous Precision |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Baseline | 298 | 2 | 1 | 20 | 76 | 9.09% | 66.67% | 16.00% | 66.67% |
| **Calibrated Evidence** | 298 | **20** | **0** | **2** | **65** | **90.91%** | **100.00%** | **95.24%** | **100.00%** |
| Autonomous High-Precision | 298 | 19 | 0 | 3 | 91 | 86.36% | 100.00% | 92.68% | 100.00% |

### Held-Out Test Partition Performance (Unseen Data: 174 records, 151 entities, 23 duplicate pairs)

| Metric | Baseline Policy | Calibrated Evidence (Production) | Autonomous High-Precision |
| :--- | :---: | :---: | :---: |
| **True Positives (TP)** | 0 | **19** | 19 |
| **False Positives (FP)** | 0 | **1** | 1 |
| **False Negatives (FN Operational)** | 23 | **4** | 4 |
| **True Negatives (TN Non-Match)** | 213 | **220** | 187 |
| **Review Decisions** | 69 | **49** | 82 |
| **Strict Operational Precision** | 0.00% | **95.00%** | 95.00% |
| **Strict Operational Recall** | 0.00% | **82.61%** | 82.61% |
| **Strict Operational F1** | 0.00% | **88.37%** | 88.37% |
| **Autonomous Precision** | 0.00% | **95.00%** | 95.00% |
| **Autonomous Specificity** | 100.00% | **99.55%** | 99.47% |

> [!IMPORTANT]
> **Test Protocol Audit & Methodological Classification**:
> - **Threshold & Policy Finalization**: Decision thresholds (tau_match=0.72) and feature weights were selected using DEV and VAL data prior to finalizing benchmark results.
> - **Execution History & Source Inspection**: During Milestone 7 execution, the benchmark suite evaluated DEV, VAL, and TEST concurrently. The single test false positive (`cp_rest_0183_rest_0822`) was inspected during diagnostic error analysis.
> - **Zero Post-Hoc Tuning**: No implementation, threshold, policy, or blocking changes were made to suppress or accommodate this test error. The error was preserved as a transparent limitation.
> - **Classification**: Because TEST metrics and errors were visible during diagnostic benchmarking iterations, this partition is methodologically classified as an **Exploratory Held-Out Partition (Exposed Unseen Evaluation)** rather than an untouched double-blind test set.

---

## 6. Independent Clustering Metrics Validation & Graph Dynamics

Clustering metrics were computed directly by comparing the predicted `EntityCluster` components against the ground-truth entity labels across **all 372,816 possible record pairs**:

| Clustering Metric | Baseline Policy | Calibrated Evidence Policy | Autonomous High-Precision | Full Arithmetic Formula |
| :--- | :---: | :---: | :---: | :--- |
| **Derived Clusters** | 855 | **761** | 763 | Multi-record: 103, Singletons: 658 |
| **Pairwise Clustering TP** | 8 | **102** | 100 | True duplicate pairs in same cluster |
| **Pairwise Clustering FP** | 1 | **1** | 1 | Non-duplicate pairs merged into same cluster |
| **Pairwise Clustering FN** | 104 | **10** | 12 | True duplicate pairs in separate clusters |
| **Pairwise Clustering TN** | 372,703 | **372,703** | 372,703 | Non-duplicate pairs in separate clusters |
| **Pairwise Clustering Precision** | 88.89% | **99.03%** | 99.01% | `102 / (102 + 1) = 102 / 103` |
| **Pairwise Clustering Recall** | 7.14% | **91.07%** | 89.29% | `102 / (102 + 10) = 102 / 112` |
| **Pairwise Clustering F1** | 13.22% | **94.88%** | 93.90% | `2 * 0.9903 * 0.9107 / (0.9903 + 0.9107)` |
| **Weighted Cluster Purity** | 0.9988 | **0.9988 (99.88%)** | 0.9988 | `863 / 864 = 99.8843%` (record-weighted) |
| **Unweighted Cluster Purity** | 0.9993 | **0.9993 (99.93%)** | 0.9993 | `760.5 / 761 = 99.9343%` (cluster-averaged) |

### Purity Mathematical Derivation
1. **Weighted Purity**: Defined as `(sum_{c in C} max_e |{r in c : GT(r)=e}|) / N`.
   - 102 pure clusters of size 2 contribute `102 * 2 = 204` majority records.
   - 658 pure singleton clusters contribute `658 * 1 = 658` majority records.
   - 1 impure cluster of size 2 (`ec_rest_0183_939a325d`) has 1 record from entity 91 and 1 from entity 711; `max(1, 1) = 1` majority record.
   - Sum = `204 + 658 + 1 = 863`. Weighted purity = `863 / 864 = 99.884%` -> **99.88%**.
2. **Unweighted Purity**: Defined as `(1 / |C|) * sum_{c in C} (max_e |{r in c : GT(r)=e}| / |c|)`.
   - 760 pure clusters have purity `1.0`. The 1 impure cluster has purity `1 / 2 = 0.5`.
   - Sum = `760 * 1.0 + 0.5 = 760.5`. Unweighted purity = `760.5 / 761 = 99.934%` -> **99.93%**.

### Downstream Graph Dynamics: Pairwise TP (103) vs Clustering TP (102)
A vital architectural insight was revealed by comparing pairwise decisions with derived clusters:
1. Pairwise decisions produced **103 True Positives**.
2. Derived clusters produced **102 Pairwise True Positives**.
3. **Root Cause**: The true duplicate pair `cp_rest_0182_rest_0183` ('ritz-carlton restaurant') was correctly classified as MATCH (score 0.9355). However, `rest_0183` was already merged with `rest_0822` ('ritz-carlton cafe') due to a higher edge score (0.9436). When `rest_0182` was considered, the edge between `rest_0182` and `rest_0822` contained a sub-venue discriminator conflict ('restaurant' vs 'cafe (atlanta)'), blocking `rest_0182` from joining the cluster. As a result, `rest_0182` remained a singleton, and the true duplicate edge was missed.
4. **Takeaway**: A single false positive pairwise merge can cause a cascading false negative in graph clustering.

---

## 7. Concrete Error Analysis & Known Limitations

### 1. False-Merge Error: `ec_rest_0183_939a325d`
- **Record A (`rest_0183`)**: `ritz-carlton restaurant` | `181 peachtree st.` | Atlanta | French (Classic)
- **Record B (`rest_0822`)**: `ritz-carlton cafe (atlanta)` | `181 peachtree st.` | Atlanta | American (New)
- **Outcome**: False Merge (Score: 0.9436 -> MATCH)
- **Root Cause**: `rest_0183` uses the generic word `restaurant` rather than a specific sub-venue keyword like `dining room`. Because `restaurant` is generic across dining establishments, treating `restaurant` as an incompatible sub-venue discriminator would cause widespread false negatives across normal duplicate listings.

### 2. Missed-Cluster Split Examples (10 Entities / 20 Records)
- **Entity 91 (`rest_0182` & `rest_0183`)**: `the ritz-carlton restaurant (atlanta)` vs `ritz-carlton restaurant` at `181 peachtree st. ne`. Blocked by downstream clustering conflict with `rest_0822`.
- **Entity 13 (`rest_0026` & `rest_0027`)**: `locanda veneta` at `3rd st.` vs `8638 w. third st.`. `rest_0026` omits building number and directional; routed to REVIEW (score 0.6975).
- **Entity 20 (`rest_0040` & `rest_0041`)**: `spago` at `1114 horn ave.` vs `spago (los angeles)` at `8795 sunset blvd.`. Restaurant relocated; conflicting building numbers trigger building veto (-0.55 penalty), dropping score to 0.1718 (NON_MATCH).
- **Entity 42 (`rest_0084` & `rest_0085`)**: `les celebrites` at `160 central park s` vs `155 w. 58th st.`. Distinct street entrances to the same hotel restaurant trigger building veto (NON_MATCH).

---

## 8. Implementation Integrity & Code Audit

A comprehensive line-by-line diff audit of all Milestone 7 code changes confirmed:
1. **Zero Ground-Truth Leakage**: Ground truth labels are never imported, accessed, or referenced in `normalization.py`, `comparison.py`, `decision.py`, or `clustering.py`. Automated test `test_scrambled_ground_truth_invariance` verifies 0.0 metric divergence when ground-truth labels are permuted.
2. **No Benchmark-Specific Hardcoding**: All normalization rules (street types, directionals, building number extraction, metro dictionary) are standard US postal/geographic canonicalizations.
3. **Backward Compatibility**: All Milestone 1-6 tests continue to pass without regression.
4. **Full Test Suite Passing**: 173 passing automated tests in 2.8s.
5. **Clean Working Tree**: `git diff --check` passes with zero whitespace or syntax errors; raw dataset `data/Restaurant.csv` remains strictly git-ignored.

---

## 9. Deterministic Fingerprints & Provenance Summary

- **Random Seed**: `42`
- **Master Deterministic Metrics Fingerprint**: `77ee58698d7009f51d6b5d369369be3de497b5743cffe3bec23b7d066d411403`
- **Dev Partition Fingerprint**: `632be003fb4fa06c5ced1e57d87d879bb029fba75e64a25ec9ca6e83a220ca92`
- **Val Partition Fingerprint**: `b86bc12c521094f69db8e9af241fe4296f09058b803c481042ff28c6702f8e36`
- **Test Partition Fingerprint**: `5e94310594b05dc13123345d7bfcd0b527445a63affabebe76017d834f5c2a7d`
- **Python Version**: `3.14.7` | **Platform**: `Linux-7.2.4-arch1-2-x86_64-with-glibc2.44`

---

## 10. Final Audit Verdict & Production Scope Limitations

### Audit Verdict: **PASS**
- All metrics, counts, denominators, and confusion matrices are 100% arithmetically reconciled.
- False negatives were reduced by **91.35%** (104 -> 9) with **zero increase in false merges** (1 FP maintained).
- Operational recall advanced from **7.14%** to **91.96%**, and Operational F1 increased from **13.22%** to **95.37%**.
- The candidate-count inconsistency between isolated sub-corpora and global blocking is fully explained and resolved.

### Scope Limitations (Non-Claim of Universal Production Readiness)
> [!WARNING]
> **Explicit Disclaimer**: While Milestone 7 satisfies all engineering criteria for this benchmark, this 864-record restaurant dataset **does not establish production readiness for arbitrary web-scale entity resolution**. Limitations include:
> 1. **Domain Specificity**: Address and venue heuristics are tailored to geographic entities; person and corporate OSINT domains require distinct attribute extractors (DOB, tax IDs, corporate affiliations).
> 2. **Metropolitan Coverage**: The metropolitan cluster mapping currently covers four major US urban areas; unbounded geographic resolution requires a comprehensive GIS database.
> 3. **Scalability Beyond O(N^2)**: At web scale (millions of records), blocking rules must use distributed inverted indices or vector search to maintain low reduction ratios.
