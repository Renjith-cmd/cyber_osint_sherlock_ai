"""
Sherlock AI — Milestone 10 Acceptance Audit Regression Test Suite.

Targeted acceptance tests covering:
- Audit A: Mock vs. Real inference, explicit error on missing live ML, simulation disclosures.
- Audit B: Entity-resolution semantics (no candidates != confirmed non-match, all 6 ER scenarios).
- Audit C: Hybrid negation reconciliation, bidirectional conflicts, 'did not establish that' epistemic handling.
- Audit D: Relation grounding, invalid mention rejection, exact text offsets, protected human reviews.
- Audit E: Benchmark integrity, mock execution disclaimer, metric calculations.
"""

import pytest
from src.core.models import (
    Record,
    EntityType,
    DecisionType,
    ReviewStatus,
    EvidencePolarity,
)
from src.core.document_ingestion import DocumentIngestionService
from src.core.ner import (
    DeterministicRuleNERExtractor,
    ModelBackedNERExtractor,
    HybridNERExtractor,
    MockTransformerNERBackend,
    HuggingFaceNERBackend,
    EntityMention,
    MLModelUnavailableError,
)
from src.core.relation_extraction import (
    DeterministicRuleRelationExtractor,
    ModelBackedRelationExtractor,
    HybridRelationExtractor,
    MockRelationNLIBackend,
    ZeroShotRelationBackend,
    ExtractedRelationCandidate,
)
from src.core.mention_entity_resolution import (
    MentionEntityResolver,
    MentionResolutionResult,
    MentionResolutionStatus,
)
from src.core.document_pipeline import (
    DocumentExtractionPipeline,
    ExtractionPipelineResult,
)
from src.core.document_evaluation import (
    DocumentEvaluationRunner,
    MultiBackendComparativeReport,
)
from src.core.decision import DecisionPolicy
from src.core.clustering import ConstraintAwareClusterer


class TestAuditAMockVsRealInference:
    """Audit A: Epistemic separation between simulated mocks and real ML inference."""

    def test_mock_backends_flagged_as_mock(self):
        """Mock backend instances explicitly declare is_mock = True."""
        mock_ner = MockTransformerNERBackend()
        assert mock_ner.is_mock is True

        mock_rel = MockRelationNLIBackend()
        assert mock_rel.is_mock is True

        hf_ner = HuggingFaceNERBackend(model_name="dslim/bert-base-NER")
        assert hf_ner.is_mock is False

        zs_rel = ZeroShotRelationBackend(model_name="cross-encoder/nli-distilroberta-base")
        assert zs_rel.is_mock is False

    def test_live_ml_backend_raises_error_when_dependencies_missing(self):
        """When live ML backend is requested in an environment lacking dependencies or weights, raises clear error."""
        extractor = ModelBackedNERExtractor(
            backend=HuggingFaceNERBackend(model_name="non-existent/offline-unloaded-model"),
            use_mock_backend=False,
        )
        ingestion = DocumentIngestionService()
        doc = ingestion.ingest(b"Dr. John Watson works for Sherlock Security.", "test.txt")

        # Live ML cannot silently succeed or run mocks when model weights are missing
        with pytest.raises(MLModelUnavailableError) as exc_info:
            extractor.extract_entities(doc)
        err = str(exc_info.value).lower()
        assert "transformers" in err or "model" in err or "failed to load" in err

    def test_live_relation_backend_raises_error_when_dependencies_missing(self):
        """Live relation extractor raises MLModelUnavailableError when dependencies or weights are missing."""
        rel_ext = ModelBackedRelationExtractor(
            backend=ZeroShotRelationBackend(model_name="non-existent/offline-unloaded-rel"),
            use_mock_backend=False,
        )
        ingestion = DocumentIngestionService()
        doc = ingestion.ingest(b"Bruce Wayne owns Wayne Enterprises.", "test.txt")
        m1 = EntityMention(
            mention_id="m1", document_id=doc.document_id, surface_text="Bruce Wayne",
            entity_type=EntityType.PERSON, start_char=0, end_char=11,
            extraction_method="rule", extraction_version="v1",
        )
        m2 = EntityMention(
            mention_id="m2", document_id=doc.document_id, surface_text="Wayne Enterprises",
            entity_type=EntityType.ORGANIZATION, start_char=17, end_char=34,
            extraction_method="rule", extraction_version="v1",
        )
        with pytest.raises(MLModelUnavailableError) as exc_info:
            rel_ext.extract_relations(doc, [m1, m2])
        err = str(exc_info.value).lower()
        assert "transformers" in err or "model" in err or "failed to load" in err

    def test_pipeline_ml_mode_raises_error_on_missing_live_dependencies(self):
        """Pipeline with backend_mode='ml' must NOT silently fall back to regex mocks."""
        pipeline = DocumentExtractionPipeline(
            backend_mode="ml",
            ner_extractor=ModelBackedNERExtractor(
                backend=HuggingFaceNERBackend(model_name="non-existent/offline-unloaded-model")
            ),
        )
        with pytest.raises(MLModelUnavailableError):
            pipeline.process_document(b"Alice works for Cyberdyne.", "doc.txt")

    def test_mock_outputs_contain_epistemic_simulation_warning(self):
        """When mock backend is explicitly selected, outputs are tagged with simulation provenance."""
        extractor = ModelBackedNERExtractor(use_mock_backend=True)
        ingestion = DocumentIngestionService()
        doc = ingestion.ingest(b"Dr. John Watson works in London.", "test.txt")
        mentions = extractor.extract_entities(doc)
        assert len(mentions) > 0
        for m in mentions:
            assert m.metadata["is_mock_simulation"] is True
            assert m.metadata["provenance"] == "mock_simulation"
            assert "epistemic_warning" in m.metadata

    def test_hybrid_mode_reports_actual_executed_backends(self):
        """Hybrid mode explicitly records which backends actually executed."""
        # When ML is unavailable, fallback records only 'rule' was executed
        hybrid = HybridNERExtractor(
            ml_extractor=ModelBackedNERExtractor(
                backend=HuggingFaceNERBackend(model_name="non-existent/offline-unloaded-model")
            ),
            allow_rule_fallback=True,
        )
        ingestion = DocumentIngestionService()
        doc = ingestion.ingest(b"Sherlock Security is in London.", "test.txt")
        mentions = hybrid.extract_entities(doc)
        assert len(mentions) > 0
        for m in mentions:
            assert m.metadata.get("hybrid_fallback") is True
            assert list(m.metadata.get("backends_executed", [])) == ["rule"]

        # When offline mock ML is provided, reports ['rule', 'mock_ml']
        hybrid_mock = HybridNERExtractor(
            ml_extractor=ModelBackedNERExtractor(use_mock_backend=True),
            allow_rule_fallback=True,
        )
        mentions_mock = hybrid_mock.extract_entities(doc)
        for m in mentions_mock:
            if "backends_executed" in m.metadata:
                assert list(m.metadata["backends_executed"]) == ["rule", "mock_ml"]


class TestAuditBEntityResolutionSemantics:
    """Audit B: Strict epistemic distinction between lack of candidates, review, non-match, and match."""

    def _setup_resolver(self) -> MentionEntityResolver:
        known = [
            Record(
                record_id="rec_bruce_01",
                source_id="src_db",
                raw_name="Bruce Wayne",
                entity_type=EntityType.PERSON,
                structured_attributes={"tax_id": "99-1234567", "date_of_birth": "1972-02-19"},
                normalized_attributes={"tax_id": "99-1234567", "date_of_birth": "1972-02-19"},
            ),
            Record(
                record_id="rec_wayne_corp",
                source_id="src_db",
                raw_name="Wayne Enterprises Inc.",
                entity_type=EntityType.ORGANIZATION,
                structured_attributes={"tax_id": "11-2233445"},
                normalized_attributes={"tax_id": "11-2233445"},
            ),
        ]
        return MentionEntityResolver(known_records=known)

    def test_scenario_1_no_candidates_found(self):
        """Scenario 1: A mention with no candidate passing blocking must NOT be a confirmed non-match."""
        resolver = self._setup_resolver()
        mention = EntityMention(
            mention_id="m_no_cand",
            document_id="doc_1",
            surface_text="Xanadu Quantum Robotics Ltd",
            entity_type=EntityType.ORGANIZATION,
            start_char=0,
            end_char=27,
            extraction_method="rule",
            extraction_version="v1",
        )
        res = resolver.resolve_mention(mention)
        assert res.resolution_status == MentionResolutionStatus.UNRESOLVED_NO_CANDIDATES
        assert res.decision_type is None  # Never evaluated against any record!
        assert res.is_resolved is False
        assert res.resolved_entity_id is None
        assert "unresolved" in res.explanation.lower()

    def test_scenario_2_candidate_exists_but_insufficient_evidence(self):
        """Scenario 2: Candidate exists but evidence is insufficient routes to REVIEW."""
        resolver = self._setup_resolver()
        # Surface name matches Wayne Enterprises partially, but no Tax ID context is provided
        mention = EntityMention(
            mention_id="m_weak",
            document_id="doc_1",
            surface_text="Wayne Corp",
            entity_type=EntityType.ORGANIZATION,
            start_char=0,
            end_char=10,
            extraction_method="rule",
            extraction_version="v1",
        )
        res = resolver.resolve_mention(mention, context_attributes={})
        assert res.resolution_status == MentionResolutionStatus.UNRESOLVED_INSUFFICIENT_EVIDENCE
        assert res.decision_type == DecisionType.REVIEW
        assert res.is_resolved is False
        assert res.resolved_entity_id is None

    def test_scenario_3_confirmed_explicit_non_match(self):
        """Scenario 3: Fatal contradiction establishes confirmed NON_MATCH."""
        resolver = self._setup_resolver()
        # Same name but contradictory fatal identifiers (e.g., conflicting tax ID and DOB)
        mention = EntityMention(
            mention_id="m_contra",
            document_id="doc_1",
            surface_text="Bruce Wayne",
            entity_type=EntityType.PERSON,
            start_char=0,
            end_char=11,
            extraction_method="rule",
            extraction_version="v1",
        )
        res = resolver.resolve_mention(
            mention,
            context_attributes={"tax_id": "00-0000000", "date_of_birth": "2005-12-12"},
        )
        assert res.resolution_status == MentionResolutionStatus.CONFIRMED_NON_MATCH
        assert res.decision_type == DecisionType.NON_MATCH
        assert res.is_resolved is False
        assert res.resolved_entity_id is None

    def test_scenario_4_valid_match_supported(self):
        """Scenario 4: High evidence similarity and matching identifiers yield MATCH."""
        resolver = self._setup_resolver()
        mention = EntityMention(
            mention_id="m_valid",
            document_id="doc_1",
            surface_text="Bruce Wayne",
            entity_type=EntityType.PERSON,
            start_char=0,
            end_char=11,
            extraction_method="rule",
            extraction_version="v1",
        )
        res = resolver.resolve_mention(
            mention,
            context_attributes={"tax_id": "99-1234567", "date_of_birth": "1972-02-19"},
        )
        assert res.resolution_status == MentionResolutionStatus.RESOLVED_MATCH
        assert res.decision_type == DecisionType.MATCH
        assert res.is_resolved is True
        assert res.resolved_entity_id == "rec_bruce_01"

    def test_scenario_5_exact_name_collision_with_conflicting_identifiers(self):
        """Scenario 5: Exact name collision with conflicting tax ID must not merge."""
        resolver = self._setup_resolver()
        mention = EntityMention(
            mention_id="m_collision",
            document_id="doc_1",
            surface_text="Wayne Enterprises Inc.",
            entity_type=EntityType.ORGANIZATION,
            start_char=0,
            end_char=22,
            extraction_method="rule",
            extraction_version="v1",
        )
        # Conflicting tax ID
        res = resolver.resolve_mention(
            mention,
            context_attributes={"tax_id": "88-9999999"},
        )
        assert res.resolution_status in (
            MentionResolutionStatus.CONFIRMED_NON_MATCH,
            MentionResolutionStatus.UNRESOLVED_INSUFFICIENT_EVIDENCE,
        )
        assert res.is_resolved is False
        assert res.resolved_entity_id is None

    def test_scenario_6_explicit_non_match_constraint_prevents_clustering(self):
        """Scenario 6: An explicit non-match constraint prevents clustering even on high similarity."""
        resolver = self._setup_resolver()
        mention = EntityMention(
            mention_id="m_constrained",
            document_id="doc_1",
            surface_text="Wayne Enterprises Inc.",
            entity_type=EntityType.ORGANIZATION,
            start_char=0,
            end_char=22,
            extraction_method="rule",
            extraction_version="v1",
        )
        resolver.add_explicit_non_match(mention.mention_id, "rec_wayne_corp")
        res = resolver.resolve_mention(
            mention,
            context_attributes={"tax_id": "11-2233445"},
        )
        assert res.resolution_status == MentionResolutionStatus.CONFIRMED_NON_MATCH
        assert res.decision_type == DecisionType.NON_MATCH
        assert res.is_resolved is False


class TestAuditCHybridNegationAndDisagreement:
    """Audit C: Reconciliation between rule and ML outputs, polarity preservation, unestablished phrasing."""

    def test_unestablished_phrasing_is_not_affirmative_negation(self):
        """Phrase 'did not establish that X owns Y' must be uncertainty, NOT affirmative negation."""
        text = "The investigation did not establish that Wayne Enterprises owns Globex Corporation."
        ingestion = DocumentIngestionService()
        doc = ingestion.ingest(text.encode("utf-8"), "report.txt")

        start1 = text.index("Wayne Enterprises")
        end1 = start1 + len("Wayne Enterprises")
        start2 = text.index("Globex Corporation")
        end2 = start2 + len("Globex Corporation")

        m1 = EntityMention(
            mention_id="m1", document_id=doc.document_id, surface_text="Wayne Enterprises",
            entity_type=EntityType.ORGANIZATION, start_char=start1, end_char=end1,
            extraction_method="rule", extraction_version="v1",
        )
        m2 = EntityMention(
            mention_id="m2", document_id=doc.document_id, surface_text="Globex Corporation",
            entity_type=EntityType.ORGANIZATION, start_char=start2, end_char=end2,
            extraction_method="rule", extraction_version="v1",
        )

        extractor = DeterministicRuleRelationExtractor()
        cands = extractor.extract_relations(doc, [m1, m2])
        assert len(cands) == 1
        cand = cands[0]
        # Crucial: is_negated must be FALSE! Lack of proof != proof of falsity!
        assert cand.is_negated is False
        assert cand.uncertainty_flag is True
        assert cand.is_allegation is True

    def test_mock_relation_unestablished_phrasing(self):
        """Mock NLI backend also handles unestablished phrasing without falsely negating."""
        text = "The investigation failed to confirm that Wayne Enterprises owns Globex Corporation."
        m1 = EntityMention(
            mention_id="m1", document_id="d1", surface_text="Wayne Enterprises",
            entity_type=EntityType.ORGANIZATION, start_char=36, end_char=53,
            extraction_method="rule", extraction_version="v1",
        )
        m2 = EntityMention(
            mention_id="m2", document_id="d1", surface_text="Globex Corporation",
            entity_type=EntityType.ORGANIZATION, start_char=59, end_char=77,
            extraction_method="rule", extraction_version="v1",
        )
        mock_backend = MockRelationNLIBackend()
        pred = mock_backend.predict_relation(text, m1, m2)
        assert pred is not None
        assert pred["is_negated"] is False
        assert pred["uncertainty_flag"] is True

    def test_hybrid_polarity_conflict_preserves_negation_and_routes_to_review(self):
        """If one backend identifies negation and the other does not, hybrid preserves negation and routes to review."""
        doc = DocumentIngestionService().ingest(b"Text", "doc.txt")
        m1 = EntityMention(
            mention_id="m1", document_id=doc.document_id, surface_text="Bruce Wayne",
            entity_type=EntityType.PERSON, start_char=0, end_char=11,
            extraction_method="rule", extraction_version="v1",
        )
        m2 = EntityMention(
            mention_id="m2", document_id=doc.document_id, surface_text="Wayne Enterprises",
            entity_type=EntityType.ORGANIZATION, start_char=20, end_char=37,
            extraction_method="rule", extraction_version="v1",
        )

        # Rule says negated, ML says positive
        cand_rule = ExtractedRelationCandidate(
            candidate_id="c_rule", document_id=doc.document_id,
            subject_mention_id="m1", subject_surface="Bruce Wayne", subject_type=EntityType.PERSON,
            predicate="OWNS", object_mention_id="m2", object_surface="Wayne Enterprises",
            object_type=EntityType.ORGANIZATION, evidence_span="Text", evidence_start_char=0,
            evidence_end_char=4, is_negated=True, extraction_method="rule",
        )
        cand_ml = ExtractedRelationCandidate(
            candidate_id="c_ml", document_id=doc.document_id,
            subject_mention_id="m1", subject_surface="Bruce Wayne", subject_type=EntityType.PERSON,
            predicate="OWNS", object_mention_id="m2", object_surface="Wayne Enterprises",
            object_type=EntityType.ORGANIZATION, evidence_span="Text", evidence_start_char=0,
            evidence_end_char=4, is_negated=False, extraction_method="ml",
        )

        hybrid = HybridRelationExtractor()
        reconciled = hybrid._reconcile_relations(doc, [cand_rule], [cand_ml])
        assert len(reconciled) == 1
        res = reconciled[0]
        # Invariant: Negation strictly preserved!
        assert res.is_negated is True
        # Invariant: Polarity conflict routes to review!
        assert res.metadata["requires_human_review"] is True
        assert res.metadata["polarity_conflict"] is True

    def test_hybrid_predicate_conflict_routes_to_review(self):
        """If backends disagree on predicate type, disagreement is preserved and routed to review."""
        doc = DocumentIngestionService().ingest(b"Text", "doc.txt")
        cand_rule = ExtractedRelationCandidate(
            candidate_id="c_rule", document_id=doc.document_id,
            subject_mention_id="m1", subject_surface="Bruce Wayne", subject_type=EntityType.PERSON,
            predicate="OWNS", object_mention_id="m2", object_surface="Wayne Enterprises",
            object_type=EntityType.ORGANIZATION, evidence_span="Text", evidence_start_char=0,
            evidence_end_char=4, is_negated=False, extraction_method="rule",
        )
        cand_ml = ExtractedRelationCandidate(
            candidate_id="c_ml", document_id=doc.document_id,
            subject_mention_id="m1", subject_surface="Bruce Wayne", subject_type=EntityType.PERSON,
            predicate="ASSOCIATED_WITH", object_mention_id="m2", object_surface="Wayne Enterprises",
            object_type=EntityType.ORGANIZATION, evidence_span="Text", evidence_start_char=0,
            evidence_end_char=4, is_negated=False, extraction_method="ml",
        )
        hybrid = HybridRelationExtractor()
        reconciled = hybrid._reconcile_relations(doc, [cand_rule], [cand_ml])
        assert len(reconciled) == 1
        assert reconciled[0].metadata["backends_disagreed"] is True
        assert reconciled[0].metadata["requires_human_review"] is True
        assert reconciled[0].metadata["disagreement_type"] == "predicate_conflict"


class TestAuditDRelationGrounding:
    """Audit D: Grounding validation, exact offsets, and protection of reviewed claims."""

    def test_ungrounded_mentions_are_rejected(self):
        """Pipeline rejects relation candidates with non-existent or ungrounded mention IDs."""
        pipeline = DocumentExtractionPipeline(backend_mode="rule")
        raw = b"Dr. John Watson works for Sherlock Security."
        res = pipeline.process_document(raw, "test.txt")

        # Manually create a relation with an ungrounded mention ID
        bogus_cand = ExtractedRelationCandidate(
            candidate_id="rel_bogus", document_id=res.document.document_id,
            subject_mention_id="m_nonexistent_1", subject_surface="Ghost Subject",
            subject_type=EntityType.PERSON, predicate="WORKS_FOR",
            object_mention_id="m_nonexistent_2", object_surface="Ghost Object",
            object_type=EntityType.ORGANIZATION, evidence_span="works for",
            evidence_start_char=16, evidence_end_char=25,
            extraction_method="rule",
        )
        # Processing through pipeline logic
        processed_res = pipeline.process_ingested_document(
            res.document,
            override_mentions=res.mentions,
            override_relation_candidates=[bogus_cand],
        )
        # Ungrounded candidate must be rejected; no bogus claims created
        assert len(processed_res.claims) == 0

    def test_mismatched_evidence_offsets_are_rejected(self):
        """Pipeline rejects candidates whose text span does not match normalized document text."""
        pipeline = DocumentExtractionPipeline(backend_mode="rule")
        raw = b"Dr. John Watson works for Sherlock Security."
        doc = pipeline.ingestion_service.ingest(raw, "test.txt")
        m_subj = EntityMention(
            mention_id="m1", document_id=doc.document_id, surface_text="Dr. John Watson",
            entity_type=EntityType.PERSON, start_char=0, end_char=15,
            extraction_method="rule", extraction_version="v1",
        )
        m_obj = EntityMention(
            mention_id="m2", document_id=doc.document_id, surface_text="Sherlock Security",
            entity_type=EntityType.ORGANIZATION, start_char=26, end_char=43,
            extraction_method="rule", extraction_version="v1",
        )
        # Create relation candidate with wrong offsets that satisfy Pydantic length validator
        # but mismatch the actual document slice at those offsets.
        # Length of "Watson works for Sherlock Sec" is 30, matching 0:30, but text at 0:30 is "Dr. John Watson works for Sher"
        mismatched_text = "Watson works for Sherlock Sec"
        corrupt_cand = ExtractedRelationCandidate(
            candidate_id="rel_corrupt", document_id=doc.document_id,
            subject_mention_id="m1", subject_surface="Dr. John Watson",
            subject_type=EntityType.PERSON, predicate="WORKS_FOR",
            object_mention_id="m2", object_surface="Sherlock Security",
            object_type=EntityType.ORGANIZATION,
            evidence_span=mismatched_text,
            evidence_start_char=0,
            evidence_end_char=len(mismatched_text),
            extraction_method="rule",
        )
        processed = pipeline.process_ingested_document(
            doc,
            override_mentions=[m_subj, m_obj],
            override_relation_candidates=[corrupt_cand],
        )
        # Rejected because offsets do not match normalized text slice
        assert len(processed.claims) == 0

    def test_human_reviewed_claims_are_protected_from_overwrite(self):
        """Retracted, verified, or rejected claims in store are protected from automated overwrite."""
        pipeline = DocumentExtractionPipeline(backend_mode="mock_ml")
        raw = b"Dr. John Watson works for Sherlock Security."
        res1 = pipeline.process_document(raw, "test.txt")
        assert len(res1.claims) > 0

        target_claim = res1.claims[0]
        # Simulate human retraction of this claim
        pipeline.lifecycle_manager.review_claim(
            claim_id=target_claim.claim_id,
            new_status=ReviewStatus.RETRACTED,
            rationale="Retracted by senior investigator after source document disproved.",
            reviewer="senior_investigator",
        )
        stored_claim = pipeline.store.get_claim(target_claim.claim_id)
        assert stored_claim.review_status == ReviewStatus.RETRACTED

        # Re-run pipeline on the same document
        res2 = pipeline.process_document(raw, "test.txt")
        assert target_claim.claim_id in res2.preserved_reviewed_claims
        final_claim = pipeline.store.get_claim(target_claim.claim_id)
        assert final_claim.review_status == ReviewStatus.RETRACTED


class TestAuditEBenchmarkIntegrity:
    """Audit E: Metric verification and explicit disclosure of simulated mock benchmarking."""

    def test_comparative_benchmark_report_contains_mock_disclosures(self):
        """Benchmark report explicitly labels mock ML and includes epistemic disclaimers."""
        runner = DocumentEvaluationRunner()
        report = runner.run_comparative_benchmark()

        assert report.is_mock_ml_simulation is True
        assert report.ml_backend_type == "mock_simulation"
        assert "simulation" in report.evaluation_provenance.lower()
        assert "latency and memory reflect cpu" in report.epistemic_disclaimer.lower()

    def test_entity_resolution_report_tracks_unresolved_no_candidates(self):
        """ER evaluation report tracks mentions without candidates separately from confirmed non-matches."""
        runner = DocumentEvaluationRunner()
        report = runner.run_comparative_benchmark()
        er_rep = report.entity_resolution

        assert hasattr(er_rep, "unresolved_no_candidates")
        # Alice Smith was in the test queries without known records, so it must be counted as unresolved
        assert er_rep.unresolved_no_candidates >= 1
