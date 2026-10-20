"""
Adversarial and Comprehensive Regression Tests for Milestone 15:
Cross-Document Entity Resolution, Evidence-Grounded Investigation, Reversibility, and Persistence.
"""

import pytest
import tempfile
import os
import json
from datetime import datetime, timezone

from src.core.models import (
    EntityType,
    DecisionType,
    ReviewStatus,
    RelationshipEpistemicTier,
    InvestigationEntity,
    Claim,
    Evidence,
    Relationship,
)
from src.core.investigation_graph import InMemoryInvestigationGraphStore
from src.core.investigation_lifecycle import InvestigationLifecycleManager
from src.core.investigation_sqlite import SQLiteInvestigationStore
from src.core.cross_document_resolver import (
    CrossDocumentEntityResolver,
    EntityMergeProposal,
    CrossDocumentDecision,
)
from src.core.investigation_service import (
    InvestigationOrchestrator,
    InvestigationStatus,
    DocumentProcessingStatus,
)
from src.core.ner import EntityMention


# =============================================================================
# 1. Entity Resolution: Adversarial and Ambiguity Test Cases
# =============================================================================

class TestCrossDocumentEntityResolution:
    """Test suite covering candidate generation, conservative pairwise decisions, and constraints."""

    def test_same_person_spelling_variations_cross_document(self):
        """Cross-document person match with slight spelling variation and shared context."""
        resolver = CrossDocumentEntityResolver(name_exact_threshold=0.95, name_high_threshold=0.85)

        doc1 = "Dr. Katherine Johnson was appointed as senior flight specialist at NASA Langley."
        doc2 = "Katherine Coleman Johnson verified orbital trajectory equations at NASA yesterday."

        resolver.ingest_document("doc1", doc1)
        resolver.ingest_document("doc2", doc2)

        m1 = EntityMention(
            mention_id="m1_kj",
            document_id="doc1",
            text="Katherine Johnson",
            entity_type=EntityType.PERSON,
            start_char=4,
            end_char=21,
        )
        m2 = EntityMention(
            mention_id="m2_kcj",
            document_id="doc2",
            text="Katherine Coleman Johnson",
            entity_type=EntityType.PERSON,
            start_char=0,
            end_char=25,
        )

        resolver.ingest_mention(m1)
        resolver.ingest_mention(m2)

        res = resolver.resolve_cross_document_mentions()
        assert len(res.decisions) == 1
        dec = res.decisions[0]
        # Should match due to shared 'NASA' org token and high substring/token overlap
        assert dec.decision in (DecisionType.MATCH, DecisionType.REVIEW)
        assert dec.is_cross_document is True
        assert "NASA" in " ".join(dec.positive_evidence)

    def test_different_people_with_identical_names(self):
        """Homonym test: identical names with conflicting age/role attributes must not auto-merge."""
        resolver = CrossDocumentEntityResolver()

        doc1 = "Dr. Michael Brown, a 64-year-old neurosurgeon at City Hospital, delivered the keynote."
        doc2 = "Michael Brown, a 22-year-old college undergraduate intern, joined the software lab."

        resolver.ingest_document("doc1", doc1)
        resolver.ingest_document("doc2", doc2)

        m1 = EntityMention(
            mention_id="m1_mb",
            document_id="doc1",
            text="Michael Brown",
            entity_type=EntityType.PERSON,
            start_char=4,
            end_char=17,
        )
        m2 = EntityMention(
            mention_id="m2_mb",
            document_id="doc2",
            text="Michael Brown",
            entity_type=EntityType.PERSON,
            start_char=0,
            end_char=13,
        )

        resolver.ingest_mention(m1)
        resolver.ingest_mention(m2)

        res = resolver.resolve_cross_document_mentions()
        assert len(res.decisions) == 1
        dec = res.decisions[0]
        # Because context has distinct roles/organizations, conservative policy must NOT force an automatic MATCH
        assert dec.decision == DecisionType.REVIEW
        assert dec.decision != DecisionType.MATCH
        assert any("conflict" in e.lower() or "context" in e.lower() or "missing" in e.lower()
                   for e in (list(dec.negative_evidence) + list(dec.missing_information) + [dec.explanation]))

    def test_similar_organization_names_distinct_entities(self):
        """Similar organization names referring to distinct companies."""
        resolver = CrossDocumentEntityResolver()

        doc1 = "Apex Logistics International expanded freight trucking routes across Ohio."
        doc2 = "Apex Cyber Security Systems released a new intrusion detection firewall patch."

        resolver.ingest_document("doc1", doc1)
        resolver.ingest_document("doc2", doc2)

        m1 = EntityMention(
            mention_id="m1_apex_log",
            document_id="doc1",
            text="Apex Logistics International",
            entity_type=EntityType.ORGANIZATION,
            start_char=0,
            end_char=28,
        )
        m2 = EntityMention(
            mention_id="m2_apex_sec",
            document_id="doc2",
            text="Apex Cyber Security Systems",
            entity_type=EntityType.ORGANIZATION,
            start_char=0,
            end_char=27,
        )

        resolver.ingest_mention(m1)
        resolver.ingest_mention(m2)

        res = resolver.resolve_cross_document_mentions()
        if res.decisions:
            dec = res.decisions[0]
            assert dec.decision != DecisionType.MATCH

    def test_missing_contextual_attributes_routes_to_review(self):
        """A mention with sparse or missing attributes must not be assumed to agree; routes to REVIEW."""
        resolver = CrossDocumentEntityResolver()

        doc1 = "John Smith was seen entering the federal courthouse yesterday morning."
        doc2 = "The committee questioned John Smith regarding confidential treasury expenditures."

        resolver.ingest_document("doc1", doc1)
        resolver.ingest_document("doc2", doc2)

        m1 = EntityMention(
            mention_id="m1_js",
            document_id="doc1",
            text="John Smith",
            entity_type=EntityType.PERSON,
            start_char=0,
            end_char=10,
        )
        m2 = EntityMention(
            mention_id="m2_js",
            document_id="doc2",
            text="John Smith",
            entity_type=EntityType.PERSON,
            start_char=25,
            end_char=35,
        )

        resolver.ingest_mention(m1)
        resolver.ingest_mention(m2)

        res = resolver.resolve_cross_document_mentions()
        assert len(res.decisions) == 1
        dec = res.decisions[0]
        # Conservative matching: High name similarity alone without corroboration -> REVIEW
        assert dec.decision == DecisionType.REVIEW
        assert dec.decision != DecisionType.MATCH

    def test_conflicting_reliable_identifiers_block_merge(self):
        """Entities with conflicting reliable identifiers must produce explicit NON_MATCH."""
        resolver = CrossDocumentEntityResolver()

        doc1 = "Passport US-987654 belongs to Robert Green of California."
        doc2 = "Passport UK-123456 was presented by Robert Green in London."

        resolver.ingest_document("doc1", doc1)
        resolver.ingest_document("doc2", doc2)

        m1 = EntityMention(
            mention_id="m1_rg",
            document_id="doc1",
            text="Robert Green",
            entity_type=EntityType.PERSON,
            start_char=30,
            end_char=42,
        )
        m2 = EntityMention(
            mention_id="m2_rg",
            document_id="doc2",
            text="Robert Green",
            entity_type=EntityType.PERSON,
            start_char=36,
            end_char=48,
        )

        resolver.ingest_mention(m1)
        resolver.ingest_mention(m2)

        # Inject reliable conflicting identifiers in records
        resolver.records["m1_rg"].identifiers["passport"] = "US-987654"
        resolver.records["m2_rg"].identifiers["passport"] = "UK-123456"

        res = resolver.resolve_cross_document_mentions()
        assert len(res.decisions) == 1
        dec = res.decisions[0]
        assert dec.decision == DecisionType.NON_MATCH
        assert any("conflicting reliable identifier" in c.lower() for c in dec.hard_constraints)

    def test_explicit_non_match_constraints_persist_and_block(self):
        """Explicit non-match constraint must block merging even if name similarity is 1.0."""
        resolver = CrossDocumentEntityResolver()
        resolver.add_explicit_non_match("m1_alex", "m2_alex", reason="Verified different twin brothers")

        doc1 = "Alex Vance inspected the perimeter."
        doc2 = "Alex Vance checked the communications terminal."

        resolver.ingest_document("doc1", doc1)
        resolver.ingest_document("doc2", doc2)

        m1 = EntityMention(
            mention_id="m1_alex",
            document_id="doc1",
            text="Alex Vance",
            entity_type=EntityType.PERSON,
            start_char=0,
            end_char=10,
        )
        m2 = EntityMention(
            mention_id="m2_alex",
            document_id="doc2",
            text="Alex Vance",
            entity_type=EntityType.PERSON,
            start_char=0,
            end_char=10,
        )

        resolver.ingest_mention(m1)
        resolver.ingest_mention(m2)

        res = resolver.resolve_cross_document_mentions()
        assert len(res.decisions) == 1
        dec = res.decisions[0]
        assert dec.decision == DecisionType.NON_MATCH
        assert any("explicit non-match" in c.lower() for c in dec.hard_constraints)

    def test_transitive_merge_cascade_prevention(self):
        """
        Transitive cascade guard:
        If A matches B, and B matches C, but A has a NON-MATCH constraint with C,
        the clusterer must NOT merge A, B, and C into one cluster.
        """
        resolver = CrossDocumentEntityResolver()

        # Constraints: A and C are explicitly distinct entities
        resolver.add_explicit_non_match("rec_a", "rec_c", reason="Known different individuals")

        # Set up manual records
        from src.core.models import Record
        rec_a = Record(record_id="rec_a", source_id="doc1", raw_name="Samuel Jackson", entity_type=EntityType.PERSON)
        rec_b = Record(record_id="rec_b", source_id="doc2", raw_name="Sam Jackson", entity_type=EntityType.PERSON)
        rec_c = Record(record_id="rec_c", source_id="doc3", raw_name="Samuel Jackson", entity_type=EntityType.PERSON)

        resolver.records["rec_a"] = rec_a
        resolver.records["rec_b"] = rec_b
        resolver.records["rec_c"] = rec_c

        # Cluster with constraint aware clusterer
        from src.core.models import MatchDecision
        dec_ab = MatchDecision(candidate_pair_id="rec_a::rec_b", decision=DecisionType.MATCH, score=0.95, threshold=0.85, model_version="v1")
        dec_bc = MatchDecision(candidate_pair_id="rec_b::rec_c", decision=DecisionType.MATCH, score=0.95, threshold=0.85, model_version="v1")
        dec_ac_non = MatchDecision(candidate_pair_id="rec_a::rec_c", decision=DecisionType.NON_MATCH, score=0.1, threshold=0.85, model_version="v1")

        result = resolver.clusterer.cluster(
            records=[rec_a, rec_b, rec_c],
            decisions=[dec_ab, dec_bc, dec_ac_non],
        )

        # rec_a and rec_c must NOT be in the same cluster
        assert result.record_to_cluster["rec_a"] != result.record_to_cluster["rec_c"]



# =============================================================================
# 2. Reversibility: Merging, Splitting, and Rollback
# =============================================================================

class TestReversibilityAndLifecycle:
    """Validate merge reversal, entity splitting, and review preservation."""

    def test_entity_merge_split_and_reversal(self):
        """Test merging two entities, splitting one, and reversing a merge."""
        store = InMemoryInvestigationGraphStore()
        resolver = CrossDocumentEntityResolver()

        # Register initial separate entities
        e1 = InvestigationEntity(
            entity_id="ent_1",
            canonical_name="Robert Vance",
            entity_type=EntityType.PERSON,
            member_record_ids=["rec_vance_1"],
        )
        e2 = InvestigationEntity(
            entity_id="ent_2",
            canonical_name="Bob Vance",
            entity_type=EntityType.PERSON,
            member_record_ids=["rec_vance_2"],
        )
        store.add_entity(e1)
        store.add_entity(e2)

        # Add an evidence and claim referencing ent_1 and ent_2
        ev = Evidence(evidence_id="ev_1", evidence_type="test", source_id="doc_vance", content="Vance refrigeration owner", text_span="owner", char_offsets=(0, 5))
        store.add_evidence(ev)
        cl = Claim(claim_id="cl_1", subject_id="ent_1", predicate="FOUNDER_OF", object_id="ent_2", supporting_evidence_ids=["ev_1"])
        store.add_claim(cl)
        rel = Relationship(relationship_id="rel_1", source_entity_id="ent_1", target_entity_id="ent_2", relationship_type="FOUNDER_OF", supporting_claim_ids=["cl_1"])
        store.add_relationship(rel)

        # 1. Propose and Apply Merge
        proposal = EntityMergeProposal(
            proposal_id="prop_vance",
            entity_id_a="ent_1",
            entity_id_b="ent_2",
            canonical_name_a="Robert Vance",
            canonical_name_b="Bob Vance",
            decision=DecisionType.MATCH,
            confidence_score=0.92,
            explanation="Verified identical person alias",
            member_records=["rec_vance_1", "rec_vance_2"],
        )

        merged = resolver.apply_merge_proposal(store, proposal, reviewer="LeadAnalyst", rationale="Confirmed same refrigeration CEO")
        assert merged.entity_id == "ent_1"
        assert set(merged.member_record_ids) == {"rec_vance_1", "rec_vance_2"}
        assert store.has_entity("ent_1")
        assert not store.has_entity("ent_2")

        # 2. Reverse the merge
        restored = resolver.reverse_merge(store, merged_entity_id="ent_1", reviewer="LeadAnalyst", rationale="Analyst corrected error: father and son")
        assert len(restored) == 2
        restored_ids = {e.entity_id for e in restored}
        assert "ent_1" in restored_ids
        assert "ent_2" in restored_ids
        assert store.has_entity("ent_1")
        assert store.has_entity("ent_2")

        # Verify non-match constraint was injected
        canon_pair = tuple(sorted(["ent_1", "ent_2"]))
        assert canon_pair in resolver.explicit_non_matches

    def test_entity_splitting_preserves_records_and_constrains(self):
        """Test splitting an entity into two distinct entities with non-match constraint."""
        store = InMemoryInvestigationGraphStore()
        resolver = CrossDocumentEntityResolver()

        composite_ent = InvestigationEntity(
            entity_id="ent_composite",
            canonical_name="David Miller",
            entity_type=EntityType.PERSON,
            member_record_ids=["rec_dm_chicago", "rec_dm_london"],
        )
        store.add_entity(composite_ent)

        ent_a, ent_b = resolver.split_entity(
            store=store,
            entity_id="ent_composite",
            split_member_records=["rec_dm_london"],
            reviewer="SeniorInvestigator",
            rationale="Discovered distinct birth dates: separating Chicago vs London David Millers",
        )

        assert ent_a.entity_id == "ent_composite"
        assert list(ent_a.member_record_ids) == ["rec_dm_chicago"]
        assert "rec_dm_london" in ent_b.member_record_ids
        assert store.has_entity("ent_composite")
        assert store.has_entity(ent_b.entity_id)

        # Verify non-match constraint
        canon_pair = tuple(sorted([ent_a.entity_id, ent_b.entity_id]))
        assert canon_pair in resolver.explicit_non_matches


# =============================================================================
# 3. Evidence-Grounded Relationships and Epistemic Tiers
# =============================================================================

class TestEvidenceGroundedRelationships:
    """Validate assertion vs denial vs quote, duplicate suppression, and contradiction handling."""

    def test_positive_vs_negative_assertions_epistemic_tiers(self):
        """Distinguish explicitly between source asserting vs source denying a relationship."""
        store = InMemoryInvestigationGraphStore()
        lifecycle = InvestigationLifecycleManager(store)

        store.add_entity(InvestigationEntity(entity_id="e_corp", canonical_name="Acorn Global", entity_type=EntityType.ORGANIZATION))
        store.add_entity(InvestigationEntity(entity_id="e_person", canonical_name="Elena Rostova", entity_type=EntityType.PERSON))

        # Positive claim
        ev_pos = Evidence(evidence_id="ev_pos", evidence_type="news", source_id="doc_news", text_span="Elena Rostova was appointed Director", polarity="positive")
        store.add_evidence(ev_pos)
        cl_pos = Claim(claim_id="cl_pos", subject_id="e_person", predicate="DIRECTOR_OF", object_id="e_corp", supporting_evidence_ids=["ev_pos"])
        store.add_claim(cl_pos)

        rel_pos = lifecycle.derive_relationship_from_claim("cl_pos", relationship_id="rel_pos_dir")
        assert rel_pos.epistemic_tier == RelationshipEpistemicTier.ASSERTED
        assert rel_pos.polarity == "POSITIVE"

        # Negative denial claim
        ev_neg = Evidence(evidence_id="ev_neg", evidence_type="press_release", source_id="doc_pr", text_span="Elena Rostova is NOT a director", polarity="negative")
        store.add_evidence(ev_neg)
        cl_neg = Claim(
            claim_id="cl_neg",
            subject_id="e_person",
            predicate="NOT_DIRECTOR_OF",
            object_id="e_corp",
            qualifiers={"negated": True, "polarity": "NEGATIVE"},
            supporting_evidence_ids=["ev_neg"],
        )
        store.add_claim(cl_neg)

        rel_neg = lifecycle.derive_relationship_from_claim("cl_neg", relationship_id="rel_neg_dir")
        assert rel_neg.epistemic_tier == RelationshipEpistemicTier.DENIED
        assert rel_neg.polarity == "NEGATIVE"

    def test_quoted_statements_and_allegations(self):
        """Quoted statements or allegations are assigned the QUOTED epistemic tier."""
        store = InMemoryInvestigationGraphStore()
        lifecycle = InvestigationLifecycleManager(store)

        store.add_entity(InvestigationEntity(entity_id="e_p1", canonical_name="Spokesperson", entity_type=EntityType.PERSON))
        store.add_entity(InvestigationEntity(entity_id="e_p2", canonical_name="Suspect", entity_type=EntityType.PERSON))

        ev_quote = Evidence(evidence_id="ev_quote", evidence_type="interview", source_id="doc_interview", text_span="He alleged that Suspect took the bribe")
        store.add_evidence(ev_quote)
        cl_quote = Claim(
            claim_id="cl_quote",
            subject_id="e_p1",
            predicate="ACCUSES",
            object_id="e_p2",
            qualifiers={"is_allegation": True, "quoted_speaker": "Spokesperson"},
            supporting_evidence_ids=["ev_quote"],
        )
        store.add_claim(cl_quote)

        rel_quote = lifecycle.derive_relationship_from_claim("cl_quote", relationship_id="rel_quote_test")
        assert rel_quote.epistemic_tier == RelationshipEpistemicTier.QUOTED
        assert rel_quote.attribution == "Spokesperson"

    def test_duplicate_evidence_does_not_inflate_corroboration(self):
        """Repeated identical statements across documents do not artificially increase independent corroboration."""
        store = InMemoryInvestigationGraphStore()
        lifecycle = InvestigationLifecycleManager(store)

        store.add_entity(InvestigationEntity(entity_id="ent_a", canonical_name="Alice", entity_type=EntityType.PERSON))
        store.add_entity(InvestigationEntity(entity_id="ent_b", canonical_name="Beta Org", entity_type=EntityType.ORGANIZATION))

        # Statement text is identical in doc 1 and doc 2
        same_statement = "Alice manages Beta Org operations daily."

        ev1 = Evidence(evidence_id="ev_doc1", evidence_type="wire", source_id="doc_wire_1", content=same_statement, text_span=same_statement)
        ev2 = Evidence(evidence_id="ev_doc2", evidence_type="wire", source_id="doc_wire_2", content=same_statement, text_span=same_statement)
        store.add_evidence(ev1)
        store.add_evidence(ev2)

        cl1 = Claim(claim_id="cl_1", subject_id="ent_a", predicate="MANAGES", object_id="ent_b", supporting_evidence_ids=["ev_doc1"])
        cl2 = Claim(claim_id="cl_2", subject_id="ent_a", predicate="MANAGES", object_id="ent_b", supporting_evidence_ids=["ev_doc2"])
        store.add_claim(cl1)
        store.add_claim(cl2)

        rel = lifecycle.derive_relationship_from_claim("cl_1", relationship_id="rel_manages")
        assert len(rel.unique_source_hashes) == 1
        assert rel.duplicate_evidence_count == 0

        # Now merge identical statement from doc 2 into the relationship
        updated_rel = lifecycle.derive_relationship_from_claim("cl_2", relationship_id="rel_manages")
        # Unique source statements must STILL be 1 (no independent corroboration inflation)
        assert len(updated_rel.unique_source_hashes) == 1
        # Duplicate evidence counter is incremented
        assert updated_rel.duplicate_evidence_count == 1

    def test_contradictory_polarity_creates_disputed_relationship(self):
        """Merging a positive assertion with a negative denial creates a DISPUTED relationship."""
        store = InMemoryInvestigationGraphStore()
        lifecycle = InvestigationLifecycleManager(store)

        store.add_entity(InvestigationEntity(entity_id="ent_x", canonical_name="Xavier", entity_type=EntityType.PERSON))
        store.add_entity(InvestigationEntity(entity_id="ent_y", canonical_name="Ypsilon Ltd", entity_type=EntityType.ORGANIZATION))

        ev_pos = Evidence(evidence_id="ev_pos_1", evidence_type="report", source_id="doc_rep_1", text_span="Xavier owns Ypsilon Ltd")
        ev_neg = Evidence(evidence_id="ev_neg_1", evidence_type="report", source_id="doc_rep_2", text_span="Xavier does NOT own Ypsilon Ltd", polarity="negative")
        store.add_evidence(ev_pos)
        store.add_evidence(ev_neg)

        cl_pos = Claim(claim_id="cl_own_pos", subject_id="ent_x", predicate="OWNS", object_id="ent_y", supporting_evidence_ids=["ev_pos_1"])
        cl_neg = Claim(claim_id="cl_own_neg", subject_id="ent_x", predicate="OWNS", object_id="ent_y", qualifiers={"negated": True, "polarity": "NEGATIVE"}, supporting_evidence_ids=["ev_neg_1"])
        store.add_claim(cl_pos)
        store.add_claim(cl_neg)

        rel = lifecycle.derive_relationship_from_claim("cl_own_pos", relationship_id="rel_owns_xy")
        assert rel.review_status == ReviewStatus.UNREVIEWED

        # Merge contradictory claim into the relationship
        disputed_rel = lifecycle.derive_relationship_from_claim("cl_own_neg", relationship_id="rel_owns_xy")
        assert disputed_rel.review_status == ReviewStatus.DISPUTED
        assert disputed_rel.epistemic_tier == RelationshipEpistemicTier.DISPUTED
        assert "cl_own_neg" in disputed_rel.contradicting_claim_ids


# =============================================================================
# 4. End-to-End Orchestrator, Reporting, and Isolation
# =============================================================================

class TestInvestigationOrchestratorMilestone15:
    """Test full multi-document investigation workflow with reporting and isolation."""

    def test_multi_document_investigation_workflow(self):
        """Ingest 2 documents, run cross-doc ER, generate report with provenance."""
        orchestrator = InvestigationOrchestrator(default_backend_mode="rule")
        orchestrator.create_investigation("inv_test_m15", "Cross-document test investigation")

        doc1_text = "Director Marcus Stone authorized financial transfers at Nexus Capital in New York."
        doc2_text = "Marcus Stone attended the regulatory summit as representative of Nexus Capital."

        orchestrator.process_document("inv_test_m15", doc1_text.encode("utf-8"), "doc_transfers.txt")
        orchestrator.process_document("inv_test_m15", doc2_text.encode("utf-8"), "doc_summit.txt")

        # Run cross-document entity resolution
        res = orchestrator.resolve_cross_document_entities("inv_test_m15", candidate_similarity_threshold=0.55, auto_apply_matches=True)
        assert res is not None

        # Generate report
        report = orchestrator.generate_report("inv_test_m15")
        assert report.report_schema_version == "v1.5.0"
        assert len(report.documents) == 2
        assert len(report.entities) >= 1

        md = report.to_markdown_report()
        assert "# Sherlock AI Investigation Report" in md
        assert "Marcus Stone" in md
        assert "Reproducibility Summary" in md

    def test_investigation_isolation(self):
        """Verify strict isolation between two parallel investigations."""
        orchestrator = InvestigationOrchestrator(default_backend_mode="rule")
        orchestrator.create_investigation("inv_alpha", "Alpha investigation")
        orchestrator.create_investigation("inv_beta", "Beta investigation")

        doc_alpha = "Agent Sarah Connor accessed warehouse 42 in Sector 7."
        doc_beta = "Agent Sarah Connor registered at Cyberdyne headquarters in Sector 9."

        orchestrator.process_document("inv_alpha", doc_alpha.encode("utf-8"), "alpha.txt")
        orchestrator.process_document("inv_beta", doc_beta.encode("utf-8"), "beta.txt")

        orchestrator.resolve_cross_document_entities("inv_alpha")
        orchestrator.resolve_cross_document_entities("inv_beta")

        session_alpha = orchestrator.get_investigation("inv_alpha")

        session_beta = orchestrator.get_investigation("inv_beta")

        alpha_docs = {d.source_name for d in session_alpha.document_records.values()}
        beta_docs = {d.source_name for d in session_beta.document_records.values()}

        assert alpha_docs == {"alpha.txt"}
        assert beta_docs == {"beta.txt"}
        assert session_alpha.store.list_entities() != []
        assert session_beta.store.list_entities() != []


# =============================================================================
# 5. SQLite Persistence and Recovery Hardening
# =============================================================================

class TestSQLitePersistenceMilestone15:
    """Verify durable persistence, entity split/merge sync, and reload survival."""

    def test_cross_document_clusters_survive_sqlite_reload(self):
        """Save investigation to SQLite, reopen store, and verify cross-document entities and relationships."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "m15_test.db")
            sqlite_store = SQLiteInvestigationStore(db_path=db_path)
            orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=sqlite_store)

            orchestrator.create_investigation("inv_durable", "Durable test")

            doc1 = "Victor Vance works for Vance Corporation."
            doc2 = "Victor Vance manages Vance Corporation."


            orchestrator.process_document("inv_durable", doc1.encode("utf-8"), "vance_1.txt")
            orchestrator.process_document("inv_durable", doc2.encode("utf-8"), "vance_2.txt")
            orchestrator.resolve_cross_document_entities("inv_durable", auto_apply_matches=True)

            # Record non-match constraint
            orchestrator.add_non_match_constraint("inv_durable", "ent_x", "ent_y", "Distinct entities", "Auditor")

            # Close connection
            sqlite_store.close()

            # Reopen new SQLite store and new orchestrator instance
            new_sqlite_store = SQLiteInvestigationStore(db_path=db_path)
            new_orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=new_sqlite_store)

            # Hydrate session from SQLite
            reopened_session = new_orchestrator.get_investigation("inv_durable")
            assert reopened_session is not None
            assert len(reopened_session.document_records) == 2
            assert len(reopened_session.store.list_entities()) >= 1
            assert len(reopened_session.store.list_claims()) >= 1

            new_sqlite_store.close()
