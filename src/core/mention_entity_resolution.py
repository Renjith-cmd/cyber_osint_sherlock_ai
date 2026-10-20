"""
Mention-to-Entity Resolution Adapter for Sherlock AI (Milestone 10).

Integrates document-extracted EntityMention instances with the production-grade
Milestones 1–7 Entity Resolution subsystem:
- Candidate Generation & Blocking (src/core/blocking.py)
- Pairwise Record Comparison & Evidence Extraction (src/core/comparison.py)
- Explainable Match Decision Engine (src/core/decision.py)
- Constraint-Aware Reversible Clustering (src/core/clustering.py)

Core Guarantees:
1. Reuses existing Milestones 1–7 components rather than creating a parallel resolution engine.
2. Preserves decision semantics: MATCH, NON_MATCH, and REVIEW.
3. Strict Epistemic Separation: Entity extractor's model confidence is NEVER used as
   an identity match probability.
4. No Forced Merges: A REVIEW decision remains explicitly unresolved; records are never
   merged on name similarity alone.
5. Preserves explicit non-match constraints and reversible cluster structures.
6. Absolute determinism across repeated executions.
"""

from enum import Enum
from typing import Dict, List, Optional, Tuple, Any, Sequence, Set
from pydantic import Field, field_validator

from src.core.models import (
    ImmutableBaseModel,
    Record,
    CandidatePair,
    MatchDecision,
    DecisionType,
    EntityType,
    Evidence,
    EntityCluster,
    _validate_non_empty_str,
)
from src.core.blocking import CandidateGenerator, get_default_blocking_rules
from src.core.comparison import PairwiseComparator, ComparisonResult
from src.core.decision import MatchDecisionEngine, DecisionPolicy
from src.core.clustering import ConstraintAwareClusterer, ClusteringPolicy
from src.core.ner import EntityMention
from src.core.document_ingestion import IngestedDocument


class MentionResolutionStatus(str, Enum):
    """
    Epistemic status of mention-to-entity resolution.

    Distinguishes clearly between:
    1. RESOLVED_MATCH: A valid MATCH is supported by comparative evidence.
    2. UNRESOLVED_NO_CANDIDATES: No candidate pairs passed blocking strategies (lack of candidates != confirmed non-match).
    3. UNRESOLVED_INSUFFICIENT_EVIDENCE: Candidates exist, but evidence is insufficient (REVIEW).
    4. CONFIRMED_NON_MATCH: Explicit evidence (fatal contradiction or constraint) establishes NON_MATCH.
    """
    RESOLVED_MATCH = "RESOLVED_MATCH"
    UNRESOLVED_NO_CANDIDATES = "UNRESOLVED_NO_CANDIDATES"
    UNRESOLVED_INSUFFICIENT_EVIDENCE = "UNRESOLVED_INSUFFICIENT_EVIDENCE"
    CONFIRMED_NON_MATCH = "CONFIRMED_NON_MATCH"


def mention_to_record(
    mention: EntityMention,
    document: Optional[IngestedDocument] = None,
    attributes: Optional[Dict[str, Any]] = None,
    source_id: Optional[str] = None,
) -> Record:
    """
    Convert an EntityMention into a canonical Record for entity resolution evaluation.

    Preserves mention surface text, offsets, and document metadata without
    confusing mention confidence with record verification.
    """
    attrs = dict(attributes or {})
    attrs.setdefault("surface_text", mention.surface_text)
    attrs.setdefault("start_char", mention.start_char)
    attrs.setdefault("end_char", mention.end_char)
    if mention.normalized_value:
        attrs.setdefault("normalized_value", mention.normalized_value)
    if mention.page_number is not None:
        attrs.setdefault("page_number", mention.page_number)
    if mention.sentence_index is not None:
        attrs.setdefault("sentence_index", mention.sentence_index)

    src = source_id or f"doc_{mention.document_id}"
    raw_name = mention.normalized_value or mention.surface_text

    return Record(
        record_id=mention.mention_id,
        source_id=src,
        raw_name=raw_name,
        entity_type=mention.entity_type,
        structured_attributes=attrs,
        normalized_attributes={k: str(v).lower() for k, v in attrs.items() if isinstance(v, (str, int, float))},
        raw_payload={
            "document_id": mention.document_id,
            "extraction_method": mention.extraction_method,
            "extraction_version": mention.extraction_version,
            "model_confidence": mention.confidence_score,
            "mention_metadata": dict(mention.metadata),
        },
    )


class MentionResolutionResult(ImmutableBaseModel):
    """
    Immutable result of evaluating an EntityMention against known entity records.
    """
    mention_id: str
    document_id: str
    surface_text: str
    entity_type: EntityType
    resolution_status: MentionResolutionStatus = MentionResolutionStatus.UNRESOLVED_NO_CANDIDATES
    decision_type: Optional[DecisionType] = None  # None when no candidate was evaluated; MATCH, NON_MATCH, REVIEW when evaluated
    resolved_entity_id: Optional[str] = None  # Matched record/entity ID if MATCH, None if unresolved
    target_record_id: Optional[str] = None   # Target record ID evaluated
    confidence_score: Optional[float] = None # Decision engine score (NOT NER model confidence!)
    is_resolved: bool = False
    explanation: str = ""
    candidate_pair_id: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)
    comparison_evidence: List[Evidence] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("mention_id", "document_id", "surface_text")
    @classmethod
    def _validate_non_empty(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)


class MentionEntityResolver:
    """
    Production-grade adapter integrating extracted mentions with the
    existing Sherlock AI entity-resolution pipeline.
    """

    def __init__(
        self,
        known_records: Optional[Sequence[Record]] = None,
        candidate_generator: Optional[CandidateGenerator] = None,
        comparator: Optional[PairwiseComparator] = None,
        decision_engine: Optional[MatchDecisionEngine] = None,
        clusterer: Optional[ConstraintAwareClusterer] = None,
        decision_policy: Optional[DecisionPolicy] = None,
        explicit_non_matches: Optional[Set[Tuple[str, str]]] = None,
    ):
        """
        known_records: Existing verified records or investigation entities to match against.
        candidate_generator: Blocking rule engine (defaults to standard blocking rules).
        comparator: Pairwise feature comparator (defaults to production comparator).
        decision_engine: Explainable match decision engine.
        clusterer: Constraint-aware clusterer.
        decision_policy: Policy thresholds for MATCH / REVIEW / NON_MATCH.
        explicit_non_matches: Known negative constraints (left_id, right_id) that forbid merging.
        """
        self.known_records: Dict[str, Record] = (
            {r.record_id: r for r in known_records} if known_records else {}
        )
        self.candidate_generator = candidate_generator or CandidateGenerator(
            rules=get_default_blocking_rules(),
            allow_cross_entity_type=False,
        )
        self.comparator = comparator or PairwiseComparator(
            enable_advanced_normalization=True,
            detect_venue_conflicts=True,
        )
        policy = decision_policy or DecisionPolicy.get_calibrated_evidence_policy()
        self.decision_engine = decision_engine or MatchDecisionEngine(policy=policy)
        self.clusterer = clusterer or ConstraintAwareClusterer(
            policy=ClusteringPolicy(allow_review_merges=False, require_full_clique=False)
        )
        # Canonicalize explicit non-matches
        self.explicit_non_matches: Set[Tuple[str, str]] = set()
        if explicit_non_matches:
            for l, r in explicit_non_matches:
                canon = tuple(sorted([l, r]))
                self.explicit_non_matches.add((canon[0], canon[1]))

    def add_known_record(self, record: Record) -> None:
        """Register a known entity record."""
        self.known_records[record.record_id] = record

    def add_explicit_non_match(self, id_a: str, id_b: str) -> None:
        """Register an explicit non-match constraint between two record IDs."""
        canon = tuple(sorted([id_a, id_b]))
        self.explicit_non_matches.add((canon[0], canon[1]))

    def resolve_mention(
        self,
        mention: EntityMention,
        context_attributes: Optional[Dict[str, Any]] = None,
    ) -> MentionResolutionResult:
        """
        Resolve a single EntityMention against known records.

        Steps:
        1. Convert mention into query Record.
        2. Generate candidate pairs against known records via CandidateGenerator.
        3. Evaluate candidate pairs via PairwiseComparator and MatchDecisionEngine.
        4. Enforce non-match constraints.
        5. Return structured MentionResolutionResult preserving MATCH, NON_MATCH, or REVIEW.
        """
        query_record = mention_to_record(mention, attributes=context_attributes)

        if not self.known_records:
            return MentionResolutionResult(
                mention_id=mention.mention_id,
                document_id=mention.document_id,
                surface_text=mention.surface_text,
                entity_type=mention.entity_type,
                resolution_status=MentionResolutionStatus.UNRESOLVED_NO_CANDIDATES,
                decision_type=None,
                resolved_entity_id=None,
                target_record_id=None,
                confidence_score=0.0,
                is_resolved=False,
                explanation="No known records in repository for entity resolution.",
            )

        # 1. Blocking & Candidate Generation
        records_to_block = [query_record] + list(self.known_records.values())
        candidate_pairs = self.candidate_generator.generate_candidates(records_to_block)

        # Filter candidate pairs that involve query_record.record_id
        q_id = query_record.record_id
        relevant_pairs = [
            cp for cp in candidate_pairs
            if cp.left_record_id == q_id or cp.right_record_id == q_id
        ]

        if not relevant_pairs:
            return MentionResolutionResult(
                mention_id=mention.mention_id,
                document_id=mention.document_id,
                surface_text=mention.surface_text,
                entity_type=mention.entity_type,
                resolution_status=MentionResolutionStatus.UNRESOLVED_NO_CANDIDATES,
                decision_type=None,
                resolved_entity_id=None,
                target_record_id=None,
                confidence_score=0.0,
                is_resolved=False,
                explanation="No candidate pairs passed blocking strategies; mention remains unresolved.",
            )

        # 2. Pairwise Comparison & Decision Evaluation
        evaluations: List[Tuple[MatchDecision, ComparisonResult, str]] = []

        for cp in relevant_pairs:
            target_id = cp.right_record_id if cp.left_record_id == q_id else cp.left_record_id
            target_record = self.known_records[target_id]

            # Check explicit non-match constraints
            pair_key = tuple(sorted([q_id, target_id]))
            if pair_key in self.explicit_non_matches:
                # Constrained non-match! Create explicit non-match decision
                forced_non_match = MatchDecision(
                    candidate_pair_id=cp.candidate_id,
                    decision=DecisionType.NON_MATCH,
                    score=0.0,
                    threshold=self.decision_engine.policy.match_threshold,
                    model_version=self.decision_engine.policy.model_version,
                    evidence_references=[],
                    explanation_metadata={"primary_reason": "Constrained by explicit non-match rule."},
                )
                comp_result = self.comparator.compare(query_record, target_record, cp)
                evaluations.append((forced_non_match, comp_result, target_id))
                continue

            comp_result = self.comparator.compare(query_record, target_record, cp)
            decision = self.decision_engine.decide_comparison(comp_result)
            evaluations.append((decision, comp_result, target_id))

        # 3. Decision Selection & Conflict Handling
        # Sort evaluations by decision type priority (MATCH > REVIEW > NON_MATCH), then confidence desc
        def eval_sort_key(item):
            dec, _, _ = item
            type_prio = {DecisionType.MATCH: 1, DecisionType.REVIEW: 2, DecisionType.NON_MATCH: 3}
            score = dec.score if dec.score is not None else 0.0
            return (type_prio.get(dec.decision, 4), -score)

        evaluations.sort(key=eval_sort_key)
        best_decision, best_comp, best_target_id = evaluations[0]

        # Check for multiple MATCH candidates (ambiguity guard)
        matches = [e for e in evaluations if e[0].decision == DecisionType.MATCH]
        if len(matches) > 1:
            # Multiple distinct known entities matched!
            # If they are distinct entities, this is an ambiguous match that MUST route to REVIEW
            matched_target_ids = {e[2] for e in matches}
            if len(matched_target_ids) > 1:
                return MentionResolutionResult(
                    mention_id=mention.mention_id,
                    document_id=mention.document_id,
                    surface_text=mention.surface_text,
                    entity_type=mention.entity_type,
                    resolution_status=MentionResolutionStatus.UNRESOLVED_INSUFFICIENT_EVIDENCE,
                    decision_type=DecisionType.REVIEW,
                    resolved_entity_id=None,
                    target_record_id=best_target_id,
                    confidence_score=best_decision.score,
                    is_resolved=False,
                    explanation=(
                        f"Mention ambiguously matched multiple distinct entities: {sorted(list(matched_target_ids))}. "
                        "Routed to human review without forced merge."
                    ),
                    candidate_pair_id=best_decision.candidate_pair_id,
                    evidence_ids=list(best_decision.evidence_references),
                    comparison_evidence=list(best_comp.evidence_items),
                    metadata={"competing_match_ids": sorted(list(matched_target_ids))},
                )

        explanation_text = str(best_decision.explanation_metadata.get("primary_reason", ""))

        if best_decision.decision == DecisionType.MATCH:
            return MentionResolutionResult(
                mention_id=mention.mention_id,
                document_id=mention.document_id,
                surface_text=mention.surface_text,
                entity_type=mention.entity_type,
                resolution_status=MentionResolutionStatus.RESOLVED_MATCH,
                decision_type=DecisionType.MATCH,
                resolved_entity_id=best_target_id,
                target_record_id=best_target_id,
                confidence_score=best_decision.score,
                is_resolved=True,
                explanation=explanation_text,
                candidate_pair_id=best_decision.candidate_pair_id,
                evidence_ids=list(best_decision.evidence_references),
                comparison_evidence=list(best_comp.evidence_items),
                metadata={"blocking_signals": best_comp.summary_metadata},
            )
        elif best_decision.decision == DecisionType.REVIEW:
            return MentionResolutionResult(
                mention_id=mention.mention_id,
                document_id=mention.document_id,
                surface_text=mention.surface_text,
                entity_type=mention.entity_type,
                resolution_status=MentionResolutionStatus.UNRESOLVED_INSUFFICIENT_EVIDENCE,
                decision_type=DecisionType.REVIEW,
                resolved_entity_id=None,  # Crucial: remains unresolved!
                target_record_id=best_target_id,
                confidence_score=best_decision.score,
                is_resolved=False,
                explanation=explanation_text,
                candidate_pair_id=best_decision.candidate_pair_id,
                evidence_ids=list(best_decision.evidence_references),
                comparison_evidence=list(best_comp.evidence_items),
                metadata={"review_candidate_id": best_target_id},
            )
        else:
            return MentionResolutionResult(
                mention_id=mention.mention_id,
                document_id=mention.document_id,
                surface_text=mention.surface_text,
                entity_type=mention.entity_type,
                resolution_status=MentionResolutionStatus.CONFIRMED_NON_MATCH,
                decision_type=DecisionType.NON_MATCH,
                resolved_entity_id=None,
                target_record_id=best_target_id,
                confidence_score=best_decision.score,
                is_resolved=False,
                explanation=explanation_text,
                candidate_pair_id=best_decision.candidate_pair_id,
                evidence_ids=list(best_decision.evidence_references),
                comparison_evidence=list(best_comp.evidence_items),
                metadata={},
            )

    def resolve_mentions(
        self,
        mentions: Sequence[EntityMention],
        context_attributes_by_mention_id: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[MentionResolutionResult]:
        """
        Deterministically resolve a collection of EntityMention instances.
        """
        results: List[MentionResolutionResult] = []
        ctx_map = context_attributes_by_mention_id or {}
        for m in mentions:
            ctx = ctx_map.get(m.mention_id)
            res = self.resolve_mention(m, context_attributes=ctx)
            results.append(res)
        return results
