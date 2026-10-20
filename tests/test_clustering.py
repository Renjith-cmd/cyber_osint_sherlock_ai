import random
import pytest
from src.core.models import (
    Record,
    EntityType,
    CandidatePair,
    DecisionType,
    MatchDecision,
    ClusterStatus,
)
from src.core.comparison import PairwiseComparator
from src.core.decision import DecisionPolicy, MatchDecisionEngine
from src.core.clustering import (
    ConstraintAwareClusterer,
    ClusteringPolicy,
    ClusteringResult,
    RejectedMerge,
    ClusterAssignment,
)
from src.core.evaluation import (
    ClusteringMetrics,
    evaluate_clustering,
)
from tests.synthetic_dataset import (
    get_fictional_records,
    get_candidate_pairs,
    GROUND_TRUTH,
    GROUND_TRUTH_CLUSTERS,
)


def _make_match_decision(
    r1: Record,
    r2: Record,
    score: float = 0.9,
    decision_type: DecisionType = DecisionType.MATCH,
) -> MatchDecision:
    pair_id = f"cp_{min(r1.record_id, r2.record_id)}_{max(r1.record_id, r2.record_id)}"
    return MatchDecision(
        candidate_pair_id=pair_id,
        decision=decision_type,
        score=score,
        threshold=0.75,
        model_version="test_v1",
        evidence_references=["ev_mock"],
        explanation_metadata={
            "pair": pair_id,
            "left_record_id": r1.record_id,
            "right_record_id": r2.record_id,
        },
    )


# ---------------------------------------------------------------------------
# 1. Basic Clustering & Determinism
# ---------------------------------------------------------------------------

def test_singletons_when_no_positive_decisions():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="Jane Doe")
    
    clusterer = ConstraintAwareClusterer()
    result = clusterer.cluster([r1, r2], decisions=[])
    
    assert len(result.clusters) == 2
    assert {len(c.member_record_ids) for c in result.clusters} == {1}
    for c in result.clusters:
        assert c.status == ClusterStatus.ACTIVE
        assert c.quality_confidence_metadata["is_singleton"] is True
        assert len(c.quality_confidence_metadata["supporting_decision_ids"]) == 0


def test_pairwise_match_merges_records():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    dec = _make_match_decision(r1, r2, score=0.95)
    
    clusterer = ConstraintAwareClusterer()
    result = clusterer.cluster([r1, r2], decisions=[dec])
    
    assert len(result.clusters) == 1
    cluster = result.clusters[0]
    assert len(cluster.member_record_ids) == 2
    assert set(cluster.member_record_ids) == {"r1", "r2"}
    assert cluster.status == ClusterStatus.ACTIVE
    assert dec.candidate_pair_id in cluster.quality_confidence_metadata["supporting_decision_ids"]
    
    # Traceability checks
    for rid in ("r1", "r2"):
        assignment = result.assignments[rid]
        assert assignment.cluster_id == cluster.entity_cluster_id
        assert dec.candidate_pair_id in assignment.supporting_decision_ids


def test_deterministic_cluster_identifiers():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    dec = _make_match_decision(r1, r2, score=0.95)
    
    clusterer = ConstraintAwareClusterer()
    res1 = clusterer.cluster([r1, r2], [dec])
    res2 = clusterer.cluster([r2, r1], [dec])
    
    assert res1.clusters[0].entity_cluster_id == res2.clusters[0].entity_cluster_id
    assert res1.clusters[0].entity_cluster_id.startswith("ec_r1_")


# ---------------------------------------------------------------------------
# 2. Transitive Merging
# ---------------------------------------------------------------------------

def test_safe_transitive_merge():
    # A = B, B = C, no conflicts -> {A, B, C}
    ra = Record(record_id="ra", source_id="s1", entity_type=EntityType.PERSON, raw_name="Bruce Wayne", structured_attributes={"city": "Gotham"})
    rb = Record(record_id="rb", source_id="s1", entity_type=EntityType.PERSON, raw_name="B. Wayne", structured_attributes={"city": "Gotham"})
    rc = Record(record_id="rc", source_id="s1", entity_type=EntityType.PERSON, raw_name="Bruce Wayne", structured_attributes={"city": "Gotham"})
    
    dec_ab = _make_match_decision(ra, rb, score=0.90)
    dec_bc = _make_match_decision(rb, rc, score=0.88)
    
    clusterer = ConstraintAwareClusterer()
    result = clusterer.cluster([ra, rb, rc], [dec_ab, dec_bc])
    
    assert len(result.clusters) == 1
    assert set(result.clusters[0].member_record_ids) == {"ra", "rb", "rc"}
    assert len(result.rejected_merges) == 0


# ---------------------------------------------------------------------------
# 3. Adversarial: Transitive Contradiction & Explicit NON_MATCH
# ---------------------------------------------------------------------------

def test_adversarial_triangle_with_explicit_non_match():
    # A matches B, B matches C, but A non_match C
    ra = Record(record_id="ra", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alice Brown")
    rb = Record(record_id="rb", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alice Brown")
    rc = Record(record_id="rc", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alice Brown")
    
    dec_ab = _make_match_decision(ra, rb, score=0.95)
    dec_bc = _make_match_decision(rb, rc, score=0.90)
    dec_ac = _make_match_decision(ra, rc, score=0.10, decision_type=DecisionType.NON_MATCH)
    
    clusterer = ConstraintAwareClusterer()
    result = clusterer.cluster([ra, rb, rc], [dec_ab, dec_bc, dec_ac])
    
    # Merge of {ra, rb} and {rc} must be blocked because ra and rc have explicit NON_MATCH!
    assert len(result.clusters) == 2
    cluster_sizes = sorted([len(c.member_record_ids) for c in result.clusters])
    assert cluster_sizes == [1, 2]
    
    # Verify rejected merge was logged
    assert len(result.rejected_merges) >= 1
    rejection = result.rejected_merges[0]
    assert "Explicit NON_MATCH" in rejection.reason
    assert "ra" in rejection.conflicting_record_ids or "rc" in rejection.conflicting_record_ids


def test_adversarial_triangle_with_conflicting_attributes():
    # A matches B (no DOB on B), B matches C (no DOB on B), but A has DOB 1990 and C has DOB 1980.
    # No pairwise decision was generated for A-C (missing decision).
    ra = Record(record_id="ra", source_id="s1", entity_type=EntityType.PERSON, raw_name="David Smith", structured_attributes={"dob": "1990-01-01"})
    rb = Record(record_id="rb", source_id="s1", entity_type=EntityType.PERSON, raw_name="David Smith", structured_attributes={})
    rc = Record(record_id="rc", source_id="s1", entity_type=EntityType.PERSON, raw_name="David Smith", structured_attributes={"dob": "1980-05-15"})
    
    dec_ab = _make_match_decision(ra, rb, score=0.92)
    dec_bc = _make_match_decision(rb, rc, score=0.91)
    
    clusterer = ConstraintAwareClusterer()
    result = clusterer.cluster([ra, rb, rc], [dec_ab, dec_bc])
    
    # Constraint check between ra in C1 and rc in C2 finds conflicting DOB!
    assert len(result.clusters) == 2
    cluster_sizes = sorted([len(c.member_record_ids) for c in result.clusters])
    assert cluster_sizes == [1, 2]
    
    assert len(result.rejected_merges) >= 1
    assert any("High-value attribute contradiction" in rej.reason for rej in result.rejected_merges)


# ---------------------------------------------------------------------------
# 4. Adversarial: REVIEW Edges
# ---------------------------------------------------------------------------

def test_review_decision_does_not_merge_by_default():
    ra = Record(record_id="ra", source_id="s1", entity_type=EntityType.PERSON, raw_name="Sam Jones", structured_attributes={"city": "Austin"})
    rb = Record(record_id="rb", source_id="s1", entity_type=EntityType.PERSON, raw_name="Sam Jones", structured_attributes={"city": "Dallas"})
    
    dec_rev = _make_match_decision(ra, rb, score=0.65, decision_type=DecisionType.REVIEW)
    
    clusterer = ConstraintAwareClusterer(policy=ClusteringPolicy(allow_review_merges=False))
    result = clusterer.cluster([ra, rb], [dec_rev])
    
    # Must remain separate singletons
    assert len(result.clusters) == 2
    assert all(c.quality_confidence_metadata["is_singleton"] for c in result.clusters)


def test_review_decision_with_allow_review_policy():
    ra = Record(record_id="ra", source_id="s1", entity_type=EntityType.PERSON, raw_name="Sam Jones")
    rb = Record(record_id="rb", source_id="s1", entity_type=EntityType.PERSON, raw_name="Sam Jones")
    
    dec_rev = _make_match_decision(ra, rb, score=0.65, decision_type=DecisionType.REVIEW)
    
    clusterer = ConstraintAwareClusterer(policy=ClusteringPolicy(allow_review_merges=True))
    result = clusterer.cluster([ra, rb], [dec_rev])
    
    assert len(result.clusters) == 1
    assert result.clusters[0].status == ClusterStatus.PROVISIONAL


# ---------------------------------------------------------------------------
# 5. Adversarial: Missing Pairwise Decisions & Clique Enforcement
# ---------------------------------------------------------------------------

def test_require_full_clique_rejects_missing_edge():
    ra = Record(record_id="ra", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alex Ray")
    rb = Record(record_id="rb", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alex Ray")
    rc = Record(record_id="rc", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alex Ray")
    
    dec_ab = _make_match_decision(ra, rb, score=0.90)
    dec_bc = _make_match_decision(rb, rc, score=0.88)
    
    # With require_full_clique=True, merge between {ra, rb} and {rc} must be rejected
    policy = ClusteringPolicy(require_full_clique=True)
    clusterer = ConstraintAwareClusterer(policy=policy)
    result = clusterer.cluster([ra, rb, rc], [dec_ab, dec_bc])
    
    assert len(result.clusters) == 2
    assert any("Missing explicit MATCH decision" in rej.reason for rej in result.rejected_merges)


# ---------------------------------------------------------------------------
# 6. Adversarial: Entity Type Mismatch
# ---------------------------------------------------------------------------

def test_conflicting_entity_types_blocked():
    r_person = Record(record_id="rp", source_id="s1", entity_type=EntityType.PERSON, raw_name="Acme")
    r_org = Record(record_id="ro", source_id="s2", entity_type=EntityType.ORGANIZATION, raw_name="Acme")
    
    # Erroneous MATCH decision
    dec = _make_match_decision(r_person, r_org, score=0.99)
    
    clusterer = ConstraintAwareClusterer()
    result = clusterer.cluster([r_person, r_org], [dec])
    
    assert len(result.clusters) == 2
    assert len(result.rejected_merges) >= 1
    assert "Incompatible entity types" in result.rejected_merges[0].reason


# ---------------------------------------------------------------------------
# 7. Reversibility & Dynamic Rebuild
# ---------------------------------------------------------------------------

def test_cluster_reversal_when_decision_changes():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe", structured_attributes={"dob": "1980-01-01"})
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe", structured_attributes={"dob": "1980-01-01"})
    
    dec_match = _make_match_decision(r1, r2, score=0.95, decision_type=DecisionType.MATCH)
    
    clusterer = ConstraintAwareClusterer()
    res1 = clusterer.cluster([r1, r2], [dec_match])
    assert len(res1.clusters) == 1
    assert len(res1.clusters[0].member_record_ids) == 2
    
    # User / analyst flips decision to NON_MATCH (or evidence disproves match)
    dec_non_match = _make_match_decision(r1, r2, score=0.05, decision_type=DecisionType.NON_MATCH)
    
    res2 = clusterer.rebuild([r1, r2], [dec_non_match])
    assert len(res2.clusters) == 2
    assert all(len(c.member_record_ids) == 1 for c in res2.clusters)
    assert all(c.status == ClusterStatus.ACTIVE for c in res2.clusters)
    
    # Confirm raw records were never mutated
    assert r1.record_id == "r1"
    assert r2.record_id == "r2"


# ---------------------------------------------------------------------------
# 8. Input-Order Independence
# ---------------------------------------------------------------------------

def test_input_order_independence():
    records = get_fictional_records()
    engine = MatchDecisionEngine()
    candidate_pairs = get_candidate_pairs()
    
    record_map = {r.record_id: r for r in records}
    decisions = []
    for cp in candidate_pairs:
        dec, _ = engine.compare_and_decide(record_map[cp.left_record_id], record_map[cp.right_record_id], cp)
        decisions.append(dec)
        
    clusterer = ConstraintAwareClusterer()
    res_original = clusterer.cluster(records, decisions)
    
    # Shuffle multiple times
    rng = random.Random(42)
    for _ in range(5):
        shuffled_records = list(records)
        shuffled_decisions = list(decisions)
        rng.shuffle(shuffled_records)
        rng.shuffle(shuffled_decisions)
        
        res_shuffled = clusterer.cluster(shuffled_records, shuffled_decisions)
        
        # Compare cluster member sets
        orig_sets = sorted([set(c.member_record_ids) for c in res_original.clusters], key=lambda s: sorted(list(s)))
        shuf_sets = sorted([set(c.member_record_ids) for c in res_shuffled.clusters], key=lambda s: sorted(list(s)))
        assert orig_sets == shuf_sets
        
        # Compare assignments
        for rid in record_map:
            assert res_original.assignments[rid].cluster_id == res_shuffled.assignments[rid].cluster_id


# ---------------------------------------------------------------------------
# 9. Duplicate Records and Invalid References
# ---------------------------------------------------------------------------

def test_duplicate_records_handled_safely():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    clusterer = ConstraintAwareClusterer()
    result = clusterer.cluster([r1, r1], decisions=[])
    assert len(result.clusters) == 1
    assert len(result.clusters[0].member_record_ids) == 1


def test_invalid_decision_references_filtered():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    dec = MatchDecision(
        candidate_pair_id="cp_r1_r999",
        decision=DecisionType.MATCH,
        score=0.99,
        model_version="test_v1",
        evidence_references=[],
    )
    clusterer = ConstraintAwareClusterer()
    result = clusterer.cluster([r1], decisions=[dec])
    assert len(result.clusters) == 1
    assert tuple(result.clusters[0].member_record_ids) == ("r1",)


# ---------------------------------------------------------------------------
# 10. Synthetic Dataset End-to-End Clustering Evaluation
# ---------------------------------------------------------------------------

def test_synthetic_dataset_clustering_pipeline_with_alias():
    records = get_fictional_records()
    pairs = get_candidate_pairs()
    comparator = PairwiseComparator(known_aliases={"marshall mathers": ["eminem"]})
    engine = MatchDecisionEngine(comparator=comparator)
    record_map = {r.record_id: r for r in records}
    
    decisions = []
    for cp in pairs:
        dec, _ = engine.compare_and_decide(record_map[cp.left_record_id], record_map[cp.right_record_id], cp)
        decisions.append(dec)
        
    clusterer = ConstraintAwareClusterer()
    result = clusterer.cluster(records, decisions)
    
    # Evaluate clusters against GROUND_TRUTH_CLUSTERS
    metrics = evaluate_clustering(result.clusters, GROUND_TRUTH_CLUSTERS)
    
    assert metrics.total_records == 21
    assert metrics.total_clusters == 14
    assert metrics.cluster_purity == 1.0
    assert metrics.pairwise_precision == 1.0
    assert metrics.pairwise_recall == 1.0
    assert metrics.pairwise_f1 == 1.0
    
    # Verify Bruce Wayne 3-record cluster
    bw_cluster = [c for c in result.clusters if "r9a" in c.member_record_ids][0]
    assert set(bw_cluster.member_record_ids) == {"r9a", "r9b", "r9c"}
    
    # Verify non-matches remained singletons
    assert any(tuple(c.member_record_ids) == ("r5a",) for c in result.clusters)
    assert any(tuple(c.member_record_ids) == ("r5b",) for c in result.clusters)
    assert any(tuple(c.member_record_ids) == ("r6a",) for c in result.clusters)
    assert any(tuple(c.member_record_ids) == ("r6b",) for c in result.clusters)
    assert any(tuple(c.member_record_ids) == ("r7a",) for c in result.clusters)
    assert any(tuple(c.member_record_ids) == ("r7b",) for c in result.clusters)


def test_synthetic_dataset_clustering_pipeline_unresolved_review():
    # Without alias knowledge, Marshall Mathers & Eminem route to REVIEW
    records = get_fictional_records()
    pairs = get_candidate_pairs()
    engine = MatchDecisionEngine()
    record_map = {r.record_id: r for r in records}
    
    decisions = []
    for cp in pairs:
        dec, _ = engine.compare_and_decide(record_map[cp.left_record_id], record_map[cp.right_record_id], cp)
        decisions.append(dec)
        
    clusterer = ConstraintAwareClusterer()
    result = clusterer.cluster(records, decisions)
    
    # cp_r8a_r8b should be in unresolved_candidate_pairs
    assert "cp_r8a_r8b" in result.unresolved_candidate_pairs
    assert len(result.clusters) == 15  # r8a and r8b stay separate singletons
    
    metrics = evaluate_clustering(result.clusters, GROUND_TRUTH_CLUSTERS)
    # Zero false positives: precision remains 1.0
    assert metrics.pairwise_precision == 1.0
    assert metrics.cluster_purity == 1.0


# ---------------------------------------------------------------------------
# 11. Additional Audit & Adversarial Checks
# ---------------------------------------------------------------------------

def test_unsupported_transitive_merge_clique_completeness():
    # A-B is MATCH, B-C is MATCH; A-C has no decision and no contradiction.
    ra = Record(record_id="ra", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe", structured_attributes={"city": "Chicago"})
    rb = Record(record_id="rb", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe", structured_attributes={"city": "Chicago"})
    rc = Record(record_id="rc", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe", structured_attributes={"city": "Chicago"})

    dec_ab = _make_match_decision(ra, rb, score=0.92)
    dec_bc = _make_match_decision(rb, rc, score=0.91)

    # 1. Under default policy (require_full_clique=False):
    # Merges into 1 cluster, but quality_confidence_metadata explicitly flags that it is NOT a full clique!
    clusterer = ConstraintAwareClusterer()
    result = clusterer.cluster([ra, rb, rc], [dec_ab, dec_bc])

    assert len(result.clusters) == 1
    cluster = result.clusters[0]
    meta = cluster.quality_confidence_metadata
    assert meta["is_full_clique"] is False
    assert meta["pairwise_match_edge_count"] == 2
    assert meta["possible_edge_count"] == 3
    assert meta["clique_completeness_ratio"] == pytest.approx(2 / 3, rel=1e-3)

    # Provenance justification explains that it was merged via path connectivity and cross-member checks
    for mid in ("ra", "rb", "rc"):
        asgn = result.assignments[mid]
        assert "merged via path connectivity and cross-member consistency checks" in asgn.justification

    # 2. Under require_full_clique=True:
    # Merge of {ra, rb} and {rc} is strictly rejected due to missing explicit A-C edge!
    clusterer_strict = ConstraintAwareClusterer(policy=ClusteringPolicy(require_full_clique=True))
    result_strict = clusterer_strict.cluster([ra, rb, rc], [dec_ab, dec_bc])

    assert len(result_strict.clusters) == 2
    assert any("Missing explicit MATCH decision" in rej.reason for rej in result_strict.rejected_merges)


def test_duplicate_and_conflicting_decisions_for_same_pair():
    # Explicit NON_MATCH must strictly take precedence over a duplicate MATCH,
    # regardless of which one appears first in the input list.
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alex Ray")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alex Ray")

    dec_non = _make_match_decision(r1, r2, score=0.10, decision_type=DecisionType.NON_MATCH)
    dec_match = _make_match_decision(r1, r2, score=0.95, decision_type=DecisionType.MATCH)

    clusterer = ConstraintAwareClusterer()

    # Order A: NON_MATCH then MATCH
    res_a = clusterer.cluster([r1, r2], [dec_non, dec_match])
    assert len(res_a.clusters) == 2

    # Order B: MATCH then NON_MATCH (MATCH appears first, NON_MATCH follows)
    res_b = clusterer.cluster([r1, r2], [dec_match, dec_non])
    assert len(res_b.clusters) == 2


def test_duplicate_match_decisions_deduplication():
    # Multiple identical MATCH decisions should not artificially duplicate scores
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alex Ray")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alex Ray")

    dec1 = _make_match_decision(r1, r2, score=0.90)
    dec2 = _make_match_decision(r1, r2, score=0.90)

    clusterer = ConstraintAwareClusterer()
    result = clusterer.cluster([r1, r2], [dec1, dec2])

    assert len(result.clusters) == 1
    # Average score should be exactly 0.90
    assert result.clusters[0].quality_confidence_metadata["average_match_score"] == 0.90


def test_cross_cluster_4_record_contradiction_blocks_merge():
    # Cluster 1: {r1, r2}; Cluster 2: {r3, r4}.
    # Proposed MATCH between r2 and r3, but explicit NON_MATCH between r1 and r4.
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Person A")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="Person A")
    r3 = Record(record_id="r3", source_id="s1", entity_type=EntityType.PERSON, raw_name="Person A")
    r4 = Record(record_id="r4", source_id="s1", entity_type=EntityType.PERSON, raw_name="Person A")

    dec_12 = _make_match_decision(r1, r2, score=0.95)
    dec_34 = _make_match_decision(r3, r4, score=0.95)
    dec_23 = _make_match_decision(r2, r3, score=0.90)  # Bridge candidate
    dec_14 = _make_match_decision(r1, r4, score=0.05, decision_type=DecisionType.NON_MATCH)

    clusterer = ConstraintAwareClusterer()
    result = clusterer.cluster([r1, r2, r3, r4], [dec_12, dec_34, dec_23, dec_14])

    # The bridge merge between {r1, r2} and {r3, r4} must be blocked because r1 and r4 are NON_MATCH!
    assert len(result.clusters) == 2
    assert {frozenset(c.member_record_ids) for c in result.clusters} == {frozenset({"r1", "r2"}), frozenset({"r3", "r4"})}
    assert any("Explicit NON_MATCH" in rej.reason for rej in result.rejected_merges)



def test_source_uncertainty_policy_routes_dob_conflict_to_review():
    # Conflicting DOB between A and C where no pairwise decision was provided.
    ra = Record(record_id="ra", source_id="s1", entity_type=EntityType.PERSON, raw_name="David Smith", structured_attributes={"dob": "1990-01-01"})
    rb = Record(record_id="rb", source_id="s1", entity_type=EntityType.PERSON, raw_name="David Smith", structured_attributes={})
    rc = Record(record_id="rc", source_id="s1", entity_type=EntityType.PERSON, raw_name="David Smith", structured_attributes={"dob": "1980-05-15"})

    dec_ab = _make_match_decision(ra, rb, score=0.92)
    dec_bc = _make_match_decision(rb, rc, score=0.91)

    policy = ClusteringPolicy(route_conflicting_identifiers_to_review=True, allow_review_merges=False)
    clusterer = ConstraintAwareClusterer(policy=policy)
    result = clusterer.cluster([ra, rb, rc], [dec_ab, dec_bc])

    # Must remain 2 separate clusters
    assert len(result.clusters) == 2
    assert any("routed to review under unverified source uncertainty policy" in rej.reason for rej in result.rejected_merges)
    assert any(rej.conflicting_decision == DecisionType.REVIEW for rej in result.rejected_merges)
    assert any("ra" in p and "rc" in p for p in result.unresolved_candidate_pairs)


def test_ritz_carlton_graph_clustering_cascade_and_reversibility():
    """
    Deterministic regression test for the Ritz-Carlton graph-clustering cascade:
    1. A false pairwise merge (rest_0183 'restaurant' vs rest_0822 'cafe') occurs due to high score (0.9436).
    2. A valid entity pair (rest_0182 vs rest_0183, score 0.9355) cannot merge because rest_0182 has
       an explicit NON_MATCH / sub-venue conflict with rest_0822.
    3. The clusterer must strictly prevent the contradictory 3-way merge and record a RejectedMerge.
    4. When the false pairwise merge is reversed/corrected, the valid entity merges into a single cluster,
       proving reversibility, explainability, and constraint enforcement.
    """
    r182 = Record(
        record_id="rest_0182",
        source_id="src_zagat",
        entity_type=EntityType.ORGANIZATION,
        raw_name="the ritz-carlton restaurant (atlanta)",
        structured_attributes={"address": "181 peachtree st. ne", "city": "atlanta"},
    )
    r183 = Record(
        record_id="rest_0183",
        source_id="src_fodors",
        entity_type=EntityType.ORGANIZATION,
        raw_name="ritz-carlton restaurant",
        structured_attributes={"address": "181 peachtree st.", "city": "atlanta"},
    )
    r822 = Record(
        record_id="rest_0822",
        source_id="src_fodors",
        entity_type=EntityType.ORGANIZATION,
        raw_name="ritz-carlton cafe (atlanta)",
        structured_attributes={"address": "181 peachtree st.", "city": "atlanta"},
    )

    # Initial decisions: false merge between r183 and r822 has higher score than true duplicate pair
    d_183_822 = MatchDecision(
        candidate_pair_id="cp_rest_0183_rest_0822",
        decision=DecisionType.MATCH,
        score=0.9436,
        threshold=0.72,
        model_version="test_m7",
        explanation_metadata={"pair": "cp_rest_0183_rest_0822"},
    )
    d_182_183 = MatchDecision(
        candidate_pair_id="cp_rest_0182_rest_0183",
        decision=DecisionType.MATCH,
        score=0.9355,
        threshold=0.72,
        model_version="test_m7",
        explanation_metadata={"pair": "cp_rest_0182_rest_0183"},
    )
    d_182_822 = MatchDecision(
        candidate_pair_id="cp_rest_0182_rest_0822",
        decision=DecisionType.NON_MATCH,
        score=0.15,
        threshold=0.35,
        model_version="test_m7",
        explanation_metadata={"pair": "cp_rest_0182_rest_0822"},
    )

    clusterer = ConstraintAwareClusterer(ClusteringPolicy())
    initial_res = clusterer.cluster([r182, r183, r822], [d_183_822, d_182_183, d_182_822])

    # 1. Contradictory cluster is NOT accepted; rest_0182 is kept out
    assert len(initial_res.clusters) == 2
    cluster_member_sets = [set(c.member_record_ids) for c in initial_res.clusters]
    assert {"rest_0183", "rest_0822"} in cluster_member_sets
    assert {"rest_0182"} in cluster_member_sets

    # 2. Rejection reason is explicitly documented with evidence
    assert len(initial_res.rejected_merges) >= 1
    rej = initial_res.rejected_merges[0]
    assert rej.candidate_pair_id == "cp_rest_0182_rest_0183" or "rest_0182" in rej.reason
    assert "Explicit NON_MATCH" in rej.reason
    assert "rest_0822" in rej.reason

    # 3. Reversibility verification: human investigator reverses false match to NON_MATCH
    d_183_822_corrected = MatchDecision(
        candidate_pair_id="cp_rest_0183_rest_0822",
        decision=DecisionType.NON_MATCH,
        score=0.20,
        threshold=0.35,
        model_version="test_m7_human_adjudicated",
        explanation_metadata={"pair": "cp_rest_0183_rest_0822", "adjudication": "rejected_venue_collision"},
    )

    corrected_res = clusterer.cluster([r182, r183, r822], [d_183_822_corrected, d_182_183, d_182_822])

    # 4. Valid entity is now unified without contradiction
    assert len(corrected_res.clusters) == 2
    corrected_member_sets = [set(c.member_record_ids) for c in corrected_res.clusters]
    assert {"rest_0182", "rest_0183"} in corrected_member_sets
    assert {"rest_0822"} in corrected_member_sets
    assert len(corrected_res.rejected_merges) == 0
