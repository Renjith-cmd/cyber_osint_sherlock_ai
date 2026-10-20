"""
Document Extraction Evaluation Harness for Sherlock AI (Milestone 9).

Provides:
- Fictional, manually-labeled gold standard fixtures completely isolated from runtime logic.
- Comprehensive NER evaluation:
  - Exact-span precision, recall, F1
  - Partial-span overlap precision, recall, F1
  - Entity-type accuracy on matched spans
  - False positive, false negative, and type error breakdowns
- Comprehensive Relation evaluation:
  - Strict (subject, predicate, object) matching
  - Relation precision, recall, F1
  - Evidence-span grounding correctness
  - Negation and attribution classification accuracy
  - Abstention and unsupported relation tracking
- Synthetic test fixtures covering:
  - Standard positive relations
  - Explicitly negated relations
  - Attributed / allegation relations
  - Repeated entity mentions
  - Ambiguous / ungrounded co-occurrences (abstention cases)
"""

from typing import Dict, List, Optional, Tuple, Any, Set
import time
import tracemalloc
from pydantic import Field

from src.core.models import ImmutableBaseModel, EntityType, Record, DecisionType
from src.core.document_ingestion import DocumentIngestionService, IngestedDocument, DocumentFormat
from src.core.ner import (
    BaseNERExtractor,
    DeterministicRuleNERExtractor,
    ModelBackedNERExtractor,
    HybridNERExtractor,
    HuggingFaceNERBackend,
    EntityMention,
)
from src.core.relation_extraction import (
    BaseRelationExtractor,
    DeterministicRuleRelationExtractor,
    ModelBackedRelationExtractor,
    HybridRelationExtractor,
    ExtractedRelationCandidate,
)
from src.core.mention_entity_resolution import (
    MentionEntityResolver,
    MentionResolutionResult,
    MentionResolutionStatus,
    mention_to_record,
)


class GoldEntity(ImmutableBaseModel):
    """Ground truth entity mention for evaluation only."""
    surface_text: str
    entity_type: EntityType
    start_char: int
    end_char: int
    normalized_value: Optional[str] = None


class GoldRelation(ImmutableBaseModel):
    """Ground truth relation candidate for evaluation only."""
    subject_surface: str
    predicate: str
    object_surface: str
    is_negated: bool = False
    is_allegation: bool = False
    evidence_text_substring: str


class GoldDocumentFixture(ImmutableBaseModel):
    """Deterministic synthetic fixture containing document text and isolated gold labels."""
    fixture_id: str
    title: str
    category: str  # positive, negated, attributed, ambiguous, repeated, negative
    text: str
    gold_entities: List[GoldEntity]
    gold_relations: List[GoldRelation] = Field(default_factory=list)


class NEREvaluationReport(ImmutableBaseModel):
    """Detailed NER metric report."""
    total_gold_entities: int
    total_predicted_mentions: int
    exact_matches: int
    partial_span_matches: int
    type_errors: int
    false_positives: int
    false_negatives: int
    exact_precision: float
    exact_recall: float
    exact_f1: float
    lenient_precision: float
    lenient_recall: float
    lenient_f1: float
    type_accuracy_on_matched: float
    errors_by_type: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    metrics_by_entity_type: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    partial_span_policy_note: str
    latency_ms: Optional[float] = None
    memory_mb: Optional[float] = None


class RelationEvaluationReport(ImmutableBaseModel):
    """Detailed relation extraction metric report."""
    total_gold_relations: int
    total_predicted_relations: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    evidence_span_correct_count: int
    evidence_span_accuracy: float
    negation_accuracy: float
    attribution_accuracy: float
    abstention_count: int
    unsupported_candidates_count: int
    breakdown_by_predicate: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    latency_ms: Optional[float] = None
    memory_mb: Optional[float] = None


class EntityResolutionEvaluationReport(ImmutableBaseModel):
    """Detailed entity resolution metric report connecting mentions to records."""
    total_mentions_evaluated: int
    true_matches: int
    false_merges: int
    missed_matches: int
    true_non_matches: int
    unresolved_no_candidates: int = 0
    reviews: int
    review_rate: float
    candidate_recall: float
    pairwise_precision: float
    pairwise_recall: float
    pairwise_f1: float
    latency_ms: float = 0.0
    memory_mb: float = 0.0


class MultiBackendComparativeReport(ImmutableBaseModel):
    """Comparative evaluation across rule, ML, and hybrid backends."""
    partition_label: str  # e.g., 'synthetic_regression_test', 'development', 'held_out_validation'
    rule_ner: NEREvaluationReport
    ml_ner: NEREvaluationReport
    hybrid_ner: NEREvaluationReport
    rule_relation: RelationEvaluationReport
    ml_relation: RelationEvaluationReport
    hybrid_relation: RelationEvaluationReport
    entity_resolution: EntityResolutionEvaluationReport
    comparative_summary: Dict[str, Any] = Field(default_factory=dict)
    ml_backend_type: str = "mock_simulation"
    is_mock_ml_simulation: bool = True
    evaluation_provenance: str = "Offline deterministic simulation (not live transformer weights)"
    epistemic_disclaimer: str = (
        "ML performance figures represent offline heuristic/mock simulation for pipeline validation. "
        "Latency and memory reflect CPU regular-expression processing, NOT neural network inference. "
        "Do not interpret as measured transformer model accuracy or latency."
    )


class DocumentEvaluationRunner:
    """
    Harness to evaluate NER and Relation Extraction on isolated gold fixtures.
    """

    def __init__(
        self,
        ner_extractor: Optional[BaseNERExtractor] = None,
        relation_extractor: Optional[BaseRelationExtractor] = None,
    ):
        self.ner_extractor = ner_extractor or DeterministicRuleNERExtractor()
        self.relation_extractor = relation_extractor or DeterministicRuleRelationExtractor()
        self.ingestion_service = DocumentIngestionService()

    @staticmethod
    def get_synthetic_benchmark_suite() -> List[GoldDocumentFixture]:
        """
        Deterministic, manually labeled synthetic benchmark suite.
        Contains positive, negated, attributed, ambiguous, repeated, and negative cases.
        """
        fixtures: List[GoldDocumentFixture] = []

        # 1. Positive case: Standard employment and location
        doc1_text = "Dr. John Watson works for Sherlock Security. Sherlock Security is located in London."
        # Spans:
        # "Dr. John Watson" [0:15] PERSON
        # "Sherlock Security" [26:43] ORGANIZATION
        # "Sherlock Security" [45:62] ORGANIZATION
        # "London" [77:83] LOCATION
        fixtures.append(
            GoldDocumentFixture(
                fixture_id="synth_pos_01",
                title="Employment and Location Grounding",
                category="positive",
                text=doc1_text,
                gold_entities=[
                    GoldEntity(surface_text="Dr. John Watson", entity_type=EntityType.PERSON, start_char=0, end_char=15),
                    GoldEntity(surface_text="Sherlock Security", entity_type=EntityType.ORGANIZATION, start_char=26, end_char=43),
                    GoldEntity(surface_text="Sherlock Security", entity_type=EntityType.ORGANIZATION, start_char=45, end_char=62),
                    GoldEntity(surface_text="London", entity_type=EntityType.LOCATION, start_char=77, end_char=83),
                ],
                gold_relations=[
                    GoldRelation(
                        subject_surface="Dr. John Watson",
                        predicate="WORKS_FOR",
                        object_surface="Sherlock Security",
                        is_negated=False,
                        is_allegation=False,
                        evidence_text_substring="Dr. John Watson works for Sherlock Security.",
                    ),
                    GoldRelation(
                        subject_surface="Sherlock Security",
                        predicate="LOCATED_IN",
                        object_surface="London",
                        is_negated=False,
                        is_allegation=False,
                        evidence_text_substring="Sherlock Security is located in London.",
                    ),
                ],
            )
        )

        # 2. Negated case: Denied/Negated association
        doc2_text = "Alice Smith does not work for Cyberdyne Systems."
        # "Alice Smith" [0:11] PERSON
        # "Cyberdyne Systems" [30:47] ORGANIZATION
        fixtures.append(
            GoldDocumentFixture(
                fixture_id="synth_neg_01",
                title="Negated Employment Assertion",
                category="negated",
                text=doc2_text,
                gold_entities=[
                    GoldEntity(surface_text="Alice Smith", entity_type=EntityType.PERSON, start_char=0, end_char=11),
                    GoldEntity(surface_text="Cyberdyne Systems", entity_type=EntityType.ORGANIZATION, start_char=30, end_char=47),
                ],
                gold_relations=[
                    GoldRelation(
                        subject_surface="Alice Smith",
                        predicate="WORKS_FOR",
                        object_surface="Cyberdyne Systems",
                        is_negated=True,
                        is_allegation=False,
                        evidence_text_substring="Alice Smith does not work for Cyberdyne Systems.",
                    ),
                ],
            )
        )

        # 3. Attributed / Allegation case:
        doc3_text = "The report alleges that Wayne Enterprises owns Globex Corporation."
        # "Wayne Enterprises" [24:41] ORGANIZATION
        # "Globex Corporation" [47:65] ORGANIZATION
        fixtures.append(
            GoldDocumentFixture(
                fixture_id="synth_allegation_01",
                title="Attributed Ownership Allegation",
                category="attributed",
                text=doc3_text,
                gold_entities=[
                    GoldEntity(surface_text="Wayne Enterprises", entity_type=EntityType.ORGANIZATION, start_char=24, end_char=41),
                    GoldEntity(surface_text="Globex Corporation", entity_type=EntityType.ORGANIZATION, start_char=47, end_char=65),
                ],
                gold_relations=[
                    GoldRelation(
                        subject_surface="Wayne Enterprises",
                        predicate="OWNS",
                        object_surface="Globex Corporation",
                        is_negated=False,
                        is_allegation=True,
                        evidence_text_substring="The report alleges that Wayne Enterprises owns Globex Corporation.",
                    ),
                ],
            )
        )

        # 4. Repeated mentions across multiple sentences
        doc4_text = "Sherlock Holmes visited Tokyo on 2024-05-10. Later, Sherlock Holmes returned to London."
        # "Sherlock Holmes" [0:15] PERSON
        # "Tokyo" [24:29] LOCATION
        # "2024-05-10" [33:43] DATE
        # "Sherlock Holmes" [52:67] PERSON
        # "London" [80:86] LOCATION
        fixtures.append(
            GoldDocumentFixture(
                fixture_id="synth_repeated_01",
                title="Repeated Mention Extraction and Dates",
                category="repeated",
                text=doc4_text,
                gold_entities=[
                    GoldEntity(surface_text="Sherlock Holmes", entity_type=EntityType.PERSON, start_char=0, end_char=15),
                    GoldEntity(surface_text="Tokyo", entity_type=EntityType.LOCATION, start_char=24, end_char=29),
                    GoldEntity(surface_text="2024-05-10", entity_type=EntityType.DATE, start_char=33, end_char=43),
                    GoldEntity(surface_text="Sherlock Holmes", entity_type=EntityType.PERSON, start_char=52, end_char=67),
                    GoldEntity(surface_text="London", entity_type=EntityType.LOCATION, start_char=80, end_char=86),
                ],
                gold_relations=[],  # No structured organization/location relations asserted
            )
        )

        # 5. Ambiguous / Distractor case where extractor must ABSTAIN:
        doc5_text = "In Paris, Agent Smith and Dr. Watson met representatives from Acme Corp and Cyberdyne Systems."
        # Multiple subjects and multiple objects in single sentence with no distinct binary predicate linking them
        fixtures.append(
            GoldDocumentFixture(
                fixture_id="synth_ambiguous_01",
                title="Complex Multi-Entity Sentence (Abstention Required)",
                category="ambiguous",
                text=doc5_text,
                gold_entities=[
                    GoldEntity(surface_text="Paris", entity_type=EntityType.LOCATION, start_char=3, end_char=8),
                    GoldEntity(surface_text="Agent Smith", entity_type=EntityType.PERSON, start_char=10, end_char=21),
                    GoldEntity(surface_text="Dr. Watson", entity_type=EntityType.PERSON, start_char=26, end_char=36),
                    GoldEntity(surface_text="Acme Corp", entity_type=EntityType.ORGANIZATION, start_char=62, end_char=71),
                    GoldEntity(surface_text="Cyberdyne Systems", entity_type=EntityType.ORGANIZATION, start_char=76, end_char=93),
                ],
                gold_relations=[],  # Baseline MUST abstain, not invent relations!
            )
        )

        # 6. Founder relation case with Money
        doc6_text = "James Moriarty founded Stark Industries with $10 million."
        # "James Moriarty" [0:14] PERSON
        # "Stark Industries" [23:39] ORGANIZATION
        # "$10 million" [45:56] MONEY
        fixtures.append(
            GoldDocumentFixture(
                fixture_id="synth_founder_01",
                title="Founder Predicate with Money Amount",
                category="positive",
                text=doc6_text,
                gold_entities=[
                    GoldEntity(surface_text="James Moriarty", entity_type=EntityType.PERSON, start_char=0, end_char=14),
                    GoldEntity(surface_text="Stark Industries", entity_type=EntityType.ORGANIZATION, start_char=23, end_char=39),
                    GoldEntity(surface_text="$10 million", entity_type=EntityType.MONEY, start_char=45, end_char=56),
                ],
                gold_relations=[
                    GoldRelation(
                        subject_surface="James Moriarty",
                        predicate="FOUNDED",
                        object_surface="Stark Industries",
                        is_negated=False,
                        is_allegation=False,
                        evidence_text_substring="James Moriarty founded Stark Industries with $10 million.",
                    )
                ],
            )
        )

        return fixtures

    def evaluate_ner(self, fixtures: Optional[List[GoldDocumentFixture]] = None) -> NEREvaluationReport:
        suite = fixtures or self.get_synthetic_benchmark_suite()

        tracemalloc.start()
        t0 = time.perf_counter()

        total_gold = 0
        total_pred = 0
        exact_matches = 0
        partial_span_matches = 0
        type_errors = 0
        false_positives = 0
        false_negatives = 0
        errors_by_type: Dict[str, Dict[str, int]] = {}

        gold_by_type: Dict[str, int] = {}
        pred_by_type: Dict[str, int] = {}
        exact_by_type: Dict[str, int] = {}

        for fix in suite:
            doc = self.ingestion_service.ingest(
                raw_content=fix.text.encode("utf-8"),
                source_name=f"fixture_{fix.fixture_id}.txt",
                doc_format=DocumentFormat.TXT,
            )
            predictions = self.ner_extractor.extract_entities(doc)

            total_gold += len(fix.gold_entities)
            total_pred += len(predictions)

            for g in fix.gold_entities:
                g_t = g.entity_type.value
                gold_by_type[g_t] = gold_by_type.get(g_t, 0) + 1

            for p in predictions:
                p_t = p.entity_type.value
                pred_by_type[p_t] = pred_by_type.get(p_t, 0) + 1

            matched_gold_indices: Set[int] = set()
            matched_pred_indices: Set[int] = set()

            # First pass: Exact span matching
            for p_idx, pred in enumerate(predictions):
                for g_idx, gold in enumerate(fix.gold_entities):
                    if g_idx in matched_gold_indices:
                        continue
                    if pred.start_char == gold.start_char and pred.end_char == gold.end_char:
                        if pred.entity_type == gold.entity_type:
                            exact_matches += 1
                            t_val = gold.entity_type.value
                            exact_by_type[t_val] = exact_by_type.get(t_val, 0) + 1
                        else:
                            type_errors += 1
                            t_gold = gold.entity_type.value
                            t_pred = pred.entity_type.value
                            errors_by_type.setdefault(t_gold, {}).setdefault(t_pred, 0)
                            errors_by_type[t_gold][t_pred] += 1
                        matched_gold_indices.add(g_idx)
                        matched_pred_indices.add(p_idx)
                        break

            # Second pass: Partial span overlap matching on remaining
            for p_idx, pred in enumerate(predictions):
                if p_idx in matched_pred_indices:
                    continue
                for g_idx, gold in enumerate(fix.gold_entities):
                    if g_idx in matched_gold_indices:
                        continue
                    if max(pred.start_char, gold.start_char) < min(pred.end_char, gold.end_char):
                        partial_span_matches += 1
                        matched_gold_indices.add(g_idx)
                        matched_pred_indices.add(p_idx)
                        break

            # Unmatched predictions are False Positives
            for p_idx in range(len(predictions)):
                if p_idx not in matched_pred_indices:
                    false_positives += 1

            # Unmatched gold are False Negatives
            for g_idx in range(len(fix.gold_entities)):
                if g_idx not in matched_gold_indices:
                    false_negatives += 1

        t1 = time.perf_counter()
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        exact_p = exact_matches / total_pred if total_pred > 0 else 0.0
        exact_r = exact_matches / total_gold if total_gold > 0 else 0.0
        exact_f1 = (2 * exact_p * exact_r / (exact_p + exact_r)) if (exact_p + exact_r) > 0 else 0.0

        lenient_matches = exact_matches + partial_span_matches
        lenient_p = lenient_matches / total_pred if total_pred > 0 else 0.0
        lenient_r = lenient_matches / total_gold if total_gold > 0 else 0.0
        lenient_f1 = (2 * lenient_p * lenient_r / (lenient_p + lenient_r)) if (lenient_p + lenient_r) > 0 else 0.0

        matched_spans = exact_matches + type_errors
        type_acc = (exact_matches / matched_spans) if matched_spans > 0 else 1.0

        metrics_by_type: Dict[str, Dict[str, float]] = {}
        all_types = sorted(set(list(gold_by_type.keys()) + list(pred_by_type.keys())))
        for t_name in all_types:
            g_cnt = gold_by_type.get(t_name, 0)
            p_cnt = pred_by_type.get(t_name, 0)
            m_cnt = exact_by_type.get(t_name, 0)
            t_p = m_cnt / p_cnt if p_cnt > 0 else 0.0
            t_r = m_cnt / g_cnt if g_cnt > 0 else 0.0
            t_f1 = (2 * t_p * t_r / (t_p + t_r)) if (t_p + t_r) > 0 else 0.0
            metrics_by_type[t_name] = {
                "precision": round(t_p, 4),
                "recall": round(t_r, 4),
                "f1": round(t_f1, 4),
                "gold_count": float(g_cnt),
                "pred_count": float(p_cnt),
                "matches": float(m_cnt),
            }

        return NEREvaluationReport(
            total_gold_entities=total_gold,
            total_predicted_mentions=total_pred,
            exact_matches=exact_matches,
            partial_span_matches=partial_span_matches,
            type_errors=type_errors,
            false_positives=false_positives,
            false_negatives=false_negatives,
            exact_precision=round(exact_p, 4),
            exact_recall=round(exact_r, 4),
            exact_f1=round(exact_f1, 4),
            lenient_precision=round(lenient_p, 4),
            lenient_recall=round(lenient_r, 4),
            lenient_f1=round(lenient_f1, 4),
            type_accuracy_on_matched=round(type_acc, 4),
            errors_by_type=errors_by_type,
            metrics_by_entity_type=metrics_by_type,
            partial_span_policy_note=(
                "Exact metric requires identical character offsets [start_char, end_char) and matching EntityType. "
                "Partial metric credits any token overlap > 0. Partial spans are excluded from exact precision."
            ),
            latency_ms=round((t1 - t0) * 1000.0, 2),
            memory_mb=round(peak_mem / (1024 * 1024), 3),
        )

    def evaluate_relations(self, fixtures: Optional[List[GoldDocumentFixture]] = None) -> RelationEvaluationReport:
        suite = fixtures or self.get_synthetic_benchmark_suite()

        tracemalloc.start()
        t0 = time.perf_counter()

        total_gold = 0
        total_pred = 0
        tp = 0
        fp = 0
        fn = 0
        evidence_correct = 0
        negation_correct = 0
        negation_tested = 0
        attribution_correct = 0
        attribution_tested = 0
        abstentions = 0
        unsupported_count = 0
        breakdown: Dict[str, Dict[str, int]] = {}

        for fix in suite:
            doc = self.ingestion_service.ingest(
                raw_content=fix.text.encode("utf-8"),
                source_name=f"fixture_{fix.fixture_id}.txt",
                doc_format=DocumentFormat.TXT,
            )
            mentions = self.ner_extractor.extract_entities(doc)
            pred_relations = self.relation_extractor.extract_relations(doc, mentions)

            total_gold += len(fix.gold_relations)
            total_pred += len(pred_relations)

            if len(fix.gold_relations) == 0:
                if len(pred_relations) == 0:
                    abstentions += 1
                else:
                    unsupported_count += len(pred_relations)

            matched_gold: Set[int] = set()
            matched_pred: Set[int] = set()

            for p_idx, pred in enumerate(pred_relations):
                pred_matched = False
                for g_idx, gold in enumerate(fix.gold_relations):
                    if g_idx in matched_gold:
                        continue

                    subj_match = (
                        pred.subject_surface.strip().lower() == gold.subject_surface.strip().lower()
                        or gold.subject_surface.strip().lower() in pred.subject_surface.strip().lower()
                    )
                    obj_match = (
                        pred.object_surface.strip().lower() == gold.object_surface.strip().lower()
                        or gold.object_surface.strip().lower() in pred.object_surface.strip().lower()
                    )
                    pred_match = pred.predicate == gold.predicate

                    if subj_match and obj_match and pred_match:
                        tp += 1
                        pred_matched = True
                        matched_gold.add(g_idx)
                        matched_pred.add(p_idx)

                        if gold.evidence_text_substring in pred.evidence_span:
                            evidence_correct += 1

                        negation_tested += 1
                        if pred.is_negated == gold.is_negated:
                            negation_correct += 1

                        attribution_tested += 1
                        if pred.is_allegation == gold.is_allegation:
                            attribution_correct += 1

                        break

                if not pred_matched:
                    fp += 1
                    unsupported_count += 1

            for g_idx in range(len(fix.gold_relations)):
                if g_idx not in matched_gold:
                    fn += 1

        t1 = time.perf_counter()
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        p = tp / total_pred if total_pred > 0 else 0.0
        r = tp / total_gold if total_gold > 0 else 0.0
        f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0

        ev_acc = (evidence_correct / tp) if tp > 0 else 1.0
        neg_acc = (negation_correct / negation_tested) if negation_tested > 0 else 1.0
        attr_acc = (attribution_correct / attribution_tested) if attribution_tested > 0 else 1.0

        return RelationEvaluationReport(
            total_gold_relations=total_gold,
            total_predicted_relations=total_pred,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            precision=round(p, 4),
            recall=round(r, 4),
            f1=round(f1, 4),
            evidence_span_correct_count=evidence_correct,
            evidence_span_accuracy=round(ev_acc, 4),
            negation_accuracy=round(neg_acc, 4),
            attribution_accuracy=round(attr_acc, 4),
            abstention_count=abstentions,
            unsupported_candidates_count=unsupported_count,
            breakdown_by_predicate=breakdown,
            latency_ms=round((t1 - t0) * 1000.0, 2),
            memory_mb=round(peak_mem / (1024 * 1024), 3),
        )

    def evaluate_entity_resolution(
        self,
        resolver: MentionEntityResolver,
        test_queries: List[Tuple[EntityMention, Optional[str]]],
    ) -> EntityResolutionEvaluationReport:
        """
        Evaluate MentionEntityResolver on test mention queries against known records.
        test_queries: List of (EntityMention, expected_target_record_id_or_None).
        """
        tracemalloc.start()
        t0 = time.perf_counter()

        true_matches = 0
        false_merges = 0
        missed_matches = 0
        true_non_matches = 0
        unresolved_no_candidates = 0
        reviews = 0
        candidate_retrieved = 0
        total_gold_matches = sum(1 for _, expected in test_queries if expected is not None)

        for mention, expected_target_id in test_queries:
            res = resolver.resolve_mention(mention)

            if expected_target_id is not None:
                # Gold is a match
                if res.decision_type == DecisionType.MATCH:
                    if res.resolved_entity_id == expected_target_id:
                        true_matches += 1
                        candidate_retrieved += 1
                    else:
                        false_merges += 1
                elif res.decision_type == DecisionType.REVIEW:
                    reviews += 1
                    missed_matches += 1
                    if res.target_record_id == expected_target_id:
                        candidate_retrieved += 1
                else:
                    missed_matches += 1
            else:
                # Gold is a non-match / unresolved
                if (
                    res.resolution_status == MentionResolutionStatus.UNRESOLVED_NO_CANDIDATES
                    or res.decision_type is None
                ):
                    unresolved_no_candidates += 1
                elif res.decision_type == DecisionType.NON_MATCH:
                    true_non_matches += 1
                elif res.decision_type == DecisionType.REVIEW:
                    reviews += 1
                elif res.decision_type == DecisionType.MATCH:
                    false_merges += 1

        t1 = time.perf_counter()
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        n = len(test_queries)
        rev_rate = reviews / n if n > 0 else 0.0
        cand_recall = candidate_retrieved / total_gold_matches if total_gold_matches > 0 else 1.0

        p = true_matches / (true_matches + false_merges) if (true_matches + false_merges) > 0 else 0.0
        r = true_matches / total_gold_matches if total_gold_matches > 0 else 0.0
        f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0

        return EntityResolutionEvaluationReport(
            total_mentions_evaluated=n,
            true_matches=true_matches,
            false_merges=false_merges,
            missed_matches=missed_matches,
            true_non_matches=true_non_matches,
            unresolved_no_candidates=unresolved_no_candidates,
            reviews=reviews,
            review_rate=round(rev_rate, 4),
            candidate_recall=round(cand_recall, 4),
            pairwise_precision=round(p, 4),
            pairwise_recall=round(r, 4),
            pairwise_f1=round(f1, 4),
            latency_ms=round((t1 - t0) * 1000.0, 2),
            memory_mb=round(peak_mem / (1024 * 1024), 3),
        )

    def run_comparative_benchmark(
        self,
        fixtures: Optional[List[GoldDocumentFixture]] = None,
        partition_label: str = "synthetic_regression_test",
        use_real_model: bool = False,
    ) -> MultiBackendComparativeReport:
        """
        Executes comparative evaluation across 'rule', 'ml', and 'hybrid' backends.
        When use_real_model=True, executes genuine pretrained Hugging Face transformer
        inference (dslim/bert-base-NER) rather than offline regex mock simulation.
        """
        suite = fixtures or self.get_synthetic_benchmark_suite()

        # 1. Rule Backend
        runner_rule = DocumentEvaluationRunner(
            ner_extractor=DeterministicRuleNERExtractor(),
            relation_extractor=DeterministicRuleRelationExtractor(),
        )
        rep_ner_rule = runner_rule.evaluate_ner(suite)
        rep_rel_rule = runner_rule.evaluate_relations(suite)

        # 2. ML Backend (Real Pretrained Transformer or Offline Mock Simulation)
        if use_real_model:
            ml_ner_backend = HuggingFaceNERBackend(model_name="dslim/bert-base-NER", device="cpu")
            ml_ner_ext = ModelBackedNERExtractor(backend=ml_ner_backend)
            # Warm up tokenizer & model on dummy input to ensure latency reflects steady state
            dummy_doc = runner_rule.ingestion_service.ingest(b"Warm up text.", "warmup.txt")
            ml_ner_ext.extract_entities(dummy_doc)

            # For relations, real NLI models are documented as unviable due to ungrounded sentence classification
            ml_rel_ext = ModelBackedRelationExtractor(use_mock_backend=True)

            runner_ml = DocumentEvaluationRunner(
                ner_extractor=ml_ner_ext,
                relation_extractor=ml_rel_ext,
            )
            rep_ner_ml = runner_ml.evaluate_ner(suite)
            rep_rel_ml = runner_ml.evaluate_relations(suite)

            # 3. Hybrid Backend (Rule + Real Pretrained ML)
            runner_hybrid = DocumentEvaluationRunner(
                ner_extractor=HybridNERExtractor(
                    rule_extractor=DeterministicRuleNERExtractor(),
                    ml_extractor=ml_ner_ext,
                    allow_rule_fallback=True,
                ),
                relation_extractor=HybridRelationExtractor(
                    ml_extractor=ml_rel_ext,
                    allow_rule_fallback=True,
                ),
            )
            rep_ner_hybrid = runner_hybrid.evaluate_ner(suite)
            rep_rel_hybrid = runner_hybrid.evaluate_relations(suite)

            ml_backend_type = "real_dslim/bert-base-NER"
            is_mock_ml = False
            provenance = "Genuine pretrained transformer inference (dslim/bert-base-NER, 107.7M parameters on CPU)"
            disclaimer = (
                "NER metrics reflect genuine pretrained BERT-base token classification on CPU. "
                "CoNLL-2003 tagset does not support DATE/MONEY. Relation extraction uses simulation "
                "due to ungrounded zero-shot NLI limitations documented in Milestone 11."
            )
        else:
            runner_ml = DocumentEvaluationRunner(
                ner_extractor=ModelBackedNERExtractor(use_mock_backend=True),
                relation_extractor=ModelBackedRelationExtractor(use_mock_backend=True),
            )
            rep_ner_ml = runner_ml.evaluate_ner(suite)
            rep_rel_ml = runner_ml.evaluate_relations(suite)

            # 3. Hybrid Backend (combining rule + offline mock ML)
            runner_hybrid = DocumentEvaluationRunner(
                ner_extractor=HybridNERExtractor(
                    ml_extractor=ModelBackedNERExtractor(use_mock_backend=True),
                    allow_rule_fallback=True,
                ),
                relation_extractor=HybridRelationExtractor(
                    ml_extractor=ModelBackedRelationExtractor(use_mock_backend=True),
                    allow_rule_fallback=True,
                ),
            )
            rep_ner_hybrid = runner_hybrid.evaluate_ner(suite)
            rep_rel_hybrid = runner_hybrid.evaluate_relations(suite)

            ml_backend_type = "mock_simulation"
            is_mock_ml = True
            provenance = "Offline deterministic simulation (not live transformer weights)"
            disclaimer = (
                "ML performance figures represent offline heuristic/mock simulation for pipeline validation. "
                "Latency and memory reflect CPU regular-expression processing, NOT neural network inference. "
                "Do not interpret as measured transformer model accuracy or latency."
            )

        # 4. Entity Resolution Evaluation
        known_records = [
            Record(
                record_id="rec_watson_01",
                source_id="src_kb",
                raw_name="Dr. John Watson",
                entity_type=EntityType.PERSON,
                structured_attributes={"city": "London", "org": "Sherlock Security"},
                normalized_attributes={"city": "london", "org": "sherlock security"},
            ),
            Record(
                record_id="rec_sherlock_sec_01",
                source_id="src_kb",
                raw_name="Sherlock Security",
                entity_type=EntityType.ORGANIZATION,
                structured_attributes={"city": "London"},
                normalized_attributes={"city": "london"},
            ),
            Record(
                record_id="rec_london_01",
                source_id="src_kb",
                raw_name="London",
                entity_type=EntityType.LOCATION,
                structured_attributes={},
                normalized_attributes={},
            ),
            Record(
                record_id="rec_cyberdyne_01",
                source_id="src_kb",
                raw_name="Cyberdyne Systems",
                entity_type=EntityType.ORGANIZATION,
                structured_attributes={},
                normalized_attributes={},
            ),
        ]

        resolver = MentionEntityResolver(known_records=known_records)

        test_queries = [
            (
                EntityMention(
                    mention_id="m_eval_1",
                    document_id="doc_eval_1",
                    surface_text="Dr. John Watson",
                    entity_type=EntityType.PERSON,
                    start_char=0,
                    end_char=15,
                ),
                "rec_watson_01",
            ),
            (
                EntityMention(
                    mention_id="m_eval_2",
                    document_id="doc_eval_1",
                    surface_text="Sherlock Security",
                    entity_type=EntityType.ORGANIZATION,
                    start_char=26,
                    end_char=43,
                ),
                "rec_sherlock_sec_01",
            ),
            (
                EntityMention(
                    mention_id="m_eval_3",
                    document_id="doc_eval_1",
                    surface_text="London",
                    entity_type=EntityType.LOCATION,
                    start_char=77,
                    end_char=83,
                ),
                "rec_london_01",
            ),
            (
                EntityMention(
                    mention_id="m_eval_4",
                    document_id="doc_eval_2",
                    surface_text="Alice Smith",
                    entity_type=EntityType.PERSON,
                    start_char=0,
                    end_char=11,
                ),
                None,  # Alice is not in known_records (unresolved)
            ),
            (
                EntityMention(
                    mention_id="m_eval_5",
                    document_id="doc_eval_2",
                    surface_text="Cyberdyne Systems",
                    entity_type=EntityType.ORGANIZATION,
                    start_char=30,
                    end_char=47,
                ),
                "rec_cyberdyne_01",
            ),
        ]
        rep_er = self.evaluate_entity_resolution(resolver, test_queries)

        summary = {
            "ner_f1_comparison": {
                "rule": rep_ner_rule.exact_f1,
                "ml": rep_ner_ml.exact_f1,
                "hybrid": rep_ner_hybrid.exact_f1,
            },
            "relation_f1_comparison": {
                "rule": rep_rel_rule.f1,
                "ml": rep_rel_ml.f1,
                "hybrid": rep_rel_hybrid.f1,
            },
            "er_metrics": {
                "pairwise_f1": rep_er.pairwise_f1,
                "candidate_recall": rep_er.candidate_recall,
                "review_rate": rep_er.review_rate,
            },
        }

        return MultiBackendComparativeReport(
            partition_label=partition_label,
            rule_ner=rep_ner_rule,
            ml_ner=rep_ner_ml,
            hybrid_ner=rep_ner_hybrid,
            rule_relation=rep_rel_rule,
            ml_relation=rep_rel_ml,
            hybrid_relation=rep_rel_hybrid,
            entity_resolution=rep_er,
            comparative_summary=summary,
            ml_backend_type=ml_backend_type,
            is_mock_ml_simulation=is_mock_ml,
            evaluation_provenance=provenance,
            epistemic_disclaimer=disclaimer,
        )

