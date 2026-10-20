# Sherlock AI Core Foundation

This directory contains the foundational, non-destructive data architecture and evaluation engine for Sherlock AI.

---

## Architectural Principles & Design Guarantees

### 1. Immutability & Deep Payload Protection
A `Record` represents an exact empirical observation from a source at a specific point in time. If raw data is modified or overwritten during downstream normalization or entity merging, the original audit trail and provenance are permanently lost.

- **Top-Level Immutability:** All domain models (`Record`, `Source`, `CandidatePair`, `Evidence`, `MatchDecision`, `EntityCluster`) inherit from `ImmutableBaseModel`, configured with Pydantic's `frozen=True` and `extra="forbid"`. Any field reassignment raises a validation error.
- **Deep Payload Protection:** Nested dictionaries, lists, and sets within `raw_payload`, `normalized_attributes`, `structured_attributes`, and `metadata` are recursively converted to Python standard library immutable types (`types.MappingProxyType` for read-only mappings, `tuple` for immutable sequences, `frozenset` for sets). Calling mutating operations (such as `.append()`, `__setitem__`, `.pop()`, or `.update()`) raises a `TypeError` or `AttributeError`.
- **Complete Input Aliasing Decoupling:** Passing mutable objects—or read-only `MappingProxyType` wrappers over externally retained dictionaries—performs a recursive deep copy into fresh immutable views. Mutating the original external dictionary post-construction cannot alter the stored model.
- **Strict Payload Type Validation & Cycle Protection:** Payload values are strictly restricted to JSON-compatible primitives (`str`, `int`, `float`, `bool`, `None`), datetimes, dates, times, bytes, UUIDs, enums, and container types (`Mapping`, `Sequence`, `Set`). Unsupported mutable custom objects raise a `TypeError`. Cyclic structures are detected and rejected with a `ValueError`.
- **Serialization Fidelity:** `ImmutableBaseModel` employs `@model_serializer(mode="plain")` to recursively unfreeze internal containers back to standard Python `dict` and `list` structures, ensuring that `model_dump()` and `model_dump_json()` output clean, JSON-compatible types without leaking internal container wrappers.

### 2. Separation of Raw vs. Normalized Attributes
- `raw_name` and `raw_payload` store unmanipulated data as observed from the underlying data source (e.g., verbatim spelling, original casing, unparsed payload strings).
- `normalized_attributes` and `structured_attributes` store derived, standardized data (e.g., lowercase names, parsed dates, standardized tax/registration IDs).
- Normalization operations must produce new derived structures and must never mutate or overwrite raw observation fields.

### 3. Canonical Candidate Pairs
Pairwise entity comparison is symmetric: comparing `(record_A, record_B)` is logically identical to `(record_B, record_A)`.
- `CandidatePair` normalizes its input record IDs during construction such that `left_record_id <= right_record_id`.
- Constructing `CandidatePair` with `(r1, r2)` or `(r2, r1)` produces the exact same canonical pair with identical `canonical_pair_key` (`"r1::r2"`).
- Candidate pairs with identical IDs (`left_record_id == right_record_id`) are rejected.

### 4. Pairwise Evaluator Policies
The `PairwiseEvaluator` assesses predictions against binary ground-truth labels.

#### A. Ungrounded Predictions (Predictions Outside Ground Truth)
A prediction whose candidate pair ID is absent from ground truth has an unknown label. Fabricating a ground-truth label or silently dropping the prediction creates severe evaluation bias.
- **Default Policy (`UnknownPredictionPolicy.RAISE`):** Raises a `ValueError` listing the unknown pair IDs.
- **Opt-in Policy (`UnknownPredictionPolicy.IGNORE`):** Silently ignores ungrounded pairs (use only for partial sub-graph benchmarks).
- **Opt-in Policy (`UnknownPredictionPolicy.PENALIZE_AS_FP`):** Penalizes any predicted MATCH on an ungrounded pair as a False Positive without fabricating ground-truth labels.

#### B. Missing Predictions
Candidate pairs present in ground truth but omitted from predictions represent candidates filtered out or missed by blocking:
- If the omitted pair was an actual match (`is_actual_match=True`), it counts as a **False Negative** (missed match).
- If the omitted pair was a non-match (`is_actual_match=False`), it counts as a **True Negative** (correct rejection).

#### C. Upstream Duplicate Detection
Dictionary inputs (`Dict[str, DecisionType]`) can mask duplicate predictions produced upstream. Use `PairwiseEvaluator.validate_and_build_predictions(decisions)` on sequences of `MatchDecision` or tuples to detect and reject duplicate pair IDs before evaluation.

#### D. The `REVIEW` Decision State
Entity resolution often encounters ambiguous cases requiring human adjudication. The evaluator supports configurable policies:
- **Default (`review_is_match=False, review_is_error=True`):**
  - REVIEW on a true match counts as a False Negative (missed match).
  - REVIEW on a true non-match counts as a False Positive (false alarm alert).
- **`review_is_match=True`:**
  - REVIEW counts as a MATCH (TP on actual match, FP on actual non-match).
- **`review_is_match=False, review_is_error=False`:**
  - REVIEW on a true match counts as FN.
  - REVIEW on a true non-match counts as TN (neutral alert).

---

## Candidate Generation & Blocking (Milestone 2)

Candidate generation is the indexing layer that proposes plausible record pairs for downstream pairwise comparison. It reduces the $O(N^2)$ Cartesian product of record comparisons into a tractable candidate set while retaining known true matches.

### Core Principles
1. **Candidate Generation is Not Matching:** Blocking does not declare two records to be the same identity. It proposes plausible candidates. Unannotated or non-matching candidate pairs are not classified as errors at this stage.
2. **High Recall with Aggressive Pair Reduction:** Candidate generation must maximize the retention of true matches while pruning unpromising comparisons.
3. **Non-Destructive & Immutable:** Input records are never mutated. No record merging or clustering takes place.
4. **Canonical Ordering:** Emits deduplicated `CandidatePair` instances where `left_record_id < right_record_id`.
5. **Deterministic Execution:** Results and blocking signals are strictly identical regardless of the order in which input records are supplied.
6. **Entity Type Compatibility:** By default (`allow_cross_entity_type=False`), records of different entity types (e.g. `ORGANIZATION` vs `LOCATION`) are never paired.

### Supported Blocking Strategies
- **`ExactNameRule`:** Blocks on exact normalized `raw_name` (Unicode NFKC normalized, casefolded, whitespace collapsed).
- **`NameTokenRule`:** Blocks on individual normalized tokens from `raw_name` (default `min_token_length=2`). Captures partial, shared family, or transposed names.
- **`NameFingerprintRule`:** Blocks on order-invariant token fingerprints (e.g. `"Smith, John"` and `"John Smith"` both map to `"fingerprint:john smith"`).
- **`InitialsAcronymRule`:** Blocks on token initials and uppercase acronyms (e.g. `"International Business Machines"` and `"IBM"` both map to `"acronym:ibm"`).
- **`NameSoundexRule`:** Blocks on American Soundex phonetic codes of Latin name tokens (e.g. `"Sarah Connor"` and `"Sara Connor"` both map to `"soundex:S600"`).
- **`StructuredAttributeRule`:** Blocks on exact normalized values of structured attributes (e.g. `dob`, `phone`, `org`, `city`). Connects aliases sharing non-name identifiers (e.g. `"Marshall Mathers"` and `"Eminem"` sharing `city: "Detroit"`).

### Candidate Recall & Reduction Metrics
Evaluated using `evaluate_candidate_generation()`:
- **Candidate Recall:**
  $$\text{candidate recall} = \frac{\text{known positive pairs generated as candidates}}{\text{all known positive pairs}}$$
  Guarded against zero denominators: returns `0.0` if no positive pairs exist.
- **Pair Reduction Ratio:**
  $$\text{reduction ratio} = 1.0 - \frac{\text{generated candidate pairs}}{\text{total possible pairs}}$$
  where $\text{total possible pairs} = \frac{N(N - 1)}{2}$. Measures the percentage of comparisons pruned from downstream evaluation.

### Usage Example
```python
from src.core.models import Record, EntityType
from src.core.blocking import CandidateGenerator, get_default_blocking_rules
from src.core.evaluation import evaluate_candidate_generation

# 1. Define records
records = [
    Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Sarah Connor", structured_attributes={"city": "Los Angeles"}),
    Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="Sara Connor", structured_attributes={"city": "Los Angeles"}),
    Record(record_id="r3", source_id="s2", entity_type=EntityType.PERSON, raw_name="David Bowman", structured_attributes={"city": "New York"}),
]

# 2. Generate candidate pairs
generator = CandidateGenerator(rules=get_default_blocking_rules())
candidates = generator.generate_candidates(records)

# 3. Evaluate candidate generation against ground truth
ground_truth = {"cp_r1_r2": True}
metrics = evaluate_candidate_generation(candidates, ground_truth, total_records=len(records))

print(f"Candidate Recall: {metrics.candidate_recall:.2%}")      # 100.00%
print(f"Reduction Ratio:  {metrics.reduction_ratio:.2%}")       # 66.67%
```

### Known Limitations & Future Improvements
1. **Script-Specific Phonetics:** Soundex is Latin/English-specific; it does not generate phonetic codes for non-Latin scripts (Cyrillic, Arabic, Chinese). Future milestones can incorporate script-aware phonetic algorithms (e.g., Metaphone or Beider-Morse).
2. **Completely Disjoint Observations:** If two records representing the same entity share no name tokens, no phonetics, no initials, and no recorded attributes, deterministic rule-based blocking will not pair them.
3. **Common Name Over-generation:** Highly frequent tokens (e.g. common first names) can produce large blocks. The `max_block_size` parameter provides a safeguard against combinatorial explosions.

---

## Pairwise Comparison & Explainable Match Decisions (Milestone 3)

Milestone 3 implements the pairwise comparison and decision layer that consumes candidate pairs generated by blocking and produces evidence-backed, explainable entity resolution decisions (`MATCH`, `NON_MATCH`, `REVIEW`).

### Conceptual Pipeline Flow

```
Records
   │
   ▼
CandidateGenerator (Blocking Rules)
   │
   ▼  CandidatePair (Unordered, deduplicated)
PairwiseComparator
   │
   ├─► ComparisonResult (Bounded similarity scores & contradiction signals)
   │
   └─► Tuple[Evidence, ...] (Immutable, auditable evidence records with provenance)
   │
   ▼
MatchDecisionEngine (DecisionPolicy)
   │
   ▼  MatchDecision (MATCH / NON_MATCH / REVIEW, score, threshold, evidence refs)
Evaluation (evaluate_match_decisions, evaluate_end_to_end_pipeline)
```

### Critical Conceptual Distinctions

To ensure auditability and avoid misleading claims, the system strictly separates four distinct concepts:

| Concept | Definition & Role |
| :--- | :--- |
| **Candidate** | An unverified pair of records proposed by blocking for further inspection. Proposing a candidate reduces the $O(N^2)$ Cartesian search space; it is context, **not** proof of identity. |
| **Comparison Score** | A deterministic, bounded numerical value in $[0.0, 1.0]$ quantifying feature similarity across specific attributes (e.g. Jaro-Winkler string similarity, token containment, attribute agreement). |
| **Match Decision** | An auditable, operational classification (`MATCH`, `NON_MATCH`, `REVIEW`) produced by applying an explicit, configurable `DecisionPolicy` to comparison scores and contradiction constraints. |
| **Calibrated Probability** | A statistical guarantee where a predicted score $s$ corresponds to empirical truth (e.g. exactly 80% of pairs scoring 0.80 are true matches). **Heuristic comparison scores in this engine are NOT claimed to be calibrated probabilities.** |

### 1. Pairwise Comparison (`PairwiseComparator`)

Located in `src/core/comparison.py`, the `PairwiseComparator` implements deterministic, offline algorithms using only the standard library and existing dependencies:

- **Exact & Fingerprint Name Agreement:** Normalized exact string match and order-invariant token fingerprint matching.
- **Acronym & Initial Matching:** Detects abbreviations (e.g. `"IBM"` $\leftrightarrow$ `"International Business Machines"`) and given-name initial + surname agreements (e.g. `"B. Wayne"` $\leftrightarrow$ `"Bruce Wayne"`).
- **Phonetic & Fuzzy Similarity:** American Soundex code matching and character-level Jaro-Winkler similarity for minor typos.
- **Discriminator Token Conflict Detection:** Identifies conflicting sequential or ordinal discriminators (e.g. `"Employee A"` vs `"Employee B"`), penalizing similarity and emitting contradiction evidence.
- **Attribute Agreement & Contradiction:** Distinguishes high-value identifiers (e.g. `dob`, `ssn`, `tax_id`) from contextual attributes (e.g. `city`, `org`, `role`).
- **Neutral Missing Attribute Handling:** Missing attributes produce `NEUTRAL` evidence with strength `0.0`, ensuring absence of information is never treated as a contradiction.
- **Entity Type Compatibility:** Records of mismatched types (e.g. `ORGANIZATION` vs `LOCATION`) trigger fatal contradiction evidence.

### 2. Evidence Model Contracts (`Evidence`)

Every feature comparison generates an immutable `Evidence` instance containing:
- `evidence_id`: Unique deterministic identifier scoped to the candidate pair.
- `evidence_type`: Specific comparison category (e.g. `name_exact_match`, `name_discriminator_conflict`, `high_value_conflict_dob`).
- `polarity`: `SUPPORTING`, `CONTRADICTING`, or `NEUTRAL`.
- `strength`: Bounded float in $[0.0, 1.0]$.
- `provenance`: Audit trail identifying the generating component version.
- `value_description`: Concise, human-readable, reproducible explanation.

### 3. Match Decision Engine (`MatchDecisionEngine`)

Located in `src/core/decision.py`, the engine evaluates `ComparisonResult` instances under a configurable `DecisionPolicy`:

- **MATCH:** Evidence sufficiently supports identity ($\text{score} \ge \text{match\_threshold}$) with no fatal contradictions.
- **NON_MATCH:** Evidence supports distinct entities ($\text{score} \le \text{non\_match\_threshold}$), mismatched entity types, or fatal high-value identifier conflicts.
- **REVIEW:** Ambiguous, incomplete, or borderline cases ($ \text{non\_match\_threshold} < \text{score} < \text{match\_threshold} $), or disparate names sharing only common contextual attributes (e.g. same city or organization).
- **Contradiction Protection:** Conflicting dates of birth or unique IDs strictly prevent `MATCH`, regardless of name agreement.
- **Context vs. Identity:** Shared city or company is never treated as sufficient proof that two people are identical.

### 4. Comprehensive Evaluation

Located in `src/core/evaluation.py`:

- **Candidate Recall ($R_{\text{cand}}$):** Evaluates blocking coverage of true positive pairs (Milestone 2).
- **Match Decision Metrics (`MatchEvaluationMetrics`):** Evaluates decision accuracy on labeled candidates ($\text{Precision}$, $\text{Recall}$, $\text{F1}$, $\text{REVIEW rate}$).
- **End-to-End Metrics (`EndToEndEvaluationMetrics`):** Assesses the complete pipeline from records to decisions:
  $$R_{\text{e2e}} = \frac{\text{True Positives Decided as MATCH}}{\text{Total Ground-Truth Positive Pairs in Dataset}}$$
  Accounting explicitly for true matches lost during candidate generation.

### End-to-End Pipeline Usage Example

```python
from src.core.models import Record, EntityType, DecisionType
from src.core.blocking import CandidateGenerator, get_default_blocking_rules
from src.core.comparison import PairwiseComparator
from src.core.decision import DecisionPolicy, MatchDecisionEngine
from src.core.evaluation import (
    evaluate_candidate_generation,
    evaluate_match_decisions,
    evaluate_end_to_end_pipeline,
)

# 1. Define records
records_list = [
    Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Bruce Wayne", structured_attributes={"role": "CEO"}),
    Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="B. Wayne", structured_attributes={"role": "CEO", "city": "Gotham"}),
    Record(record_id="r3", source_id="s2", entity_type=EntityType.PERSON, raw_name="David Bowman", structured_attributes={"city": "Gotham"}),
]
records = {r.record_id: r for r in records_list}

# 2. Generate candidate pairs via blocking
generator = CandidateGenerator(rules=get_default_blocking_rules())
candidates = generator.generate_candidates(records_list)

# 3. Pairwise comparison and decision engine
engine = MatchDecisionEngine(policy=DecisionPolicy(match_threshold=0.75, non_match_threshold=0.38))
decisions = engine.decide_candidates(records, candidates)

for dec in decisions:
    print(f"Pair: {dec.candidate_pair_id} -> Decision: {dec.decision.value} (Score: {dec.score:.3f})")

# 4. End-to-end evaluation against labeled ground truth
ground_truth = {"cp_r1_r2": True}
cand_metrics = evaluate_candidate_generation(candidates, ground_truth, total_records=len(records))
e2e_metrics = evaluate_end_to_end_pipeline(cand_metrics, decisions, ground_truth)

print(f"Candidate Recall: {e2e_metrics.candidate_recall:.2%}")
print(f"End-to-End Recall: {e2e_metrics.end_to_end_recall:.2%}")
print(f"Decision Precision: {e2e_metrics.precision:.2%}")
```

---

## Constraint-Aware Clustering & Reversible Identity Assignments (Milestone 4)

Milestone 4 implements the clustering layer that converts pairwise `MatchDecision` outputs into derived `EntityCluster` instances while preserving raw records and allowing cluster assignments to be dynamically revised or reversed.

### Why Naive Connected Components is Insufficient

In entity resolution, identity is not unconditionally transitive. Naive connected components assumes that if $A \approx B$ and $B \approx C$, then $A \approx C$. In real-world OSINT and entity resolution, this assumption fails catastrophically:
1. **Adversarial Triangles:** Record $A$ matches $B$ (common name, missing DOB) and $B$ matches $C$ (same name, missing DOB), but $A$ and $C$ possess contradictory dates of birth or explicit `NON_MATCH` decisions. Naive connected components silently merges all three records into a single corrupted entity.
2. **Ambiguity Masking:** Naive clustering treats uncertain `REVIEW` edges identically to high-confidence `MATCH` edges, contaminating clean identity clusters.
3. **Absence of Negative Constraints:** A single false positive match can cause an entire cascade of distinct identities to collapse into a single giant cluster.

### The Constraint-Aware Clustering Strategy

The `ConstraintAwareClusterer` (located in `src/core/clustering.py`) employs a greedy, constrained agglomerative clustering algorithm with deterministic edge ordering and strict cross-member invariant checks:

1. **Deterministic Edge Prioritization:** Positive candidate edges are sorted descending by match score, tie-breaking lexicographically by canonical pair key (`idA::idB`). This guarantees strictly **input-order-independent** results.
2. **All-Pairs Cross-Member Compatibility:** Before merging two clusters $C_1$ and $C_2$, the clusterer inspects every cross-cluster pair $(u, v) \in C_1 \times C_2$:
   - **Entity Type Invariance:** If any $u$ and $v$ have different `EntityType`, the merge is rejected.
   - **Explicit Negative Decisions:** If any pair has an explicit `NON_MATCH` decision, the merge is strictly blocked. In duplicate or conflicting pairwise inputs, `NON_MATCH` strictly takes precedence over `MATCH`.
   - **Unresolved Ambiguities:** If any pair has a `REVIEW` decision and `allow_review_merges=False` (default), the merge is blocked.
   - **Missing Comparison Inspection:** Missing decisions are never assumed to be positive evidence. When `require_full_clique=False`, the clusterer invokes `PairwiseComparator` directly on $(u, v)$ to verify that no fatal attribute contradictions (conflicting DOB, SSN, Tax ID) exist before permitting the merge.
   - **Source Quality Uncertainty:** When `route_conflicting_identifiers_to_review=True`, high-value attribute conflicts on missing edges are treated as REVIEW-level uncertainty and tracked in `unresolved_candidate_pairs`, rather than assumed to be an infallible factual contradiction.
   - **Cluster Size Limits:** Merges exceeding `max_cluster_size` are rejected to prevent runaway giant clusters.
3. **Auditability & Explainability:** Every rejected merge is logged as an immutable `RejectedMerge` instance with the exact contradiction reason, conflicting decision, and record IDs. Every record's assignment is recorded in `ClusterAssignment` with supporting decision IDs and justification. The cluster's `quality_confidence_metadata` tracks `is_full_clique`, `pairwise_match_edge_count`, and `clique_completeness_ratio` so that transitive closure is never misrepresented as direct pairwise proof.
4. **Stable Deterministic Cluster Identifiers:** Cluster IDs are generated using the lexicographically lowest record ID and a cryptographic hash of all sorted member IDs (`ec_{min_id}_{hash}`).
5. **Complete Reversibility:** Raw `Record` objects are never merged or mutated. If a previously accepted `MATCH` decision is corrected to `NON_MATCH` (or removed), invoking `clusterer.rebuild(records, updated_decisions)` immediately dissolves the cluster into separate singletons or sub-clusters without data loss.


### Cluster Evaluation Metrics

Located in `src/core/evaluation.py`, `evaluate_clustering()` evaluates derived clusters against ground-truth entity labels:
- **Pairwise Cluster Precision:** Proportion of record pairs placed in the same cluster that truly belong together.
- **Pairwise Cluster Recall:** Proportion of true matching record pairs that were successfully placed in the same cluster.
- **Pairwise Cluster F1:** Harmonic mean of cluster precision and recall.
- **Cluster Purity:** Weighted majority class agreement across all clusters.

### Clustering Pipeline Usage Example

```python
from src.core.models import Record, EntityType
from src.core.blocking import CandidateGenerator, get_default_blocking_rules
from src.core.decision import MatchDecisionEngine
from src.core.clustering import ConstraintAwareClusterer, ClusteringPolicy
from src.core.evaluation import evaluate_clustering

# 1. Input records
records = [
    Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Bruce Wayne", structured_attributes={"city": "Gotham"}),
    Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="B. Wayne", structured_attributes={"city": "Gotham"}),
    Record(record_id="r3", source_id="s2", entity_type=EntityType.PERSON, raw_name="Bruce Wayne", structured_attributes={"city": "Gotham"}),
]

# 2. Candidate generation & match decisions
generator = CandidateGenerator(rules=get_default_blocking_rules())
candidates = generator.generate_candidates(records)

engine = MatchDecisionEngine()
decisions = engine.decide_candidates({r.record_id: r for r in records}, candidates)

# 3. Constraint-aware clustering
clusterer = ConstraintAwareClusterer(policy=ClusteringPolicy(allow_review_merges=False))
result = clusterer.cluster(records, decisions)

for cluster in result.clusters:
    print(f"Cluster {cluster.entity_cluster_id}: members={cluster.member_record_ids}, status={cluster.status.value}")

# 4. Reversibility demonstration
# Revoke a decision -> rebuild immediately reconstitutes clean clusters
revised_decisions = [d for d in decisions if d.candidate_pair_id != "cp_r1_r2"]
rebuilt = clusterer.rebuild(records, revised_decisions)
```

---

---

## Reproducible End-to-End Evaluation & Benchmarking (Milestone 5)

Milestone 5 establishes a reproducible, leakage-resistant benchmark and evaluation suite (`src/core/benchmark.py`) that executes the entire Sherlock AI entity resolution pipeline end-to-end:

$$\text{Records} \longrightarrow \text{Candidate Generation} \longrightarrow \text{Pairwise Comparison} \longrightarrow \text{Match Decision} \longrightarrow \text{Constraint-Aware Clustering} \longrightarrow \text{Multi-Stage Evaluation}$$

### 1. Architectural Leakage Prevention

A primary failure mode in machine learning and entity resolution evaluation is benchmark leakage. Sherlock AI enforces strict architectural safeguards:
- **Oracle Boundary:** The benchmark pipeline runner `execute_pipeline()` accepts only raw `Record` objects, explicit alias configuration mappings, and pipeline components. Ground truth (`ground_truth_entities` and `ground_truth_pairs`) is strictly segregated and cannot be passed to or accessed by blocking, comparison, decision, or clustering logic.
- **Explicit Alias Configuration:** Known alias mappings (such as Samuel Clemens $\leftrightarrow$ Mark Twain) must be supplied as explicit configuration, rather than inferred from benchmark labels. Unconfigured aliases (such as Eric Arthur Blair $\leftrightarrow$ George Orwell) are evaluated adversarially to prove the model does not leak truth.
- **Derived Cluster Purity:** Raw records remain immutable. Clusters are purely derived views that can be torn down and reconstituted.

### 2. Stage-by-Stage Independent Metrics

Each stage of the pipeline is evaluated independently to isolate blocking efficiency, pairwise classification quality, and clustering cohesion:

#### A. Candidate Generation
- **Total Possible Pairs:** Full Cartesian baseline $N(N - 1) / 2$.
- **Compatible Pairs:** Total pairs sharing the same `EntityType` when cross-type matching is disabled.
- **Candidate Count:** Number of canonical `CandidatePair` instances emitted by blocking.
- **Candidate Recall:** Proportion of known true positive pairs retained in the candidate set:
  $$\text{Candidate Recall} = \frac{|\text{Known Positives in Candidates}|}{|\text{All Known Positives}|}$$
- **Reduction Ratio (All Pairs):** $1.0 - (\text{Candidates} / \text{Total Possible Pairs})$.
- **Compatible Reduction Ratio:** $1.0 - (\text{Candidates} / \text{Compatible Possible Pairs})$.
- **Missed Known Positives:** Enumeration and count of true positive pairs filtered or unindexed by blocking rules. Never treats unannotated pairs as negative decisions.

#### B. Pairwise Matching
- **Confusion Matrix:** True Positives (TP), False Positives (FP), False Negatives (FN), True Negatives (TN).
- **Precision, Recall, F1, Accuracy:** Binary metrics with zero-division protection (returning `0.0` when denominators are zero).
- **Review Rate:** $\text{Review Count} / \text{Total Evaluated Pairs}$.
- **Configurable Review Handling:** Supports evaluating `REVIEW` decisions under default alert-error policy (`review_is_match=False, review_is_error=True`) or permissive policy (`review_is_match=True`).
- **Explainable Diagnostics:** Structured lists of false matches and missed matches, including record IDs, names, assigned scores, and decision justifications.

#### C. Constraint-Aware Clustering
- **Pairwise Cluster Precision:** Proportion of co-clustered record pairs that truly belong together.
- **Pairwise Cluster Recall:** Proportion of true entity record pairs successfully placed in the same cluster.
- **Pairwise Cluster F1:** Harmonic mean of cluster precision and recall.
- **Cluster Purity:** Weighted majority class agreement across all clusters.
- **Cluster Morphology:** Total clusters, singleton cluster count, multi-record cluster count, and largest cluster size.
- **Clustering Diagnostics:** Enumeration of incorrect merges, missed co-memberships, rejected merges blocked by negative constraints, and unclustered ground-truth records.

#### D. End-to-End Performance
- **Monotonic High-Resolution Timing:** Captures `candidate_generation_seconds`, `pairwise_matching_seconds`, `clustering_seconds`, `evaluation_seconds`, and `total_runtime_seconds` using `time.perf_counter()`.
- **Deterministic Metrics Fingerprint:** Computes a SHA-256 hash over deterministic scenario metadata, generated candidates, sorted decisions, cluster assignments, and metric scores. **All monotonic timings, timestamps, and environment metadata are strictly excluded from the fingerprint**, ensuring that repeated runs with identical seeds produce identical cryptographic fingerprints.

### 3. Controlled Benchmark Scenarios (14 Fixture Types)

The benchmark provides fixtures covering 14 distinct entity resolution challenges:
1. **Exact Duplicates:** Verbatim matching across names and identifiers (`dup_1`, `dup_2`).
2. **Spelling Variations & Transpositions:** Typographical errors and last-name-first permutations (`Alexander Hamilton` vs `Alexandar Hamilton` vs `Hamilton, Alexander`).
3. **Initials & Abbreviations:** Acronym expansion and given-name abbreviations (`NASA` $\leftrightarrow$ `National Aeronautics and Space Administration`, `A. C. Doyle` $\leftrightarrow$ `Arthur Conan Doyle`).
4. **Known Aliases (Configured):** Pseudonyms backed by explicit alias configuration (`Samuel Clemens` $\leftrightarrow$ `Mark Twain`).
5. **Known Aliases (Unconfigured / Adversarial):** Disparate names with unconfigured aliases (`Eric Arthur Blair` $\leftrightarrow$ `George Orwell`) to verify no leakage from oracle.
6. **Missing Attributes:** Records agreeing on name with missing auxiliary contact data.
7. **Common Names:** Homonyms belonging to different individuals (`John Smith` dentist vs `John Smith` architect).
8. **Shared Context:** Colleagues sharing company and office location (`Alice Vance` vs `Gordon Freeman` at Black Mesa).
9. **Conflicting Attributes:** Identical names with fatal contradictions in high-value legal identifiers (conflicting DOB, Tax ID).
10. **Cross-Entity Types:** Similar names belonging to different entity types (`Abraham Lincoln` PERSON vs `Lincoln Motor Company` ORGANIZATION vs `Lincoln, Nebraska` LOCATION).
11. **Transitive Chain with Missing Edge:** Records $A \approx B$ and $B \approx C$ where pair $(A, C)$ is unindexed by blocking; demonstrates the operational difference between full-clique and default clustering.
12. **Explicit Contradictions in Candidate Component:** Positive edges co-existing with fatal `NON_MATCH` edges, verifying that transitive merges are safely blocked.
13. **Unrelated Isolated Records:** Singletons that generate no candidates, verifying clean singleton cluster formation.
14. **Mixed Cluster Sizes:** Benchmark populations containing singletons alongside clusters of 2, 3, and more records.

### 4. Fair Baseline Comparison

The benchmark evaluates four standard baselines under identical scenarios, records, comparator, and decision policies:

| Baseline | Candidate Pairs | Candidate Recall | Cluster Precision | Cluster Recall | Cluster F1 | Purity | Notes |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Baseline 1: Exhaustive Pairs** | 1,103 | 100.00% | 47.37% | 81.82% | 60.00% | 94.64% | Evaluates all type-compatible pairs; uncovers unindexed matches at the expense of lower precision. |
| **Baseline 2: Blocking Pipeline** | 51 | 90.91% | 68.00% | 85.00% | 75.56% | 94.64% | 95.38% candidate reduction; prunes noisy comparisons while preserving high recall. |
| **Baseline 3: Conservative Clustering** | 51 | 90.91% | 88.24% | 68.18% | 76.92% | 94.64% | Enforces strict full-clique requirement; prevents merges across uncorroborated transitive links. |
| **Baseline 4: Default Clustering** | 51 | 90.91% | 89.47% | 77.27% | 82.93% | 94.64% | Connected-component clustering with pairwise contradiction checks; bridges unindexed transitive chains safely. |

### 5. Running the Benchmark

#### CLI Command
```bash
# Run benchmark with seed 42 and output JSON results
.venv/bin/python -m src.core.benchmark --seed 42 --output artifacts/benchmarks/benchmark_results.json
```

#### CLI Options
- `--seed <int>`: Explicit random seed for procedural scenarios (default: `42`).
- `--output <path>`: Destination path for machine-readable JSON artifact (default: `artifacts/benchmarks/benchmark_results.json`).
- `--review-is-match`: Treat `REVIEW` decisions as `MATCH` outcomes during evaluation (default: `False`).
- `--review-not-error`: Do not penalize `REVIEW` decisions as errors when evaluating non-matches.
- `--procedural-size <int>`: Number of base entities for deterministic procedural generation (default: `15`).
- `--quiet`: Suppress human-readable console report.

#### Python API Usage
```python
from src.core.benchmark import BenchmarkRunner, BenchmarkRunConfig

config = BenchmarkRunConfig(seed=42)
runner = BenchmarkRunner(config)
report = runner.run_suite(include_edge_cases=True, include_procedural=True)

print("Deterministic Fingerprint:", report.deterministic_fingerprint)
print("Scenarios Evaluated:", len(report.scenarios))
```

---

## Real-World Dataset Integration & Evaluation (Milestone 6)

Milestone 6 integrates an authentic, real-world entity resolution benchmark into Sherlock AI, verifying operational performance, candidate blocking, pairwise matching, and constraint-aware clustering against empirical directory records with verified public domain licensing.

### 1. Dataset Selection & Provenance Verification

- **Selected Dataset:** Zagat-Fodor's Restaurant Entity Resolution Benchmark.
- **Original Source & Authors:** Sheila Tejada, Craig A. Knoblock, and Steven Minton (2001), *Learning Object Identification Rules for Information Integration*.
- **Curators & Distribution:** Rebecca Steorts et al. (CRAN `restaurant` package v0.1.0) and Chen, Shrivastava, Steorts (2018) in `cleanzr/fasthash`.
- **License:** **CC0 1.0 Universal (Public Domain Dedication)** — verified permitted use for modification, evaluation, and redistribution without restriction.
- **Scope & Characteristics:**
  - 864 records across Zagat Survey (533 records) and Fodor's Guide (331 records).
  - 752 unique ground-truth dining entities.
  - 112 true positive duplicate pairs (pure pairwise duplicates; no multi-party cliques).
  - 372,816 total possible unordered pairs.
  - 100% type-compatible (`ORGANIZATION`).

### 2. Dataset Adapter Architecture (`src/core/datasets.py`)

The dataset adapter provides clean ingest, schema mapping, and validation without external heavyweight dependencies:
- **Strict Ground-Truth Boundary:** Ground-truth class labels are never placed into `Record` attributes, blocking keys, comparator inputs, or clustering policies. They are returned separately as an evaluation oracle (`ground_truth_entities` and `ground_truth_pairs`).
- **Deterministic Record IDs:** Records are assigned stable, deterministic identifiers (`rest_0000`, `rest_0001`, ...).
- **Comprehensive Row Validation:** Verifies column counts, non-empty names, non-empty class IDs, and logs explicit rejection reasons (`DatasetLoadingReport`).
- **Offline Network-Independent Fixture:** Includes 10 authentic rows covering 3 true duplicate pairs and 4 singletons for fast, offline unit and integration testing without network access.

### 3. Real-World Evaluation & Baseline Results

Sherlock AI evaluated the entire 864-record dataset across all 4 benchmark baselines:

| Baseline | Candidates Evaluated | Candidate Reduction | Pairwise Recall | Pairwise Precision | Pairwise F1 | Cluster Purity |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Baseline 1: Exhaustive Pair Evaluation** | 372,816 | 0.00% | 7.14% | 0.01% | 0.02% | 99.88% |
| **Baseline 2: Existing Blocking Pipeline** | 6,797 | 98.18% | 7.14% | 0.50% | 0.94% | 99.88% |
| **Baseline 3: Conservative Clustering** | 6,797 | 98.18% | 7.14% | 88.89% | 13.22% | 99.88% |
| **Baseline 4: Default Clustering** | 6,797 | 98.18% | 7.14% | 88.89% | 13.22% | 99.88% |

#### Key Empirical Findings:
1. **Candidate Blocking Recall:** The candidate generator achieved **100.00% candidate recall** (retaining all 112 true duplicates) while reducing pairwise comparison volume by **98.18%** (from 372,816 pairs down to 6,797).
2. **Explainable Safety Policy:** Without governmental tax or business registration IDs, minor text discrepancies ("Third St." vs "3rd St.", "italian" vs "italian/californian") cause 104 true matches to be routed to analyst **REVIEW** (23.94% review rate) rather than forced into automated merges.
3. **Graph Integrity:** Constraint-aware clustering achieved **88.89% pairwise precision** and **99.88% cluster purity** because `allow_review_merges: False` protects against uncorroborated transitive links.

### 4. Running Real-World Evaluation

```bash
# Acquire dataset and run complete real-world benchmark with JSON and Markdown artifacts:
.venv/bin/python -m src.core.benchmark --real-world \
    --output artifacts/benchmarks/real_world/restaurant_benchmark_results.json \
    --report-md artifacts/benchmarks/real_world/restaurant_error_analysis.md

# Run offline using the 10-record fixture (no network, instant execution):
.venv/bin/python -m src.core.benchmark --real-world --use-fixture
```

---

## Installation & Running Tests

### 1. Requirements
The core domain models require Pydantic v2. Test suites require pytest.
- Production requirements: `requirements.txt`
- Development & test requirements: `requirements-dev.txt`

### 2. Environment Setup
```bash
# In your virtual environment:
pip install -r requirements-dev.txt
```

### 3. Executing Tests
```bash
# Run all core, normalization, blocking, comparison, decision, clustering, and benchmark tests:
.venv/bin/python -m pytest tests/ -v
```
