import pytest
from tests.synthetic_dataset import get_fictional_records, get_candidate_pairs, GROUND_TRUTH

def test_dataset_deterministic_loading():
    records1 = get_fictional_records()
    records2 = get_fictional_records()
    assert len(records1) == len(records2)
    assert records1[0].record_id == records2[0].record_id

def test_dataset_unique_record_ids():
    records = get_fictional_records()
    ids = [r.record_id for r in records]
    assert len(ids) == len(set(ids)), "Record IDs must be unique"

def test_dataset_valid_references():
    records = {r.record_id: r for r in get_fictional_records()}
    pairs = get_candidate_pairs()
    
    for p in pairs:
        assert p.left_record_id in records, f"Left record {p.left_record_id} not found"
        assert p.right_record_id in records, f"Right record {p.right_record_id} not found"

def test_dataset_no_self_candidate_pairs():
    pairs = get_candidate_pairs()
    for p in pairs:
        assert p.left_record_id != p.right_record_id, "Found a self-referencing candidate pair"

def test_dataset_consistent_ground_truth():
    pairs = get_candidate_pairs()
    pair_ids = {p.candidate_id for p in pairs}
    
    # Ground truth should cover exactly the candidate pairs generated
    assert set(GROUND_TRUTH.keys()) == pair_ids, "Ground truth keys do not match candidate pair IDs"
