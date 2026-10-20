"""
Milestone 12 Comprehensive Test Suite:
End-to-End Investigation Engine Integration & Orchestration.

Tests:
1. Successful processing of a document end-to-end.
2. Multiple documents and cross-document entity references.
3. Stable IDs and idempotent re-ingestion (no duplicates, no review overwrites).
4. Source-span integrity and Unicode character offsets.
5. Missing evidence/entity references (prevention of dangling references).
6. No-candidate unresolved behavior (distinguishing UNRESOLVED from CONFIRMED_NON_MATCH).
7. Conflicting match decisions (ambiguity routing to REVIEW without forced merge).
8. Epistemic qualifiers: negation, allegations, and uncertainty.
9. Retraction and correction lifecycle (cascading to relationships, preserving audit history).
10. Cycle-safe graph traversal with depth and node bounding.
11. Partial processing failure visibility and recovery/retry.
12. Report determinism and complete provenance tracing.
13. Explicit verification that in-memory state does not claim durable persistence.
14. Immutability of raw ingested documents across pipeline executions.
"""

import hashlib
import json
import pytest
from datetime import datetime, timezone

from src.core.models import (
    EntityType,
    ReviewStatus,
    RelationshipEpistemicTier,
    InvestigationEntity,
    Record,
    Claim,
    Evidence,
    DecisionType,
)
from src.core.document_ingestion import (
    DocumentFormat,
    DocumentParsingError,
)
from src.core.ner import (
    EntityMention,
    DeterministicRuleNERExtractor,
)
from src.core.relation_extraction import (
    DeterministicRuleRelationExtractor,
)
from src.core.mention_entity_resolution import (
    MentionEntityResolver,
    MentionResolutionStatus,
)
from src.core.investigation_service import (
    InvestigationOrchestrator,
    InvestigationStatus,
    DocumentProcessingStatus,
    InvestigationReport,
)


@pytest.fixture
def orchestrator():
    """Fresh orchestrator fixture with default rule backend."""
    return InvestigationOrchestrator(default_backend_mode="rule")


class TestInvestigationOrchestrationEndToEnd:
    """Test suite covering the complete Milestone 12 investigation engine flow."""

    def test_single_document_successful_processing(self, orchestrator):
        """Test complete document ingestion -> NER -> RE -> Claim -> Relationship flow."""
        inv_id = "test_inv_single_doc"
        orchestrator.create_investigation(inv_id, description="Single document test")

        doc_text = "Dr. John Watson works for Sherlock Security.\nSherlock Security is located in London."
        record = orchestrator.process_document(
            investigation_id=inv_id,
            raw_content=doc_text.encode("utf-8"),
            source_name="memo_01.txt",
            source_uri="internal://test/memo_01.txt",
            derive_relationships=True,
        )

        assert record.status == DocumentProcessingStatus.COMPLETED
        assert record.char_count == len(doc_text)
        assert record.mention_count >= 3
        assert record.claim_count >= 2
        assert record.evidence_count >= 2

        claims = orchestrator.get_extracted_claims(inv_id)
        assert len(claims) >= 2
        for c in claims:
            # Epistemic discipline: Automated claims default to UNREVIEWED
            assert c.review_status == ReviewStatus.UNREVIEWED
            assert len(c.supporting_evidence_ids) >= 1

        summary = orchestrator.get_summary(inv_id)
        assert summary.completed_documents == 1
        assert summary.failed_documents == 0
        assert summary.status == InvestigationStatus.COMPLETED

    def test_multi_document_cross_references(self, orchestrator):
        """Test multi-document processing where entities resolve across documents."""
        inv_id = "test_inv_multi_doc"
        session = orchestrator.create_investigation(inv_id)

        # Pre-register canonical entities
        ent_watson = InvestigationEntity(
            entity_id="ent_watson_canonical",
            entity_type=EntityType.PERSON,
            canonical_name="Dr. John Watson",
            member_record_ids=["rec_watson"],
        )
        ent_sec = InvestigationEntity(
            entity_id="ent_sec_canonical",
            entity_type=EntityType.ORGANIZATION,
            canonical_name="Sherlock Security",
            member_record_ids=["rec_sec"],
        )
        orchestrator.register_known_entity(inv_id, ent_watson)
        orchestrator.register_known_entity(inv_id, ent_sec)

        # Register normalized mention variants in resolver
        session.resolver.add_known_record(Record(
            record_id="ent_watson_canonical",
            source_id="alias_reg",
            raw_name="John Watson",
            entity_type=EntityType.PERSON,
        ))
        session.resolver.add_known_record(Record(
            record_id="ent_sec_canonical",
            source_id="alias_reg",
            raw_name="Sherlock Security Ltd",
            entity_type=EntityType.ORGANIZATION,
        ))

        # Document 1 mentions "Sherlock Security"
        doc1_text = "Dr. John Watson works for Sherlock Security."
        orchestrator.process_document(
            inv_id, doc1_text.encode("utf-8"), source_name="doc1.txt", derive_relationships=True
        )

        # Document 2 mentions "Sherlock Security Ltd" (variant name)
        doc2_text = "Dr. John Watson works for Sherlock Security Ltd."
        orchestrator.process_document(
            inv_id, doc2_text.encode("utf-8"), source_name="doc2.txt", derive_relationships=True
        )

        # Query root entity: relationship should link both to same canonical endpoints
        res = orchestrator.query_entity(inv_id, "ent_watson_canonical")
        assert len(res.relationships) == 1
        rel = res.relationships[0]
        assert rel.source_entity_id == "ent_watson_canonical"
        assert rel.target_entity_id == "ent_sec_canonical"
        assert rel.relationship_type == "WORKS_FOR"
        # Multi-evidence grounding: supported by claims and evidence from both documents!
        assert len(rel.supporting_claim_ids) == 2
        assert len(rel.supporting_evidence_ids) == 2

    def test_idempotent_reingestion_no_duplicates(self, orchestrator):
        """Test that re-ingesting the exact same document does not duplicate data."""
        inv_id = "test_inv_idempotency"
        orchestrator.create_investigation(inv_id)

        content = b"Dr. John Watson works for Sherlock Security.\nSherlock Security is located in London."

        # First run
        rec1 = orchestrator.process_document(inv_id, content, source_name="doc.txt")
        assert rec1.status == DocumentProcessingStatus.COMPLETED

        claims_count_1 = len(orchestrator.get_extracted_claims(inv_id))
        rels_count_1 = len(orchestrator.get_extracted_relationships(inv_id))

        # Re-ingest identical content without force flag
        rec2 = orchestrator.process_document(inv_id, content, source_name="doc.txt", force_reprocess=False)
        assert rec2.status == DocumentProcessingStatus.SKIPPED_DUPLICATE
        assert rec2.metadata.get("idempotent_duplicate") is True

        claims_count_2 = len(orchestrator.get_extracted_claims(inv_id))
        rels_count_2 = len(orchestrator.get_extracted_relationships(inv_id))

        assert claims_count_1 == claims_count_2
        assert rels_count_1 == rels_count_2

    def test_idempotency_preserves_human_review(self, orchestrator):
        """Test that re-ingesting a document never overwrites a human review status."""
        inv_id = "test_inv_review_preservation"
        orchestrator.create_investigation(inv_id)

        content = b"The report alleges that Wayne Enterprises owns Globex Corporation."
        rec = orchestrator.process_document(inv_id, content, source_name="allegation.txt")
        assert rec.status == DocumentProcessingStatus.COMPLETED

        claims = orchestrator.get_extracted_claims(inv_id)
        owns_claim = next(c for c in claims if c.predicate == "OWNS")

        # Investigator reviews and retracts the claim
        orchestrator.review_claim(
            inv_id,
            claim_id=owns_claim.claim_id,
            new_status=ReviewStatus.RETRACTED,
            rationale="Corporate filings show no ownership.",
            reviewer="Senior_Auditor",
        )

        # Force re-ingest the same document
        rec_forced = orchestrator.process_document(
            inv_id, content, source_name="allegation.txt", force_reprocess=True
        )
        assert rec_forced.status == DocumentProcessingStatus.COMPLETED

        # Verify claim remains RETRACTED and was not reset to UNREVIEWED
        post_claims = orchestrator.get_extracted_claims(inv_id)
        post_owns_claim = next(c for c in post_claims if c.predicate == "OWNS")
        assert post_owns_claim.review_status == ReviewStatus.RETRACTED
        assert len(post_owns_claim.correction_history) >= 1

    def test_source_span_integrity_and_unicode_offsets(self, orchestrator):
        """Test that evidence text spans and character offsets strictly match source text."""
        inv_id = "test_inv_unicode"
        session = orchestrator.create_investigation(inv_id)

        # Text with Unicode accents and emojis/symbols
        text = "René François works for Sherlock Security.\nLocation: Zürich, 2024-03-15."
        raw_bytes = text.encode("utf-8")

        rec = orchestrator.process_document(inv_id, raw_bytes, source_name="unicode.txt")
        assert rec.status == DocumentProcessingStatus.COMPLETED

        # Check all evidence items
        ev_items = session.store.list_evidence()
        assert len(ev_items) >= 1
        for ev in ev_items:
            start, end = ev.char_offsets
            assert text[start:end] == ev.text_span
            assert ev.content_hash == hashlib.sha256(raw_bytes).hexdigest()

    def test_no_candidate_unresolved_behavior(self, orchestrator):
        """Test that entities with no candidate pairs remain explicitly UNRESOLVED, not NON_MATCH."""
        inv_id = "test_inv_unresolved_no_cands"
        session = orchestrator.create_investigation(inv_id)

        # Register a known entity of different type/name
        orchestrator.register_known_entity(
            inv_id,
            InvestigationEntity(
                entity_id="ent_existing_corp",
                entity_type=EntityType.ORGANIZATION,
                canonical_name="Cyberdyne Systems",
                member_record_ids=["rec_corp_01"],
            ),
        )

        # Document mentioning a completely unknown individual
        doc_text = "Marcus Vance was seen walking past the warehouse."
        orchestrator.process_document(inv_id, doc_text.encode("utf-8"), source_name="patrol.txt")

        unresolved = orchestrator.get_unresolved_mentions(inv_id)
        vance_mention = next((um for um in unresolved if "Marcus Vance" in um.surface_text), None)
        assert vance_mention is not None
        # Must be UNRESOLVED_NO_CANDIDATES, NOT CONFIRMED_NON_MATCH!
        assert vance_mention.resolution_status == MentionResolutionStatus.UNRESOLVED_NO_CANDIDATES
        assert vance_mention.decision_type is None
        assert vance_mention.is_resolved is False

    def test_conflicting_match_decisions_route_to_review(self, orchestrator):
        """Test that ambiguous matching across multiple known entities routes to REVIEW without forced merge."""
        inv_id = "test_inv_ambiguity"
        session = orchestrator.create_investigation(inv_id)

        # Register two competing known records with very similar names
        r1 = Record(
            record_id="rec_corp_a",
            source_id="src_1",
            raw_name="Apex Global Technologies",
            entity_type=EntityType.ORGANIZATION,
        )
        r2 = Record(
            record_id="rec_corp_b",
            source_id="src_2",
            raw_name="Apex Global Technologies Inc",
            entity_type=EntityType.ORGANIZATION,
        )
        orchestrator.register_known_record(inv_id, r1)
        orchestrator.register_known_record(inv_id, r2)

        # An ambiguous mention matching both
        mention = EntityMention(
            mention_id="men_ambig_01",
            document_id="doc_ambig",
            surface_text="Apex Global Technologies",
            entity_type=EntityType.ORGANIZATION,
            start_char=0,
            end_char=24,
            extraction_method="rule",
            confidence_score=0.9,
        )
        res = session.resolver.resolve_mention(mention)
        assert res.resolution_status == MentionResolutionStatus.UNRESOLVED_INSUFFICIENT_EVIDENCE
        assert res.decision_type == DecisionType.REVIEW
        assert res.is_resolved is False
        assert "ambiguously matched multiple distinct entities" in res.explanation

    def test_negation_and_allegations_epistemic_qualifiers(self, orchestrator):
        """Test that negation produces contradicting evidence and allegations are flagged."""
        inv_id = "test_inv_epistemic"
        orchestrator.create_investigation(inv_id)

        doc_text = (
            "Alice Smith does not work for Cyberdyne Systems.\n"
            "The report alleges that Wayne Enterprises owns Globex Corporation."
        )
        rec = orchestrator.process_document(inv_id, doc_text.encode("utf-8"), source_name="memo.txt")
        assert rec.status == DocumentProcessingStatus.COMPLETED

        claims = orchestrator.get_extracted_claims(inv_id)
        neg_claim = next(c for c in claims if c.predicate == "WORKS_FOR")
        assert neg_claim.qualifiers.get("is_negated") is True
        assert len(neg_claim.contradicting_evidence_ids) >= 1
        assert len(neg_claim.supporting_evidence_ids) == 0

        allegation_claim = next(c for c in claims if c.predicate == "OWNS")
        assert allegation_claim.qualifiers.get("is_allegation") is True
        assert allegation_claim.qualifiers.get("attribution_source") == "The report alleges that"

    def test_retraction_and_cascade_lifecycle(self, orchestrator):
        """Test claim retraction cascades to relationship status and updates report audit log."""
        inv_id = "test_inv_retraction_cascade"
        orchestrator.create_investigation(inv_id)

        doc_text = "The report alleges that Wayne Enterprises owns Globex Corporation."
        orchestrator.process_document(inv_id, doc_text.encode("utf-8"), source_name="doc.txt", derive_relationships=True)

        claims = orchestrator.get_extracted_claims(inv_id)
        owns_claim = next(c for c in claims if c.predicate == "OWNS")
        rels = orchestrator.get_extracted_relationships(inv_id)
        owns_rel = next(r for r in rels if owns_claim.claim_id in r.supporting_claim_ids)

        assert owns_rel.review_status == ReviewStatus.UNREVIEWED

        # Retract the claim
        orchestrator.review_claim(
            inv_id,
            claim_id=owns_claim.claim_id,
            new_status=ReviewStatus.RETRACTED,
            rationale="Corporate registration records prove complete independence.",
            reviewer="Auditor_Smith",
        )

        # Check cascaded relationship status
        updated_rels = orchestrator.get_extracted_relationships(inv_id)
        updated_rel = next(r for r in updated_rels if r.relationship_id == owns_rel.relationship_id)
        assert updated_rel.review_status == ReviewStatus.RETRACTED

        # Report audit
        report = orchestrator.generate_report(inv_id)
        assert len(report.retractions_and_supersessions) >= 1
        entry = report.retractions_and_supersessions[0]
        assert entry["new_status"] == "RETRACTED"
        assert entry["reviewer"] == "Auditor_Smith"
        assert "complete independence" in entry["rationale"]

    def test_cycle_safe_graph_traversal_and_bounds(self, orchestrator):
        """Test bounded traversal handles cyclic graphs without infinite loops."""
        inv_id = "test_inv_cycle_safety"
        session = orchestrator.create_investigation(inv_id)

        # Build cyclic entity triad: A -> B -> C -> A
        e_a = InvestigationEntity(entity_id="e_a", entity_type=EntityType.ORGANIZATION, canonical_name="Node A")
        e_b = InvestigationEntity(entity_id="e_b", entity_type=EntityType.ORGANIZATION, canonical_name="Node B")
        e_c = InvestigationEntity(entity_id="e_c", entity_type=EntityType.ORGANIZATION, canonical_name="Node C")
        session.store.add_entity(e_a)
        session.store.add_entity(e_b)
        session.store.add_entity(e_c)

        # Ingest evidence & claims for triad
        ev = Evidence(
            evidence_id="ev_cycle",
            evidence_type="test",
            content="cycle",
            text_span="cycle",
            char_offsets=(0, 5),
            provenance="doc_cycle:0-5",
        )
        session.store.add_evidence(ev)

        c1 = session.lifecycle_manager.extract_claim("c1", "e_a", "PARTNER_WITH", "e_b", ["ev_cycle"])
        c2 = session.lifecycle_manager.extract_claim("c2", "e_b", "PARTNER_WITH", "e_c", ["ev_cycle"])
        c3 = session.lifecycle_manager.extract_claim("c3", "e_c", "PARTNER_WITH", "e_a", ["ev_cycle"])

        session.lifecycle_manager.derive_relationship_from_claim("c1")
        session.lifecycle_manager.derive_relationship_from_claim("c2")
        session.lifecycle_manager.derive_relationship_from_claim("c3")

        # Bounded query should terminate safely
        res = orchestrator.query_entity(inv_id, entity_id="e_a", max_depth=5, max_nodes=10)
        assert len(res.entities) == 3
        assert len(res.relationships) == 3
        assert len(res.explanations) == 3

    def test_partial_processing_failure_visibility_and_retry(self, orchestrator):
        """Test partial document parsing failure is visible in status and does not corrupt session."""
        inv_id = "test_inv_partial_failure"
        session = orchestrator.create_investigation(inv_id)

        # Valid document
        valid_rec = orchestrator.process_document(
            inv_id, b"Dr. John Watson works for Sherlock Security.", source_name="valid.txt"
        )
        assert valid_rec.status == DocumentProcessingStatus.COMPLETED

        # Force a failure: invalid PDF bytes with doc_format=PDF
        corrupt_rec = orchestrator.process_document(
            inv_id, b"Not a valid PDF header", source_name="corrupt.pdf", doc_format=DocumentFormat.PDF
        )
        assert corrupt_rec.status == DocumentProcessingStatus.FAILED
        assert corrupt_rec.error_message is not None

        # Verify session status reflects partial failure
        summary = orchestrator.get_summary(inv_id)
        assert summary.status == InvestigationStatus.PARTIAL_FAILURE
        assert summary.completed_documents == 1
        assert summary.failed_documents == 1
        assert len(summary.warnings) >= 1

    def test_report_determinism_and_provenance(self, orchestrator):
        """Test that report generation is strictly read-only and produces deterministic output."""
        inv_id = "test_inv_report_det"
        orchestrator.create_investigation(inv_id)

        doc_text = "Dr. John Watson works for Sherlock Security."
        orchestrator.process_document(inv_id, doc_text.encode("utf-8"), source_name="doc.txt", derive_relationships=True)

        report1 = orchestrator.generate_report(inv_id)
        report2 = orchestrator.generate_report(inv_id)

        # Structural equality of reports
        assert report1.investigation_id == report2.investigation_id
        assert report1.metrics == report2.metrics
        assert len(report1.claims) == len(report2.claims)
        assert len(report1.relationships) == len(report2.relationships)
        assert len(report1.documents) == len(report2.documents)

        # Check persistence disclaimer is present
        assert "In-memory reference graph" in report1.persistence_notice
        assert "does not survive process termination" in report1.persistence_notice

    def test_referential_integrity_no_dangling_entities(self, orchestrator):
        """Test that creating claims or relationships with nonexistent entities is rejected."""
        inv_id = "test_inv_referential_integrity"
        session = orchestrator.create_investigation(inv_id)

        ev = Evidence(
            evidence_id="ev_ref",
            evidence_type="test",
            content="test",
            text_span="test",
            char_offsets=(0, 4),
            provenance="doc_ref:0-4",
        )
        session.store.add_evidence(ev)

        # Attempt to add claim with nonexistent subject and object that are not flagged as unresolved
        claim = Claim(
            claim_id="cl_dangling",
            subject_id="nonexistent_entity_subject",
            predicate="WORKS_FOR",
            object_id="nonexistent_entity_object",
            supporting_evidence_ids=["ev_ref"],
            extraction_method="rule",
        )
        with pytest.raises(ValueError, match="Dangling entity reference"):
            session.store.add_claim(claim)

    def test_raw_ingested_document_immutability(self, orchestrator):
        """Test that raw ingested document text and attributes are never mutated."""
        inv_id = "test_inv_immutability"
        session = orchestrator.create_investigation(inv_id)

        original_bytes = b"CONFIDENTIAL FACT: Dr. John Watson works for Sherlock Security."
        rec = orchestrator.process_document(inv_id, original_bytes, source_name="immutable.txt")

        ingested_doc = session.documents[rec.document_id]
        # IngestedDocument is an ImmutableBaseModel
        with pytest.raises(Exception):
            ingested_doc.normalized_text = "Mutated text"
