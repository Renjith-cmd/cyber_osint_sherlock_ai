"""
Comprehensive Unit and Integration Tests for Milestone 9:
Document Ingestion, Named Entity Recognition & Grounded Relation Extraction.
"""

import json
import os
import subprocess
import sys
import tempfile
import pytest

from src.core.models import (
    EntityType,
    ReviewStatus,
    EvidencePolarity,
    RelationshipEpistemicTier,
)
from src.core.document_ingestion import (
    DocumentFormat,
    DocumentParsingError,
    ExtractionCapabilityError,
    DocumentLimitExceededError,
    IngestionConfig,
    IngestedDocument,
    TextDocumentParser,
    JsonDocumentParser,
    PdfDocumentParser,
    DocumentIngestionService,
)
from src.core.ner import (
    EntityMention,
    DeterministicRuleNERExtractor,
    split_sentences_with_spans,
)
from src.core.relation_extraction import (
    ExtractedRelationCandidate,
    DeterministicRuleRelationExtractor,
)
from src.core.document_pipeline import (
    DocumentExtractionPipeline,
    ExtractionPipelineResult,
)
from src.core.document_evaluation import (
    DocumentEvaluationRunner,
    GoldEntity,
    GoldRelation,
    GoldDocumentFixture,
)
from src.core.document_cli import main as cli_main, run_pipeline_on_file


class TestDocumentIngestion:
    """Test suite for document ingestion, parsing, hashing, and limit guards."""

    def test_text_ingestion_success(self):
        service = DocumentIngestionService()
        raw_text = "This is a confidential investigation memo.\nSecond line of facts."
        doc, is_dup = service.ingest_bytes(
            raw_content=raw_text.encode("utf-8"),
            source_name="memo.txt",
            source_uri="file:///path/memo.txt",
        )

        assert isinstance(doc, IngestedDocument)
        assert doc.format == DocumentFormat.TXT
        assert doc.char_count == len(raw_text)
        assert doc.source_name == "memo.txt"
        assert doc.source_uri == "file:///path/memo.txt"
        assert len(doc.content_hash) == 64
        assert not is_dup
        assert doc.document_id.startswith("doc_")
        assert doc.normalized_text == raw_text

    def test_json_ingestion_success(self):
        service = DocumentIngestionService()
        payload = {"title": "Incident 42", "content": "The suspect departed via London airport."}
        raw_bytes = json.dumps(payload).encode("utf-8")
        doc, is_dup = service.ingest_bytes(
            raw_content=raw_bytes,
            source_name="report.json",
        )

        assert doc.format == DocumentFormat.JSON
        assert "suspect departed via London airport" in doc.normalized_text
        assert not is_dup

    def test_json_list_of_records(self):
        service = DocumentIngestionService()
        payload = [
            {"text": "First intelligence note."},
            {"text": "Second intelligence note."},
        ]
        doc, _ = service.ingest_bytes(
            raw_content=json.dumps(payload).encode("utf-8"),
            source_name="notes.json",
        )
        assert "First intelligence note." in doc.normalized_text
        assert "Second intelligence note." in doc.normalized_text

    def test_json_parsing_error_on_invalid_syntax(self):
        parser = JsonDocumentParser()
        with pytest.raises(DocumentParsingError, match="Invalid JSON syntax"):
            parser.parse(b"{corrupted json content")

    def test_text_parsing_error_on_invalid_encoding(self):
        parser = TextDocumentParser()
        with pytest.raises(DocumentParsingError, match="Failed to decode text document"):
            # Invalid UTF-8 sequence
            parser.parse(b"\xff\xfe\x00\x00invalid")

    def test_pdf_capability_error_handling(self, monkeypatch):
        parser = PdfDocumentParser()
        # When pypdf is not installed, it must raise explicit ExtractionCapabilityError
        monkeypatch.setitem(sys.modules, "pypdf", None)
        with pytest.raises(ExtractionCapabilityError) as exc_info:
            parser.parse(b"%PDF-1.4 dummy pdf bytes")
        assert "PDF extraction is unavailable" in str(exc_info.value)
        assert "TXT and JSON ingestion remain fully operational" in str(exc_info.value)

    def test_pdf_malformed_error_handling_when_installed(self):
        pytest.importorskip("pypdf", reason="pypdf not installed in this environment.")
        parser = PdfDocumentParser()
        with pytest.raises(DocumentParsingError, match="Malformed or unreadable PDF document"):
            parser.parse(b"%PDF-1.4 dummy corrupt truncated bytes")

    def test_guardrail_file_size_limit(self):
        config = IngestionConfig(max_file_size_bytes=100)
        service = DocumentIngestionService(config=config)
        huge_bytes = b"A" * 150
        with pytest.raises(DocumentLimitExceededError, match="exceeds limit"):
            service.ingest_bytes(huge_bytes, source_name="oversize.txt")

    def test_guardrail_text_length_limit(self):
        config = IngestionConfig(max_text_length_chars=50)
        parser = TextDocumentParser()
        with pytest.raises(DocumentLimitExceededError, match="exceeds character limit"):
            parser.parse(b"A" * 60, config=config)

    def test_duplicate_detection(self):
        service = DocumentIngestionService()
        raw = b"Exact identical text content for testing hashing."
        doc1, is_dup1 = service.ingest_bytes(raw, source_name="doc1.txt")
        doc2, is_dup2 = service.ingest_bytes(raw, source_name="doc2.txt")

        assert not is_dup1
        assert is_dup2
        assert doc1.content_hash == doc2.content_hash
        assert service.is_duplicate_content(doc1.content_hash)


class TestNamedEntityRecognition:
    """Test suite for NER extraction, spans, repeated mentions, and normalization."""

    def test_character_offset_correctness(self):
        extractor = DeterministicRuleNERExtractor()
        text = "Dr. John Watson visited Baker Street on 2024-01-15 and spent $50,000 at Acme Corp."
        doc = DocumentIngestionService().ingest(text.encode("utf-8"), source_name="test.txt")
        mentions = extractor.extract_entities(doc)

        assert len(mentions) >= 5
        for m in mentions:
            # Crucial invariant: character offsets refer strictly to normalized_text
            extracted_slice = doc.normalized_text[m.start_char:m.end_char]
            assert extracted_slice == m.surface_text, (
                f"Offset mismatch for {m.surface_text}: expected slice '{extracted_slice}' "
                f"at [{m.start_char}:{m.end_char}]"
            )

    def test_ner_entity_types_and_normalization(self):
        extractor = DeterministicRuleNERExtractor()
        text = "Dr. John Watson paid $10 million on 2023-11-20 to Acme Corp in London."
        doc = DocumentIngestionService().ingest(text.encode("utf-8"), source_name="test.txt")
        mentions = extractor.extract_entities(doc)

        by_type = {m.entity_type: m for m in mentions}
        assert EntityType.PERSON in by_type
        assert EntityType.MONEY in by_type
        assert EntityType.DATE in by_type
        assert EntityType.ORGANIZATION in by_type
        assert EntityType.LOCATION in by_type

        # Verify normalization
        person_m = by_type[EntityType.PERSON]
        assert person_m.surface_text == "Dr. John Watson"
        assert person_m.normalized_value == "John Watson"  # Stripped honorific

        date_m = by_type[EntityType.DATE]
        assert date_m.surface_text == "2023-11-20"
        assert date_m.normalized_value == "2023-11-20"

        money_m = by_type[EntityType.MONEY]
        assert money_m.surface_text == "$10 million"
        assert money_m.normalized_value == "$10000000"

    def test_repeated_entity_mentions_preserved_separately(self):
        extractor = DeterministicRuleNERExtractor()
        text = "Sherlock Holmes arrived in London. Sherlock Holmes investigated the crime. Sherlock Holmes left."
        doc = DocumentIngestionService().ingest(text.encode("utf-8"), source_name="test.txt")
        mentions = extractor.extract_entities(doc)

        holmes_mentions = [m for m in mentions if m.surface_text == "Sherlock Holmes"]
        assert len(holmes_mentions) == 3
        # Invariant: Each mention has a unique ID and non-identical offsets
        mention_ids = {m.mention_id for m in holmes_mentions}
        assert len(mention_ids) == 3
        offsets = [(m.start_char, m.end_char) for m in holmes_mentions]
        assert len(set(offsets)) == 3

    def test_rule_baseline_reports_no_fabricated_confidence(self):
        extractor = DeterministicRuleNERExtractor()
        doc = DocumentIngestionService().ingest(b"Dr. Watson", source_name="test.txt")
        mentions = extractor.extract_entities(doc)
        assert len(mentions) == 1
        assert mentions[0].confidence_score is None
        assert mentions[0].confidence_semantics is None


class TestRelationExtraction:
    """Test suite for relation extraction, evidence grounding, negation, and attribution."""

    def test_supported_predicates_and_evidence_spans(self):
        extractor = DeterministicRuleRelationExtractor()
        text = (
            "Alice Smith works for Cyberdyne Systems.\n"
            "Cyberdyne Systems is located in Tokyo.\n"
            "James Moriarty founded Stark Industries with $500."
        )
        doc = DocumentIngestionService().ingest(text.encode("utf-8"), source_name="test.txt")
        ner = DeterministicRuleNERExtractor()
        mentions = ner.extract_entities(doc)
        relations = extractor.extract_relations(doc, mentions)

        predicates = {r.predicate for r in relations}
        assert "WORKS_FOR" in predicates
        assert "LOCATED_IN" in predicates
        assert "FOUNDED" in predicates

        for r in relations:
            # Evidence span offset fidelity
            assert doc.normalized_text[r.evidence_start_char:r.evidence_end_char] == r.evidence_span
            assert r.evidence_span.strip() in text

    def test_negation_preservation(self):
        extractor = DeterministicRuleRelationExtractor()
        text = "Alice Smith does not work for Cyberdyne Systems."
        doc = DocumentIngestionService().ingest(text.encode("utf-8"), source_name="test.txt")
        ner = DeterministicRuleNERExtractor()
        mentions = ner.extract_entities(doc)
        relations = extractor.extract_relations(doc, mentions)

        assert len(relations) == 1
        rel = relations[0]
        assert rel.predicate == "WORKS_FOR"
        assert rel.is_negated is True
        assert not rel.is_allegation

    def test_attribution_and_allegation_preservation(self):
        extractor = DeterministicRuleRelationExtractor()
        text = "The report alleges that Wayne Enterprises owns Globex Corporation."
        doc = DocumentIngestionService().ingest(text.encode("utf-8"), source_name="test.txt")
        ner = DeterministicRuleNERExtractor()
        mentions = ner.extract_entities(doc)
        relations = extractor.extract_relations(doc, mentions)

        assert len(relations) == 1
        rel = relations[0]
        assert rel.predicate == "OWNS"
        assert rel.is_negated is False
        assert rel.is_allegation is True
        assert "alleges that" in rel.attribution_source

    def test_abstention_on_ambiguous_and_ungrounded_sentences(self):
        extractor = DeterministicRuleRelationExtractor()
        # Sentence mentions entities but has NO valid predicate linking them
        text = "Alice Smith and Sherlock Holmes met representatives in London."
        doc = DocumentIngestionService().ingest(text.encode("utf-8"), source_name="test.txt")
        ner = DeterministicRuleNERExtractor()
        mentions = ner.extract_entities(doc)
        relations = extractor.extract_relations(doc, mentions)

        # Baseline must abstain, not hallucinate relations!
        assert len(relations) == 0


class TestMilestone8Integration:
    """Test suite for Milestone 8 Evidence, Claim, and Graph Store integration."""

    def test_evidence_and_claim_creation(self):
        pipeline = DocumentExtractionPipeline()
        text = "Dr. John Watson works for Sherlock Security."
        res = pipeline.process_document(
            raw_content=text.encode("utf-8"),
            source_name="memo.txt",
        )

        assert len(res.evidence_items) == 1
        ev = res.evidence_items[0]
        assert ev.polarity == EvidencePolarity.SUPPORTING
        assert ev.text_span == text
        assert ev.review_status == ReviewStatus.UNREVIEWED
        assert ev.document_reference == res.document.document_id

        assert len(res.claims) == 1
        claim = res.claims[0]
        assert claim.predicate == "WORKS_FOR"
        assert claim.review_status == ReviewStatus.UNREVIEWED
        assert ev.evidence_id in claim.supporting_evidence_ids

    def test_negated_evidence_mapped_to_contradicting(self):
        pipeline = DocumentExtractionPipeline()
        text = "Alice Smith does not work for Cyberdyne Systems."
        res = pipeline.process_document(
            raw_content=text.encode("utf-8"),
            source_name="negated.txt",
        )

        assert len(res.evidence_items) == 1
        ev = res.evidence_items[0]
        assert ev.polarity == EvidencePolarity.CONTRADICTING

        assert len(res.claims) == 1
        claim = res.claims[0]
        assert ev.evidence_id in claim.contradicting_evidence_ids
        assert len(claim.supporting_evidence_ids) == 0

    def test_human_retraction_preservation_across_reingestion(self):
        """Crucial requirement: Re-ingestion must not overwrite human review decisions."""
        pipeline = DocumentExtractionPipeline()
        text = "Alice Smith works for Cyberdyne Systems."
        raw_bytes = text.encode("utf-8")

        # 1. Initial ingestion
        res1 = pipeline.process_document(raw_bytes, source_name="memo.txt")
        assert len(res1.claims) == 1
        claim_id = res1.claims[0].claim_id
        assert res1.claims[0].review_status == ReviewStatus.UNREVIEWED

        # 2. Human reviewer retracts the claim
        pipeline.store.update_claim_status(
            claim_id=claim_id,
            new_status=ReviewStatus.RETRACTED,
            rationale="Investigation showed Alice Smith was a temporary contractor, not employee.",
            corrected_by="analyst_jane",
        )

        retracted_claim = pipeline.store.get_claim(claim_id)
        assert retracted_claim.review_status == ReviewStatus.RETRACTED

        # 3. Document is re-ingested (e.g. reprocessing pipeline batch)
        res2 = pipeline.process_document(raw_bytes, source_name="memo.txt")

        # Human retraction MUST be preserved!
        assert claim_id in res2.preserved_reviewed_claims
        stored_claim = pipeline.store.get_claim(claim_id)
        assert stored_claim.review_status == ReviewStatus.RETRACTED
        assert len(stored_claim.correction_history) == 1

    def test_idempotent_reprocessing(self):
        pipeline = DocumentExtractionPipeline()
        text = "Sherlock Security is located in London."
        raw_bytes = text.encode("utf-8")

        res1 = pipeline.process_document(raw_bytes, source_name="memo.txt")
        res2 = pipeline.process_document(raw_bytes, source_name="memo.txt")

        assert res1.document.document_id == res2.document.document_id
        assert len(res1.claims) == len(res2.claims)
        assert res1.claims[0].claim_id == res2.claims[0].claim_id


class TestEvaluationAndCLI:
    """Test suite for evaluation harness and CLI commands."""

    def test_synthetic_evaluation_runner(self):
        runner = DocumentEvaluationRunner()
        ner_rep = runner.evaluate_ner()
        rel_rep = runner.evaluate_relations()

        # NER Metrics assertions
        assert ner_rep.total_gold_entities > 0
        assert ner_rep.exact_f1 > 0.8
        assert ner_rep.lenient_f1 == 1.0
        assert ner_rep.type_accuracy_on_matched == 1.0

        # Relation Metrics assertions
        assert rel_rep.total_gold_relations > 0
        assert rel_rep.precision == 1.0
        assert rel_rep.recall == 1.0
        assert rel_rep.evidence_span_accuracy == 1.0
        assert rel_rep.negation_accuracy == 1.0
        assert rel_rep.attribution_accuracy == 1.0
        assert rel_rep.abstention_count >= 1

    def test_cli_sample_run(self):
        code = run_pipeline_on_file(
            file_path="/nonexistent/doc.txt",
            as_json=False,
        )
        assert code == 1

    def test_cli_subprocess_sample_and_evaluate(self):
        py_bin = sys.executable

        # 1. Sample demo run
        proc1 = subprocess.run(
            [py_bin, "-m", "src.core.document_cli", "--sample"],
            capture_output=True,
            text=True,
        )
        assert proc1.returncode == 0
        assert "SHERLOCK AI - DOCUMENT EXTRACTION DOSSIER" in proc1.stdout
        assert "EPISTEMIC NOTICE: Extraction is NOT verification." in proc1.stdout

        # 2. Sample demo run with --json
        proc2 = subprocess.run(
            [py_bin, "-m", "src.core.document_cli", "--sample", "--json"],
            capture_output=True,
            text=True,
        )
        assert proc2.returncode == 0
        data = json.loads(proc2.stdout)
        assert "document" in data
        assert "claims" in data
        assert "evidence" in data

        # 3. Evaluation run
        proc3 = subprocess.run(
            [py_bin, "-m", "src.core.document_cli", "--evaluate"],
            capture_output=True,
            text=True,
        )
        assert proc3.returncode == 0
        assert "SHERLOCK AI - MILESTONE 9 EXTRACTION EVALUATION REPORT" in proc3.stdout


class TestAdversarialRobustness:
    """Targeted regression test suite verifying Audit A, B, C, D findings."""

    def test_audit_a_10_adversarial_cases(self):
        pipeline = DocumentExtractionPipeline()

        # 1. Positive ownership
        r1 = pipeline.process_document(b"Wayne Enterprises owns Globex Corporation.", "c1.txt")
        assert len(r1.relation_candidates) == 1
        assert r1.relation_candidates[0].predicate == "OWNS"
        assert not r1.relation_candidates[0].is_negated

        # 2. Negated ownership ("does not own")
        r2 = pipeline.process_document(b"Wayne Enterprises does not own Globex Corporation.", "c2.txt")
        assert len(r2.relation_candidates) == 1
        assert r2.relation_candidates[0].is_negated is True
        assert r2.evidence_items[0].polarity == EvidencePolarity.CONTRADICTING
        assert r2.claims[0].contradicting_evidence_ids

        # 3. Alleged ownership
        r3 = pipeline.process_document(b"The report alleges that Wayne Enterprises owns Globex Corporation.", "c3.txt")
        assert len(r3.relation_candidates) == 1
        assert r3.relation_candidates[0].is_allegation is True
        assert "alleges" in r3.relation_candidates[0].attribution_source

        # 4. Denied ownership ("denies owning")
        r4 = pipeline.process_document(b"Wayne Enterprises denies owning Globex Corporation.", "c4.txt")
        assert len(r4.relation_candidates) == 1
        assert r4.relation_candidates[0].is_negated is True

        # 5. Uncertainty ("unclear whether")
        r5 = pipeline.process_document(b"It is unclear whether Wayne Enterprises owns Globex Corporation.", "c5.txt")
        assert len(r5.relation_candidates) == 1
        assert r5.relation_candidates[0].uncertainty_flag is True

        # 6. Negated + attributed ("does not own ... according to the report")
        r6 = pipeline.process_document(b"Wayne Enterprises does not own Globex Corporation, according to the report.", "c6.txt")
        assert len(r6.relation_candidates) == 1
        assert r6.relation_candidates[0].is_negated is True
        assert r6.relation_candidates[0].is_allegation is True
        assert "according to" in r6.relation_candidates[0].attribution_source

        # 7. Noun negation ("owns no shares in")
        r7 = pipeline.process_document(b"Wayne Enterprises owns no shares in Globex Corporation.", "c7.txt")
        assert len(r7.relation_candidates) == 1
        assert r7.relation_candidates[0].is_negated is True

        # 8. Correlative conjunction ("not only owns ... but also operates")
        r8 = pipeline.process_document(b"Wayne Enterprises not only owns Globex Corporation but also operates it.", "c8.txt")
        assert len(r8.relation_candidates) == 1
        assert r8.relation_candidates[0].is_negated is False

        # 9. Negative/unestablished finding ("did not establish that" -> uncertainty, not affirmative negation)
        r9 = pipeline.process_document(b"The report did not establish that Wayne Enterprises owns Globex Corporation.", "c9.txt")
        assert len(r9.relation_candidates) == 1
        assert r9.relation_candidates[0].is_negated is False
        assert r9.relation_candidates[0].uncertainty_flag is True
        assert r9.relation_candidates[0].is_allegation is True

        # 10. Multi-sentence contradiction in single document
        doc10 = "Wayne Enterprises owns Globex Corporation. However, Wayne Enterprises denies owning Globex Corporation."
        r10 = pipeline.process_document(doc10.encode("utf-8"), "c10.txt")
        assert len(r10.relation_candidates) == 2
        # One positive, one negated
        neg_flags = {c.is_negated for c in r10.relation_candidates}
        assert neg_flags == {True, False}
        assert len(r10.claims) == 2
        assert r10.claims[0].claim_id != r10.claims[1].claim_id

    def test_audit_a_clause_level_negation_isolation(self):
        pipeline = DocumentExtractionPipeline()
        text = "Alice Smith does not work for Cyberdyne Systems, but Dr. John Watson works for Sherlock Security."
        res = pipeline.process_document(text.encode("utf-8"), "compound.txt")

        assert len(res.relation_candidates) == 2
        cands_by_subj = {c.subject_surface: c for c in res.relation_candidates}
        assert "Alice Smith" in cands_by_subj
        assert "Dr. John Watson" in cands_by_subj

        # Alice must be negated
        assert cands_by_subj["Alice Smith"].is_negated is True
        # Watson must NOT be negated
        assert cands_by_subj["Dr. John Watson"].is_negated is False

    def test_audit_b_unicode_and_emoji_offsets(self):
        pipeline = DocumentExtractionPipeline()
        text = "Dr. René François works for Cyberdyne Systems. Angela Müller visited Berlin. 🔍 Dr. John Watson at Baker Street 🚀"
        res = pipeline.process_document(text.encode("utf-8"), "unicode.txt")

        # Every mention's offset must match normalized text slice exactly
        assert len(res.mentions) >= 6
        for m in res.mentions:
            slice_text = res.document.normalized_text[m.start_char:m.end_char]
            assert slice_text == m.surface_text

        # Verify accented names recognized
        surfaces = {m.surface_text for m in res.mentions}
        assert "Dr. René François" in surfaces
        assert "Angela Müller" in surfaces

    def test_audit_b_empty_and_whitespace_documents_rejected(self):
        service = DocumentIngestionService()
        with pytest.raises(DocumentParsingError, match="empty or contains no extractable"):
            service.ingest(b"", "empty.txt")

        with pytest.raises(DocumentParsingError, match="empty or contains no extractable"):
            service.ingest(b"   \n\t   ", "whitespace.txt")

    def test_audit_b_nested_json_extraction(self):
        service = DocumentIngestionService()
        raw = b'{"status": 200, "response": {"data": {"article": "Dr. John Watson works for Sherlock Security."}}}'
        doc = service.ingest(raw, "nested.json", doc_format=DocumentFormat.JSON)
        assert "Dr. John Watson works for Sherlock Security." in doc.normalized_text

    def test_audit_c_unresolved_participants_remain_separate(self):
        pipeline = DocumentExtractionPipeline()
        # Same name in two separate sentences produces two distinct provisional entity IDs
        text = "Dr. Watson visited London. Later, Dr. Watson arrived in Tokyo."
        res = pipeline.process_document(text.encode("utf-8"), "repeat.txt")

        watson_mentions = [m for m in res.mentions if "Watson" in m.surface_text]
        assert len(watson_mentions) == 2
        assert watson_mentions[0].mention_id != watson_mentions[1].mention_id

        # Verify they create two distinct provisional entities
        id1 = pipeline._resolve_entity_reference(watson_mentions[0])
        id2 = pipeline._resolve_entity_reference(watson_mentions[1])
        assert id1 != id2
        assert id1.startswith("unresolved_")
        assert id2.startswith("unresolved_")

    def test_audit_d_mutation_checks(self):
        from src.core.ner import BaseNERExtractor
        from src.core.relation_extraction import BaseRelationExtractor

        runner = DocumentEvaluationRunner()
        base_ner = runner.evaluate_ner()
        base_rel = runner.evaluate_relations()

        # 1. Mutate NER: drop first prediction -> F1 must drop
        class DropNERExtractor(BaseNERExtractor):
            def __init__(self, real):
                self.real = real
            def extract_entities(self, doc):
                res = self.real.extract_entities(doc)
                return res[1:] if res else []

        mut_ner_rep = DocumentEvaluationRunner(ner_extractor=DropNERExtractor(runner.ner_extractor)).evaluate_ner()
        assert mut_ner_rep.exact_f1 < base_ner.exact_f1

        # 2. Mutate Relation: invert negation -> negation accuracy must drop
        class InvertNegRelExtractor(BaseRelationExtractor):
            def __init__(self, real):
                self.real = real
            def extract_relations(self, doc, mentions):
                rels = self.real.extract_relations(doc, mentions)
                return [
                    ExtractedRelationCandidate(
                        candidate_id=r.candidate_id,
                        document_id=r.document_id,
                        subject_mention_id=r.subject_mention_id,
                        subject_surface=r.subject_surface,
                        subject_type=r.subject_type,
                        predicate=r.predicate,
                        object_mention_id=r.object_mention_id,
                        object_surface=r.object_surface,
                        object_type=r.object_type,
                        evidence_span=r.evidence_span,
                        evidence_start_char=r.evidence_start_char,
                        evidence_end_char=r.evidence_end_char,
                        is_negated=not r.is_negated,
                        is_allegation=r.is_allegation,
                        attribution_source=r.attribution_source,
                        uncertainty_flag=r.uncertainty_flag,
                        temporal_context=r.temporal_context,
                        extraction_method=r.extraction_method,
                        extraction_version=r.extraction_version,
                    )
                    for r in rels
                ]

        mut_rel_rep = DocumentEvaluationRunner(relation_extractor=InvertNegRelExtractor(runner.relation_extractor)).evaluate_relations()
        assert mut_rel_rep.negation_accuracy < base_rel.negation_accuracy
