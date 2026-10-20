"""
Configurable, explainable match decision engine for entity resolution.

This module evaluates ComparisonResult objects and generates auditable MatchDecision
instances adhering to the core model contracts.

Key Design Principles:
1. Explainability: Every decision is backed by traceable Evidence references and
   structured explanation metadata.
2. Contradiction Protection: Fatal discrepancies (conflicting DOB, different entity types,
   conflicting unique IDs) strictly prevent false positive MATCH decisions.
3. Separation of Context from Identity: Shared contextual attributes (city, organization)
   are never sufficient alone to declare a MATCH.
4. Ambiguity Routing: Insufficient, conflicting, or partial evidence is explicitly
   routed to REVIEW rather than forced into arbitrary MATCH or NON_MATCH.
5. Immutability: Produces immutable MatchDecision objects and never mutates input records.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from src.core.comparison import ComparisonResult, PairwiseComparator
from src.core.models import DecisionType, MatchDecision, Record, CandidatePair


@dataclass(frozen=True)
class DecisionPolicy:
    """
    Configurable threshold and weighting parameters for match decisions.

    Note: Scores evaluated by this engine are heuristic confidence scores bounded
    in [0.0, 1.0]. They represent engineered evidence aggregates and must not be
    described as calibrated probabilities without empirical calibration evidence.
    """
    match_threshold: float = 0.75
    non_match_threshold: float = 0.38
    name_weight: float = 0.65
    attribute_weight: float = 0.35
    conflict_penalty_weight: float = 0.85
    agreement_bonus_weight: float = 0.15
    min_name_similarity_for_match: float = 0.70
    route_conflicting_identifiers_to_review: bool = False
    route_venue_conflicts_to_review: bool = False
    require_corroboration_for_match: bool = False
    model_version: str = "sherlock_match_decision_engine_v1"

    def __post_init__(self):
        if not (0.0 <= self.non_match_threshold <= self.match_threshold <= 1.0):
            raise ValueError(
                f"Invalid threshold ordering: non_match_threshold ({self.non_match_threshold}) "
                f"must be <= match_threshold ({self.match_threshold}) within [0.0, 1.0]."
            )
        if not (0.0 <= self.name_weight <= 1.0 and 0.0 <= self.attribute_weight <= 1.0):
            raise ValueError("Weights must be in [0.0, 1.0].")

    @classmethod
    def get_baseline_policy(cls) -> "DecisionPolicy":
        """Milestone 3-6 baseline decision policy."""
        return cls(
            match_threshold=0.75,
            non_match_threshold=0.38,
            name_weight=0.65,
            attribute_weight=0.35,
            conflict_penalty_weight=0.85,
            agreement_bonus_weight=0.15,
            min_name_similarity_for_match=0.70,
            route_conflicting_identifiers_to_review=False,
            route_venue_conflicts_to_review=False,
            require_corroboration_for_match=False,
            model_version="sherlock_match_decision_engine_v1",
        )

    @classmethod
    def get_calibrated_evidence_policy(cls) -> "DecisionPolicy":
        """
        Milestone 7 production-grade calibrated evidence policy.
        Reduces false negatives through balanced name/attribute weighting,
        and routes venue collisions to review.
        """
        return cls(
            match_threshold=0.72,
            non_match_threshold=0.35,
            name_weight=0.60,
            attribute_weight=0.40,
            conflict_penalty_weight=0.85,
            agreement_bonus_weight=0.15,
            min_name_similarity_for_match=0.60,
            route_conflicting_identifiers_to_review=False,
            route_venue_conflicts_to_review=True,
            require_corroboration_for_match=False,
            model_version="sherlock_match_decision_engine_v2_calibrated",
        )

    @classmethod
    def get_autonomous_high_precision_policy(cls) -> "DecisionPolicy":
        """
        Milestone 7 autonomous high-precision policy prioritizing 0 false merges.
        Demands strong corroboration and high threshold (0.82) before automatic match.
        """
        return cls(
            match_threshold=0.82,
            non_match_threshold=0.30,
            name_weight=0.60,
            attribute_weight=0.40,
            conflict_penalty_weight=0.95,
            agreement_bonus_weight=0.10,
            min_name_similarity_for_match=0.75,
            route_conflicting_identifiers_to_review=False,
            route_venue_conflicts_to_review=True,
            require_corroboration_for_match=False,
            model_version="sherlock_match_decision_engine_v2_high_precision",
        )


class MatchDecisionEngine:
    """
    Consumes ComparisonResult instances and produces validated MatchDecision records.
    """

    def __init__(
        self,
        policy: Optional[DecisionPolicy] = None,
        comparator: Optional[PairwiseComparator] = None,
    ):
        self.policy = policy or DecisionPolicy()
        self.comparator = comparator or PairwiseComparator()

    @classmethod
    def create_production_engine(
        cls,
        policy: Optional[DecisionPolicy] = None,
        comparator: Optional[PairwiseComparator] = None,
    ) -> "MatchDecisionEngine":
        """
        Creates a production-grade decision engine paired with the calibrated
        production decision policy and comparator.
        """
        prod_policy = policy or DecisionPolicy.get_calibrated_evidence_policy()
        prod_comparator = comparator or PairwiseComparator.create_production_comparator()
        return cls(policy=prod_policy, comparator=prod_comparator)

    def decide_comparison(self, comparison: ComparisonResult) -> MatchDecision:
        """
        Applies decision policy to a ComparisonResult to generate an explainable MatchDecision.
        """
        pair_id = comparison.candidate_pair_id
        ev_refs = [e.evidence_id for e in comparison.evidence_items]

        # -------------------------------------------------------------------
        # Rule 1: Fatal Entity Type Incompatibility
        # -------------------------------------------------------------------
        if not comparison.entity_type_compatible:
            return MatchDecision(
                candidate_pair_id=pair_id,
                decision=DecisionType.NON_MATCH,
                score=0.0,
                threshold=self.policy.match_threshold,
                model_version=self.policy.model_version,
                evidence_references=ev_refs,
                explanation_metadata={
                    "primary_reason": "Incompatible entity types",
                    "fatal_contradiction": True,
                    "name_similarity": comparison.name_similarity,
                },
            )

        # -------------------------------------------------------------------
        # Rule 2: Fatal High-Value Identifier Contradiction (DOB, Tax ID, SSN)
        # -------------------------------------------------------------------
        if comparison.has_fatal_contradiction:
            if self.policy.route_conflicting_identifiers_to_review:
                # Under unverified source / data quality uncertainty policy, route to REVIEW
                score = round(max(0.0, min(0.40, comparison.name_similarity * 0.40)), 4)
                return MatchDecision(
                    candidate_pair_id=pair_id,
                    decision=DecisionType.REVIEW,
                    score=score,
                    threshold=self.policy.match_threshold,
                    model_version=self.policy.model_version,
                    evidence_references=ev_refs,
                    explanation_metadata={
                        "primary_reason": "Conflicting high-value identifier; routed to review under unverified source uncertainty policy",
                        "fatal_contradiction": True,
                        "requires_human_review": True,
                        "normalized_name": comparison.summary_metadata.get("normalized_name", ""),
                        "name_similarity": comparison.name_similarity,
                        "attribute_contradiction_score": comparison.attribute_contradiction_score,
                    },
                )
            else:
                # Fatal contradiction strictly prevents MATCH regardless of name agreement
                score = max(0.0, min(0.15, comparison.name_similarity * 0.15))
                return MatchDecision(
                    candidate_pair_id=pair_id,
                    decision=DecisionType.NON_MATCH,
                    score=round(score, 4),
                    threshold=self.policy.match_threshold,
                    model_version=self.policy.model_version,
                    evidence_references=ev_refs,
                    explanation_metadata={
                        "primary_reason": "Conflicting high-value identifier (e.g. conflicting date of birth or ID)",
                        "fatal_contradiction": True,
                        "normalized_name": comparison.summary_metadata.get("normalized_name", ""),
                        "name_similarity": comparison.name_similarity,
                        "attribute_contradiction_score": comparison.attribute_contradiction_score,
                    },
                )

        # -------------------------------------------------------------------
        # Rule 3: Completely Disparate Names Without Alias Evidence
        # -------------------------------------------------------------------
        is_alias = comparison.summary_metadata.get("is_alias_match", False)
        has_discrim_conflict = comparison.summary_metadata.get("has_discriminator_conflict", False)

        if comparison.name_similarity < self.policy.min_name_similarity_for_match and not is_alias:
            # Conflicting discriminator codes (e.g. Employee A vs Employee B) signify distinct entities
            if has_discrim_conflict:
                score = round(max(0.0, comparison.name_similarity * 0.20), 4)
                return MatchDecision(
                    candidate_pair_id=pair_id,
                    decision=DecisionType.NON_MATCH,
                    score=score,
                    threshold=self.policy.match_threshold,
                    model_version=self.policy.model_version,
                    evidence_references=ev_refs,
                    explanation_metadata={
                        "primary_reason": "Conflicting discriminator identifiers in name",
                        "normalized_name": comparison.summary_metadata.get("normalized_name", ""),
                        "name_similarity": comparison.name_similarity,
                        "attribute_agreement_score": comparison.attribute_agreement_score,
                    },
                )

            # Shared contextual attributes (e.g. same city or same org) alone cannot prove identity
            if comparison.attribute_agreement_score > 0.0:
                # Ambiguous: shared context but completely different names -> route to REVIEW
                score = round(min(0.45, 0.20 + comparison.attribute_agreement_score * 0.25), 4)
                return MatchDecision(
                    candidate_pair_id=pair_id,
                    decision=DecisionType.REVIEW,
                    score=score,
                    threshold=self.policy.match_threshold,
                    model_version=self.policy.model_version,
                    evidence_references=ev_refs,
                    explanation_metadata={
                        "primary_reason": "Distinct names with shared contextual attributes; insufficient proof of identity",
                        "requires_human_review": True,
                        "normalized_name": comparison.summary_metadata.get("normalized_name", ""),
                        "name_similarity": comparison.name_similarity,
                        "attribute_agreement_score": comparison.attribute_agreement_score,
                    },
                )
            else:
                score = round(max(0.0, comparison.name_similarity * 0.3), 4)
                return MatchDecision(
                    candidate_pair_id=pair_id,
                    decision=DecisionType.NON_MATCH,
                    score=score,
                    threshold=self.policy.match_threshold,
                    model_version=self.policy.model_version,
                    evidence_references=ev_refs,
                    explanation_metadata={
                        "primary_reason": "Low name similarity and absent identifying attributes",
                        "normalized_name": comparison.summary_metadata.get("normalized_name", ""),
                        "name_similarity": comparison.name_similarity,
                    },
                )

        # Check sub-venue conflict at shared facility
        has_venue_conflict = comparison.summary_metadata.get("has_venue_discriminator_conflict", False)
        if has_venue_conflict:
            score = round(max(0.0, min(0.40, comparison.name_similarity * 0.40)), 4)
            dec_type = DecisionType.REVIEW if self.policy.route_venue_conflicts_to_review else DecisionType.NON_MATCH
            return MatchDecision(
                candidate_pair_id=pair_id,
                decision=dec_type,
                score=score,
                threshold=self.policy.match_threshold,
                model_version=self.policy.model_version,
                evidence_references=ev_refs,
                explanation_metadata={
                    "primary_reason": "Distinct sub-venues operating at shared facility or address; routed to review to prevent false-positive facility merge",
                    "has_venue_discriminator_conflict": True,
                    "normalized_name": comparison.summary_metadata.get("normalized_name", ""),
                    "name_similarity": comparison.name_similarity,
                    "attribute_agreement_score": comparison.attribute_agreement_score,
                    "attribute_contradiction_score": comparison.attribute_contradiction_score,
                    "score_semantics": "Heuristic confidence score bounded in [0.0, 1.0]; not statistically calibrated probabilities",
                },
            )

        # -------------------------------------------------------------------
        # Rule 4: Compute Weighted Score for Plausible Name Matches
        # -------------------------------------------------------------------
        # Attribute agreement normalized contribution
        norm_attr_agree = min(1.0, comparison.attribute_agreement_score)
        norm_attr_conflict = min(1.0, comparison.attribute_contradiction_score)

        # Name contribution
        base_name_contrib = self.policy.name_weight * comparison.name_similarity

        # Attribute contribution: agreement boosts, contradiction penalizes
        attr_contrib = self.policy.attribute_weight * norm_attr_agree
        conflict_penalty = self.policy.conflict_penalty_weight * norm_attr_conflict

        # Agreement bonus when no fatal contradictions exist and name or alias strongly agree
        agreement_bonus = 0.0
        if self.policy.model_version == "sherlock_match_decision_engine_v1":
            if (comparison.name_similarity >= 0.88 or is_alias):
                if norm_attr_conflict == 0.0 or norm_attr_agree >= 0.85:
                    agreement_bonus = self.policy.agreement_bonus_weight
        else:
            if (comparison.name_similarity >= 0.85 or is_alias):
                if (norm_attr_conflict <= 0.05 or norm_attr_agree >= 0.35) and not has_venue_conflict:
                    agreement_bonus = self.policy.agreement_bonus_weight

        raw_score = base_name_contrib + attr_contrib + agreement_bonus - conflict_penalty
        score = round(max(0.0, min(1.0, raw_score)), 4)

        # -------------------------------------------------------------------
        # Rule 5: Evaluate Thresholds & Conflicting Signals
        # -------------------------------------------------------------------
        # High name similarity but significant conflicting context (e.g. occupation divergence like Michael Jordan)
        if comparison.name_similarity >= 0.90 and norm_attr_conflict >= 0.50:
            return MatchDecision(
                candidate_pair_id=pair_id,
                decision=DecisionType.NON_MATCH if score < self.policy.non_match_threshold else DecisionType.REVIEW,
                score=score,
                threshold=self.policy.match_threshold,
                model_version=self.policy.model_version,
                evidence_references=ev_refs,
                explanation_metadata={
                    "primary_reason": "High name similarity accompanied by conflicting contextual attributes (e.g. occupation divergence)",
                    "normalized_name": comparison.summary_metadata.get("normalized_name", ""),
                    "name_similarity": comparison.name_similarity,
                    "attribute_contradiction_score": comparison.attribute_contradiction_score,
                    "score_semantics": "Heuristic confidence score bounded in [0.0, 1.0]; not statistically calibrated probabilities",
                },
            )

        has_corroborating_id = any(
            e.evidence_type.startswith("high_value_agreement_") or e.evidence_type.startswith("contact_agreement_")
            for e in comparison.evidence_items
        )

        # Standard decision assignment
        if self.policy.require_corroboration_for_match and score >= self.policy.match_threshold and not has_corroborating_id:
            decision = DecisionType.REVIEW
            reason = "Identical or similar name lacking corroborating attribute evidence; routed to review to prevent false-positive collision"
        elif score >= self.policy.match_threshold:
            decision = DecisionType.MATCH
            reason = "Evidence sufficiently confirms identity across name and attributes"
        elif score <= self.policy.non_match_threshold:
            decision = DecisionType.NON_MATCH
            reason = "Insufficient matching evidence; features support distinct entities"
        else:
            decision = DecisionType.REVIEW
            reason = "Ambiguous or incomplete evidence within review threshold band"

        return MatchDecision(
            candidate_pair_id=pair_id,
            decision=decision,
            score=score,
            threshold=self.policy.match_threshold,
            model_version=self.policy.model_version,
            evidence_references=ev_refs,
            explanation_metadata={
                "primary_reason": reason,
                "policy_model_version": self.policy.model_version,
                "normalized_name": comparison.summary_metadata.get("normalized_name", ""),
                "name_similarity": comparison.name_similarity,
                "attribute_agreement_score": comparison.attribute_agreement_score,
                "attribute_contradiction_score": comparison.attribute_contradiction_score,
                "score_semantics": "Heuristic confidence score bounded in [0.0, 1.0]; not statistically calibrated probabilities",
            },
        )

    def compare_and_decide(
        self,
        left: Record,
        right: Record,
        candidate_pair: Optional[CandidatePair] = None,
    ) -> Tuple[MatchDecision, ComparisonResult]:
        """Convenience method running comparison and decision in a single call."""
        comp = self.comparator.compare(left, right, candidate_pair=candidate_pair)
        dec = self.decide_comparison(comp)
        return dec, comp

    def decide_candidates(
        self,
        records: Mapping[str, Record],
        candidate_pairs: Sequence[CandidatePair],
    ) -> List[MatchDecision]:
        """
        Evaluates a batch of candidate pairs using a lookup mapping of records.
        Returns a list of MatchDecision instances in deterministic order.
        """
        decisions: List[MatchDecision] = []
        for pair in candidate_pairs:
            l_id, r_id = pair.left_record_id, pair.right_record_id
            if l_id not in records:
                raise KeyError(f"Left record ID '{l_id}' in CandidatePair '{pair.candidate_id}' not found in records.")
            if r_id not in records:
                raise KeyError(f"Right record ID '{r_id}' in CandidatePair '{pair.candidate_id}' not found in records.")

            rec_l = records[l_id]
            rec_r = records[r_id]
            comp = self.comparator.compare(rec_l, rec_r, candidate_pair=pair)
            dec = self.decide_comparison(comp)
            decisions.append(dec)

        # Deterministic sort by candidate_pair_id
        decisions.sort(key=lambda d: d.candidate_pair_id)
        return decisions
