import pytest
from src.core.models import Record, EntityType, EvidencePolarity, CandidatePair
from src.core.comparison import (
    PairwiseComparator,
    jaro_similarity,
    jaro_winkler_similarity,
    token_jaccard_similarity,
    token_containment,
)


# ---------------------------------------------------------------------------
# 1. String & Token Similarity Algorithms
# ---------------------------------------------------------------------------

def test_jaro_and_jaro_winkler_similarity():
    # Exact match
    assert jaro_similarity("sarah", "sarah") == 1.0
    assert jaro_winkler_similarity("sarah", "sarah") == 1.0

    # Empty inputs
    assert jaro_similarity("", "sarah") == 0.0
    assert jaro_similarity("sarah", "") == 0.0
    assert jaro_winkler_similarity("", "") == 1.0

    # Completely disjoint
    assert jaro_similarity("abc", "xyz") == 0.0
    assert jaro_winkler_similarity("abc", "xyz") == 0.0

    # Minor typo with shared prefix: Sarah vs Sara
    jw_typo = jaro_winkler_similarity("sarah", "sara")
    assert jw_typo > 0.95

    # Prefix weighting behavior: Martha vs Marhta
    jw_transposition = jaro_winkler_similarity("martha", "marhta")
    assert jw_transposition > 0.94


def test_token_jaccard_and_containment():
    t1 = ["bruce", "wayne"]
    t2 = ["wayne"]
    assert token_jaccard_similarity(t1, t2) == 0.5
    assert token_containment(t1, t2) == 1.0

    assert token_jaccard_similarity([], []) == 1.0
    assert token_containment([], ["wayne"]) == 0.0


# ---------------------------------------------------------------------------
# 2. Pairwise Comparator Name & Acronym Evaluations
# ---------------------------------------------------------------------------

def test_comparator_exact_name_match():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    comparator = PairwiseComparator()
    result = comparator.compare(r1, r2)

    assert result.name_similarity == 1.0
    assert result.entity_type_compatible is True
    assert not result.has_fatal_contradiction

    exact_ev = [e for e in result.evidence_items if e.evidence_type == "name_exact_match"]
    assert len(exact_ev) == 1
    assert exact_ev[0].polarity == EvidencePolarity.SUPPORTING
    assert exact_ev[0].strength == 1.0


def test_comparator_name_order_permutation():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Smith, John")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Smith")
    comparator = PairwiseComparator()
    result = comparator.compare(r1, r2)

    assert result.name_similarity >= 0.90
    ev = [e for e in result.evidence_items if e.evidence_type == "name_order_match"]
    assert len(ev) == 1
    assert ev[0].polarity == EvidencePolarity.SUPPORTING


def test_comparator_acronym_match():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.ORGANIZATION, raw_name="International Business Machines")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.ORGANIZATION, raw_name="IBM")
    comparator = PairwiseComparator()
    result = comparator.compare(r1, r2)

    assert result.name_similarity >= 0.90
    ev = [e for e in result.evidence_items if e.evidence_type == "name_acronym_match"]
    assert len(ev) == 1
    assert ev[0].polarity == EvidencePolarity.SUPPORTING


def test_comparator_minor_spelling_variation():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Sarah Connor")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="Sara Connor")
    comparator = PairwiseComparator()
    result = comparator.compare(r1, r2)

    assert result.name_similarity >= 0.95
    ev = [e for e in result.evidence_items if e.evidence_type == "name_spelling_similarity"]
    assert len(ev) == 1
    assert ev[0].polarity == EvidencePolarity.SUPPORTING


def test_comparator_alias_agreement():
    # 1. Configured alias dictionary
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Marshall Mathers")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="Eminem")
    comparator = PairwiseComparator(known_aliases={"Marshall Mathers": ["Eminem"]})
    result = comparator.compare(r1, r2)

    assert result.name_similarity >= 0.95
    assert result.summary_metadata["is_alias_match"] is True
    ev = [e for e in result.evidence_items if e.evidence_type == "name_alias_match"]
    assert len(ev) == 1
    assert ev[0].polarity == EvidencePolarity.SUPPORTING

    # 2. Record payload aliases attribute
    r3 = Record(
        record_id="r3",
        source_id="s1",
        entity_type=EntityType.PERSON,
        raw_name="Bruce Wayne",
        structured_attributes={"aliases": ["Batman"]},
    )
    r4 = Record(record_id="r4", source_id="s1", entity_type=EntityType.PERSON, raw_name="Batman")
    comparator_no_dict = PairwiseComparator()
    result_payload = comparator_no_dict.compare(r3, r4)
    assert result_payload.summary_metadata["is_alias_match"] is True


# ---------------------------------------------------------------------------
# 3. Attribute Agreement, Discrepancies, and Missing Values
# ---------------------------------------------------------------------------

def test_comparator_high_value_identifier_agreement_and_conflict():
    # Agreeing DOB
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="David Bowman", structured_attributes={"dob": "1960-05-12"})
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="David Bowman", structured_attributes={"dob": "1960-05-12"})
    comparator = PairwiseComparator()
    res_agree = comparator.compare(r1, r2)
    assert not res_agree.has_fatal_contradiction
    assert res_agree.attribute_agreement_score >= 0.80

    # Conflicting DOB (1960 vs 1985)
    r3 = Record(record_id="r3", source_id="s1", entity_type=EntityType.PERSON, raw_name="David Bowman", structured_attributes={"dob": "1985-09-30"})
    res_conflict = comparator.compare(r1, r3)
    assert res_conflict.has_fatal_contradiction is True
    assert res_conflict.attribute_contradiction_score >= 0.90
    conflict_ev = [e for e in res_conflict.evidence_items if e.evidence_type == "high_value_conflict_dob"]
    assert len(conflict_ev) == 1
    assert conflict_ev[0].polarity == EvidencePolarity.CONTRADICTING


def test_comparator_missing_attribute_explicit_neutral():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alice Smith", structured_attributes={"phone": "555-1234"})
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alice Smith", structured_attributes={})
    comparator = PairwiseComparator()
    res = comparator.compare(r1, r2)

    assert not res.has_fatal_contradiction
    # Missing attribute must be NEUTRAL with strength 0.0, NOT a contradiction
    missing_ev = [e for e in res.evidence_items if e.evidence_type == "attribute_missing"]
    assert len(missing_ev) == 1
    assert missing_ev[0].polarity == EvidencePolarity.NEUTRAL
    assert missing_ev[0].strength == 0.0


def test_comparator_entity_type_incompatibility():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.ORGANIZATION, raw_name="Acme Corp")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.LOCATION, raw_name="Mount Everest")
    comparator = PairwiseComparator()
    res = comparator.compare(r1, r2)

    assert res.entity_type_compatible is False
    assert res.has_fatal_contradiction is True
    assert res.name_similarity == 0.0
    ev = [e for e in res.evidence_items if e.evidence_type == "entity_type_conflict"]
    assert len(ev) == 1
    assert ev[0].polarity == EvidencePolarity.CONTRADICTING
    assert ev[0].strength == 1.0


# ---------------------------------------------------------------------------
# 4. Evidence Model Contract Guarantees
# ---------------------------------------------------------------------------

def test_evidence_model_contract_compliance():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe", structured_attributes={"city": "Detroit"})
    r2 = Record(record_id="r2", source_id="s2", entity_type=EntityType.PERSON, raw_name="John Doe", structured_attributes={"city": "Detroit"})
    comparator = PairwiseComparator()
    res = comparator.compare(r1, r2)

    for ev in res.evidence_items:
        # Check field constraints
        assert ev.evidence_id.strip() != ""
        assert ev.evidence_type.strip() != ""
        assert ev.value_description.strip() != ""
        assert ev.provenance.strip() != ""
        assert ev.polarity in (EvidencePolarity.SUPPORTING, EvidencePolarity.CONTRADICTING, EvidencePolarity.NEUTRAL)
        assert 0.0 <= ev.strength <= 1.0
        assert ev.record_reference == "r1::r2"
        assert ev.source_reference == "s1::s2"


# ---------------------------------------------------------------------------
# 5. Adversarial & Data Integrity Audit Tests
# ---------------------------------------------------------------------------

def test_comparator_mismatched_candidate_pair_ids_rejected():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    # CandidatePair with foreign record IDs "x" and "y"
    foreign_cp = CandidatePair(candidate_id="cp_x_y", left_record_id="x", right_record_id="y", generation_method="test")
    comparator = PairwiseComparator()
    with pytest.raises(ValueError) as exc:
        comparator.compare(r1, r2, candidate_pair=foreign_cp)
    assert "do not match supplied Record IDs" in str(exc.value)


def test_comparator_blocking_signals_emitted_as_neutral_context():
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe")
    cp = CandidatePair(
        candidate_id="cp_r1_r2",
        left_record_id="r1",
        right_record_id="r2",
        generation_method="test",
        blocking_signals={"strategies": ["soundex"], "matched_keys": ["soundex:J500"]},
    )
    comparator = PairwiseComparator()
    res = comparator.compare(r1, r2, candidate_pair=cp)

    blocking_ev = [e for e in res.evidence_items if e.evidence_type == "blocking_context"]
    assert len(blocking_ev) == 1
    # Must be NEUTRAL with 0.0 strength so indexing heuristic cannot mislead identity proof
    assert blocking_ev[0].polarity == EvidencePolarity.NEUTRAL
    assert blocking_ev[0].strength == 0.0


def test_comparator_contact_attribute_phone_conflict_not_fatal():
    # Two records with same name and matching DOB, but different phone numbers (e.g. mobile vs work)
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alice Smith", structured_attributes={"dob": "1990-01-01", "phone": "555-1111"})
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.PERSON, raw_name="Alice Smith", structured_attributes={"dob": "1990-01-01", "phone": "555-9999"})
    comparator = PairwiseComparator()
    res = comparator.compare(r1, r2)

    # Phone difference is NOT fatal (people have multiple phone numbers)
    assert res.has_fatal_contradiction is False
    assert res.attribute_agreement_score >= 0.90  # DOB agreed
    divergence_ev = [e for e in res.evidence_items if e.evidence_type == "contact_divergence_phone"]
    assert len(divergence_ev) == 1
    assert divergence_ev[0].polarity == EvidencePolarity.CONTRADICTING
    assert divergence_ev[0].strength == 0.35


def test_comparator_address_normalization_and_building_veto():
    # 1. Matching address despite street abbreviation variation (blv. vs boulevard)
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.ORGANIZATION, raw_name="Test Venue", structured_attributes={"address": "100 Sunset Blv."})
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.ORGANIZATION, raw_name="Test Venue", structured_attributes={"address": "100 Sunset Boulevard"})
    prod_comparator = PairwiseComparator.create_production_comparator()
    res_agree = prod_comparator.compare(r1, r2)

    assert res_agree.attribute_agreement_score >= 0.50
    agree_ev = [e for e in res_agree.evidence_items if e.evidence_type == "context_agreement_address"]
    assert len(agree_ev) == 1
    assert agree_ev[0].polarity == EvidencePolarity.SUPPORTING

    # 2. Conflicting building numbers on the same street (100 vs 500 Sunset Blvd) -> building veto
    r3 = Record(record_id="r3", source_id="s1", entity_type=EntityType.ORGANIZATION, raw_name="Test Venue", structured_attributes={"address": "500 Sunset Boulevard"})
    res_conflict = prod_comparator.compare(r1, r3)

    assert res_conflict.attribute_contradiction_score >= 0.55
    conflict_ev = [e for e in res_conflict.evidence_items if e.evidence_type == "address_building_conflict_address"]
    assert len(conflict_ev) == 1
    assert conflict_ev[0].polarity == EvidencePolarity.CONTRADICTING
    assert conflict_ev[0].strength >= 0.55


def test_comparator_metro_cluster_city_agreement():
    # Los Angeles and Beverly Hills belong to the same metropolitan cluster
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.ORGANIZATION, raw_name="Test Entity", structured_attributes={"city": "Los Angeles"})
    r2 = Record(record_id="r2", source_id="s1", entity_type=EntityType.ORGANIZATION, raw_name="Test Entity", structured_attributes={"city": "Beverly Hills"})
    prod_comparator = PairwiseComparator.create_production_comparator()
    res = prod_comparator.compare(r1, r2)

    assert res.attribute_agreement_score >= 0.15
    metro_ev = [e for e in res.evidence_items if e.evidence_type == "context_agreement_city_metro"]
    assert len(metro_ev) == 1
    assert metro_ev[0].polarity == EvidencePolarity.SUPPORTING


def test_comparator_subvenue_conflict_detection():
    # Distinct sub-venues (Cafe vs Dining Room) sharing the same hotel property and address
    r_cafe = Record(
        record_id="rest_cafe",
        source_id="s1",
        entity_type=EntityType.ORGANIZATION,
        raw_name="Ritz-Carlton Cafe (Buckhead)",
        structured_attributes={"address": "3434 Peachtree Rd. NE", "city": "Atlanta"},
    )
    r_dining = Record(
        record_id="rest_dining",
        source_id="s2",
        entity_type=EntityType.ORGANIZATION,
        raw_name="Ritz-Carlton Dining Room (Buckhead)",
        structured_attributes={"address": "3434 Peachtree Rd. NE", "city": "Atlanta"},
    )
    prod_comparator = PairwiseComparator.create_production_comparator()
    res = prod_comparator.compare(r_cafe, r_dining)

    assert res.summary_metadata["has_venue_discriminator_conflict"] is True
    assert res.attribute_contradiction_score >= 0.70
    venue_ev = [e for e in res.evidence_items if e.evidence_type == "venue_discriminator_conflict"]
    assert len(venue_ev) == 1
    assert venue_ev[0].polarity == EvidencePolarity.CONTRADICTING

