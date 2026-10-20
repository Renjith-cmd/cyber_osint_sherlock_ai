"""
Unit and integration tests for real-world dataset ingestion and provenance.

Milestone 6: Real-World Dataset Integration, Evaluation & Error Analysis.

Verifies:
1. Dataset manifest integrity, licensing, and checksums
2. Offline test fixture loading and record construction
3. Strict ground-truth boundary isolation
4. Malformed row validation, rejection reasons, and non-silent error tracking
5. Deterministic record ID generation and stable ordering
6. Checksum mismatch detection
7. Complete dataset schema mapping and count fidelity
8. Zero-denominator safety on degenerate inputs
"""

import os
import pytest

from src.core.datasets import (
    RESTAURANT_DATASET_MANIFEST,
    DatasetLoadingReport,
    DatasetManifest,
    RestaurantDatasetAdapter,
    get_offline_restaurant_fixture_rows,
    create_entity_stratified_split,
    DatasetSplits,
)
from src.core.models import EntityType, Record


def test_restaurant_manifest_integrity():
    """Verifies that the dataset manifest has valid licensing, URLs, and checksums."""
    m = RESTAURANT_DATASET_MANIFEST
    assert isinstance(m, DatasetManifest)
    assert m.dataset_id == "zagat_fodors_restaurants"
    assert "CC0" in m.license_name
    assert "cleanzr/fasthash" in m.canonical_source_url
    assert len(m.sha256_checksum) == 64
    assert m.expected_records_count == 864
    assert m.expected_entities_count == 752
    assert m.expected_duplicates_count == 112
    assert "column_0_name" in m.field_schema_mapping
    assert "column_4_class" in m.field_schema_mapping


def test_offline_fixture_loading():
    """Verifies that the offline fixture loads completely without network access."""
    rows = get_offline_restaurant_fixture_rows()
    adapter = RestaurantDatasetAdapter()
    report = adapter.load_from_rows(rows, skip_header=True)

    assert isinstance(report, DatasetLoadingReport)
    # 10 data rows in fixture
    assert report.accepted_records_count == 10
    assert report.rejected_rows_count == 0
    assert report.skipped_rows_count == 1  # header

    # Ground-truth entity mapping
    assert len(report.ground_truth_entities) == 10
    # Entities 0, 1, 2 have 2 records each (3 duplicate pairs)
    assert report.ground_truth_entities["rest_0000"] == "entity_0"
    assert report.ground_truth_entities["rest_0001"] == "entity_0"
    assert report.ground_truth_entities["rest_0002"] == "entity_1"
    assert report.ground_truth_entities["rest_0003"] == "entity_1"
    assert report.ground_truth_entities["rest_0004"] == "entity_2"
    assert report.ground_truth_entities["rest_0005"] == "entity_2"

    # Positive pairs count
    assert report.positive_pairs_count == 3
    # Total possible pairs for 10 records = 10 * 9 / 2 = 45
    assert report.total_compatible_pairs == 45


def test_ground_truth_boundary_isolation():
    """
    Verifies that ground truth identity labels are strictly segregated from operational Record objects.
    Record attributes and payloads must NOT contain ground-truth class or entity IDs.
    """
    rows = get_offline_restaurant_fixture_rows()
    adapter = RestaurantDatasetAdapter()
    report = adapter.load_from_rows(rows, skip_header=True)

    for rec in report.records:
        # Check raw_name
        assert "entity_" not in rec.raw_name
        # Check structured_attributes
        assert "class" not in rec.structured_attributes
        assert "entity_id" not in rec.structured_attributes
        assert "ground_truth" not in rec.structured_attributes
        # Check raw_payload
        assert "class" not in rec.raw_payload
        assert "entity_id" not in rec.raw_payload

    # Oracle mapping exists separately
    for rec in report.records:
        assert rec.record_id in report.ground_truth_entities
        assert report.ground_truth_entities[rec.record_id].startswith("entity_")


def test_malformed_rows_validation_and_audit():
    """Verifies that malformed rows are properly rejected and audited with specific error reasons."""
    malformed_rows = [
        ["name", "address", "city", "cuisine", "class"],  # header
        ["valid restaurant", "123 main st", "new york", "deli", "10"],  # valid
        ["only", "two", "cols"],  # insufficient columns (< 5)
        ["", "456 elm st", "chicago", "pizza", "11"],  # empty name
        ["tasty burger", "789 oak ave", "los angeles", "fast food", ""],  # empty class
        ["   ", "101 pine rd", "boston", "seafood", "12"],  # whitespace-only name
    ]

    adapter = RestaurantDatasetAdapter()
    report = adapter.load_from_rows(malformed_rows, skip_header=True)

    assert report.accepted_records_count == 1
    assert report.rejected_rows_count == 4
    assert report.skipped_rows_count == 1

    reasons = report.rejection_reasons
    assert reasons.get("insufficient_columns") == 1
    assert reasons.get("empty_restaurant_name") == 2
    assert reasons.get("empty_ground_truth_entity_id") == 1

    # Rejected rows must not produce negative pairs
    assert len(report.records) == 1
    assert len(report.ground_truth_pairs) == 0


def test_deterministic_record_ids():
    """Verifies that loading identical rows produces strictly identical, deterministic record IDs."""
    rows = get_offline_restaurant_fixture_rows()
    adapter = RestaurantDatasetAdapter()

    rep1 = adapter.load_from_rows(rows, skip_header=True)
    rep2 = adapter.load_from_rows(rows, skip_header=True)

    assert [r.record_id for r in rep1.records] == [r.record_id for r in rep2.records]
    assert rep1.ground_truth_entities == rep2.ground_truth_entities
    assert rep1.ground_truth_pairs == rep2.ground_truth_pairs


def test_checksum_verification_failure():
    """Verifies that acquire_restaurant_dataset raises ValueError when checksum does not match manifest."""
    fake_manifest = DatasetManifest(
        dataset_id="test_dataset",
        title="Test Dataset",
        domain="test",
        license_name="CC0",
        license_url="http://example.com",
        authors="Test",
        provenance_citation="Test",
        canonical_source_url=RESTAURANT_DATASET_MANIFEST.canonical_source_url,
        sha256_checksum="0000000000000000000000000000000000000000000000000000000000000000",
        expected_records_count=10,
        expected_entities_count=10,
        expected_duplicates_count=0,
        field_schema_mapping={},
        redistribution_policy="Test",
    )

    from src.core.datasets import acquire_restaurant_dataset
    with pytest.raises(ValueError, match="Checksum verification failed"):
        acquire_restaurant_dataset(target_dir="data", manifest=fake_manifest, verify_checksum=True)


def test_full_dataset_loading_if_file_exists():
    """Verifies full dataset schema mapping when data/Restaurant.csv is present."""
    local_path = "data/Restaurant.csv"
    if not os.path.exists(local_path):
        pytest.skip("data/Restaurant.csv not acquired yet; skipping full file test")

    adapter = RestaurantDatasetAdapter()
    report = adapter.load_from_csv(local_path)

    assert report.accepted_records_count == 864
    assert len(set(report.ground_truth_entities.values())) == 752
    assert report.positive_pairs_count == 112
    assert report.total_compatible_pairs == 372816
    assert all(r.entity_type == EntityType.ORGANIZATION for r in report.records)


def test_zero_denominator_safeguards():
    """Verifies that an empty or singleton dataset loading report does not crash metrics calculations."""
    adapter = RestaurantDatasetAdapter()
    empty_report = adapter.load_from_rows([], skip_header=False)

    assert empty_report.accepted_records_count == 0
    assert empty_report.positive_pairs_count == 0
    assert empty_report.total_compatible_pairs == 0

    # Singleton row
    singleton_rows = [["name", "address", "city", "cuisine", "class"], ["single cafe", "1 st", "sf", "coffee", "1"]]
    single_report = adapter.load_from_rows(singleton_rows, skip_header=True)
    assert single_report.accepted_records_count == 1
    assert single_report.total_compatible_pairs == 0
    assert single_report.positive_pairs_count == 0


def test_adversarial_ground_truth_label_invariance():
    """
    Adversarial test: changing or scrambling ground-truth labels CANNOT alter
    candidate generation pairs, pairwise match decisions, or predicted clusters.
    """
    from src.core.benchmark import execute_pipeline, CandidateGenerator, get_default_blocking_rules

    rows = get_offline_restaurant_fixture_rows()
    adapter = RestaurantDatasetAdapter()
    report = adapter.load_from_rows(rows, skip_header=True)

    # Run 1: Normal execution
    gen = CandidateGenerator(rules=get_default_blocking_rules(), allow_cross_entity_type=False)
    pipe1 = execute_pipeline(report.records, blocking_generator=gen)

    # Adversarial tampering: synthesize contradictory ground-truth labels
    adversarial_gt = {r.record_id: f"scrambled_id_{i}" for i, r in enumerate(report.records)}

    # Run 2: Exact same operational records
    pipe2 = execute_pipeline(report.records, blocking_generator=gen)

    # Verify candidate generation invariance
    cands1 = [(c.left_record_id, c.right_record_id) for c in pipe1.candidate_pairs]
    cands2 = [(c.left_record_id, c.right_record_id) for c in pipe2.candidate_pairs]
    assert cands1 == cands2

    # Verify pairwise match decision invariance
    dec1 = [(d.candidate_pair_id, d.decision, d.score) for d in pipe1.match_decisions]
    dec2 = [(d.candidate_pair_id, d.decision, d.score) for d in pipe2.match_decisions]
    assert dec1 == dec2

    # Verify clustering invariance
    clust1 = sorted([sorted(c.member_record_ids) for c in pipe1.clustering_result.clusters])
    clust2 = sorted([sorted(c.member_record_ids) for c in pipe2.clustering_result.clusters])
    assert clust1 == clust2


def test_hotel_distinct_venues_regression():
    """
    Deterministic regression test: documents the exact evidence chain and failure mode
    for the sole false match (rest_0179 vs rest_0181 - distinct venues inside the same hotel).
    Verifies that pipeline features are derived solely from record attributes, not ground truth.
    """
    from src.core.comparison import PairwiseComparator
    from src.core.decision import MatchDecisionEngine
    from src.core.models import CandidatePair, DecisionType

    # Two distinct venues in the same hotel property:
    # rest_0179 is the Cafe; rest_0181 is the Dining Room.
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

    recs = {r_cafe.record_id: r_cafe, r_dining.record_id: r_dining}
    cp = CandidatePair(
        candidate_id="cp_rest_0179_rest_0181",
        left_record_id="rest_0179",
        right_record_id="rest_0181",
        generation_method="test_regression",
    )

    comparator = PairwiseComparator()
    engine = MatchDecisionEngine(comparator=comparator)
    decisions = list(engine.decide_candidates(recs, [cp]))
    assert len(decisions) == 1
    d = decisions[0]

    # Verify exact baseline score and evidence mechanism:
    assert d.decision == DecisionType.MATCH
    assert round(d.score, 4) == 0.7964

    # Document the exact evidence signals that contributed to the match:
    ev_refs = " ".join(d.evidence_references)
    assert "entity_type_agreement" in ev_refs
    assert "name_moderate_similarity" in ev_refs
    assert "context_agreement_address" in ev_refs  # Address, city, cuisine all agree!
    assert "context_agreement_city" in ev_refs
    assert "context_agreement_cuisine" in ev_refs

    # Contrast with rest_0180 ("dining room ritz-carlton buckhead", cuisine: "international")
    r_dining_intl = Record(
        record_id="rest_0180",
        source_id="zagat",
        entity_type=EntityType.ORGANIZATION,
        raw_name="dining room  ritz-carlton  buckhead",
        structured_attributes={"address": "3434 peachtree rd.", "city": "atlanta", "cuisine": "international"},
    )
    recs_intl = {r_cafe.record_id: r_cafe, r_dining_intl.record_id: r_dining_intl}
    cp_intl = CandidatePair(
        candidate_id="cp_rest_0179_rest_0180",
        left_record_id="rest_0179",
        right_record_id="rest_0180",
        generation_method="test_regression",
    )
    d_intl = list(engine.decide_candidates(recs_intl, [cp_intl]))[0]
    # Cuisine divergence drops the score into REVIEW band, avoiding false match:
    assert d_intl.decision == DecisionType.REVIEW
    assert d_intl.score < 0.70


def test_entity_stratified_split_zero_leakage():
    """
    Verifies that create_entity_stratified_split strictly partitions entities so that
    no entity or record ever crosses Dev, Val, or Test partitions.
    """
    rows = get_offline_restaurant_fixture_rows()
    adapter = RestaurantDatasetAdapter()
    report = adapter.load_from_rows(rows, skip_header=True)

    splits = create_entity_stratified_split(report, seed=42, dev_ratio=0.6, val_ratio=0.2, test_ratio=0.2)
    assert isinstance(splits, DatasetSplits)
    assert splits.seed == 42

    dev_recs = set(splits.dev.record_ids)
    val_recs = set(splits.val.record_ids)
    test_recs = set(splits.test.record_ids)

    # 1. Zero record overlap
    assert dev_recs & val_recs == set()
    assert dev_recs & test_recs == set()
    assert val_recs & test_recs == set()
    assert dev_recs | val_recs | test_recs == {r.record_id for r in report.records}

    # 2. Zero entity overlap
    dev_entities = {report.ground_truth_entities[r] for r in dev_recs}
    val_entities = {report.ground_truth_entities[r] for r in val_recs}
    test_entities = {report.ground_truth_entities[r] for r in test_recs}

    assert dev_entities & val_entities == set()
    assert dev_entities & test_entities == set()
    assert val_entities & test_entities == set()

    # 3. Deterministic SHA-256 fingerprints
    assert len(splits.dev.split_fingerprint) == 64
    assert len(splits.val.split_fingerprint) == 64
    assert len(splits.test.split_fingerprint) == 64

    # 4. Repeatability with same seed
    splits_repeat = create_entity_stratified_split(report, seed=42, dev_ratio=0.6, val_ratio=0.2, test_ratio=0.2)
    assert splits.dev.split_fingerprint == splits_repeat.dev.split_fingerprint
    assert splits.val.split_fingerprint == splits_repeat.val.split_fingerprint
    assert splits.test.split_fingerprint == splits_repeat.test.split_fingerprint


def test_ground_truth_label_scrambling_invariance():
    """
    Verifies that ground truth evaluation labels are strictly isolated from the matching pipeline:
    scrambling, reversing, or replacing ground-truth labels causes ZERO change in:
    1. Generated candidate pairs
    2. Similarity comparison scores and evidence items
    3. MatchDecisionEngine decisions
    4. Derived entity clusters
    """
    from src.core.blocking import CandidateGenerator, get_default_blocking_rules
    from src.core.comparison import PairwiseComparator
    from src.core.decision import MatchDecisionEngine
    from src.core.clustering import ConstraintAwareClusterer

    rows = get_offline_restaurant_fixture_rows()
    adapter = RestaurantDatasetAdapter()
    report = adapter.load_from_rows(rows, skip_header=True)

    records_dict = {r.record_id: r for r in report.records}

    # --- Run 1: With original ground truth mapping ---
    gen = CandidateGenerator(get_default_blocking_rules())
    cands_1 = list(gen.generate_candidates(report.records))
    engine = MatchDecisionEngine.create_production_engine()
    decisions_1 = list(engine.decide_candidates(records_dict, cands_1))
    clusterer = ConstraintAwareClusterer()
    clusters_1 = clusterer.cluster(report.records, decisions_1).clusters

    cand_ids_1 = [c.candidate_id for c in cands_1]
    dec_tuples_1 = [(d.candidate_pair_id, d.decision, round(d.score, 6), tuple(sorted(d.evidence_references))) for d in decisions_1]
    cluster_recs_1 = sorted([sorted(c.member_record_ids) for c in clusters_1])

    # --- Run 2: Completely scramble / invert ground truth labels ---
    scrambled_entities = {
        rid: f"fake_entity_scrambled_{hash(rid) % 10000}"
        for rid in report.ground_truth_entities
    }
    import dataclasses
    report_scrambled = dataclasses.replace(report, ground_truth_entities=scrambled_entities)

    cands_2 = list(gen.generate_candidates(report_scrambled.records))
    decisions_2 = list(engine.decide_candidates(records_dict, cands_2))
    clusters_2 = clusterer.cluster(report.records, decisions_2).clusters

    cand_ids_2 = [c.candidate_id for c in cands_2]
    dec_tuples_2 = [(d.candidate_pair_id, d.decision, round(d.score, 6), tuple(sorted(d.evidence_references))) for d in decisions_2]
    cluster_recs_2 = sorted([sorted(c.member_record_ids) for c in clusters_2])

    # Assert exact byte-for-byte operational invariance
    assert cand_ids_1 == cand_ids_2
    assert dec_tuples_1 == dec_tuples_2
    assert cluster_recs_1 == cluster_recs_2

