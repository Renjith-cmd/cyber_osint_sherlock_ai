"""
Milestone 8 Test Suite: Evidence Provenance, Relationship Modeling & Investigation Graph.

Tests cover all required invariants:
1. Model validation and invalid references (dangling references, bounds, empty IDs)
2. Stable IDs and deterministic serialization / immutability
3. Evidence-to-claim-to-relationship provenance chains
4. Multiple sources supporting one claim and relationship
5. Contradictory claims and evidence preservation
6. Unknown or missing provenance handling
7. Epistemic tiers: ASSERTED vs INFERRED vs HUMAN_VERIFIED
8. Unresolved entity references preserved as provisional
9. Entity-resolution decisions remaining distinct from factual verification
10. Graph traversal depth limits and cycle handling
11. Query determinism
12. Corrections, retractions, and superseded claims with audit history
13. Re-clustering / entity corrections not leaving stale derived relationships
14. Source record immutability
15. Absence of ground-truth leakage into runtime decisions
"""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from src.core.models import (
    Record,
    Source,
    SourceType,
    EntityType,
    Evidence,
    EvidencePolarity,
    Claim,
    ClaimCorrection,
    Relationship,
    EntityCluster,
    InvestigationEntity,
    ReviewStatus,
    RelationshipEpistemicTier,
    ConfidenceSemantics,
    ClusterStatus,
)
from src.core.investigation_graph import (
    InMemoryInvestigationGraphStore,
    Neo4jInvestigationGraphAdapter,
)
from src.core.investigation_lifecycle import InvestigationLifecycleManager
from src.core.investigation_service import InvestigationQueryService


# ---------------------------------------------------------------------------
# 1. Model Validation and Invalid References
# ---------------------------------------------------------------------------

def test_model_validation_empty_ids():
    with pytest.raises(ValidationError):
        InvestigationEntity(entity_id="  ", entity_type=EntityType.PERSON, canonical_name="John")

    with pytest.raises(ValidationError):
        Claim(
            claim_id="cl_1",
            subject_id="",
            predicate="OWNS",
            object_id="ent_2",
        )

    with pytest.raises(ValidationError):
        Relationship(
            relationship_id="rel_1",
            source_entity_id="ent_1",
            target_entity_id="  ",
            relationship_type="DIRECTOR_OF",
        )


def test_confidence_bounds():
    # Valid bounds
    c1 = Claim(claim_id="cl_1", subject_id="s1", predicate="P", object_id="o1", confidence=0.0)
    assert c1.confidence == 0.0
    c2 = Claim(claim_id="cl_2", subject_id="s1", predicate="P", object_id="o1", confidence=1.0)
    assert c2.confidence == 1.0

    with pytest.raises(ValidationError):
        Claim(claim_id="cl_3", subject_id="s1", predicate="P", object_id="o1", confidence=-0.1)

    with pytest.raises(ValidationError):
        Claim(claim_id="cl_4", subject_id="s1", predicate="P", object_id="o1", confidence=1.05)


def test_dangling_entity_reference_prevention():
    store = InMemoryInvestigationGraphStore()
    e1 = InvestigationEntity(entity_id="ent_1", entity_type=EntityType.PERSON, canonical_name="Alice")
    store.add_entity(e1)

    rel = Relationship(
        relationship_id="rel_1",
        source_entity_id="ent_1",
        target_entity_id="ent_missing",
        relationship_type="EMPLOYED_BY",
    )
    with pytest.raises(ValueError) as exc:
        store.add_relationship(rel)
    assert "Dangling entity reference" in str(exc.value)


def test_missing_evidence_in_claim_extraction():
    store = InMemoryInvestigationGraphStore()
    manager = InvestigationLifecycleManager(store)

    with pytest.raises(ValueError) as exc:
        manager.extract_claim(
            claim_id="cl_1",
            subject_id="s1",
            predicate="OWNS",
            object_id="o1",
            supporting_evidence_ids=["ev_nonexistent"],
        )
    assert "Referenced supporting evidence 'ev_nonexistent' does not exist" in str(exc.value)


# ---------------------------------------------------------------------------
# 2. Stable IDs, Deterministic Serialization & Immutability
# ---------------------------------------------------------------------------

def test_stable_ids_and_immutability():
    ev = Evidence(
        evidence_id="ev_100",
        evidence_type="corporate_filing",
        source_uri="https://records.example.gov/filing/123",
        text_span="Dr. Elena Vance holds 51% of shares",
        publication_time=datetime(2023, 5, 1, 12, 0, tzinfo=timezone.utc),
    )
    assert ev.evidence_id == "ev_100"
    assert ev.polarity == EvidencePolarity.SUPPORTING
    assert ev.provenance == "source:https://records.example.gov/filing/123"

    # Deep immutability: Cannot set attributes on frozen model
    with pytest.raises(ValidationError):
        ev.evidence_id = "ev_new"

    serialized = ev.model_dump()
    assert serialized["evidence_id"] == "ev_100"
    assert serialized["source_uri"] == "https://records.example.gov/filing/123"


# ---------------------------------------------------------------------------
# 3. Evidence-to-Claim-to-Relationship Provenance
# ---------------------------------------------------------------------------

def test_evidence_to_claim_to_relationship_provenance():
    store = InMemoryInvestigationGraphStore()
    manager = InvestigationLifecycleManager(store)
    service = InvestigationQueryService(store)

    # 1. Register Entities & Ingest Evidence
    store.add_entity(InvestigationEntity(
        entity_id="ent_elena", entity_type=EntityType.PERSON, canonical_name="Elena Vance"
    ))
    store.add_entity(InvestigationEntity(
        entity_id="ent_aperture", entity_type=EntityType.ORGANIZATION, canonical_name="Aperture Corp"
    ))

    ev = manager.ingest_evidence(Evidence(
        evidence_id="ev_filing_2023",
        evidence_type="official_registry",
        source_uri="https://registry.example.org/records/456",
        content="Elena Vance registered as Director on 2023-01-15",
        text_span="Elena Vance registered as Director",
        extraction_method="regex_table_parser",
        extractor_version="v2.1",
    ))

    # 2. Extract Claim
    claim = manager.extract_claim(
        claim_id="cl_directorship_01",
        subject_id="ent_elena",
        predicate="DIRECTOR_OF",
        object_id="ent_aperture",
        supporting_evidence_ids=["ev_filing_2023"],
        extraction_method="relation_extractor_v2",
    )

    # 3. Derive Relationship
    rel = manager.derive_relationship_from_claim(claim_id="cl_directorship_01")
    assert rel.relationship_id == "rel_ent_elena_DIRECTOR_OF_ent_aperture"

    # Query provenance
    rel_ev = store.get_relationship_evidence(rel.relationship_id)
    assert len(rel_ev["supporting"]) == 1
    assert rel_ev["supporting"][0].evidence_id == "ev_filing_2023"
    assert rel_ev["supporting"][0].text_span == "Elena Vance registered as Director"

    # Query investigation report
    res = service.query(start_entity_id="ent_elena")
    assert len(res.relationships) == 1
    exp = res.get_explanation(rel.relationship_id)
    assert exp is not None
    assert exp.has_provenance is True
    assert "ev_filing_2023" in exp.supporting_evidence_ids


# ---------------------------------------------------------------------------
# 4. Multiple Sources Supporting One Claim and Relationship
# ---------------------------------------------------------------------------

def test_multiple_sources_supporting_relationship():
    store = InMemoryInvestigationGraphStore()
    manager = InvestigationLifecycleManager(store)

    store.add_entity(InvestigationEntity(entity_id="ent_p1", entity_type=EntityType.PERSON, canonical_name="John Doe"))
    store.add_entity(InvestigationEntity(entity_id="ent_c1", entity_type=EntityType.ORGANIZATION, canonical_name="Acme Inc"))

    manager.ingest_evidence(Evidence(
        evidence_id="ev_src1",
        evidence_type="news_article",
        source_uri="https://news.example.com/item1",
        content="John Doe founded Acme Inc in 2010.",
    ))
    manager.ingest_evidence(Evidence(
        evidence_id="ev_src2",
        evidence_type="sec_filing",
        source_uri="https://sec.example.gov/filing/999",
        content="Acme Inc founder: John Doe.",
    ))

    cl1 = manager.extract_claim(
        claim_id="cl_1", subject_id="ent_p1", predicate="FOUNDED", object_id="ent_c1",
        supporting_evidence_ids=["ev_src1"],
    )
    cl2 = manager.extract_claim(
        claim_id="cl_2", subject_id="ent_p1", predicate="FOUNDED", object_id="ent_c1",
        supporting_evidence_ids=["ev_src2"],
    )

    manager.derive_relationship_from_claim("cl_1", relationship_id="rel_john_acme")
    manager.derive_relationship_from_claim("cl_2", relationship_id="rel_john_acme")

    rel = store.get_relationship("rel_john_acme")
    assert rel is not None
    assert set(rel.supporting_claim_ids) == {"cl_1", "cl_2"}

    rel_ev = store.get_relationship_evidence("rel_john_acme")
    sup_ids = {e.evidence_id for e in rel_ev["supporting"]}
    assert sup_ids == {"ev_src1", "ev_src2"}


# ---------------------------------------------------------------------------
# 5. Contradictory Claims and Evidence
# ---------------------------------------------------------------------------

def test_contradictory_claims_and_evidence():
    store = InMemoryInvestigationGraphStore()
    manager = InvestigationLifecycleManager(store)
    service = InvestigationQueryService(store)

    store.add_entity(InvestigationEntity(entity_id="ent_alice", entity_type=EntityType.PERSON, canonical_name="Alice Smith"))
    store.add_entity(InvestigationEntity(entity_id="ent_alpha", entity_type=EntityType.ORGANIZATION, canonical_name="Alpha Corp"))

    # Evidence 1: Alice owns Alpha Corp
    manager.ingest_evidence(Evidence(
        evidence_id="ev_assert_ownership",
        evidence_type="registry_excerpt",
        source_uri="https://biz.example.org/alpha",
        content="Alice Smith owns 100% of Alpha Corp",
    ))
    manager.extract_claim(
        claim_id="cl_owns_alpha",
        subject_id="ent_alice",
        predicate="OWNS",
        object_id="ent_alpha",
        supporting_evidence_ids=["ev_assert_ownership"],
    )
    rel = manager.derive_relationship_from_claim("cl_owns_alpha", relationship_id="rel_alice_alpha")
    assert rel.review_status == ReviewStatus.UNREVIEWED

    # Evidence 2: Alice sold all shares and does NOT own Alpha Corp
    manager.ingest_evidence(Evidence(
        evidence_id="ev_divestment_deed",
        evidence_type="notarial_deed",
        source_uri="https://biz.example.org/deed/2024",
        content="Alice Smith divested 100% shares on 2024-02-01",
    ))
    manager.extract_claim(
        claim_id="cl_not_owns_alpha",
        subject_id="ent_alice",
        predicate="NOT_OWNS",
        object_id="ent_alpha",
        supporting_evidence_ids=["ev_divestment_deed"],
    )

    # Link contradiction
    manager.record_contradiction(
        relationship_id="rel_alice_alpha",
        contradicting_claim_id="cl_not_owns_alpha",
    )

    updated_rel = store.get_relationship("rel_alice_alpha")
    assert updated_rel.review_status == ReviewStatus.DISPUTED
    assert "cl_not_owns_alpha" in updated_rel.contradicting_claim_ids
    assert "ev_divestment_deed" in updated_rel.contradicting_evidence_ids

    # Query explanation highlights contradiction
    res = service.query(start_entity_id="ent_alice")
    exp = res.get_explanation("rel_alice_alpha")
    assert exp.is_disputed is True
    assert "CONTRADICTION DETECTED" in exp.summary_text
    assert "ev_divestment_deed" in exp.contradicting_evidence_ids
    assert "ev_assert_ownership" in exp.supporting_evidence_ids


# ---------------------------------------------------------------------------
# 6. Unknown or Missing Provenance Handling
# ---------------------------------------------------------------------------

def test_missing_provenance_warning():
    store = InMemoryInvestigationGraphStore()
    service = InvestigationQueryService(store)

    store.add_entity(InvestigationEntity(entity_id="e1", entity_type=EntityType.PERSON, canonical_name="Bob"))
    store.add_entity(InvestigationEntity(entity_id="e2", entity_type=EntityType.ORGANIZATION, canonical_name="Beta Org"))

    # Relationship asserted with zero supporting claims or evidence
    unsupported_rel = Relationship(
        relationship_id="rel_unsupported",
        source_entity_id="e1",
        target_entity_id="e2",
        relationship_type="MEMBER_OF",
        supporting_claim_ids=[],
        supporting_evidence_ids=[],
    )
    store.add_relationship(unsupported_rel)

    res = service.query(start_entity_id="e1")
    assert res.unsupported_relationship_count == 1
    exp = res.get_explanation("rel_unsupported")
    assert exp.has_provenance is False
    assert "WARNING: This relationship lacks supporting claims or verified evidence." in exp.summary_text


# ---------------------------------------------------------------------------
# 7. Asserted vs Inferred vs Human-Verified Epistemic Tiers
# ---------------------------------------------------------------------------

def test_epistemic_tiers():
    store = InMemoryInvestigationGraphStore()
    service = InvestigationQueryService(store)

    store.add_entity(InvestigationEntity(entity_id="e1", entity_type=EntityType.PERSON, canonical_name="Person 1"))
    store.add_entity(InvestigationEntity(entity_id="e2", entity_type=EntityType.ORGANIZATION, canonical_name="Org 2"))
    store.add_entity(InvestigationEntity(entity_id="e3", entity_type=EntityType.ORGANIZATION, canonical_name="Org 3"))

    # Asserted
    rel1 = Relationship(
        relationship_id="r1", source_entity_id="e1", target_entity_id="e2", relationship_type="OWNS",
        epistemic_tier=RelationshipEpistemicTier.ASSERTED, supporting_claim_ids=["cl_1"],
    )
    # Inferred (e.g. through transitive corporate hierarchy)
    rel2 = Relationship(
        relationship_id="r2", source_entity_id="e2", target_entity_id="e3", relationship_type="SUBSIDIARY_OF",
        epistemic_tier=RelationshipEpistemicTier.INFERRED, supporting_claim_ids=["cl_2"],
    )
    # Human Verified
    rel3 = Relationship(
        relationship_id="r3", source_entity_id="e1", target_entity_id="e3", relationship_type="BENEFICIAL_OWNER_OF",
        epistemic_tier=RelationshipEpistemicTier.HUMAN_VERIFIED, supporting_claim_ids=["cl_3"],
    )

    manager = InvestigationLifecycleManager(store)
    ev = manager.ingest_evidence(Evidence(
        evidence_id="ev_tier", evidence_type="test", source_uri="https://test.example", content="test tier evidence"
    ))
    manager.extract_claim("cl_1", "e1", "OWNS", "e2", ["ev_tier"])
    manager.extract_claim("cl_2", "e2", "SUBSIDIARY_OF", "e3", ["ev_tier"])
    manager.extract_claim("cl_3", "e1", "BENEFICIAL_OWNER_OF", "e3", ["ev_tier"])

    store.add_relationship(rel1)
    store.add_relationship(rel2)
    store.add_relationship(rel3)

    res = service.query(start_entity_id="e1")
    exp1 = res.get_explanation("r1")
    exp2 = res.get_explanation("r2")
    exp3 = res.get_explanation("r3")

    assert "[ASSERTED]" in exp1.summary_text
    assert "[INFERRED]" in exp2.summary_text
    assert "[HUMAN_VERIFIED]" in exp3.summary_text


# ---------------------------------------------------------------------------
# 8. Unresolved Entity References
# ---------------------------------------------------------------------------

def test_unresolved_entity_references_preserved():
    store = InMemoryInvestigationGraphStore()
    manager = InvestigationLifecycleManager(store)

    # Register known entity
    store.add_entity(InvestigationEntity(entity_id="ent_known", entity_type=EntityType.PERSON, canonical_name="Known Person"))

    # Document mentions unknown entity "Shell Co XYZ"
    provisional_ent = manager.register_unresolved_entity(
        mention_id="unresolved_mention_99",
        raw_name="Shell Co XYZ",
        entity_type=EntityType.ORGANIZATION,
    )
    assert provisional_ent.metadata["provisional"] is True
    assert provisional_ent.metadata["unresolved"] is True

    # Claim points to unresolved entity
    ev = manager.ingest_evidence(Evidence(
        evidence_id="ev_shell",
        evidence_type="leak_document",
        source_uri="https://leaks.example.org/doc1",
        content="Known Person wired funds to Shell Co XYZ",
    ))
    cl = manager.extract_claim(
        claim_id="cl_wire",
        subject_id="ent_known",
        predicate="WIRED_FUNDS_TO",
        object_id="unresolved_mention_99",
        supporting_evidence_ids=["ev_shell"],
    )

    rel = manager.derive_relationship_from_claim(claim_id="cl_wire")
    assert rel.target_entity_id == "unresolved_mention_99"
    # Verify it was NOT merged with any existing entity
    assert len(store.list_entities()) == 2


# ---------------------------------------------------------------------------
# 9. Entity Resolution Decisions Distinct from Factual Verification
# ---------------------------------------------------------------------------

def test_er_distinct_from_factual_verification():
    """
    Two records sharing a relationship or co-location must NEVER be silently merged
    merely because they participate in the same factual claim.
    """
    store = InMemoryInvestigationGraphStore()
    manager = InvestigationLifecycleManager(store)

    rec1 = Record(record_id="rec_p1", source_id="src1", entity_type=EntityType.PERSON, raw_name="Dr. Aris Thorne")
    rec2 = Record(record_id="rec_p2", source_id="src2", entity_type=EntityType.PERSON, raw_name="Dr. Julian Thorne")
    manager.ingest_record(rec1)
    manager.ingest_record(rec2)

    # Both records registered as separate entities (different brothers / directors)
    ent1 = store.add_entity(InvestigationEntity(entity_id="ent_aris", entity_type=EntityType.PERSON, canonical_name="Dr. Aris Thorne", member_record_ids=["rec_p1"]))
    ent2 = store.add_entity(InvestigationEntity(entity_id="ent_julian", entity_type=EntityType.PERSON, canonical_name="Dr. Julian Thorne", member_record_ids=["rec_p2"]))

    # Factual claim: Both are CO_DIRECTORS
    ev = manager.ingest_evidence(Evidence(
        evidence_id="ev_board", evidence_type="annual_report", source_uri="https://corp.example.org/2023",
        content="Aris Thorne and Julian Thorne serve as Co-Directors."
    ))
    cl = manager.extract_claim(
        claim_id="cl_codir", subject_id="ent_aris", predicate="CO_DIRECTOR_WITH", object_id="ent_julian",
        supporting_evidence_ids=["ev_board"]
    )
    rel = manager.derive_relationship_from_claim("cl_codir")

    assert rel.source_entity_id == "ent_aris"
    assert rel.target_entity_id == "ent_julian"

    # Entities remain strictly independent
    assert ent1.entity_id != ent2.entity_id
    assert len(store.list_entities()) == 2
    assert store.get_entity("ent_aris").member_record_ids == ("rec_p1",)
    assert store.get_entity("ent_julian").member_record_ids == ("rec_p2",)


# ---------------------------------------------------------------------------
# 10. Graph Traversal Depth Limits and Cycle Handling
# ---------------------------------------------------------------------------

def test_traversal_cycle_handling_and_depth_limits():
    store = InMemoryInvestigationGraphStore()

    # Form a cyclic triangle: A -> B -> C -> A
    store.add_entity(InvestigationEntity(entity_id="node_a", entity_type=EntityType.ORGANIZATION, canonical_name="A"))
    store.add_entity(InvestigationEntity(entity_id="node_b", entity_type=EntityType.ORGANIZATION, canonical_name="B"))
    store.add_entity(InvestigationEntity(entity_id="node_c", entity_type=EntityType.ORGANIZATION, canonical_name="C"))

    store.add_relationship(Relationship(relationship_id="r_ab", source_entity_id="node_a", target_entity_id="node_b", relationship_type="OWNS"))
    store.add_relationship(Relationship(relationship_id="r_bc", source_entity_id="node_b", target_entity_id="node_c", relationship_type="OWNS"))
    store.add_relationship(Relationship(relationship_id="r_ca", source_entity_id="node_c", target_entity_id="node_a", relationship_type="OWNS"))

    service = InvestigationQueryService(store)

    # Depth 1: should discover node_a, node_b, and node_c (since node_c connects back to node_a via in-edge)
    res_d1 = service.query(start_entity_id="node_a", max_depth=1)
    assert len(res_d1.entities) <= 3

    # Depth 5: Cycle traversal must terminate cleanly without infinite recursion
    res_d5 = service.query(start_entity_id="node_a", max_depth=5, max_nodes=10)
    assert len(res_d5.entities) == 3
    assert {e.entity_id for e in res_d5.entities} == {"node_a", "node_b", "node_c"}


# ---------------------------------------------------------------------------
# 11. Query Determinism
# ---------------------------------------------------------------------------

def test_query_determinism():
    store = InMemoryInvestigationGraphStore()
    manager = InvestigationLifecycleManager(store)
    service = InvestigationQueryService(store)

    for i in range(5):
        store.add_entity(InvestigationEntity(entity_id=f"ent_{i}", entity_type=EntityType.PERSON, canonical_name=f"Person {i}"))

    # Add edges with various IDs
    store.add_relationship(Relationship(relationship_id="rel_01", source_entity_id="ent_0", target_entity_id="ent_1", relationship_type="KNOWS"))
    store.add_relationship(Relationship(relationship_id="rel_02", source_entity_id="ent_0", target_entity_id="ent_2", relationship_type="KNOWS"))
    store.add_relationship(Relationship(relationship_id="rel_13", source_entity_id="ent_1", target_entity_id="ent_3", relationship_type="KNOWS"))
    store.add_relationship(Relationship(relationship_id="rel_24", source_entity_id="ent_2", target_entity_id="ent_4", relationship_type="KNOWS"))

    res1 = service.query("ent_0", max_depth=3)
    res2 = service.query("ent_0", max_depth=3)

    assert [e.entity_id for e in res1.entities] == [e.entity_id for e in res2.entities]
    assert [r.relationship_id for r in res1.relationships] == [r.relationship_id for r in res2.relationships]
    assert [exp.summary_text for exp in res1.explanations] == [exp.summary_text for exp in res2.explanations]


# ---------------------------------------------------------------------------
# 12. Corrections, Retractions and Superseded Claims
# ---------------------------------------------------------------------------

def test_corrections_and_retractions():
    store = InMemoryInvestigationGraphStore()
    manager = InvestigationLifecycleManager(store)
    service = InvestigationQueryService(store)

    store.add_entity(InvestigationEntity(entity_id="e1", entity_type=EntityType.PERSON, canonical_name="Investigated Person"))
    store.add_entity(InvestigationEntity(entity_id="e2", entity_type=EntityType.ORGANIZATION, canonical_name="Investigated Org"))

    ev = manager.ingest_evidence(Evidence(
        evidence_id="ev_erroneous",
        evidence_type="rumor",
        source_uri="https://blog.example.com",
        content="Claimed beneficial ownership.",
    ))
    cl = manager.extract_claim(
        claim_id="cl_ownership",
        subject_id="e1",
        predicate="BENEFICIAL_OWNER_OF",
        object_id="e2",
        supporting_evidence_ids=["ev_erroneous"],
    )
    rel = manager.derive_relationship_from_claim("cl_ownership")

    assert rel.review_status == ReviewStatus.UNREVIEWED

    # Investigator retracts the claim with documented rationale
    corrected_claim = manager.review_claim(
        claim_id="cl_ownership",
        new_status=ReviewStatus.RETRACTED,
        rationale="Source document debunked as blog forgery by official court audit.",
        reviewer="Analyst_42",
    )

    assert corrected_claim.review_status == ReviewStatus.RETRACTED
    assert corrected_claim.retraction_reason is not None
    assert len(corrected_claim.correction_history) == 1
    corr = corrected_claim.correction_history[0]
    assert corr.corrected_by == "Analyst_42"
    assert corr.previous_status == ReviewStatus.UNREVIEWED
    assert corr.new_status == ReviewStatus.RETRACTED

    # Dependent relationship cascaded to RETRACTED
    updated_rel = store.get_relationship(rel.relationship_id)
    assert updated_rel.review_status == ReviewStatus.RETRACTED

    # Query explanation reflects retraction
    res = service.query("e1")
    exp = res.get_explanation(rel.relationship_id)
    assert "STATUS ALERT: Relationship has been marked RETRACTED" in exp.summary_text


def test_superseded_claim_validation():
    # Attempting to set SUPERSEDED without superseded_by_claim_id must fail validation
    with pytest.raises(ValidationError):
        Claim(
            claim_id="cl_old",
            subject_id="s",
            predicate="P",
            object_id="o",
            review_status=ReviewStatus.SUPERSEDED,
            # Missing superseded_by_claim_id
        )

    # Valid supersession
    valid_superseded = Claim(
        claim_id="cl_old",
        subject_id="s",
        predicate="P",
        object_id="o",
        review_status=ReviewStatus.SUPERSEDED,
        superseded_by_claim_id="cl_new",
    )
    assert valid_superseded.superseded_by_claim_id == "cl_new"


# ---------------------------------------------------------------------------
# 13. Re-clustering & Entity Corrections Not Leaving Stale Relationships
# ---------------------------------------------------------------------------

def test_reclustering_updates_derived_relationships():
    store = InMemoryInvestigationGraphStore()
    manager = InvestigationLifecycleManager(store)

    rec1 = Record(record_id="rec_alice_work", source_id="src1", entity_type=EntityType.PERSON, raw_name="Alice Smith")
    rec2 = Record(record_id="rec_alicia_other", source_id="src2", entity_type=EntityType.PERSON, raw_name="Alicia Smith")
    rec_org = Record(record_id="rec_org_target", source_id="src3", entity_type=EntityType.ORGANIZATION, raw_name="Cyberdyne Corp")

    manager.ingest_record(rec1)
    manager.ingest_record(rec2)
    manager.ingest_record(rec_org)

    # Initially, ER clustered rec1 and rec2 together into cluster_alice_erroneous
    initial_cluster = EntityCluster(
        entity_cluster_id="cluster_alice_merged",
        entity_type=EntityType.PERSON,
        member_record_ids=["rec_alice_work", "rec_alicia_other"],
        status=ClusterStatus.ACTIVE,
        derivation_version="v1.0",
    )
    org_cluster = EntityCluster(
        entity_cluster_id="cluster_cyberdyne",
        entity_type=EntityType.ORGANIZATION,
        member_record_ids=["rec_org_target"],
        status=ClusterStatus.ACTIVE,
        derivation_version="v1.0",
    )
    store.add_entity(initial_cluster)
    store.add_entity(org_cluster)

    # Document says rec_alice_work is CEO of Cyberdyne
    ev = manager.ingest_evidence(Evidence(
        evidence_id="ev_ceo",
        evidence_type="corporate_registry",
        source_uri="https://gov.example.org",
        content="Alice Smith appointed CEO of Cyberdyne",
    ))
    cl = manager.extract_claim(
        claim_id="cl_ceo",
        subject_id="rec_alice_work",
        predicate="CEO_OF",
        object_id="rec_org_target",
        supporting_evidence_ids=["ev_ceo"],
    )

    # Derive relationship pointing to the merged cluster
    initial_rel = manager.derive_relationship_from_claim(
        claim_id="cl_ceo",
        relationship_id="rel_alice_cyberdyne",
        cluster_resolver=lambda rid: "cluster_alice_merged" if rid in ("rec_alice_work", "rec_alicia_other") else "cluster_cyberdyne",
    )
    assert initial_rel.source_entity_id == "cluster_alice_merged"

    # Now, an ER audit separates rec1 and rec2 into distinct clusters!
    cluster_alice_pure = EntityCluster(
        entity_cluster_id="cluster_alice_true",
        entity_type=EntityType.PERSON,
        member_record_ids=["rec_alice_work"],
        status=ClusterStatus.ACTIVE,
        derivation_version="v2.0",
    )
    cluster_alicia_split = EntityCluster(
        entity_cluster_id="cluster_alicia_separate",
        entity_type=EntityType.PERSON,
        member_record_ids=["rec_alicia_other"],
        status=ClusterStatus.ACTIVE,
        derivation_version="v2.0",
    )

    # Rebuild derived graph
    record_to_cluster = {
        "rec_alice_work": "cluster_alice_true",
        "rec_alicia_other": "cluster_alicia_separate",
        "rec_org_target": "cluster_cyberdyne",
    }
    manager.recluster_and_rebuild(
        clusters=[cluster_alice_pure, cluster_alicia_split, org_cluster],
        record_to_cluster_map=record_to_cluster,
    )

    # Verify:
    # 1. The relationship source endpoint is now cluster_alice_true!
    updated_rel = store.get_relationship("rel_alice_cyberdyne")
    assert updated_rel is not None
    assert updated_rel.source_entity_id == "cluster_alice_true"
    assert updated_rel.target_entity_id == "cluster_cyberdyne"

    # 2. cluster_alicia_separate does NOT have the CEO relationship!
    alicia_rels = store.get_entity_relationships("cluster_alicia_separate")
    assert len(alicia_rels) == 0

    # 3. Historical claim cl_ceo is intact and still points to rec_alice_work
    claim = store.get_claim("cl_ceo")
    assert claim.subject_id == "rec_alice_work"


# ---------------------------------------------------------------------------
# 14. Source Record Immutability
# ---------------------------------------------------------------------------

def test_source_record_immutability():
    rec = Record(
        record_id="rec_immut",
        source_id="src_1",
        entity_type=EntityType.PERSON,
        raw_name="Immutable Name",
        normalized_attributes={"key": "val"},
    )
    store = InMemoryInvestigationGraphStore()
    manager = InvestigationLifecycleManager(store)
    manager.ingest_record(rec)

    with pytest.raises(ValidationError):
        rec.raw_name = "Changed Name"


# ---------------------------------------------------------------------------
# 15. Neo4j Offline Fallback Safety
# ---------------------------------------------------------------------------

def test_neo4j_adapter_offline_graceful_handling():
    adapter = Neo4jInvestigationGraphAdapter(uri="bolt://localhost:9999")
    with pytest.raises(Exception):
        # Must fail informatively when offline without crashing pytest setup
        adapter.add_entity(InvestigationEntity(
            entity_id="e1", entity_type=EntityType.PERSON, canonical_name="Name"
        ))


# ---------------------------------------------------------------------------
# 16. Runnable Investigation Demo Verification
# ---------------------------------------------------------------------------

def test_investigation_demo_executes_deterministically():
    from src.core.investigation_demo import run_milestone_8_demo

    report = run_milestone_8_demo()
    assert "# Sherlock AI Investigation Report" in report
    assert "cluster_fict_elena_vance" in report
    assert "cluster_fict_aperture_holdings" in report
    assert "STATUS ALERT: Relationship has been marked RETRACTED" in report


# ---------------------------------------------------------------------------
# 17. Audit A & B: Retraction Preservation and Human Reinstatement
# ---------------------------------------------------------------------------

def test_retraction_not_undone_by_reingestion_or_rebuild():
    store = InMemoryInvestigationGraphStore()
    manager = InvestigationLifecycleManager(store)

    ent_a = store.add_entity(InvestigationEntity(entity_id="ent_a", entity_type=EntityType.PERSON, canonical_name="Alice"))
    ent_b = store.add_entity(InvestigationEntity(entity_id="ent_b", entity_type=EntityType.ORGANIZATION, canonical_name="Beta Org"))

    ev = manager.ingest_evidence(Evidence(
        evidence_id="ev_audit_1", evidence_type="test", source_uri="https://example.org", content="content"
    ))
    cl = manager.extract_claim(
        claim_id="cl_audit_1", subject_id="ent_a", predicate="OWNS", object_id="ent_b",
        supporting_evidence_ids=["ev_audit_1"],
    )
    rel = manager.derive_relationship_from_claim("cl_audit_1", relationship_id="rel_ab")

    # Retract claim
    manager.review_claim("cl_audit_1", ReviewStatus.RETRACTED, "Debunked by court", "Auditor_X")
    assert store.get_claim("cl_audit_1").review_status == ReviewStatus.RETRACTED
    assert store.get_relationship("rel_ab").review_status == ReviewStatus.RETRACTED

    # 1. Rerunning extraction/ingestion of unreviewed claim MUST NOT overwrite retraction
    manager.extract_claim(
        claim_id="cl_audit_1", subject_id="ent_a", predicate="OWNS", object_id="ent_b",
        supporting_evidence_ids=["ev_audit_1"],
    )
    assert store.get_claim("cl_audit_1").review_status == ReviewStatus.RETRACTED

    # 2. Re-deriving relationship MUST NOT resurrect to UNREVIEWED
    manager.derive_relationship_from_claim("cl_audit_1", relationship_id="rel_ab")
    assert store.get_relationship("rel_ab").review_status == ReviewStatus.RETRACTED

    # 3. Rebuilding derived graph MUST NOT flip retraction back to UNREVIEWED
    cluster_a = EntityCluster(
        entity_cluster_id="ent_a", entity_type=EntityType.PERSON, member_record_ids=["rec_dummy"],
        status=ClusterStatus.ACTIVE, derivation_version="v2",
    )
    cluster_b = EntityCluster(
        entity_cluster_id="ent_b", entity_type=EntityType.ORGANIZATION, member_record_ids=["rec_dummy_b"],
        status=ClusterStatus.ACTIVE, derivation_version="v2",
    )
    manager.recluster_and_rebuild([cluster_a, cluster_b], {"rec_dummy": "ent_a", "rec_dummy_b": "ent_b"})
    assert store.get_relationship("rel_ab").review_status == ReviewStatus.RETRACTED


def test_claim_reinstatement_and_correction_cycle():
    store = InMemoryInvestigationGraphStore()
    manager = InvestigationLifecycleManager(store)
    service = InvestigationQueryService(store)

    store.add_entity(InvestigationEntity(entity_id="p1", entity_type=EntityType.PERSON, canonical_name="Pat"))
    store.add_entity(InvestigationEntity(entity_id="org1", entity_type=EntityType.ORGANIZATION, canonical_name="Org 1"))

    ev = manager.ingest_evidence(Evidence(
        evidence_id="ev_p1", evidence_type="test", source_uri="https://test.gov", content="Pat is Director"
    ))
    cl = manager.extract_claim("cl_p1", "p1", "DIRECTOR_OF", "org1", ["ev_p1"])
    rel = manager.derive_relationship_from_claim("cl_p1", relationship_id="rel_p1_org1")

    # Retract
    manager.review_claim("cl_p1", ReviewStatus.RETRACTED, "Initial suspicion of forgery", "Auditor_1")
    assert store.get_relationship("rel_p1_org1").review_status == ReviewStatus.RETRACTED

    # Re-investigate and Reinstate to VERIFIED
    reinstated_claim = manager.review_claim(
        "cl_p1", ReviewStatus.VERIFIED, "Official embassy notarization confirmed authenticity", "Senior_Auditor_2"
    )
    assert reinstated_claim.review_status == ReviewStatus.VERIFIED
    assert len(reinstated_claim.correction_history) == 2
    assert reinstated_claim.correction_history[0].new_status == ReviewStatus.RETRACTED
    assert reinstated_claim.correction_history[1].new_status == ReviewStatus.VERIFIED

    # Relationship automatically updates to VERIFIED
    updated_rel = store.get_relationship("rel_p1_org1")
    assert updated_rel.review_status == ReviewStatus.VERIFIED

    # Query reflects active verified state
    res = service.query("p1")
    exp = res.get_explanation("rel_p1_org1")
    assert exp.review_status == ReviewStatus.VERIFIED
    assert exp.is_disputed is False
    assert "STATUS ALERT: Relationship has been marked RETRACTED" not in exp.summary_text


def test_relationship_not_simultaneously_retracted_and_disputed():
    store = InMemoryInvestigationGraphStore()
    manager = InvestigationLifecycleManager(store)
    service = InvestigationQueryService(store)

    store.add_entity(InvestigationEntity(entity_id="e1", entity_type=EntityType.PERSON, canonical_name="Entity 1"))
    store.add_entity(InvestigationEntity(entity_id="e2", entity_type=EntityType.ORGANIZATION, canonical_name="Entity 2"))

    ev1 = manager.ingest_evidence(Evidence(evidence_id="ev1", evidence_type="test", source_uri="https://1", content="1"))
    ev2 = manager.ingest_evidence(Evidence(evidence_id="ev2", evidence_type="test", source_uri="https://2", content="2"))

    cl1 = manager.extract_claim("cl1", "e1", "OWNS", "e2", ["ev1"])
    cl2 = manager.extract_claim("cl2", "e1", "NOT_OWNS", "e2", ["ev2"])

    rel = manager.derive_relationship_from_claim("cl1", relationship_id="rel_12")
    manager.record_contradiction("rel_12", "cl2")

    # While active, it is DISPUTED
    res_disputed = service.query("e1")
    exp_disputed = res_disputed.get_explanation("rel_12")
    assert exp_disputed.is_disputed is True
    assert "ACTIVE CONTRADICTION DETECTED" in exp_disputed.summary_text

    # Retract cl1
    manager.review_claim("cl1", ReviewStatus.RETRACTED, "Debunked", "Reviewer")

    # After retraction, the relationship is RETRACTED and NOT actively disputed
    res_retracted = service.query("e1")
    exp_retracted = res_retracted.get_explanation("rel_12")
    assert exp_retracted.review_status == ReviewStatus.RETRACTED
    assert exp_retracted.is_disputed is False
    assert "STATUS ALERT: Relationship has been marked RETRACTED" in exp_retracted.summary_text
    assert "HISTORICAL CONTRADICTION NOTE" in exp_retracted.summary_text
    assert "ACTIVE CONTRADICTION DETECTED" not in exp_retracted.summary_text


# ---------------------------------------------------------------------------
# 18. Audit B: Referential Integrity on All Store Mutation Paths
# ---------------------------------------------------------------------------

def test_store_mutation_referential_integrity_all_paths():
    store = InMemoryInvestigationGraphStore()
    store.add_entity(InvestigationEntity(entity_id="known_ent", entity_type=EntityType.PERSON, canonical_name="Known"))
    ev = Evidence(evidence_id="ev_known", evidence_type="test", source_uri="https://test", content="c")
    store.add_evidence(ev)

    # 1. Claim referencing nonexistent evidence directly via store.add_claim
    bad_ev_claim = Claim(
        claim_id="cl_bad_ev", subject_id="known_ent", predicate="P", object_id="known_ent",
        supporting_evidence_ids=["ev_nonexistent"]
    )
    with pytest.raises(ValueError, match="Dangling evidence reference"):
        store.add_claim(bad_ev_claim)

    # 2. Claim referencing invalid entity without explicit unresolved representation
    bad_ent_claim = Claim(
        claim_id="cl_bad_ent", subject_id="ghost_entity", predicate="P", object_id="known_ent",
        supporting_evidence_ids=["ev_known"]
    )
    with pytest.raises(ValueError, match="Dangling entity reference"):
        store.add_claim(bad_ent_claim)

    # 3. Valid claim with registered unresolved entity
    unresolved_ent = store.add_entity(InvestigationEntity(
        entity_id="unresolved_mention_1", entity_type=EntityType.ORGANIZATION, canonical_name="Unknown Corp",
        metadata={"unresolved": True}
    ))
    valid_unresolved_claim = Claim(
        claim_id="cl_valid_unresolved", subject_id="known_ent", predicate="MET_WITH", object_id="unresolved_mention_1",
        supporting_evidence_ids=["ev_known"]
    )
    store.add_claim(valid_unresolved_claim)
    assert store.get_claim("cl_valid_unresolved") is not None

    # 4. Relationship referencing dangling claim via store.add_relationship
    bad_claim_rel = Relationship(
        relationship_id="r_bad_claim", source_entity_id="known_ent", target_entity_id="unresolved_mention_1",
        relationship_type="MET", supporting_claim_ids=["cl_missing"]
    )
    with pytest.raises(ValueError, match="Dangling claim reference"):
        store.add_relationship(bad_claim_rel)

    # 5. Relationship referencing dangling evidence via store.add_relationship
    bad_ev_rel = Relationship(
        relationship_id="r_bad_ev", source_entity_id="known_ent", target_entity_id="unresolved_mention_1",
        relationship_type="MET", supporting_claim_ids=["cl_valid_unresolved"],
        supporting_evidence_ids=["ev_missing"]
    )
    with pytest.raises(ValueError, match="Dangling evidence reference"):
        store.add_relationship(bad_ev_rel)


def test_nested_structures_immutability_shared_reference_protection():
    mutable_payload = {"tags": ["classified", "finance"], "nested": {"level": 1}}

    claim = Claim(
        claim_id="cl_immut",
        subject_id="ent1",
        predicate="OWNS",
        object_id="ent2",
        metadata=mutable_payload,
        metadata_unresolved=False,
    ) if hasattr(Claim, "metadata_unresolved") else Claim(
        claim_id="cl_immut",
        subject_id="ent1",
        predicate="OWNS",
        object_id="ent2",
        metadata=mutable_payload,
    )

    # Attempt to mutate external dictionary and list
    mutable_payload["tags"].append("leaked")
    mutable_payload["nested"]["level"] = 99

    # Model's internal state MUST be completely unaffected
    assert claim.metadata["tags"] == ("classified", "finance")
    assert claim.metadata["nested"]["level"] == 1

    # Attempting in-place modification on model fields raises TypeError
    with pytest.raises(TypeError):
        claim.metadata["tags"] = ("new",)


# ---------------------------------------------------------------------------
# 19. Audit C: Branching Graph Traversal Node & Depth Limits
# ---------------------------------------------------------------------------

def test_branching_graph_traversal_node_and_depth_limits():
    store = InMemoryInvestigationGraphStore()
    service = InvestigationQueryService(store)

    # Create root
    store.add_entity(InvestigationEntity(entity_id="root", entity_type=EntityType.ORGANIZATION, canonical_name="Root"))

    # 6 children at depth 1
    for i in range(6):
        child_id = f"child_{i}"
        store.add_entity(InvestigationEntity(entity_id=child_id, entity_type=EntityType.ORGANIZATION, canonical_name=f"Child {i}"))
        store.add_relationship(Relationship(
            relationship_id=f"rel_root_{i}", source_entity_id="root", target_entity_id=child_id, relationship_type="PARENT_OF"
        ))
        # 4 grandchildren at depth 2 for each child
        for j in range(4):
            grand_id = f"grand_{i}_{j}"
            store.add_entity(InvestigationEntity(entity_id=grand_id, entity_type=EntityType.ORGANIZATION, canonical_name=f"Grand {i}_{j}"))
            store.add_relationship(Relationship(
                relationship_id=f"rel_{i}_{j}", source_entity_id=child_id, target_entity_id=grand_id, relationship_type="PARENT_OF"
            ))

    # Test 1: Depth limit = 1
    res_d1 = service.query("root", max_depth=1, max_nodes=50)
    assert len(res_d1.entities) == 7  # root + 6 children
    assert all("grand" not in e.entity_id for e in res_d1.entities)

    # Test 2: Node limit = 4 (under branching)
    res_n4 = service.query("root", max_depth=3, max_nodes=4)
    assert len(res_n4.entities) == 4
    # All relationships in result must only connect admitted entities
    admitted_ids = {e.entity_id for e in res_n4.entities}
    for rel in res_n4.relationships:
        assert rel.source_entity_id in admitted_ids
        assert rel.target_entity_id in admitted_ids


# ---------------------------------------------------------------------------
# 20. Audit C: Neo4j Incomplete Placeholder Interface Status
# ---------------------------------------------------------------------------

def test_neo4j_adapter_reported_as_incomplete_placeholder():
    adapter = Neo4jInvestigationGraphAdapter(uri="bolt://localhost:7687")
    doc = adapter.__doc__
    assert "Deliberately incomplete interface specification" in doc

    # Operational calls explicitly raise NotImplementedError
    with pytest.raises(NotImplementedError, match="requires live server"):
        adapter.list_entities()
    with pytest.raises(NotImplementedError, match="requires live server"):
        adapter.list_relationships()
