from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Sequence, Tuple, Union
from src.core.models import DecisionType, MatchDecision, CandidatePair, EntityCluster

class UnknownPredictionPolicy(str, Enum):
    """
    Policy for handling predictions whose candidate pair IDs are not in ground truth.
    
    - RAISE: Default. Raises a ValueError. Ground truth labels for unknown pairs 
      are unknown; fabricating labels or silently ignoring them is unacceptable.
    - IGNORE: Opt-in. Silently skips predictions not found in ground truth.
    - PENALIZE_AS_FP: Opt-in. Penalizes any predicted MATCH (or REVIEW if review_is_match=True)
      for unknown pairs as a False Positive, without fabricating a ground-truth label.
    """
    RAISE = "RAISE"
    IGNORE = "IGNORE"
    PENALIZE_AS_FP = "PENALIZE_AS_FP"

class EvaluationMetrics:
    """
    Standard binary evaluation metrics for pairwise entity resolution.
    
    All division operations are guarded against zero denominators:
    - If TP + FP == 0, precision returns 0.0.
    - If TP + FN == 0, recall returns 0.0.
    - If precision + recall == 0, F1 returns 0.0.
    """
    def __init__(self, tp: int, fp: int, fn: int, true_negatives: int = 0):
        self.true_positives = tp
        self.false_positives = fp
        self.false_negatives = fn
        self.true_negatives = true_negatives

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        if denom == 0:
            return 0.0
        return self.true_positives / denom

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        if denom == 0:
            return 0.0
        return self.true_positives / denom

    @property
    def f1(self) -> float:
        p = self.precision
        r = self.recall
        if p + r == 0:
            return 0.0
        return 2 * (p * r) / (p + r)

class PairwiseEvaluator:
    """
    Evaluates pairwise match decisions against ground truth.

    Missing Predictions Policy:
    Ground-truth pairs omitted from predictions represent candidate pairs that
    were either blocked or not classified. An omitted true match is penalized as
    a False Negative (missed match). An omitted true non-match counts as a True
    Negative (correct non-candidate).

    Ungrounded Predictions Policy:
    Predictions for candidate pairs not present in ground truth have unknown labels.
    By default (policy=RAISE), a ValueError is raised to prevent silent evaluation bias.
    Alternative policies (IGNORE, PENALIZE_AS_FP) must be explicitly configured.

    REVIEW Policy:
    - By default, review_is_match=False and review_is_error=True:
      * REVIEW on an actual match counts as FN (failed to confirm a true match).
      * REVIEW on an actual non-match counts as FP (unnecessary alert/review burden).
    - If review_is_match=True:
      * REVIEW counts as a MATCH (TP on actual match, FP on actual non-match).
    - If review_is_match=False and review_is_error=False:
      * REVIEW on an actual match counts as FN.
      * REVIEW on an actual non-match counts as TN (not penalized as an alert error).
    """
    def __init__(
        self,
        review_is_match: bool = False,
        review_is_error: bool = True,
        unknown_prediction_policy: UnknownPredictionPolicy = UnknownPredictionPolicy.RAISE
    ):
        self.review_is_match = review_is_match
        self.review_is_error = review_is_error
        self.unknown_prediction_policy = unknown_prediction_policy

    @staticmethod
    def validate_and_build_predictions(
        decisions: Iterable[Union[MatchDecision, Tuple[str, DecisionType]]]
    ) -> Dict[str, DecisionType]:
        """
        Validates an iterable of decisions and constructs a prediction dictionary,
        detecting and rejecting duplicate candidate pair IDs before dictionary conversion.
        """
        seen: Dict[str, DecisionType] = {}
        duplicates: List[str] = []
        for item in decisions:
            if isinstance(item, MatchDecision):
                pair_id = item.candidate_pair_id
                decision = item.decision
            elif isinstance(item, (tuple, list)) and len(item) == 2:
                pair_id, decision = item
            else:
                raise TypeError(f"Expected MatchDecision or 2-tuple (pair_id, DecisionType), got {type(item)}")

            if pair_id in seen:
                duplicates.append(pair_id)
            seen[pair_id] = decision

        if duplicates:
            unique_dups = sorted(set(duplicates))
            raise ValueError(f"Duplicate predictions detected for candidate pair IDs: {unique_dups}")
        return seen

    def evaluate(
        self,
        predictions: Union[Dict[str, DecisionType], Iterable[Union[MatchDecision, Tuple[str, DecisionType]]]],
        ground_truth: Dict[str, bool]
    ) -> EvaluationMetrics:
        """
        Evaluate predictions against ground truth.

        predictions: Dict[candidate_pair_id, DecisionType] or Iterable of MatchDecision/tuples.
        ground_truth: Dict[candidate_pair_id, bool] (True if actual match, False if non-match).
        """
        if not isinstance(predictions, dict):
            pred_dict = self.validate_and_build_predictions(predictions)
        else:
            pred_dict = predictions

        # Check for predictions with unknown ground-truth labels
        unknown_ids = set(pred_dict.keys()) - set(ground_truth.keys())
        if unknown_ids:
            if self.unknown_prediction_policy == UnknownPredictionPolicy.RAISE:
                sorted_unknown = sorted(list(unknown_ids))[:10]
                raise ValueError(
                    f"Found {len(unknown_ids)} prediction(s) outside ground truth: {sorted_unknown}. "
                    "Actual ground-truth labels are unknown. Configure unknown_prediction_policy "
                    "explicitly if evaluating partial benchmarks."
                )

        tp = 0
        fp = 0
        fn = 0
        tn = 0

        for pair_id, is_actual_match in ground_truth.items():
            if pair_id not in pred_dict:
                # Pair was omitted by candidate generation or model
                if is_actual_match:
                    fn += 1
                else:
                    tn += 1
                continue

            decision = pred_dict[pair_id]
            is_pred_match = False
            is_review = False

            if decision == DecisionType.MATCH:
                is_pred_match = True
            elif decision == DecisionType.REVIEW:
                is_review = True
                is_pred_match = self.review_is_match

            if is_actual_match:
                if is_pred_match:
                    tp += 1
                else:
                    fn += 1
            else:
                if is_pred_match:
                    fp += 1
                else:
                    if is_review and self.review_is_error:
                        fp += 1
                    else:
                        tn += 1

        # Apply opt-in policy for ungrounded predictions
        if self.unknown_prediction_policy == UnknownPredictionPolicy.PENALIZE_AS_FP:
            for unk_id in unknown_ids:
                decision = pred_dict[unk_id]
                if decision == DecisionType.MATCH or (decision == DecisionType.REVIEW and self.review_is_match):
                    fp += 1

        return EvaluationMetrics(tp, fp, fn, tn)


# ---------------------------------------------------------------------------
# Candidate Generation Evaluation (Milestone 2)
# ---------------------------------------------------------------------------

class CandidateEvaluationMetrics:
    """
    Focused metrics for evaluating candidate generation and blocking efficiency.

    Distinctions from Match Evaluation:
    - Candidate recall measures the proportion of true identity matches successfully
      retained in the generated candidate set.
    - Candidate generation proposes plausible pairs; an unannotated or false-match
      candidate pair is NOT treated as a match decision error or false positive.
    - The absence of a candidate is NOT a negative identity decision.
    - Zero denominators are explicitly guarded against.
    """

    def __init__(
        self,
        candidate_pairs_count: int,
        total_possible_pairs: int,
        ground_truth_positives_count: int,
        covered_positives_count: int,
        total_compatible_pairs: Optional[int] = None,
    ):
        self.candidate_pairs_count = candidate_pairs_count
        self.total_possible_pairs = total_possible_pairs
        self.ground_truth_positives_count = ground_truth_positives_count
        self.covered_positives_count = covered_positives_count
        self.total_compatible_pairs = total_compatible_pairs

    @property
    def candidate_recall(self) -> float:
        """
        candidate recall = known positive pairs generated / all known positive pairs
        Guarded: returns 0.0 if ground_truth_positives_count == 0.
        """
        if self.ground_truth_positives_count == 0:
            return 0.0
        return self.covered_positives_count / self.ground_truth_positives_count

    @property
    def reduction_ratio(self) -> float:
        """
        reduction ratio = 1.0 - (candidate_pairs / total_possible_pairs)
        Measures the fraction of pairs pruned from pairwise comparison against
        the full Cartesian product baseline (N * (N - 1) // 2).
        Guarded: returns 0.0 if total_possible_pairs == 0.
        """
        if self.total_possible_pairs == 0:
            return 0.0
        return 1.0 - (self.candidate_pairs_count / self.total_possible_pairs)

    @property
    def compatible_reduction_ratio(self) -> float:
        """
        compatible reduction ratio = 1.0 - (candidate_pairs / total_compatible_pairs)
        Measures the fraction of pairs pruned against the entity-type-compatible
        baseline when cross-type matching is disabled.
        Guarded: returns 0.0 if total_compatible_pairs is None or 0.
        """
        if self.total_compatible_pairs is None or self.total_compatible_pairs == 0:
            return 0.0
        return 1.0 - (self.candidate_pairs_count / self.total_compatible_pairs)

    @property
    def pair_reduction(self) -> float:
        """Alias for reduction_ratio."""
        return self.reduction_ratio

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "candidate_pairs_count": self.candidate_pairs_count,
            "total_possible_pairs": self.total_possible_pairs,
            "ground_truth_positives_count": self.ground_truth_positives_count,
            "covered_positives_count": self.covered_positives_count,
            "candidate_recall": self.candidate_recall,
            "reduction_ratio": self.reduction_ratio,
        }
        if self.total_compatible_pairs is not None:
            d["total_compatible_pairs"] = self.total_compatible_pairs
            d["compatible_reduction_ratio"] = self.compatible_reduction_ratio
        return d


def _extract_pair_signatures(pair: Union[CandidatePair, str]) -> Set[str]:
    """Helper returning canonical identifier aliases for a candidate pair."""
    sigs: Set[str] = set()
    if isinstance(pair, CandidatePair):
        sigs.add(pair.candidate_id)
        sigs.add(pair.canonical_pair_key)
        sigs.add(f"cp_{pair.left_record_id}_{pair.right_record_id}")
        sigs.add(f"cp_{pair.right_record_id}_{pair.left_record_id}")
        sigs.add(f"{pair.left_record_id}::{pair.right_record_id}")
        sigs.add(f"{pair.right_record_id}::{pair.left_record_id}")
    elif isinstance(pair, str):
        sigs.add(pair)
        if pair.startswith("cp_"):
            parts = pair[3:].split("_")
            if len(parts) == 2:
                a, b = parts
                sigs.add(f"{a}::{b}")
                sigs.add(f"{b}::{a}")
                sigs.add(f"cp_{b}_{a}")
        elif "::" in pair:
            parts = pair.split("::")
            if len(parts) == 2:
                a, b = parts
                sigs.add(f"cp_{a}_{b}")
                sigs.add(f"cp_{b}_{a}")
                sigs.add(f"{b}::{a}")
    else:
        raise TypeError(f"Expected CandidatePair or str, got {type(pair).__name__}")
    return sigs


def evaluate_candidate_generation(
    candidate_pairs: Iterable[Union[CandidatePair, str]],
    ground_truth: Dict[str, bool],
    total_records: Optional[Union[int, Sequence[Any]]] = None,
    total_compatible_pairs: Optional[int] = None,
) -> CandidateEvaluationMetrics:
    """
    Evaluates candidate generation efficiency and recall against ground truth.

    candidate_pairs: Iterable of CandidatePair objects or pair ID strings.
    ground_truth: Mapping of candidate_pair_id -> bool (True indicates an actual match).
    total_records: Optional total count of input records (int), or a sequence of Record
                   objects. If a sequence of records is provided, calculates both
                   total_possible_pairs (Cartesian product) and total_compatible_pairs
                   (pairs sharing the same entity_type).
    total_compatible_pairs: Optional precomputed count of entity-type-compatible pairs.
    """
    # Materialize candidate pairs and collect recognized signature aliases
    cand_list = list(candidate_pairs)
    candidate_signatures: Set[str] = set()
    for item in cand_list:
        candidate_signatures.update(_extract_pair_signatures(item))

    # Calculate total possible pairs and compatible pairs
    computed_total_possible = 0
    computed_compatible = total_compatible_pairs

    if total_records is not None:
        if isinstance(total_records, int):
            num_records = total_records
            if num_records >= 2:
                computed_total_possible = num_records * (num_records - 1) // 2
        elif isinstance(total_records, Sequence):
            num_records = len(total_records)
            if num_records >= 2:
                computed_total_possible = num_records * (num_records - 1) // 2
                # Calculate entity-type-compatible pairs if records have entity_type
                if computed_compatible is None and all(hasattr(r, "entity_type") for r in total_records):
                    from collections import Counter
                    type_counts = Counter(r.entity_type for r in total_records)
                    computed_compatible = sum(c * (c - 1) // 2 for c in type_counts.values())
        else:
            num_records = int(total_records)
            if num_records >= 2:
                computed_total_possible = num_records * (num_records - 1) // 2

    # Ground truth evaluation
    ground_truth_positives = 0
    covered_positives = 0

    for gt_id, is_actual_match in ground_truth.items():
        if is_actual_match:
            ground_truth_positives += 1
            # Check if this positive pair was generated under any recognized signature
            gt_sigs = _extract_pair_signatures(gt_id)
            if any(sig in candidate_signatures for sig in gt_sigs):
                covered_positives += 1

    return CandidateEvaluationMetrics(
        candidate_pairs_count=len(cand_list),
        total_possible_pairs=computed_total_possible,
        ground_truth_positives_count=ground_truth_positives,
        covered_positives_count=covered_positives,
        total_compatible_pairs=computed_compatible,
    )


# ---------------------------------------------------------------------------
# Match Decision and End-to-End Evaluation (Milestone 3)
# ---------------------------------------------------------------------------

class MatchEvaluationMetrics:
    """
    Detailed evaluation metrics for match decisions on explicitly labeled pairs.
    Tracks confusion counts (TP, FP, FN, TN) and explicit REVIEW counts and rates.
    """

    def __init__(
        self,
        true_positives: int,
        false_positives: int,
        false_negatives: int,
        true_negatives: int,
        review_count: int,
        total_evaluated: int,
        match_count: int = 0,
        non_match_count: int = 0,
    ):
        self.true_positives = true_positives
        self.false_positives = false_positives
        self.false_negatives = false_negatives
        self.true_negatives = true_negatives
        self.review_count = review_count
        self.total_evaluated = total_evaluated
        self.match_count = match_count
        self.non_match_count = non_match_count

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * (p * r) / (p + r) if (p + r) > 0 else 0.0

    @property
    def specificity(self) -> float:
        denom = self.true_negatives + self.false_positives
        return self.true_negatives / denom if denom > 0 else 0.0

    @property
    def positive_support(self) -> int:
        return self.true_positives + self.false_negatives

    @property
    def negative_support(self) -> int:
        return self.true_negatives + self.false_positives

    @property
    def review_rate(self) -> float:
        return self.review_count / self.total_evaluated if self.total_evaluated > 0 else 0.0

    @property
    def accuracy(self) -> float:
        return (self.true_positives + self.true_negatives) / self.total_evaluated if self.total_evaluated > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "true_negatives": self.true_negatives,
            "match_count": self.match_count,
            "non_match_count": self.non_match_count,
            "review_count": self.review_count,
            "total_evaluated": self.total_evaluated,
            "positive_support": self.positive_support,
            "negative_support": self.negative_support,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "specificity": self.specificity,
            "review_rate": self.review_rate,
            "accuracy": self.accuracy,
        }


class EndToEndEvaluationMetrics:
    """
    Multi-stage entity resolution pipeline evaluation.
    Clearly distinguishes:
    1. Candidate recall from Milestone 2 (candidate generation phase)
    2. Matcher recall on candidate pairs (decision engine phase)
    3. End-to-end recall (accounting for true matches missed during candidate generation)
    """

    def __init__(
        self,
        candidate_metrics: CandidateEvaluationMetrics,
        match_metrics: MatchEvaluationMetrics,
        total_ground_truth_positives: int,
        end_to_end_true_positives: int,
    ):
        self.candidate_metrics = candidate_metrics
        self.match_metrics = match_metrics
        self.total_ground_truth_positives = total_ground_truth_positives
        self.end_to_end_true_positives = end_to_end_true_positives

    @property
    def candidate_recall(self) -> float:
        return self.candidate_metrics.candidate_recall

    @property
    def matcher_recall_on_candidates(self) -> float:
        return self.match_metrics.recall

    @property
    def end_to_end_recall(self) -> float:
        if self.total_ground_truth_positives == 0:
            return 0.0
        return self.end_to_end_true_positives / self.total_ground_truth_positives

    @property
    def precision(self) -> float:
        return self.match_metrics.precision

    @property
    def f1(self) -> float:
        p, r = self.precision, self.end_to_end_recall
        return 2 * (p * r) / (p + r) if (p + r) > 0 else 0.0

    @property
    def reduction_ratio(self) -> float:
        return self.candidate_metrics.reduction_ratio

    @property
    def review_rate(self) -> float:
        return self.match_metrics.review_rate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_recall": self.candidate_recall,
            "matcher_recall_on_candidates": self.matcher_recall_on_candidates,
            "end_to_end_recall": self.end_to_end_recall,
            "precision": self.precision,
            "f1": self.f1,
            "reduction_ratio": self.reduction_ratio,
            "review_rate": self.review_rate,
            "candidate_pairs_count": self.candidate_metrics.candidate_pairs_count,
            "total_evaluated_decisions": self.match_metrics.total_evaluated,
        }


def evaluate_match_decisions(
    decisions: Union[Dict[str, DecisionType], Iterable[Union[MatchDecision, Tuple[str, DecisionType]]]],
    ground_truth: Dict[str, bool],
    review_is_match: bool = False,
    review_is_error: bool = True,
    unknown_prediction_policy: UnknownPredictionPolicy = UnknownPredictionPolicy.RAISE,
) -> MatchEvaluationMetrics:
    """
    Evaluates match decisions against ground truth, explicitly reporting REVIEW counts and rates.
    """
    if not isinstance(decisions, dict):
        pred_dict = PairwiseEvaluator.validate_and_build_predictions(decisions)
    else:
        pred_dict = decisions

    # Validate unknown prediction IDs
    unknown_ids = set(pred_dict.keys()) - set(ground_truth.keys())
    if unknown_ids:
        if unknown_prediction_policy == UnknownPredictionPolicy.RAISE:
            sorted_unknown = sorted(list(unknown_ids))[:10]
            raise ValueError(
                f"Found {len(unknown_ids)} prediction(s) outside ground truth: {sorted_unknown}. "
                "Actual ground-truth labels are unknown."
            )

    tp = 0
    fp = 0
    fn = 0
    tn = 0
    match_count = 0
    non_match_count = 0
    review_count = 0

    evaluated_ids = [p for p in pred_dict if p in ground_truth]
    for pair_id in evaluated_ids:
        decision = pred_dict[pair_id]
        is_actual_match = ground_truth[pair_id]
        if decision == DecisionType.MATCH:
            match_count += 1
        elif decision == DecisionType.NON_MATCH:
            non_match_count += 1
        elif decision == DecisionType.REVIEW:
            review_count += 1

        is_pred_match = (decision == DecisionType.MATCH) or (decision == DecisionType.REVIEW and review_is_match)

        if is_actual_match:
            if is_pred_match:
                tp += 1
            else:
                fn += 1
        else:
            if is_pred_match:
                fp += 1
            else:
                if decision == DecisionType.REVIEW and review_is_error:
                    fp += 1
                else:
                    tn += 1

    if unknown_prediction_policy == UnknownPredictionPolicy.PENALIZE_AS_FP:
        for unk_id in unknown_ids:
            decision = pred_dict[unk_id]
            if decision == DecisionType.MATCH or (decision == DecisionType.REVIEW and review_is_match):
                fp += 1

    total_evaluated = len(evaluated_ids) + (len(unknown_ids) if unknown_prediction_policy == UnknownPredictionPolicy.PENALIZE_AS_FP else 0)
    return MatchEvaluationMetrics(
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_negatives=tn,
        review_count=review_count,
        total_evaluated=total_evaluated,
        match_count=match_count,
        non_match_count=non_match_count,
    )


def evaluate_end_to_end_pipeline(
    candidate_metrics: CandidateEvaluationMetrics,
    decisions: Union[Dict[str, DecisionType], Iterable[Union[MatchDecision, Tuple[str, DecisionType]]]],
    ground_truth: Dict[str, bool],
    review_is_match: bool = False,
    review_is_error: bool = True,
    unknown_prediction_policy: UnknownPredictionPolicy = UnknownPredictionPolicy.RAISE,
) -> EndToEndEvaluationMetrics:
    """
    Evaluates end-to-end pipeline, connecting candidate generation and match decisions.
    """
    match_metrics = evaluate_match_decisions(
        decisions=decisions,
        ground_truth=ground_truth,
        review_is_match=review_is_match,
        review_is_error=review_is_error,
        unknown_prediction_policy=unknown_prediction_policy,
    )

    total_gt_positives = sum(1 for is_pos in ground_truth.values() if is_pos)
    end_to_end_tp = match_metrics.true_positives

    return EndToEndEvaluationMetrics(
        candidate_metrics=candidate_metrics,
        match_metrics=match_metrics,
        total_ground_truth_positives=total_gt_positives,
        end_to_end_true_positives=end_to_end_tp,
    )


class ClusteringMetrics:
    """
    Cluster-level evaluation metrics assessing derived clusters against ground truth.
    """

    def __init__(
        self,
        total_records: int,
        total_clusters: int,
        singleton_clusters: int,
        multi_record_clusters: int,
        largest_cluster_size: int,
        pairwise_true_positives: int,
        pairwise_false_positives: int,
        pairwise_false_negatives: int,
        pairwise_true_negatives: int,
        purity: float,
    ):
        self.total_records = total_records
        self.total_clusters = total_clusters
        self.singleton_clusters = singleton_clusters
        self.multi_record_clusters = multi_record_clusters
        self.largest_cluster_size = largest_cluster_size
        self.pairwise_true_positives = pairwise_true_positives
        self.pairwise_false_positives = pairwise_false_positives
        self.pairwise_false_negatives = pairwise_false_negatives
        self.pairwise_true_negatives = pairwise_true_negatives
        self.purity = purity

    @property
    def pairwise_precision(self) -> float:
        denom = self.pairwise_true_positives + self.pairwise_false_positives
        return self.pairwise_true_positives / denom if denom > 0 else 0.0

    @property
    def pairwise_recall(self) -> float:
        denom = self.pairwise_true_positives + self.pairwise_false_negatives
        return self.pairwise_true_positives / denom if denom > 0 else 0.0

    @property
    def pairwise_f1(self) -> float:
        p, r = self.pairwise_precision, self.pairwise_recall
        return 2 * (p * r) / (p + r) if (p + r) > 0 else 0.0

    @property
    def cluster_purity(self) -> float:
        return self.purity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_records": self.total_records,
            "total_clusters": self.total_clusters,
            "singleton_clusters": self.singleton_clusters,
            "multi_record_clusters": self.multi_record_clusters,
            "largest_cluster_size": self.largest_cluster_size,
            "pairwise_true_positives": self.pairwise_true_positives,
            "pairwise_false_positives": self.pairwise_false_positives,
            "pairwise_false_negatives": self.pairwise_false_negatives,
            "pairwise_true_negatives": self.pairwise_true_negatives,
            "pairwise_precision": self.pairwise_precision,
            "pairwise_recall": self.pairwise_recall,
            "pairwise_f1": self.pairwise_f1,
            "purity": self.purity,
        }


def evaluate_clustering(
    clusters: Sequence[EntityCluster],
    ground_truth_entities: Mapping[str, str],
) -> ClusteringMetrics:
    """
    Evaluates cluster assignments against ground truth mapping of record_id -> canonical_entity_id.
    """
    if not clusters or not ground_truth_entities:
        return ClusteringMetrics(
            total_records=0,
            total_clusters=0,
            singleton_clusters=0,
            multi_record_clusters=0,
            largest_cluster_size=0,
            pairwise_true_positives=0,
            pairwise_false_positives=0,
            pairwise_false_negatives=0,
            pairwise_true_negatives=0,
            purity=0.0,
        )

    # 1. Map each record to its predicted cluster ID, validating partition disjointness
    seen_members: Dict[str, str] = {}
    for c in clusters:
        for mid in c.member_record_ids:
            if mid in seen_members:
                raise ValueError(
                    f"Invalid clustering: Record '{mid}' appears in multiple clusters: "
                    f"'{seen_members[mid]}' and '{c.entity_cluster_id}'."
                )
            seen_members[mid] = c.entity_cluster_id

    # 2. Complete evaluation universe: all records in ground_truth_entities.
    # Unclustered ground-truth records are treated as implicit singletons so that
    # missed entity merges are accurately penalized as false negatives rather
    # than silently ignored.
    pred_cluster_map = dict(seen_members)
    for r in ground_truth_entities:
        if r not in pred_cluster_map:
            pred_cluster_map[r] = f"__unclustered_singleton_{r}__"

    evaluated_records = sorted(list(ground_truth_entities.keys()))
    n = len(evaluated_records)

    # 3. Pairwise cluster evaluation across all evaluated record pairs
    tp = 0
    fp = 0
    fn = 0
    tn = 0

    for i in range(n):
        for j in range(i + 1, n):
            r_i = evaluated_records[i]
            r_j = evaluated_records[j]
            same_cluster = (pred_cluster_map[r_i] == pred_cluster_map[r_j])
            same_truth = (ground_truth_entities[r_i] == ground_truth_entities[r_j])

            if same_cluster and same_truth:
                tp += 1
            elif same_cluster and not same_truth:
                fp += 1
            elif not same_cluster and same_truth:
                fn += 1
            else:
                tn += 1

    # 4. Cluster purity: sum of max class counts in each cluster / total evaluated records
    majority_sum = 0
    for c in clusters:
        members = [m for m in c.member_record_ids if m in ground_truth_entities]
        if not members:
            continue
        counts: Dict[str, int] = {}
        for m in members:
            gt_id = ground_truth_entities[m]
            counts[gt_id] = counts.get(gt_id, 0) + 1
        majority_sum += max(counts.values())

    # Unclustered ground-truth records are singletons contributing 1 each
    unclustered_count = sum(1 for r in ground_truth_entities if r not in seen_members)
    majority_sum += unclustered_count

    purity = (majority_sum / len(evaluated_records)) if evaluated_records else 0.0

    singleton_count = sum(1 for c in clusters if len(c.member_record_ids) == 1)
    multi_count = sum(1 for c in clusters if len(c.member_record_ids) > 1)
    max_size = max((len(c.member_record_ids) for c in clusters), default=0)

    return ClusteringMetrics(
        total_records=len(evaluated_records),
        total_clusters=len(clusters),
        singleton_clusters=singleton_count,
        multi_record_clusters=multi_count,
        largest_cluster_size=max_size,
        pairwise_true_positives=tp,
        pairwise_false_positives=fp,
        pairwise_false_negatives=fn,
        pairwise_true_negatives=tn,
        purity=purity,
    )
