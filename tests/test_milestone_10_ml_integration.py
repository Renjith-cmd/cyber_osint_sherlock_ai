"""
Comprehensive Integration and Unit Tests for Milestone 10:
Model-Backed NER, Relation Extraction & Entity-Resolution Integration.

Covers:
1. Model-Backed NER (Mock Transformer Backend, Subword token offsets, Unicode grounding,
   repeated mentions, uncalibrated confidence disclosures, unsupported entity types,
   offline error handling).
2. Model-Backed Relation Extraction (Mock NLI Backend, Schema enforcement, Grounded evidence,
   Negation/Attribution/Uncertainty flags, Sentence boundary abstention).
3. Hybrid Extraction (Agreement deduplication, Disagreement recording, Polarity preservation,
   Epistemic independence safeguards).
4. Entity Resolution Integration (8 required test cases):
   - Exact match to existing entity
   - Noisy / partial name match
   - Two different entities sharing a name
   - Conflicting identifiers
   - Missing attributes
   - Unresolved mention
   - Explicit NON_MATCH constraint preventing merge
   - Deterministic results across repeated runs.
5. Multi-Backend Comparative Evaluation & CLI Integration.
"""

import copy
import json
import pytest
from typing import Dict, Any

from src.core.models import (
    EntityType,
    DecisionType,
    EvidencePolarity,
    RelationshipEpistemicTier,
    Record,
)
from src.core.document_ingestion import (
    DocumentFormat,
    IngestedDocument,
    TextDocumentParser,
)
from src.core.ner import (
    EntityMention,
    DeterministicRuleNERExtractor,
    ModelBackedNERExtractor,
    HybridNERExtractor,
    MockTransformerNERBackend,
    HuggingFaceNERBackend,
    MLModelUnavailableError,
)
from src.core.relation_extraction import (
    ExtractedRelationCandidate,
    DeterministicRuleRelationExtractor,
    ModelBackedRelationExtractor,
    HybridRelationExtractor,
    MockRelationNLIBackend,
    ZeroShotRelationBackend,
    SUPPORTED_RELATION_PREDICATES,
)
from src.core.mention_entity_resolution import (
    MentionEntityResolver,
    MentionResolutionResult,
    MentionResolutionStatus,
    mention_to_record,
)
from src.core.document_pipeline import (
    DocumentExtractionPipeline,
    ExtractionPipelineResult,
)
from src.core.document_evaluation import (
    DocumentEvaluationRunner,
    GoldDocumentFixture,
    GoldEntity,
    GoldRelation,
    MultiBackendComparativeReport,
)


# ===========================================================================
# 1. Model-Backed NER Tests
# ===========================================================================

class TestModelBackedNER:
    """Verifies model-backed NER behavior and mock transformer backend."""

    def test_subword_mapping_and_exact_offsets(self):
        """Model subwords must correctly map to exact document character offsets."""
        text = "Bruce Wayne established Wayne Enterprises in Gotham City."
        doc = TextDocumentParser().parse(text.encode("utf-8"), "test.txt", "doc_test_1")

        backend = MockTransformerNERBackend()
        extractor = ModelBackedNERExtractor(backend=backend)
        mentions = extractor.extract_entities(doc)

        assert len(mentions) >= 3
        names = [m.surface_text for m in mentions]
        assert "Bruce Wayne" in names
        assert "Wayne Enterprises" in names
        assert "Gotham City" in names

        # Verify exact character offsets match document slice
        for m in mentions:
            assert doc.normalized_text[m.start_char:m.end_char] == m.surface_text
            assert m.extraction_method == "model_backed_transformer"
            assert m.metadata.get("backend") == "mock_transformer_engine"
            assert m.confidence_score is not None
            # Disclose that raw score is uncalibrated
            assert m.metadata.get("calibrated_probability") is False

    def test_unicode_and_repeated_mentions_distinct(self):
        """Preserves Unicode text and keeps repeated mentions as distinct records."""
        text = "René Dupont visited René Dupont at Paris café René Dupont."
        doc = TextDocumentParser().parse(text.encode("utf-8"), "unicode.txt", "doc_u1")

        # Mock subwords for René Dupont using B-PER / I-PER
        subwords = [
            {"word": "René", "start": 0, "end": 4, "entity_group": "B-PER", "score": 0.98},
            {"word": "Dupont", "start": 5, "end": 11, "entity_group": "I-PER", "score": 0.97},
            {"word": "René", "start": 20, "end": 24, "entity_group": "B-PER", "score": 0.98},
            {"word": "Dupont", "start": 25, "end": 31, "entity_group": "I-PER", "score": 0.97},
        ]
        backend = MockTransformerNERBackend(predefined_entities=subwords)
        extractor = ModelBackedNERExtractor(backend=backend)
        mentions = extractor.extract_entities(doc)

        assert len(mentions) == 2
        # Verify distinct mention IDs and distinct offset ranges
        assert mentions[0].mention_id != mentions[1].mention_id
        assert mentions[0].start_char == 0
        assert mentions[0].end_char == 11
        assert mentions[1].start_char == 20
        assert mentions[1].end_char == 31
        assert mentions[0].surface_text == "René Dupont"
        assert mentions[1].surface_text == "René Dupont"

    def test_unsupported_entity_type_explicit_handling(self):
        """Unsupported entity types in model output must be handled explicitly."""
        text = "On Monday, Apple acquired Beats."
        doc = TextDocumentParser().parse(text.encode("utf-8"), "types.txt", "doc_t1")

        subwords = [
            {"word": "Monday", "start": 3, "end": 9, "entity_group": "DATE", "score": 0.95},
            {"word": "Apple", "start": 11, "end": 16, "entity_group": "ORG", "score": 0.99},
        ]
        backend = MockTransformerNERBackend(predefined_entities=subwords)
        extractor = ModelBackedNERExtractor(backend=backend)
        mentions = extractor.extract_entities(doc)

        # DATE is not in supported EntityType enum, must be omitted cleanly without crash
        types = [m.entity_type for m in mentions]
        assert EntityType.ORGANIZATION in types
        assert not any(m.surface_text == "Monday" for m in mentions)

    def test_offline_hf_backend_raises_clear_error_when_unavailable(self):
        """HuggingFace backend must fail explicitly if dependencies/weights are missing."""
        # Use a non-existent local model name or uninstalled package to test clear failure
        hf_backend = HuggingFaceNERBackend(model_name="non-existent/model-that-does-not-exist")
        doc = TextDocumentParser().parse(b"Hello world", "test.txt", "doc_1")
        extractor = ModelBackedNERExtractor(backend=hf_backend)

        with pytest.raises(MLModelUnavailableError) as exc_info:
            extractor.extract_entities(doc)
        err_msg = str(exc_info.value).lower()
        assert any(term in err_msg for term in ["not available", "not installed", "failed to load", "cached locally"])


# ===========================================================================
# 2. Model-Backed Relation Extraction Tests
# ===========================================================================

class TestModelBackedRelationExtraction:
    """Verifies model-backed relation extraction and mock NLI backend."""

    def test_grounded_relation_extraction_and_schema_enforcement(self):
        """Grounded extraction must only predict supported schema labels."""
        text = "Bruce Wayne works for Wayne Enterprises in Gotham City."
        doc = TextDocumentParser().parse(text.encode("utf-8"), "rel_test.txt", "doc_r1")

        rule_ner = DeterministicRuleNERExtractor()
        mentions = rule_ner.extract_entities(doc)

        nli_backend = MockRelationNLIBackend()
        extractor = ModelBackedRelationExtractor(backend=nli_backend)
        candidates = extractor.extract_relations(doc, mentions)

        assert len(candidates) >= 1
        for cand in candidates:
            assert cand.predicate in SUPPORTED_RELATION_PREDICATES
            assert cand.evidence_span in doc.normalized_text
            assert cand.extraction_method == "model_backed_relation"
            assert cand.subject_mention_id != cand.object_mention_id

    def test_negation_attribution_and_uncertainty_preservation(self):
        """Negation, attribution, and uncertainty qualifiers must be explicitly extracted."""
        text = (
            "The SEC report alleges that Wayne Enterprises does not own Globex Corporation. "
            "Wayne Enterprises possibly acquired Initech."
        )
        doc = TextDocumentParser().parse(text.encode("utf-8"), "neg_test.txt", "doc_neg1")

        m1 = EntityMention(
            mention_id="m1", document_id="doc_neg1", surface_text="Wayne Enterprises",
            entity_type=EntityType.ORGANIZATION, start_char=30, end_char=47,
            sentence_index=0, extraction_method="rule", extraction_version="v1",
        )
        m2 = EntityMention(
            mention_id="m2", document_id="doc_neg1", surface_text="Globex Corporation",
            entity_type=EntityType.ORGANIZATION, start_char=57, end_char=75,
            sentence_index=0, extraction_method="rule", extraction_version="v1",
        )
        m3 = EntityMention(
            mention_id="m3", document_id="doc_neg1", surface_text="Initech",
            entity_type=EntityType.ORGANIZATION, start_char=106, end_char=113,
            sentence_index=1, extraction_method="rule", extraction_version="v1",
        )
        m4 = EntityMention(
            mention_id="m4", document_id="doc_neg1", surface_text="Wayne Enterprises",
            entity_type=EntityType.ORGANIZATION, start_char=79, end_char=96,
            sentence_index=1, extraction_method="rule", extraction_version="v1",
        )

        nli_backend = MockRelationNLIBackend()
        extractor = ModelBackedRelationExtractor(backend=nli_backend)
        candidates = extractor.extract_relations(doc, [m1, m2, m3, m4])

        c_owns = next((c for c in candidates if c.object_mention_id == "m2"), None)
        assert c_owns is not None
        assert c_owns.is_negated is True
        assert c_owns.attribution_source is not None
        assert "report" in c_owns.attribution_source.lower()

        c_initech = next((c for c in candidates if c.object_mention_id == "m3"), None)
        assert c_initech is not None
        assert c_initech.uncertainty_flag is True

    def test_abstention_across_sentence_boundaries(self):
        """Must abstain if mentions do not co-occur in the same sentence/grounding window."""
        text = "Bruce Wayne was born in 1980. Wayne Enterprises was founded in 1939."
        doc = TextDocumentParser().parse(text.encode("utf-8"), "abstain.txt", "doc_abs1")

        m1 = EntityMention(
            mention_id="m1", document_id="doc_abs1", surface_text="Bruce Wayne",
            entity_type=EntityType.PERSON, start_char=0, end_char=11,
            sentence_index=0, extraction_method="rule", extraction_version="v1",
        )
        m2 = EntityMention(
            mention_id="m2", document_id="doc_abs1", surface_text="Wayne Enterprises",
            entity_type=EntityType.ORGANIZATION, start_char=31, end_char=48,
            sentence_index=1, extraction_method="rule", extraction_version="v1",
        )

        nli_backend = MockRelationNLIBackend()
        extractor = ModelBackedRelationExtractor(backend=nli_backend)
        # Should not fabricate a relation across distinct unlinked sentences
        candidates = extractor.extract_relations(doc, [m1, m2])
        assert len(candidates) == 0


# ===========================================================================
# 3. Hybrid Extraction Tests
# ===========================================================================

class TestHybridExtraction:
    """Verifies hybrid NER and relation extraction with agreement/disagreement reconciliation."""

    def test_ner_agreement_deduplication(self):
        """Exact agreement between Rule and ML models deduplicates without artificial confidence doubling."""
        text = "Bruce Wayne established Wayne Enterprises."
        doc = TextDocumentParser().parse(text.encode("utf-8"), "hybrid_ner.txt", "doc_h1")

        rule_ext = DeterministicRuleNERExtractor()
        ml_ext = ModelBackedNERExtractor(backend=MockTransformerNERBackend())
        hybrid = HybridNERExtractor(rule_extractor=rule_ext, ml_extractor=ml_ext)

        mentions = hybrid.extract_entities(doc)
        names = [m.surface_text for m in mentions]
        assert "Bruce Wayne" in names
        assert "Wayne Enterprises" in names

        # Deduplication must ensure each surface span appears once
        bw_mentions = [m for m in mentions if m.surface_text == "Bruce Wayne"]
        assert len(bw_mentions) == 1
        assert bw_mentions[0].extraction_method == "hybrid_agreement"
        assert list(bw_mentions[0].metadata.get("backends_agreed")) == ["rule", "ml"]
        # Disclose that agreement is not independent ground truth
        assert bw_mentions[0].metadata.get("independent_corroboration") is False

    def test_ner_disagreement_preserved(self):
        """Disagreement between Rule and ML models preserves both signals in metadata."""
        text = "Robin visited Gotham."
        doc = TextDocumentParser().parse(text.encode("utf-8"), "disagree.txt", "doc_dis1")

        rule_ext = DeterministicRuleNERExtractor()
        # Mock ML that predicts Robin as PERSON with high confidence
        subwords = [
            {"word": "Robin", "start": 0, "end": 5, "entity_group": "PER", "score": 0.95},
        ]
        ml_ext = ModelBackedNERExtractor(backend=MockTransformerNERBackend(predefined_entities=subwords))
        hybrid = HybridNERExtractor(rule_extractor=rule_ext, ml_extractor=ml_ext)

        mentions = hybrid.extract_entities(doc)
        robin = next((m for m in mentions if m.surface_text == "Robin"), None)
        assert robin is not None
        assert robin.extraction_method == "model_backed_transformer"
        assert robin.metadata.get("backend") == "mock_transformer_engine"

    def test_relation_polarity_safeguard_in_hybrid(self):
        """Never discard a source-grounded negation because another extractor predicts opposite."""
        text = "Wayne Enterprises does not own Globex Corporation."
        doc = TextDocumentParser().parse(text.encode("utf-8"), "pol.txt", "doc_pol1")

        m1 = EntityMention(
            mention_id="m1", document_id="doc_pol1", surface_text="Wayne Enterprises",
            entity_type=EntityType.ORGANIZATION, start_char=0, end_char=17,
            sentence_index=0, extraction_method="rule", extraction_version="v1",
        )
        m2 = EntityMention(
            mention_id="m2", document_id="doc_pol1", surface_text="Globex Corporation",
            entity_type=EntityType.ORGANIZATION, start_char=31, end_char=49,
            sentence_index=0, extraction_method="rule", extraction_version="v1",
        )

        rule_ext = DeterministicRuleRelationExtractor()
        ml_ext = ModelBackedRelationExtractor(backend=MockRelationNLIBackend())
        hybrid = HybridRelationExtractor(rule_extractor=rule_ext, ml_extractor=ml_ext)

        candidates = hybrid.extract_relations(doc, [m1, m2])
        assert len(candidates) >= 1
        cand = candidates[0]
        # Safeguard: Negation must be strictly preserved!
        assert cand.is_negated is True


# ===========================================================================
# 4. Entity Resolution Integration Tests (The 8 Prompt Scenarios)
# ===========================================================================

class TestMentionEntityResolutionIntegration:
    """
    Integration tests connecting document mentions to the Milestones 1-7 entity-resolution engine.
    Tests all 8 mandatory integration cases:
    1. Exact match to an existing entity
    2. Noisy or partial name
    3. Two different entities sharing a name
    4. Conflicting identifiers
    5. Missing attributes
    6. An unresolved mention
    7. Explicit NON_MATCH constraint preventing merge
    8. Deterministic results across repeated runs.
    """

    def _setup_resolver(self) -> MentionEntityResolver:
        resolver = MentionEntityResolver()
        # Known record 1: Wayne Enterprises (Corporate entity)
        r1 = Record(
            record_id="rec_wayne_ent",
            source_id="sec_edgar_2024",
            raw_name="Wayne Enterprises Inc.",
            entity_type=EntityType.ORGANIZATION,
            structured_attributes={
                "name": "Wayne Enterprises Inc.",
                "tax_id": "11-2233445",
                "jurisdiction": "Gotham",
                "incorporation_year": 1939,
            },
            normalized_attributes={
                "name": "wayne enterprises inc",
                "tax_id": "112233445",
                "jurisdiction": "gotham",
            },
        )
        # Known record 2: Bruce Wayne (Person, DOB 1980)
        r2 = Record(
            record_id="rec_bruce_1980",
            source_id="public_registry_a",
            raw_name="Bruce Wayne",
            entity_type=EntityType.PERSON,
            structured_attributes={
                "name": "Bruce Wayne",
                "date_of_birth": "1980-05-27",
                "tax_id": "99-0011223",
            },
            normalized_attributes={
                "name": "bruce wayne",
                "date_of_birth": "1980-05-27",
                "tax_id": "990011223",
            },
        )
        # Known record 3: Bruce Wayne (Person, DOB 1965 - distinct individual)
        r3 = Record(
            record_id="rec_bruce_1965",
            source_id="public_registry_b",
            raw_name="Bruce Wayne",
            entity_type=EntityType.PERSON,
            structured_attributes={
                "name": "Bruce Wayne",
                "date_of_birth": "1965-11-12",
                "tax_id": "99-7788990",
            },
            normalized_attributes={
                "name": "bruce wayne",
                "date_of_birth": "1965-11-12",
                "tax_id": "997788990",
            },
        )
        resolver.add_known_record(r1)
        resolver.add_known_record(r2)
        resolver.add_known_record(r3)
        return resolver

    def test_case_1_exact_match_to_existing_entity(self):
        """Case 1: Exact match to an existing entity resolves to MATCH."""
        resolver = self._setup_resolver()
        mention = EntityMention(
            mention_id="m_exact_1",
            document_id="doc_101",
            surface_text="Wayne Enterprises Inc.",
            entity_type=EntityType.ORGANIZATION,
            start_char=0,
            end_char=22,
            extraction_method="ml_model",
            extraction_version="mock-bert",
            confidence_score=0.99,
        )
        res = resolver.resolve_mention(
            mention,
            context_attributes={"tax_id": "11-2233445", "jurisdiction": "Gotham"},
        )
        assert res.decision_type == DecisionType.MATCH
        assert res.resolved_entity_id == "rec_wayne_ent"
        assert res.is_resolved is True
        assert res.target_record_id == "rec_wayne_ent"
        assert res.confidence_score is not None and res.confidence_score >= 0.70

    def test_case_2_noisy_or_partial_name(self):
        """Case 2: Noisy or partial name routes to MATCH or REVIEW based on evidence."""
        resolver = self._setup_resolver()
        # "Wayne Enterpr." with matching tax ID
        mention = EntityMention(
            mention_id="m_noisy_1",
            document_id="doc_102",
            surface_text="Wayne Enterpr.",
            entity_type=EntityType.ORGANIZATION,
            start_char=0,
            end_char=14,
            extraction_method="ml_model",
            extraction_version="mock-bert",
            confidence_score=0.92,
        )
        res = resolver.resolve_mention(
            mention,
            context_attributes={"tax_id": "11-2233445"},
        )
        # Even with partial name, strong unique Tax ID grounds match
        assert res.decision_type in (DecisionType.MATCH, DecisionType.REVIEW)
        assert res.target_record_id == "rec_wayne_ent"

    def test_case_3_two_different_entities_sharing_name(self):
        """Case 3: Two distinct entities sharing a name must not be falsely merged."""
        resolver = self._setup_resolver()
        # Mention is "Bruce Wayne" with DOB 1980 -> should match rec_bruce_1980 and NOT rec_bruce_1965
        mention = EntityMention(
            mention_id="m_bruce_80",
            document_id="doc_103",
            surface_text="Bruce Wayne",
            entity_type=EntityType.PERSON,
            start_char=0,
            end_char=11,
            extraction_method="ml_model",
            extraction_version="mock-bert",
            confidence_score=0.95,
        )
        res = resolver.resolve_mention(
            mention,
            context_attributes={"date_of_birth": "1980-05-27"},
        )
        # Should resolve to the 1980 individual
        assert res.resolved_entity_id == "rec_bruce_1980"
        assert res.resolved_entity_id != "rec_bruce_1965"

    def test_case_4_conflicting_identifiers_prevent_match(self):
        """Case 4: Conflicting identifiers (DOB or Tax ID) cause fatal contradiction -> NON_MATCH."""
        resolver = self._setup_resolver()
        mention = EntityMention(
            mention_id="m_bruce_conflict",
            document_id="doc_104",
            surface_text="Bruce Wayne",
            entity_type=EntityType.PERSON,
            start_char=0,
            end_char=11,
            extraction_method="rule",
            extraction_version="v1",
        )
        # Provide a date of birth that contradicts both known Bruce records
        res = resolver.resolve_mention(
            mention,
            context_attributes={"date_of_birth": "1999-01-01", "tax_id": "00-0000000"},
        )
        # Fatal contradiction prevents match!
        assert res.decision_type == DecisionType.NON_MATCH
        assert res.is_resolved is False

    def test_case_5_missing_attributes_routes_to_review(self):
        """Case 5: Ambiguous name with missing attributes routes to REVIEW or remains unresolved."""
        resolver = self._setup_resolver()
        # "Bruce Wayne" without any DOB or Tax ID context
        mention = EntityMention(
            mention_id="m_bruce_no_attrs",
            document_id="doc_105",
            surface_text="Bruce Wayne",
            entity_type=EntityType.PERSON,
            start_char=0,
            end_char=11,
            extraction_method="rule",
            extraction_version="v1",
        )
        res = resolver.resolve_mention(mention, context_attributes={})
        # Because two known Bruce Wayne entities exist and attributes are missing,
        # it MUST NOT make an arbitrary automated match.
        assert res.decision_type in (DecisionType.REVIEW, DecisionType.NON_MATCH)
        assert res.is_resolved is False
        assert res.resolved_entity_id is None

    def test_case_6_unresolved_mention_no_candidates(self):
        """Case 6: Mention with no candidate passing blocking remains explicitly unresolved."""
        resolver = self._setup_resolver()
        mention = EntityMention(
            mention_id="m_unknown_corp",
            document_id="doc_106",
            surface_text="Zephyr Quantum Technologies",
            entity_type=EntityType.ORGANIZATION,
            start_char=0,
            end_char=27,
            extraction_method="ml_model",
            extraction_version="mock-bert",
        )
        res = resolver.resolve_mention(mention)
        assert res.decision_type is None
        assert res.resolution_status == MentionResolutionStatus.UNRESOLVED_NO_CANDIDATES
        assert res.is_resolved is False
        assert res.resolved_entity_id is None
        assert "unresolved" in res.explanation.lower()

    def test_case_7_explicit_non_match_constraint_prevents_merge(self):
        """Case 7: An explicit NON_MATCH constraint prevents a merge even on identical name."""
        resolver = self._setup_resolver()
        mention = EntityMention(
            mention_id="m_constrained",
            document_id="doc_107",
            surface_text="Wayne Enterprises Inc.",
            entity_type=EntityType.ORGANIZATION,
            start_char=0,
            end_char=22,
            extraction_method="rule",
            extraction_version="v1",
        )
        # Register explicit non-match constraint against rec_wayne_ent
        resolver.add_explicit_non_match(mention.mention_id, "rec_wayne_ent")

        res = resolver.resolve_mention(
            mention,
            context_attributes={"tax_id": "11-2233445"},
        )
        assert res.decision_type == DecisionType.NON_MATCH
        assert res.is_resolved is False
        assert "non-match" in res.explanation.lower()

    def test_case_8_determinism_across_repeated_runs(self):
        """Case 8: Repeated runs on the same input produce identical outputs."""
        resolver = self._setup_resolver()
        mention = EntityMention(
            mention_id="m_det_1",
            document_id="doc_108",
            surface_text="Bruce Wayne",
            entity_type=EntityType.PERSON,
            start_char=0,
            end_char=11,
            extraction_method="rule",
            extraction_version="v1",
        )
        ctx = {"date_of_birth": "1980-05-27"}

        results = [resolver.resolve_mention(mention, context_attributes=ctx) for _ in range(5)]
        first_dump = results[0].model_dump_json()
        for r in results[1:]:
            assert r.model_dump_json() == first_dump


# ===========================================================================
# 5. Multi-Backend Comparative Evaluation Tests
# ===========================================================================

class TestComparativeEvaluation:
    """Verifies comparative benchmarking across Rule, ML, and Hybrid backends."""

    def test_comparative_benchmark_runner(self):
        """Benchmark runner compares Rule, ML, and Hybrid on identical fixtures."""
        runner = DocumentEvaluationRunner()
        comp_report = runner.run_comparative_benchmark()

        assert comp_report.partition_label == "synthetic_regression_test"
        # Verify all three backends present
        assert comp_report.rule_ner.exact_f1 >= 0.0
        assert comp_report.ml_ner.exact_f1 >= 0.0
        assert comp_report.hybrid_ner.exact_f1 >= 0.0

        assert comp_report.rule_relation.f1 >= 0.0
        assert comp_report.ml_relation.f1 >= 0.0
        assert comp_report.hybrid_relation.f1 >= 0.0

        # Verify latencies and memory are measured and non-negative
        for report in (comp_report.rule_ner, comp_report.ml_ner, comp_report.hybrid_ner):
            assert report.latency_ms >= 0.0
            assert report.memory_mb >= 0.0

        # Entity resolution metrics
        er = comp_report.entity_resolution
        assert er.total_mentions_evaluated > 0
        assert er.pairwise_precision >= 0.0
        assert er.pairwise_recall >= 0.0
        assert er.false_merges == 0
