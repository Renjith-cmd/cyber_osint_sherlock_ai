import pytest
from src.core.models import DecisionType, MatchDecision
from src.core.cross_document_resolver import CrossDocumentEntityResolver
from tests.synthetic_dataset import (
    get_fictional_records,
    get_candidate_pairs,
    GROUND_TRUTH,
    GROUND_TRUTH_CLUSTERS,
)

def _candidate_id_map(candidates):
    """Map (left_id, right_id) -> candidate_id for quick lookup."""
    return {(cp.left_record_id, cp.right_record_id): cp.candidate_id for cp in candidates}

def evaluate_metrics(decisions):
    tp = sum(1 for d in decisions if GROUND_TRUTH.get(d.candidate_id) and d.decision == DecisionType.MATCH)
    fp = sum(1 for d in decisions if not GROUND_TRUTH.get(d.candidate_id) and d.decision == DecisionType.MATCH)
    fn = sum(1 for d in decisions if GROUND_TRUTH.get(d.candidate_id) and d.decision != DecisionType.MATCH)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1

def test_synthetic_candidate_generation_recall():
    """Ensure that the blocking generator produces *all* expected candidate pairs for same‑type records."""
    records = get_fictional_records()
    resolver = CrossDocumentEntityResolver()
    for rec in records:
        resolver.records[rec.record_id] = rec
    candidates = resolver.generate_candidates(records)
    generated_ids = {cp.candidate_id for cp in candidates}
    # Filter synthetic pairs to those where entity types match (resolver drops cross‑type)
    expected_ids = {
        cp.candidate_id
        for cp in get_candidate_pairs()
        if resolver.records[cp.left_record_id].entity_type == resolver.records[cp.right_record_id].entity_type
    }
    missing = expected_ids - generated_ids
    extra = generated_ids - expected_ids
    assert not missing, f"Missing expected candidate IDs: {missing}"
    assert not extra, f"Generated unexpected candidate IDs: {extra}"

def test_synthetic_end_to_end_workflow():
    """Full workflow: candidate generation → decision evaluation → metrics → provenance checks."""
    records = get_fictional_records()
    resolver = CrossDocumentEntityResolver()
    for rec in records:
        resolver.records[rec.record_id] = rec
    candidates = resolver.generate_candidates(records)
    decisions = []
    for cp in candidates:
        left = resolver.records[cp.left_record_id]
        right = resolver.records[cp.right_record_id]
        decisions.append(resolver.evaluate_pair(left, right, cp.candidate_id))
    precision, recall, f1 = evaluate_metrics(decisions)
    assert precision >= 0.9, f"Precision too low: {precision}"
    assert recall >= 0.9, f"Recall too low: {recall}"
    assert f1 >= 0.9, f"F1 too low: {f1}"
    for d in decisions:
        assert d.left_document_id, "Left document ID missing"
        assert d.right_document_id, "Right document ID missing"
        ev_text = " ".join(d.positive_evidence)
        assert d.left_document_id in ev_text or d.right_document_id in ev_text, (
            f"Provenance not reflected in evidence for {d.candidate_id}"
        )
    # Transitive clustering verification for r9a/r9b/r9c
    match_decisions = [d for d in decisions if d.decision == DecisionType.MATCH]
    from src.core.models import MatchDecision
    match_objs = [
        MatchDecision(
            candidate_pair_id=d.candidate_id,
            decision=DecisionType.MATCH,
            score=d.score,
            threshold=resolver.POLICY_THRESHOLD,
            model_version=resolver.POLICY_VERSION,
        )
        for d in match_decisions
    ]
    clusters = resolver.clusterer.cluster(records, match_objs)
    r9_cluster = clusters.record_to_cluster["r9a"]
    assert clusters.record_to_cluster["r9b"] == r9_cluster
    assert clusters.record_to_cluster["r9c"] == r9_cluster
