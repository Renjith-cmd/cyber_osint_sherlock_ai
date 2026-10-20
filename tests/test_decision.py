import pytest
from src.core.models import Record, EntityType, CandidatePair, DecisionType
from src.core.blocking import CandidateGenerator, get_default_blocking_rules
from src.core.comparison import PairwiseComparator
from src.core.decision import DecisionPolicy, MatchDecisionEngine
from src.core.evaluation import (
    evaluate_candidate_generation,
    evaluate_match_decisions,
    evaluate_end_to_end_pipeline,
    UnknownPredictionPolicy,
)
from tests.synthetic_dataset import get_fictional_records, get_candidate_pairs, GROUND_TRUTH


# ---------------------------------------------------------------------------
# 1. Match Decision Scenarios
# ---------------------------------------------------------------------------

def test_decision_exact_duplicate_match():
    r1 = Record(record_id="r1a", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe", structured_attributes={"dob": "1980-01-01"})
    r2 = Record(record_id="r1b", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe", structured_attributes={"dob": "1980-01-01"})
    engine = MatchDecisionEngine()
    dec, comp = engine.compare_and_decide(r1, r2)

    assert dec.decision == DecisionType.MATCH
    assert dec.score >= 0.85
    assert len(dec.evidence_references) == len(comp.evidence_items)
    assert "john doe" in str(dec.explanation_metadata)


def test_decision_minor_spelling_variation_match():
    r1 = Record(record_id="r3a", source_id="s3", entity_type=EntityType.PERSON, raw_name="Sarah Connor", structured_attributes={"city": "Los Angeles"})
    r2 = Record(record_id="r3b", source_id="s3", entity_type=EntityType.PERSON, raw_name="Sara Connor", structured_attributes={"city": "Los Angeles"})
    engine = MatchDecisionEngine()
    dec, _ = engine.compare_and_decide(r1, r2)

    assert dec.decision == DecisionType.MATCH
    assert dec.score >= 0.75


def test_decision_acronym_match():
    r1 = Record(record_id="r2a", source_id="s2", entity_type=EntityType.ORGANIZATION, raw_name="International Business Machines", structured_attributes={"country": "USA"})
    r2 = Record(record_id="r2b", source_id="s2", entity_type=EntityType.ORGANIZATION, raw_name="IBM", structured_attributes={"country": "USA"})
    engine = MatchDecisionEngine()
    dec, _ = engine.compare_and_decide(r1, r2)

    assert dec.decision == DecisionType.MATCH
    assert dec.score >= 0.75


def test_decision_missing_attributes_does_not_block_match():
    r1 = Record(record_id="r4a", source_id="s4", entity_type=EntityType.PERSON, raw_name="Alice Smith", structured_attributes={"phone": "555-1234"})
    r2 = Record(record_id="r4b", source_id="s4", entity_type=EntityType.PERSON, raw_name="Alice Smith", structured_attributes={})
    engine = MatchDecisionEngine()
    dec, _ = engine.compare_and_decide(r1, r2)

    assert dec.decision == DecisionType.MATCH
    assert dec.score >= 0.75


def test_decision_conflicting_dob_fatal_non_match():
    # David Bowman with conflicting dates of birth (1960 vs 1985)
    r1 = Record(record_id="r7a", source_id="s7", entity_type=EntityType.PERSON, raw_name="David Bowman", structured_attributes={"dob": "1960-05-12"})
    r2 = Record(record_id="r7b", source_id="s7", entity_type=EntityType.PERSON, raw_name="David Bowman", structured_attributes={"dob": "1985-09-30"})
    engine = MatchDecisionEngine()
    dec, comp = engine.compare_and_decide(r1, r2)

    assert dec.decision == DecisionType.NON_MATCH
    assert dec.score <= 0.15
    assert comp.has_fatal_contradiction is True
    assert "Conflicting high-value identifier" in dec.explanation_metadata["primary_reason"]


def test_decision_same_org_different_people_non_match():
    r1 = Record(record_id="r6a", source_id="s6", entity_type=EntityType.PERSON, raw_name="Employee A", structured_attributes={"org": "Cyberdyne Systems"})
    r2 = Record(record_id="r6b", source_id="s6", entity_type=EntityType.PERSON, raw_name="Employee B", structured_attributes={"org": "Cyberdyne Systems"})
    engine = MatchDecisionEngine()
    dec, _ = engine.compare_and_decide(r1, r2)

    assert dec.decision == DecisionType.NON_MATCH
    assert dec.score <= engine.policy.non_match_threshold


def test_decision_common_name_collision_different_occupation():
    r1 = Record(record_id="r5a", source_id="s5", entity_type=EntityType.PERSON, raw_name="Michael Jordan", structured_attributes={"occupation": "Basketball Player"})
    r2 = Record(record_id="r5b", source_id="s5", entity_type=EntityType.PERSON, raw_name="Michael Jordan", structured_attributes={"occupation": "AI Researcher"})
    engine = MatchDecisionEngine()
    dec, _ = engine.compare_and_decide(r1, r2)

    # Must NOT be a MATCH due to occupation divergence
    assert dec.decision in (DecisionType.NON_MATCH, DecisionType.REVIEW)
    assert dec.decision != DecisionType.MATCH


def test_decision_disparate_names_shared_city_routed_to_review():
    # Marshall Mathers vs Eminem (without alias dictionary configured)
    r1 = Record(record_id="r8a", source_id="s8", entity_type=EntityType.PERSON, raw_name="Marshall Mathers", structured_attributes={"city": "Detroit"})
    r2 = Record(record_id="r8b", source_id="s8", entity_type=EntityType.PERSON, raw_name="Eminem", structured_attributes={"city": "Detroit"})
    engine = MatchDecisionEngine()
    dec, _ = engine.compare_and_decide(r1, r2)

    # Disparate names with only shared city must be routed to REVIEW, never automatic MATCH
    assert dec.decision == DecisionType.REVIEW
    assert "insufficient proof of identity" in dec.explanation_metadata["primary_reason"]


def test_decision_alias_with_known_alias_mapping():
    r1 = Record(record_id="r8a", source_id="s8", entity_type=EntityType.PERSON, raw_name="Marshall Mathers", structured_attributes={"city": "Detroit"})
    r2 = Record(record_id="r8b", source_id="s8", entity_type=EntityType.PERSON, raw_name="Eminem", structured_attributes={"city": "Detroit"})
    comparator = PairwiseComparator(known_aliases={"Marshall Mathers": ["Eminem"]})
    engine = MatchDecisionEngine(comparator=comparator)
    dec, _ = engine.compare_and_decide(r1, r2)

    assert dec.decision == DecisionType.MATCH
    assert dec.score >= 0.75


def test_decision_different_entity_types_non_match():
    r1 = Record(record_id="r10a", source_id="s10", entity_type=EntityType.ORGANIZATION, raw_name="Acme Corp")
    r2 = Record(record_id="r10b", source_id="s10", entity_type=EntityType.LOCATION, raw_name="Mount Everest")
    engine = MatchDecisionEngine()
    dec, _ = engine.compare_and_decide(r1, r2)

    assert dec.decision == DecisionType.NON_MATCH
    assert dec.score == 0.0


# ---------------------------------------------------------------------------
# 2. Threshold Configuration and Evidence Traceability
# ---------------------------------------------------------------------------

def test_decision_custom_thresholds_configuration():
    # Strict policy
    strict_policy = DecisionPolicy(
        match_threshold=0.90,
        non_match_threshold=0.50,
    )
    engine = MatchDecisionEngine(policy=strict_policy)
    
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Robert Smith", structured_attributes={"city": "Chicago"})
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="Bob Smith", structured_attributes={"city": "Chicago"})
    dec, _ = engine.compare_and_decide(r1, r2)

    # Under strict policy with score between 0.50 and 0.90, decision is REVIEW
    assert dec.threshold == 0.90
    assert dec.decision == DecisionType.REVIEW


def test_decision_policy_invalid_thresholds_rejected():
    with pytest.raises(ValueError):
        DecisionPolicy(match_threshold=0.30, non_match_threshold=0.60)


def test_batch_decide_missing_record_raises_key_error():
    records = {"r1": Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alice")}
    pair = CandidatePair(candidate_id="cp_r1_r2", left_record_id="r1", right_record_id="r2", generation_method="b")
    engine = MatchDecisionEngine()
    with pytest.raises(KeyError):
        engine.decide_candidates(records, [pair])


# ---------------------------------------------------------------------------
# 3. Full Benchmark and End-to-End Evaluation
# ---------------------------------------------------------------------------

def test_full_pipeline_evaluation_on_synthetic_dataset():
    records = {r.record_id: r for r in get_fictional_records()}
    candidate_pairs = get_candidate_pairs()
    
    # 1. Candidate evaluation metrics
    cand_metrics = evaluate_candidate_generation(candidate_pairs, GROUND_TRUTH, total_records=len(records))
    assert cand_metrics.candidate_recall == 1.0
    
    # 2. Match Decision Engine with known alias
    comparator = PairwiseComparator(known_aliases={"Marshall Mathers": ["Eminem"]})
    engine = MatchDecisionEngine(comparator=comparator)
    decisions = engine.decide_candidates(records, candidate_pairs)
    
    assert len(decisions) == len(candidate_pairs)
    
    # 3. Match Decision Evaluation (review_is_match=False)
    match_metrics = evaluate_match_decisions(decisions, GROUND_TRUTH, review_is_match=False)
    
    # Check that true positives are correctly identified
    assert match_metrics.true_positives >= 7
    assert match_metrics.precision >= 0.85
    assert match_metrics.total_evaluated == len(candidate_pairs)
    
    # 4. End-to-end pipeline evaluation
    e2e_metrics = evaluate_end_to_end_pipeline(cand_metrics, decisions, GROUND_TRUTH)
    assert e2e_metrics.candidate_recall == 1.0
    assert e2e_metrics.end_to_end_recall >= 0.85
    assert e2e_metrics.precision >= 0.85


def test_adversarial_same_name_different_city_and_occupation():
    # Two different people named "John Smith" in different cities with different occupations
    r1 = Record(record_id="js1", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Smith", structured_attributes={"city": "Dallas", "occupation": "Doctor"})
    r2 = Record(record_id="js2", source_id="s2", entity_type=EntityType.PERSON, raw_name="John Smith", structured_attributes={"city": "Seattle", "occupation": "Plumber"})
    engine = MatchDecisionEngine()
    dec, comp = engine.compare_and_decide(r1, r2)

    # Must NOT be automatically matched despite identical names
    assert dec.decision != DecisionType.MATCH
    assert comp.attribute_contradiction_score > 0.0


# ---------------------------------------------------------------------------
# 4. Adversarial & Policy Audit Scenarios
# ---------------------------------------------------------------------------

def test_decision_conflicting_dob_with_uncertain_source_policy_routed_to_review():
    # When source data quality is uncertain, route_conflicting_identifiers_to_review
    # routes the pair to REVIEW rather than forcing blind NON_MATCH.
    r1 = Record(record_id="r7a", source_id="s7", entity_type=EntityType.PERSON, raw_name="David Bowman", structured_attributes={"dob": "1960-05-12"})
    r2 = Record(record_id="r7b", source_id="s7", entity_type=EntityType.PERSON, raw_name="David Bowman", structured_attributes={"dob": "1985-09-30"})
    policy = DecisionPolicy(route_conflicting_identifiers_to_review=True)
    engine = MatchDecisionEngine(policy=policy)
    dec, comp = engine.compare_and_decide(r1, r2)

    assert dec.decision == DecisionType.REVIEW
    assert "uncertainty policy" in dec.explanation_metadata["primary_reason"]
    assert dec.score <= 0.40


def test_decision_contact_attribute_difference_allows_match():
    # Two records with same name and matching DOB/SSN, but differing phone numbers
    r1 = Record(record_id="u1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alice Smith", structured_attributes={"dob": "1990-01-01", "phone": "555-1111"})
    r2 = Record(record_id="u2", source_id="s2", entity_type=EntityType.PERSON, raw_name="Alice Smith", structured_attributes={"dob": "1990-01-01", "phone": "555-2222"})
    engine = MatchDecisionEngine()
    dec, comp = engine.compare_and_decide(r1, r2)

    # Phone difference does NOT override identity confirmed by name and DOB
    assert dec.decision == DecisionType.MATCH
    assert dec.score >= 0.75
    assert comp.has_fatal_contradiction is False


def test_decision_common_name_without_corroboration_routed_to_review():
    # Two records named "John Smith" with only shared city and NO corroborating identifiers
    r1 = Record(record_id="js1", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Smith", structured_attributes={"city": "Chicago"})
    r2 = Record(record_id="js2", source_id="s2", entity_type=EntityType.PERSON, raw_name="John Smith", structured_attributes={"city": "Chicago"})
    
    # Strict corroboration policy prevents automated false-positive match on uncorroborated common names
    policy = DecisionPolicy(require_corroboration_for_match=True)
    engine = MatchDecisionEngine(policy=policy)
    dec, _ = engine.compare_and_decide(r1, r2)

    assert dec.decision == DecisionType.REVIEW
    assert "lacking corroborating attribute evidence" in dec.explanation_metadata["primary_reason"]


def test_evaluate_match_decisions_subset_preserves_accuracy_bounds():
    # Ground truth contains 20 pairs, but matcher only evaluated a candidate subset of 3 pairs
    ground_truth = {f"cp_{i}": (i < 5) for i in range(20)}
    decisions = {
        "cp_0": DecisionType.MATCH,      # True Positive
        "cp_1": DecisionType.NON_MATCH,  # False Negative
        "cp_10": DecisionType.NON_MATCH, # True Negative
    }
    metrics = evaluate_match_decisions(decisions, ground_truth)

    assert metrics.total_evaluated == 3
    assert metrics.true_positives == 1
    assert metrics.false_negatives == 1
    assert metrics.true_negatives == 1
    assert metrics.false_positives == 0
    # Accuracy must equal (TP + TN) / total_evaluated = 2/3 <= 1.0
    assert abs(metrics.accuracy - 2/3) < 1e-5


# ---------------------------------------------------------------------------
# 5. Milestone 7: Policy Comparison & Production Decision Audits
# ---------------------------------------------------------------------------

def test_decision_policies_factory_and_configuration():
    """Verifies that all three documented decision policies have explicit, distinct parameters."""
    p_base = DecisionPolicy.get_baseline_policy()
    p_cal = DecisionPolicy.get_calibrated_evidence_policy()
    p_high = DecisionPolicy.get_autonomous_high_precision_policy()

    assert p_base.model_version == "sherlock_match_decision_engine_v1"
    assert p_base.match_threshold == 0.75
    assert p_base.route_venue_conflicts_to_review is False

    assert p_cal.model_version == "sherlock_match_decision_engine_v2_calibrated"
    assert p_cal.match_threshold == 0.72
    assert p_cal.route_venue_conflicts_to_review is True
    assert p_cal.attribute_weight == 0.40

    assert p_high.model_version == "sherlock_match_decision_engine_v2_high_precision"
    assert p_high.match_threshold == 0.82
    assert p_high.non_match_threshold == 0.30
    assert p_high.route_venue_conflicts_to_review is True


def test_production_engine_hotel_distinct_venues_routed_to_review():
    """
    Verifies that distinct sub-venues at the same address (e.g. Ritz-Carlton Cafe vs Dining Room)
    are routed to REVIEW by the production engine, preventing false-positive identity merge.
    """
    r_cafe = Record(
        record_id="rest_0179",
        source_id="zagat",
        entity_type=EntityType.ORGANIZATION,
        raw_name="ritz-carlton cafe (buckhead)",
        structured_attributes={"address": "3434 peachtree rd. ne", "city": "atlanta", "cuisine": "american (new)"},
    )
    r_dining = Record(
        record_id="rest_0181",
        source_id="fodors",
        entity_type=EntityType.ORGANIZATION,
        raw_name="ritz-carlton dining room (buckhead)",
        structured_attributes={"address": "3434 peachtree rd. ne", "city": "atlanta", "cuisine": "american (new)"},
    )

    prod_engine = MatchDecisionEngine.create_production_engine()
    dec, comp = prod_engine.compare_and_decide(r_cafe, r_dining)

    # Must NOT be a MATCH: routed to REVIEW due to venue discriminator conflict
    assert dec.decision == DecisionType.REVIEW
    assert comp.has_venue_discriminator_conflict is True
    assert "Distinct sub-venues" in dec.explanation_metadata["primary_reason"]
    assert any("venue_discriminator_conflict" in ev for ev in dec.evidence_references)


def test_decision_word_order_business_name_match():
    """
    Verifies that business name variations with word order inverted (e.g. 'Hotel Bel-Air' vs 'Bel-Air Hotel')
    are correctly matched with production engine.
    """
    r1 = Record(
        record_id="h1",
        source_id="zagat",
        entity_type=EntityType.ORGANIZATION,
        raw_name="hotel bel-air",
        structured_attributes={"address": "701 stone canyon rd.", "city": "los angeles"},
    )
    r2 = Record(
        record_id="h2",
        source_id="fodors",
        entity_type=EntityType.ORGANIZATION,
        raw_name="bel-air hotel",
        structured_attributes={"address": "701 stone canyon rd.", "city": "los angeles"},
    )

    prod_engine = MatchDecisionEngine.create_production_engine()
    dec, comp = prod_engine.compare_and_decide(r1, r2)

    assert dec.decision == DecisionType.MATCH
    assert any(
        "name_order_match" in ev or "name_token_jaccard" in ev or "name_strong_similarity" in ev
        for ev in dec.evidence_references
    )


def test_heuristic_score_semantics_metadata_and_provenance():
    """Verifies that decision explanations explicitly document heuristic score semantics."""
    r1 = Record(record_id="a1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Jane Doe", structured_attributes={"city": "Chicago"})
    r2 = Record(record_id="a2", source_id="s2", entity_type=EntityType.PERSON, raw_name="Jane Doe", structured_attributes={"city": "Chicago"})
    engine = MatchDecisionEngine.create_production_engine()
    dec, _ = engine.compare_and_decide(r1, r2)

    assert "score_semantics" in dec.explanation_metadata
    assert "Heuristic confidence score" in dec.explanation_metadata["score_semantics"]
    assert "not statistically calibrated probabilities" in dec.explanation_metadata["score_semantics"]
    assert dec.explanation_metadata["policy_model_version"] == "sherlock_match_decision_engine_v2_calibrated"


def test_building_number_conflict_prevents_false_match():
    """Verifies that a conflicting building number on the same street prevents false match."""
    r1 = Record(
        record_id="p1",
        source_id="s1",
        entity_type=EntityType.ORGANIZATION,
        raw_name="Original Joe's Pizza",
        structured_attributes={"address": "123 main street", "city": "new york"},
    )
    r2 = Record(
        record_id="p2",
        source_id="s2",
        entity_type=EntityType.ORGANIZATION,
        raw_name="Original Joe's Pizza",
        structured_attributes={"address": "456 main street", "city": "new york"},
    )

    prod_engine = MatchDecisionEngine.create_production_engine()
    dec, comp = prod_engine.compare_and_decide(r1, r2)

    assert dec.decision in (DecisionType.NON_MATCH, DecisionType.REVIEW)
    assert dec.decision != DecisionType.MATCH
    assert any("address_building_conflict" in ev for ev in dec.evidence_references)

