import pytest
from types import MappingProxyType
from datetime import datetime, timezone
from pydantic import ValidationError
from src.core.models import (
    Record, CandidatePair, Evidence, EntityCluster, MatchDecision,
    EntityType, EvidencePolarity, DecisionType, SourceType, Source,
    ClusterStatus
)

# ---------------------------------------------------------------------------
# 1. Basic Creation & Invariants
# ---------------------------------------------------------------------------

def test_source_creation():
    s = Source(source_id="s1", source_type=SourceType.URL, source_name="Test Source")
    assert s.source_id == "s1"
    assert s.source_type == SourceType.URL
    assert isinstance(s.reliability_metadata, (dict, MappingProxyType))

def test_record_creation():
    r = Record(
        record_id="r1", 
        source_id="s1", 
        entity_type=EntityType.PERSON, 
        raw_name="Test Person"
    )
    assert r.record_id == "r1"
    assert r.entity_type == EntityType.PERSON
    assert len(r.raw_payload) == 0
    assert len(r.normalized_attributes) == 0

# ---------------------------------------------------------------------------
# 2. Immutability: Top-Level Mutation
# ---------------------------------------------------------------------------

def test_record_top_level_mutation_rejected():
    r = Record(
        record_id="r1", 
        source_id="s1", 
        entity_type=EntityType.PERSON, 
        raw_name="Original Name"
    )
    with pytest.raises(ValidationError):
        r.raw_name = "Mutated Name"

    with pytest.raises(ValidationError):
        r.raw_payload = {"foo": "bar"}

# ---------------------------------------------------------------------------
# 3. Immutability: Nested Mutation (Dicts & Lists)
# ---------------------------------------------------------------------------

def test_record_nested_dict_mutation_rejected():
    r = Record(
        record_id="r1",
        source_id="s1",
        entity_type=EntityType.PERSON,
        raw_name="Alice",
        raw_payload={"profile": {"contact": {"email": "alice@example.com"}}},
        normalized_attributes={"clean_email": "alice@example.com"}
    )
    # Payload is protected via standard library MappingProxyType
    assert isinstance(r.raw_payload, MappingProxyType)
    assert isinstance(r.raw_payload["profile"], MappingProxyType)

    # Top-level payload item assignment
    with pytest.raises(TypeError, match="does not support item assignment"):
        r.raw_payload["new_key"] = "val"

    # Deep nested item assignment
    with pytest.raises(TypeError, match="does not support item assignment"):
        r.raw_payload["profile"]["contact"]["email"] = "hacked@example.com"

    # Deletion attempt
    with pytest.raises(TypeError):
        del r.raw_payload["profile"]

    # Normalized attributes immutability
    with pytest.raises(TypeError, match="does not support item assignment"):
        r.normalized_attributes["clean_email"] = "bob@example.com"

    assert r.raw_payload["profile"]["contact"]["email"] == "alice@example.com"

def test_record_nested_list_mutation_rejected():
    r = Record(
        record_id="r1",
        source_id="s1",
        entity_type=EntityType.PERSON,
        raw_name="Bob",
        raw_payload={"aliases": ["Bobby", "Robert"], "matrix": [[1, 2], [3, 4]]}
    )
    # Sequences are stored as immutable tuples
    assert isinstance(r.raw_payload["aliases"], tuple)
    assert isinstance(r.raw_payload["matrix"], tuple)
    assert isinstance(r.raw_payload["matrix"][0], tuple)

    with pytest.raises(AttributeError, match="has no attribute 'append'"):
        r.raw_payload["aliases"].append("Bobster")

    with pytest.raises(TypeError, match="does not support item assignment"):
        r.raw_payload["aliases"][0] = "Modified"

    with pytest.raises(AttributeError, match="has no attribute 'append'"):
        r.raw_payload["matrix"][0].append(99)

    assert r.raw_payload["aliases"] == ("Bobby", "Robert")

# ---------------------------------------------------------------------------
# 4. Input Aliasing & MappingProxyType Protection
# ---------------------------------------------------------------------------

def test_record_input_aliasing_protection():
    external_dict = {
        "tags": ["vip", "osint"],
        "info": {"level": 1, "sub": {"flag": True}}
    }
    r = Record(
        record_id="r1",
        source_id="s1",
        entity_type=EntityType.PERSON,
        raw_name="Charlie",
        raw_payload=external_dict
    )
    # Mutating external dictionary after passing into model must not alter stored state
    external_dict["tags"].append("compromised")
    external_dict["info"]["level"] = 999
    external_dict["info"]["sub"]["flag"] = False
    external_dict["injected_key"] = "hacked"

    assert "compromised" not in r.raw_payload["tags"]
    assert r.raw_payload["info"]["level"] == 1
    assert r.raw_payload["info"]["sub"]["flag"] is True
    assert "injected_key" not in r.raw_payload

def test_top_level_mapping_proxy_aliasing_protection():
    external_dict = {"confidential": "alpha", "numbers": [10, 20]}
    top_proxy = MappingProxyType(external_dict)

    r = Record(
        record_id="r1",
        source_id="s1",
        entity_type=EntityType.PERSON,
        raw_name="David",
        raw_payload=top_proxy
    )
    # Mutating the underlying dictionary behind the top-level MappingProxyType
    external_dict["confidential"] = "compromised"
    external_dict["numbers"].append(30)
    external_dict["new_key"] = "leak"

    assert r.raw_payload["confidential"] == "alpha"
    assert r.raw_payload["numbers"] == (10, 20)
    assert "new_key" not in r.raw_payload

def test_nested_mapping_proxy_aliasing_protection():
    external_dict = {"target_name": "Target Alpha", "roles": ["CEO"]}
    nested_proxy = MappingProxyType(external_dict)

    r = Record(
        record_id="r1",
        source_id="s1",
        entity_type=EntityType.PERSON,
        raw_name="David",
        raw_payload={"layer1": {"layer2": nested_proxy}}
    )
    # Mutating the underlying dictionary behind the nested MappingProxyType
    external_dict["target_name"] = "Target Compromised"
    external_dict["roles"].append("Traitor")
    external_dict["injected"] = True

    assert r.raw_payload["layer1"]["layer2"]["target_name"] == "Target Alpha"
    assert r.raw_payload["layer1"]["layer2"]["roles"] == ("CEO",)
    assert "injected" not in r.raw_payload["layer1"]["layer2"]

def test_deep_multi_level_nesting_immutability():
    deep_input = {
        "l1_dict": {
            "l2_list": [
                {
                    "l3_dict": {
                        "l4_tuple": (
                            {"l5_dict": {"val": 42}},
                        )
                    }
                }
            ]
        }
    }
    r = Record(
        record_id="r1",
        source_id="s1",
        entity_type=EntityType.PERSON,
        raw_name="Explorer",
        raw_payload=deep_input
    )
    l5 = r.raw_payload["l1_dict"]["l2_list"][0]["l3_dict"]["l4_tuple"][0]["l5_dict"]
    assert isinstance(l5, MappingProxyType)
    assert l5["val"] == 42

    with pytest.raises(TypeError, match="does not support item assignment"):
        l5["val"] = 99

# ---------------------------------------------------------------------------
# 5. Unsupported Value Rejection & Cycle Detection
# ---------------------------------------------------------------------------

def test_unsupported_mutable_object_rejection():
    class CustomMutableState:
        def __init__(self):
            self.x = 100

    bad_obj = CustomMutableState()
    with pytest.raises(TypeError) as exc_info:
        Record(
            record_id="r1",
            source_id="s1",
            entity_type=EntityType.PERSON,
            raw_name="BadState",
            raw_payload={"custom": bad_obj}
        )
    assert "Unsupported payload value" in str(exc_info.value)
    assert "CustomMutableState" in str(exc_info.value)

def test_cyclic_payload_rejection():
    cyclic_dict = {"name": "loop"}
    cyclic_dict["self_ref"] = cyclic_dict

    with pytest.raises((ValueError, ValidationError)) as exc_info:
        Record(
            record_id="r1",
            source_id="s1",
            entity_type=EntityType.PERSON,
            raw_name="Cyclic",
            raw_payload=cyclic_dict
        )
    assert "Cyclic reference detected" in str(exc_info.value)

# ---------------------------------------------------------------------------
# 6. Serialization & JSON Round Trip
# ---------------------------------------------------------------------------

def test_record_serialization_and_json_roundtrip():
    r = Record(
        record_id="r1",
        source_id="s1",
        entity_type=EntityType.PERSON,
        raw_name="Dave",
        raw_payload={"nested": {"numbers": [1, 2, 3]}},
        normalized_attributes={"score": 0.95}
    )
    # Serialization produces ordinary JSON-compatible dicts and lists, not internal wrappers
    dumped = r.model_dump()
    assert isinstance(dumped["raw_payload"], dict)
    assert not isinstance(dumped["raw_payload"], MappingProxyType)
    assert isinstance(dumped["raw_payload"]["nested"]["numbers"], list)
    assert not isinstance(dumped["raw_payload"]["nested"]["numbers"], tuple)

    json_str = r.model_dump_json()
    r_restored = Record.model_validate_json(json_str)

    # Round trip equality
    assert r == r_restored
    assert r_restored.raw_payload["nested"]["numbers"] == (1, 2, 3)

# ---------------------------------------------------------------------------
# 7. Equality Semantics
# ---------------------------------------------------------------------------

def test_record_equality_semantics():
    fixed_dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    r1 = Record(
        record_id="r1",
        source_id="s1",
        entity_type=EntityType.PERSON,
        raw_name="Eve",
        raw_payload={"age": 30},
        created_at=fixed_dt
    )
    r2 = Record(
        record_id="r1",
        source_id="s1",
        entity_type=EntityType.PERSON,
        raw_name="Eve",
        raw_payload={"age": 30},
        created_at=fixed_dt
    )
    r3 = Record(
        record_id="r1",
        source_id="s1",
        entity_type=EntityType.PERSON,
        raw_name="Eve Different",
        raw_payload={"age": 30},
        created_at=fixed_dt
    )
    assert r1 == r2
    assert r1 != r3

# ---------------------------------------------------------------------------
# 8. CandidatePair Self-Rejection & Canonical Identity
# ---------------------------------------------------------------------------

def test_candidate_pair_self_rejection():
    with pytest.raises(ValidationError) as exc_info:
        CandidatePair(
            candidate_id="cp1",
            left_record_id="r1",
            right_record_id="r1",
            generation_method="test"
        )
    assert "CandidatePair cannot contain identical record IDs" in str(exc_info.value)

def test_candidate_pair_canonical_ordering_and_equality():
    fixed_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    cp_forward = CandidatePair(
        candidate_id="cp_test",
        left_record_id="r1",
        right_record_id="r2",
        generation_method="test",
        generated_at=fixed_time
    )
    cp_reversed = CandidatePair(
        candidate_id="cp_test",
        left_record_id="r2",
        right_record_id="r1",
        generation_method="test",
        generated_at=fixed_time
    )
    # Both input orders normalize to the same canonical candidate pair
    assert cp_forward.left_record_id == "r1"
    assert cp_forward.right_record_id == "r2"
    assert cp_reversed.left_record_id == "r1"
    assert cp_reversed.right_record_id == "r2"
    assert cp_forward.canonical_pair_key == "r1::r2"
    assert cp_reversed.canonical_pair_key == "r1::r2"
    assert cp_forward == cp_reversed

# ---------------------------------------------------------------------------
# 9. Blank and Whitespace Identifier Rejection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_id", ["", "   ", "\t\n"])
def test_non_empty_identifier_rejection(bad_id):
    with pytest.raises(ValidationError):
        Record(record_id=bad_id, source_id="s1", entity_type=EntityType.PERSON, raw_name="John")

    with pytest.raises(ValidationError):
        Source(source_id=bad_id, source_type=SourceType.URL, source_name="Source")

    with pytest.raises(ValidationError):
        CandidatePair(candidate_id=bad_id, left_record_id="r1", right_record_id="r2", generation_method="m")

    with pytest.raises(ValidationError):
        Evidence(
            evidence_id=bad_id,
            evidence_type="type",
            polarity=EvidencePolarity.SUPPORTING,
            value_description="desc",
            provenance="source1"
        )

# ---------------------------------------------------------------------------
# 10. Evidence Strength & Provenance Bounds
# ---------------------------------------------------------------------------

def test_evidence_provenance_required():
    with pytest.raises(ValidationError) as exc_info:
        Evidence(
            evidence_id="e1",
            evidence_type="name_match",
            polarity=EvidencePolarity.SUPPORTING,
            value_description="Exact match",
            provenance="   "
        )
    assert "Evidence must have provenance" in str(exc_info.value)

def test_evidence_strength_bounds():
    e_min = Evidence(
        evidence_id="e1",
        evidence_type="name_match",
        polarity=EvidencePolarity.SUPPORTING,
        value_description="Exact match",
        provenance="source1",
        strength=0.0
    )
    assert e_min.strength == 0.0

    e_max = Evidence(
        evidence_id="e2",
        evidence_type="name_match",
        polarity=EvidencePolarity.SUPPORTING,
        value_description="Exact match",
        provenance="source1",
        strength=1.0
    )
    assert e_max.strength == 1.0

    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="e3",
            evidence_type="name_match",
            polarity=EvidencePolarity.SUPPORTING,
            value_description="Exact match",
            provenance="source1",
            strength=-0.01
        )

    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="e4",
            evidence_type="name_match",
            polarity=EvidencePolarity.SUPPORTING,
            value_description="Exact match",
            provenance="source1",
            strength=1.05
        )

# ---------------------------------------------------------------------------
# 11. MatchDecision Score & Threshold Bounds
# ---------------------------------------------------------------------------

def test_match_decision_score_bounds():
    md = MatchDecision(
        candidate_pair_id="cp1",
        decision=DecisionType.MATCH,
        model_version="1.0",
        score=0.88,
        threshold=0.85
    )
    assert md.score == 0.88
    assert md.threshold == 0.85

    with pytest.raises(ValidationError):
        MatchDecision(
            candidate_pair_id="cp1",
            decision=DecisionType.MATCH,
            model_version="1.0",
            score=1.5
        )

    with pytest.raises(ValidationError):
        MatchDecision(
            candidate_pair_id="cp1",
            decision=DecisionType.MATCH,
            model_version="1.0",
            threshold=-0.1
        )

def test_match_decision_serialization():
    md = MatchDecision(
        candidate_pair_id="cp1",
        decision=DecisionType.REVIEW,
        model_version="1.0",
    )
    serialized = md.model_dump()
    assert serialized["decision"] == "REVIEW"
    
    deserialized = MatchDecision.model_validate(serialized)
    assert deserialized.decision == DecisionType.REVIEW

# ---------------------------------------------------------------------------
# 12. EntityCluster Membership & Status Validation
# ---------------------------------------------------------------------------

def test_entity_cluster_empty_members_rejection():
    with pytest.raises(ValidationError):
        EntityCluster(
            entity_cluster_id="c1",
            entity_type=EntityType.PERSON,
            member_record_ids=[],
            status=ClusterStatus.ACTIVE,
            derivation_version="v1"
        )

def test_entity_cluster_unique_members():
    with pytest.raises(ValidationError) as exc_info:
        EntityCluster(
            entity_cluster_id="c1",
            entity_type=EntityType.PERSON,
            member_record_ids=["r1", "r2", "r1"],
            status=ClusterStatus.ACTIVE,
            derivation_version="v1"
        )
    assert "EntityCluster cannot contain duplicate record IDs" in str(exc_info.value)

def test_entity_cluster_valid_statuses():
    for status_str in ["active", "provisional", "merged", "split", "archived"]:
        c = EntityCluster(
            entity_cluster_id="c1",
            entity_type=EntityType.PERSON,
            member_record_ids=["r1", "r2"],
            status=status_str,
            derivation_version="v1"
        )
        assert c.status.value == status_str

    with pytest.raises(ValidationError):
        EntityCluster(
            entity_cluster_id="c1",
            entity_type=EntityType.PERSON,
            member_record_ids=["r1", "r2"],
            status="invalid_status",
            derivation_version="v1"
        )
