import pytest
from src.core.models import Record, EntityType, CandidatePair
from src.core.blocking import (
    CandidateGenerator,
    ExactNameRule,
    NameTokenRule,
    NameFingerprintRule,
    InitialsAcronymRule,
    NameSoundexRule,
    StructuredAttributeRule,
    get_default_blocking_rules,
)
from src.core.evaluation import (
    CandidateEvaluationMetrics,
    evaluate_candidate_generation,
)
from tests.synthetic_dataset import get_fictional_records, GROUND_TRUTH


# ---------------------------------------------------------------------------
# 1. Input Validation and Structural Contracts
# ---------------------------------------------------------------------------

def test_empty_and_singleton_inputs():
    gen = CandidateGenerator()
    assert gen.generate_candidates([]) == []
    
    rec = Record(
        record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe"
    )
    assert gen.generate_candidates([rec]) == []


def test_invalid_input_type_rejected():
    gen = CandidateGenerator()
    with pytest.raises(TypeError):
        gen.generate_candidates(["not_a_record"])  # type: ignore


def test_duplicate_record_ids_rejected():
    gen = CandidateGenerator()
    r1 = Record(record_id="dup_id", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    r2 = Record(record_id="dup_id", source_id="s2", entity_type=EntityType.PERSON, raw_name="Jane Doe")
    with pytest.raises(ValueError) as exc:
        gen.generate_candidates([r1, r2])
    assert "Duplicate record ID detected" in str(exc.value)


def test_canonical_pair_ordering_and_no_self_or_duplicates():
    gen = CandidateGenerator(rules=[ExactNameRule()])
    r1 = Record(record_id="r_bravo", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alice Smith")
    r2 = Record(record_id="r_alpha", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alice Smith")
    
    pairs = gen.generate_candidates([r1, r2])
    assert len(pairs) == 1
    pair = pairs[0]
    # left must be less than right
    assert pair.left_record_id == "r_alpha"
    assert pair.right_record_id == "r_bravo"
    assert pair.candidate_id == "cp_r_alpha_r_bravo"
    assert pair.left_record_id != pair.right_record_id


def test_deterministic_output_under_input_shuffling():
    records = get_fictional_records()
    gen = CandidateGenerator()
    
    pairs_normal = gen.generate_candidates(records)
    
    # Reverse input order
    reversed_records = list(reversed(records))
    pairs_reversed = gen.generate_candidates(reversed_records)
    
    assert len(pairs_normal) == len(pairs_reversed)
    for p1, p2 in zip(pairs_normal, pairs_reversed):
        assert p1.candidate_id == p2.candidate_id
        assert p1.left_record_id == p2.left_record_id
        assert p1.right_record_id == p2.right_record_id
        assert p1.blocking_signals == p2.blocking_signals


def test_input_record_immutability():
    rec = Record(
        record_id="r1",
        source_id="s1",
        entity_type=EntityType.PERSON,
        raw_name="John Doe",
        structured_attributes={"city": "Boston"},
    )
    gen = CandidateGenerator()
    gen.generate_candidates([rec])
    
    # Verify input record remains unmodified
    assert rec.raw_name == "John Doe"
    assert rec.structured_attributes["city"] == "Boston"


# ---------------------------------------------------------------------------
# 2. Entity Type Compatibility
# ---------------------------------------------------------------------------

def test_entity_type_compatibility_filtering():
    # By default, cross-entity-type candidates are rejected
    r_org = Record(
        record_id="r_org",
        source_id="s1",
        entity_type=EntityType.ORGANIZATION,
        raw_name="Phoenix",
    )
    r_loc = Record(
        record_id="r_loc",
        source_id="s1",
        entity_type=EntityType.LOCATION,
        raw_name="Phoenix",
    )
    
    gen_strict = CandidateGenerator(rules=[ExactNameRule()], allow_cross_entity_type=False)
    assert gen_strict.generate_candidates([r_org, r_loc]) == []
    
    gen_cross = CandidateGenerator(rules=[ExactNameRule()], allow_cross_entity_type=True)
    cross_pairs = gen_cross.generate_candidates([r_org, r_loc])
    assert len(cross_pairs) == 1
    assert cross_pairs[0].candidate_id == "cp_r_loc_r_org"


# ---------------------------------------------------------------------------
# 3. Specific Candidate Generation Scenarios from Synthetic Dataset
# ---------------------------------------------------------------------------

def test_exact_duplicate_names():
    r1a = Record(record_id="r1a", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    r1b = Record(record_id="r1b", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    gen = CandidateGenerator(rules=[ExactNameRule()])
    pairs = gen.generate_candidates([r1a, r1b])
    assert len(pairs) == 1
    assert pairs[0].candidate_id == "cp_r1a_r1b"
    assert "exact_name" in pairs[0].blocking_signals["strategies"]


def test_case_punctuation_whitespace_variations():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="  John   DOE  ")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="john, doe.")
    gen = CandidateGenerator(rules=[NameFingerprintRule()])
    pairs = gen.generate_candidates([r1, r2])
    assert len(pairs) == 1
    assert pairs[0].candidate_id == "cp_r1_r2"


def test_minor_spelling_variation_soundex():
    # Sarah Connor vs Sara Connor
    r3a = Record(record_id="r3a", source_id="s3", entity_type=EntityType.PERSON, raw_name="Sarah Connor")
    r3b = Record(record_id="r3b", source_id="s3", entity_type=EntityType.PERSON, raw_name="Sara Connor")
    gen = CandidateGenerator(rules=[NameSoundexRule()])
    pairs = gen.generate_candidates([r3a, r3b])
    assert len(pairs) == 1
    assert pairs[0].candidate_id == "cp_r3a_r3b"
    assert "soundex:S600" in pairs[0].blocking_signals["matched_keys"]


def test_abbreviation_and_acronym_blocking():
    # International Business Machines vs IBM
    r2a = Record(record_id="r2a", source_id="s2", entity_type=EntityType.ORGANIZATION, raw_name="International Business Machines")
    r2b = Record(record_id="r2b", source_id="s2", entity_type=EntityType.ORGANIZATION, raw_name="IBM")
    gen = CandidateGenerator(rules=[InitialsAcronymRule()])
    pairs = gen.generate_candidates([r2a, r2b])
    assert len(pairs) == 1
    assert pairs[0].candidate_id == "cp_r2a_r2b"
    assert "acronym:ibm" in pairs[0].blocking_signals["matched_keys"]


def test_missing_attributes_blocking():
    # Alice Smith with phone vs Alice Smith with empty attributes
    r4a = Record(record_id="r4a", source_id="s4", entity_type=EntityType.PERSON, raw_name="Alice Smith", structured_attributes={"phone": "555-1234"})
    r4b = Record(record_id="r4b", source_id="s4", entity_type=EntityType.PERSON, raw_name="Alice Smith", structured_attributes={})
    gen = CandidateGenerator(rules=[ExactNameRule()])
    pairs = gen.generate_candidates([r4a, r4b])
    assert len(pairs) == 1
    assert pairs[0].candidate_id == "cp_r4a_r4b"


def test_alias_linked_via_structured_attribute():
    # Marshall Mathers vs Eminem linked via city='Detroit'
    r8a = Record(record_id="r8a", source_id="s8", entity_type=EntityType.PERSON, raw_name="Marshall Mathers", structured_attributes={"city": "Detroit"})
    r8b = Record(record_id="r8b", source_id="s8", entity_type=EntityType.PERSON, raw_name="Eminem", structured_attributes={"city": "Detroit"})
    gen = CandidateGenerator(rules=[StructuredAttributeRule("city")])
    pairs = gen.generate_candidates([r8a, r8b])
    assert len(pairs) == 1
    assert pairs[0].candidate_id == "cp_r8a_r8b"
    assert "attr:city:detroit" in pairs[0].blocking_signals["matched_keys"]


def test_common_name_collision_different_people():
    # Michael Jordan (Basketball) vs Michael Jordan (AI Researcher)
    # Blocking MUST propose this pair (high recall); downstream matching decides identity
    r5a = Record(record_id="r5a", source_id="s5", entity_type=EntityType.PERSON, raw_name="Michael Jordan", structured_attributes={"occupation": "Basketball"})
    r5b = Record(record_id="r5b", source_id="s5", entity_type=EntityType.PERSON, raw_name="Michael Jordan", structured_attributes={"occupation": "AI Researcher"})
    gen = CandidateGenerator(rules=[ExactNameRule()])
    pairs = gen.generate_candidates([r5a, r5b])
    assert len(pairs) == 1
    assert pairs[0].candidate_id == "cp_r5a_r5b"


def test_same_organization_different_people():
    # Employee A vs Employee B both in Cyberdyne Systems
    r6a = Record(record_id="r6a", source_id="s6", entity_type=EntityType.PERSON, raw_name="Employee A", structured_attributes={"org": "Cyberdyne Systems"})
    r6b = Record(record_id="r6b", source_id="s6", entity_type=EntityType.PERSON, raw_name="Employee B", structured_attributes={"org": "Cyberdyne Systems"})
    gen = CandidateGenerator(rules=[StructuredAttributeRule("org")])
    pairs = gen.generate_candidates([r6a, r6b])
    assert len(pairs) == 1
    assert pairs[0].candidate_id == "cp_r6a_r6b"


def test_unrelated_records_not_paired():
    # Acme Corp vs Mount Everest
    r10a = Record(record_id="r10a", source_id="s10", entity_type=EntityType.ORGANIZATION, raw_name="Acme Corp")
    r10b = Record(record_id="r10b", source_id="s10", entity_type=EntityType.LOCATION, raw_name="Mount Everest")
    gen = CandidateGenerator(rules=get_default_blocking_rules())
    pairs = gen.generate_candidates([r10a, r10b])
    assert pairs == []


def test_blocking_honest_limitation():
    # Records that share NO name tokens, NO phonetic keys, NO acronym, and NO attributes
    # CANNOT be retrieved by blocking rules alone.
    r_unlinked_a = Record(record_id="rx1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alice Walker", structured_attributes={"color": "blue"})
    r_unlinked_b = Record(record_id="rx2", source_id="s1", entity_type=EntityType.PERSON, raw_name="Zoe Taylor", structured_attributes={"color": "red"})
    gen = CandidateGenerator(rules=get_default_blocking_rules())
    pairs = gen.generate_candidates([r_unlinked_a, r_unlinked_b])
    assert pairs == []


# ---------------------------------------------------------------------------
# 4. Candidate Recall & Pair Reduction on Full Synthetic Dataset
# ---------------------------------------------------------------------------

def test_candidate_recall_and_reduction_on_synthetic_dataset():
    records = get_fictional_records()
    num_records = len(records)
    total_possible_pairs = num_records * (num_records - 1) // 2  # 21 * 20 / 2 = 210
    
    gen = CandidateGenerator(rules=get_default_blocking_rules())
    candidates = gen.generate_candidates(records)
    
    # Evaluate candidates
    metrics = evaluate_candidate_generation(
        candidate_pairs=candidates,
        ground_truth=GROUND_TRUTH,
        total_records=num_records,
    )
    
    # Every known positive pair in GROUND_TRUTH (8 pairs) must be retrieved:
    # cp_r1a_r1b, cp_r2a_r2b, cp_r3a_r3b, cp_r4a_r4b, cp_r8a_r8b, cp_r9a_r9b, cp_r9b_r9c, cp_r9a_r9c
    assert metrics.ground_truth_positives_count == 8
    assert metrics.covered_positives_count == 8
    assert metrics.candidate_recall == 1.0  # 100% recall
    
    # Verify significant pair reduction:
    assert metrics.total_possible_pairs == total_possible_pairs
    assert metrics.candidate_pairs_count < 25  # Pruned from 210 to < 25
    assert metrics.reduction_ratio > 0.85     # Over 85% pair reduction achieved!


# ---------------------------------------------------------------------------
# 5. Candidate Evaluation Guardrails and Zero Denominators
# ---------------------------------------------------------------------------

def test_evaluation_zero_denominators():
    # Empty ground truth (0 positive matches)
    m1 = CandidateEvaluationMetrics(
        candidate_pairs_count=10,
        total_possible_pairs=100,
        ground_truth_positives_count=0,
        covered_positives_count=0,
    )
    assert m1.candidate_recall == 0.0
    assert m1.reduction_ratio == 0.9
    
    # Zero possible pairs
    m2 = CandidateEvaluationMetrics(
        candidate_pairs_count=0,
        total_possible_pairs=0,
        ground_truth_positives_count=5,
        covered_positives_count=0,
    )
    assert m2.reduction_ratio == 0.0
    assert m2.candidate_recall == 0.0


def test_evaluation_unannotated_pairs_not_penalized_as_fp():
    # Candidate generation generates candidate pairs not present in partial ground truth.
    # Candidate generator does NOT classify; unannotated candidate pairs must not decrease recall.
    ground_truth = {"cp_a_b": True}
    candidates = [
        CandidatePair(candidate_id="cp_a_b", left_record_id="a", right_record_id="b", generation_method="b"),
        CandidatePair(candidate_id="cp_x_y", left_record_id="x", right_record_id="y", generation_method="b"),
    ]
    metrics = evaluate_candidate_generation(candidates, ground_truth, total_records=4)
    assert metrics.candidate_recall == 1.0
    assert metrics.ground_truth_positives_count == 1
    assert metrics.covered_positives_count == 1


# ---------------------------------------------------------------------------
# 6. Milestone 2 Acceptance Audit Regressions
# ---------------------------------------------------------------------------

def test_candidate_recall_reduced_when_positive_pair_missed():
    """
    REGRESSION TEST:
    Prove that the candidate evaluator accurately reports reduced recall (and not 1.0)
    when blocking intentionally fails to retrieve a known positive pair due to disjoint attributes.
    """
    records = get_fictional_records()
    # Add two records representing the same person but sharing NO names, NO tokens, NO soundex, NO attributes
    r_unlinked_a = Record(record_id="r_miss_a", source_id="s1", entity_type=EntityType.PERSON, raw_name="Dr. Jekyll", structured_attributes={"era": "Victorian"})
    r_unlinked_b = Record(record_id="r_miss_b", source_id="s1", entity_type=EntityType.PERSON, raw_name="Mr. Hyde", structured_attributes={"era": "Modern"})
    
    extended_records = records + [r_unlinked_a, r_unlinked_b]
    
    # Ground truth contains the 8 known positives from synthetic dataset + 1 unlinked positive pair = 9 positives
    ground_truth = dict(GROUND_TRUTH)
    ground_truth["cp_r_miss_a_r_miss_b"] = True
    
    gen = CandidateGenerator(rules=get_default_blocking_rules())
    candidates = gen.generate_candidates(extended_records)
    
    # cp_r_miss_a_r_miss_b cannot be generated by default rules
    cand_ids = {c.candidate_id for c in candidates}
    assert "cp_r_miss_a_r_miss_b" not in cand_ids
    
    metrics = evaluate_candidate_generation(candidates, ground_truth, total_records=extended_records)
    
    # 9 total ground truth positives, but only 8 covered
    assert metrics.ground_truth_positives_count == 9
    assert metrics.covered_positives_count == 8
    # candidate recall must be 8 / 9 (~0.8889), NOT 1.0!
    assert abs(metrics.candidate_recall - (8 / 9)) < 1e-5
    assert metrics.candidate_recall < 1.0


def test_pair_reduction_both_baselines_reproduced():
    """
    AUDIT TEST:
    Reproduce pair reduction against both baselines on the 21-record synthetic dataset:
    1. Full Cartesian baseline: 21 * 20 / 2 = 210 pairs
    2. Entity-type-compatible baseline: 17*16/2 (PERSON) + 3*2/2 (ORG) + 0 (LOC) = 139 pairs
    """
    records = get_fictional_records()
    gen = CandidateGenerator(rules=get_default_blocking_rules())
    candidates = gen.generate_candidates(records)
    
    # Pass records sequence to evaluate_candidate_generation
    metrics = evaluate_candidate_generation(candidates, GROUND_TRUTH, total_records=records)
    
    assert metrics.candidate_pairs_count == 11
    assert metrics.total_possible_pairs == 210
    assert metrics.total_compatible_pairs == 139
    
    # Baseline 1: Cartesian product (210)
    # (210 - 11) / 210 = 199 / 210 = 94.7619%
    assert abs(metrics.reduction_ratio - (199 / 210)) < 1e-4
    assert round(metrics.reduction_ratio, 4) == 0.9476
    
    # Baseline 2: Entity-type compatible (139)
    # (139 - 11) / 139 = 128 / 139 = 92.0863%
    assert abs(metrics.compatible_reduction_ratio - (128 / 139)) < 1e-4
    assert round(metrics.compatible_reduction_ratio, 4) == 0.9209


def test_candidate_generation_isolation_from_matching():
    """
    AUDIT TEST:
    Verify that candidate generation does not make match decisions,
    assign similarity scores, or modify entity clusters.
    """
    # Cyberdyne employees sharing organization
    r6a = Record(record_id="r6a", source_id="s6", entity_type=EntityType.PERSON, raw_name="Employee A", structured_attributes={"org": "Cyberdyne Systems"})
    r6b = Record(record_id="r6b", source_id="s6", entity_type=EntityType.PERSON, raw_name="Employee B", structured_attributes={"org": "Cyberdyne Systems"})
    
    gen = CandidateGenerator(rules=[StructuredAttributeRule("org")])
    candidates = gen.generate_candidates([r6a, r6b])
    
    assert len(candidates) == 1
    pair = candidates[0]
    
    # CandidatePair contract: only holds indexing provenance, no match decisions
    assert isinstance(pair, CandidatePair)
    assert not hasattr(pair, "decision")
    assert not hasattr(pair, "score")
    assert not hasattr(pair, "cluster_id")
    assert pair.generation_method == "blocking"
    assert "attr_org" in pair.blocking_signals["strategies"]


def test_max_block_size_prevents_explosions():
    """
    AUDIT TEST:
    Verify that max_block_size prunes oversized blocks to avoid combinatorial explosions.
    """
    # 5 records with identical name "John Doe"
    records = [
        Record(record_id=f"r_{i}", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
        for i in range(5)
    ]
    # Without cap, 5 records produce 5 * 4 / 2 = 10 pairs
    gen_uncapped = CandidateGenerator(rules=[ExactNameRule()])
    assert len(gen_uncapped.generate_candidates(records)) == 10
    
    # With max_block_size=3, blocks of size 5 are skipped
    gen_capped = CandidateGenerator(rules=[ExactNameRule()], max_block_size=3)
    assert len(gen_capped.generate_candidates(records)) == 0
