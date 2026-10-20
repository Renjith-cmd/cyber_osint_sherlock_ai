import pytest
from src.core.evaluation import PairwiseEvaluator, EvaluationMetrics, UnknownPredictionPolicy
from src.core.models import DecisionType, MatchDecision

# ---------------------------------------------------------------------------
# 8. Existing TP=2, FP=1, FN=1 Mathematical Example
# ---------------------------------------------------------------------------

def test_pairwise_evaluation_mathematics():
    # Setup a scenario where TP=2, FP=1, FN=1, TN=2
    # Total actual matches = TP + FN = 3
    # Total actual non-matches = FP + TN = 3
    ground_truth = {
        "cp_tp1": True,
        "cp_tp2": True,
        "cp_fn1": True,
        "cp_fp1": False,
        "cp_tn1": False,
        "cp_tn2": False
    }
    
    predictions = {
        "cp_tp1": DecisionType.MATCH,
        "cp_tp2": DecisionType.MATCH,
        "cp_fn1": DecisionType.NON_MATCH,
        "cp_fp1": DecisionType.MATCH,
        "cp_tn1": DecisionType.NON_MATCH,
        "cp_tn2": DecisionType.NON_MATCH
    }
    
    evaluator = PairwiseEvaluator()
    metrics = evaluator.evaluate(predictions, ground_truth)
    
    assert metrics.true_positives == 2
    assert metrics.false_positives == 1
    assert metrics.false_negatives == 1
    assert metrics.true_negatives == 2
    
    # Precision = TP / (TP + FP) = 2 / 3
    assert abs(metrics.precision - 2/3) < 1e-5
    
    # Recall = TP / (TP + FN) = 2 / 3
    assert abs(metrics.recall - 2/3) < 1e-5
    
    # F1 = 2 * (P * R) / (P + R) = 2/3
    assert abs(metrics.f1 - 2/3) < 1e-5

# ---------------------------------------------------------------------------
# 1. Predictions Containing Unknown Pair IDs
# ---------------------------------------------------------------------------

def test_evaluation_unknown_pair_ids_raise_by_default():
    ground_truth = {"cp_known": True}
    predictions = {
        "cp_known": DecisionType.MATCH,
        "cp_unknown_1": DecisionType.MATCH,
        "cp_unknown_2": DecisionType.NON_MATCH
    }
    evaluator = PairwiseEvaluator()
    with pytest.raises(ValueError) as exc_info:
        evaluator.evaluate(predictions, ground_truth)
    assert "outside ground truth" in str(exc_info.value)
    assert "cp_unknown_1" in str(exc_info.value)

def test_evaluation_unknown_pair_ids_opt_in_policies():
    ground_truth = {"cp_known": True}
    predictions = {
        "cp_known": DecisionType.MATCH,
        "cp_unknown": DecisionType.MATCH
    }
    # Opt-in policy: IGNORE
    eval_ignore = PairwiseEvaluator(unknown_prediction_policy=UnknownPredictionPolicy.IGNORE)
    m_ignore = eval_ignore.evaluate(predictions, ground_truth)
    assert m_ignore.true_positives == 1
    assert m_ignore.false_positives == 0

    # Opt-in policy: PENALIZE_AS_FP
    eval_penalize = PairwiseEvaluator(unknown_prediction_policy=UnknownPredictionPolicy.PENALIZE_AS_FP)
    m_penalize = eval_penalize.evaluate(predictions, ground_truth)
    assert m_penalize.true_positives == 1
    assert m_penalize.false_positives == 1  # The ungrounded MATCH is penalized as FP

# ---------------------------------------------------------------------------
# 2. Missing Predictions for Known Ground-Truth Pairs
# ---------------------------------------------------------------------------

def test_evaluation_missing_predictions_handling():
    ground_truth = {
        "cp_match": True,
        "cp_non_match": False
    }
    # Predictions dictionary completely omits both pairs
    predictions = {}
    evaluator = PairwiseEvaluator()
    metrics = evaluator.evaluate(predictions, ground_truth)

    # Missing true match must count as False Negative (missed match)
    assert metrics.false_negatives == 1
    # Missing true non-match counts as True Negative (correct rejection)
    assert metrics.true_negatives == 1
    assert metrics.true_positives == 0
    assert metrics.false_positives == 0

# ---------------------------------------------------------------------------
# 3. Empty Ground Truth and Empty Predictions
# ---------------------------------------------------------------------------

def test_evaluation_empty_inputs():
    evaluator = PairwiseEvaluator()
    metrics = evaluator.evaluate({}, {})
    assert metrics.true_positives == 0
    assert metrics.false_positives == 0
    assert metrics.false_negatives == 0
    assert metrics.true_negatives == 0
    assert metrics.precision == 0.0
    assert metrics.recall == 0.0
    assert metrics.f1 == 0.0

# ---------------------------------------------------------------------------
# 4. Zero-Denominator Metric Cases
# ---------------------------------------------------------------------------

def test_evaluation_zero_denominator_safeties():
    # TP=0, FP=0, FN=2 (no positive predictions made, all true matches missed)
    m1 = EvaluationMetrics(tp=0, fp=0, fn=2, true_negatives=2)
    assert m1.precision == 0.0  # Denominator (TP + FP) == 0
    assert m1.recall == 0.0
    assert m1.f1 == 0.0

    # TP=0, FP=2, FN=0 (no true matches exist, model predicted 2 matches)
    m2 = EvaluationMetrics(tp=0, fp=2, fn=0, true_negatives=2)
    assert m2.precision == 0.0
    assert m2.recall == 0.0     # Denominator (TP + FN) == 0
    assert m2.f1 == 0.0

# ---------------------------------------------------------------------------
# 5 & 6. REVIEW on True Match and True Non-Match
# ---------------------------------------------------------------------------

def test_evaluation_review_handling():
    ground_truth = {
        "cp_match": True,
        "cp_non_match": False
    }
    predictions = {
        "cp_match": DecisionType.REVIEW,
        "cp_non_match": DecisionType.REVIEW
    }

    # Config 1: Default (review_is_match=False, review_is_error=True)
    eval1 = PairwiseEvaluator(review_is_match=False, review_is_error=True)
    m1 = eval1.evaluate(predictions, ground_truth)
    assert m1.true_positives == 0
    assert m1.false_negatives == 1  # Missed match
    assert m1.false_positives == 1  # False alarm on non-match

    # Config 2: Review is treated as match (review_is_match=True)
    eval2 = PairwiseEvaluator(review_is_match=True)
    m2 = eval2.evaluate(predictions, ground_truth)
    assert m2.true_positives == 1
    assert m2.false_positives == 1

    # Config 3: Review is not match, but non-match review not penalized (review_is_error=False)
    eval3 = PairwiseEvaluator(review_is_match=False, review_is_error=False)
    m3 = eval3.evaluate(predictions, ground_truth)
    assert m3.false_positives == 0
    assert m3.true_negatives == 1
    assert m3.false_negatives == 1

# ---------------------------------------------------------------------------
# 7. Duplicate Logical Candidate Pairs
# ---------------------------------------------------------------------------

def test_evaluation_duplicate_predictions_rejected():
    decisions = [
        MatchDecision(candidate_pair_id="cp_1", decision=DecisionType.MATCH, model_version="v1"),
        MatchDecision(candidate_pair_id="cp_1", decision=DecisionType.NON_MATCH, model_version="v1")
    ]
    evaluator = PairwiseEvaluator()
    ground_truth = {"cp_1": True}

    with pytest.raises(ValueError) as exc_info:
        evaluator.evaluate(decisions, ground_truth)
    assert "Duplicate predictions detected" in str(exc_info.value)
    assert "cp_1" in str(exc_info.value)


def test_validate_and_build_predictions_tuples():

    pairs = [
        ("cp_1", DecisionType.MATCH),
        ("cp_1", DecisionType.REVIEW)
    ]
    with pytest.raises(ValueError) as exc_info:
        PairwiseEvaluator.validate_and_build_predictions(pairs)
    assert "Duplicate predictions detected" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 8. Clustering Metrics and Evaluation

# ---------------------------------------------------------------------------

def test_evaluate_clustering_metrics_math():
    from src.core.models import EntityCluster, EntityType, ClusterStatus
    from src.core.evaluation import evaluate_clustering, ClusteringMetrics

    ground_truth = {
        "r1": "E1",
        "r2": "E1",
        "r3": "E2",
        "r4": "E2",
    }

    # Case A: Perfect clustering
    c1 = EntityCluster(entity_cluster_id="c1", entity_type=EntityType.PERSON, member_record_ids=["r1", "r2"], status=ClusterStatus.ACTIVE, derivation_version="v1")
    c2 = EntityCluster(entity_cluster_id="c2", entity_type=EntityType.PERSON, member_record_ids=["r3", "r4"], status=ClusterStatus.ACTIVE, derivation_version="v1")

    m_perfect = evaluate_clustering([c1, c2], ground_truth)
    assert m_perfect.total_records == 4
    assert m_perfect.total_clusters == 2
    assert m_perfect.pairwise_true_positives == 2
    assert m_perfect.pairwise_false_positives == 0
    assert m_perfect.pairwise_false_negatives == 0
    assert m_perfect.pairwise_true_negatives == 4
    assert m_perfect.pairwise_precision == 1.0
    assert m_perfect.pairwise_recall == 1.0
    assert m_perfect.pairwise_f1 == 1.0
    assert m_perfect.purity == 1.0

    # Case B: Over-merged clustering (merged E1 and E2 into one cluster)
    c_all = EntityCluster(entity_cluster_id="c_all", entity_type=EntityType.PERSON, member_record_ids=["r1", "r2", "r3", "r4"], status=ClusterStatus.ACTIVE, derivation_version="v1")
    m_over = evaluate_clustering([c_all], ground_truth)
    assert m_over.pairwise_true_positives == 2
    assert m_over.pairwise_false_positives == 4
    assert m_over.pairwise_false_negatives == 0
    assert m_over.pairwise_precision == pytest.approx(2 / 6)
    assert m_over.pairwise_recall == 1.0
    assert m_over.purity == 0.5

    # Case C: Under-merged clustering (all singletons)
    c_singletons = [
        EntityCluster(entity_cluster_id=f"c_{rid}", entity_type=EntityType.PERSON, member_record_ids=[rid], status=ClusterStatus.ACTIVE, derivation_version="v1")
        for rid in ["r1", "r2", "r3", "r4"]
    ]
    m_under = evaluate_clustering(c_singletons, ground_truth)
    assert m_under.pairwise_true_positives == 0
    assert m_under.pairwise_false_positives == 0
    assert m_under.pairwise_false_negatives == 2
    assert m_under.pairwise_precision == 0.0
    assert m_under.pairwise_recall == 0.0
    assert m_under.purity == 1.0


def test_evaluate_clustering_empty_inputs():
    from src.core.evaluation import evaluate_clustering
    m_empty = evaluate_clustering([], {})
    assert m_empty.total_records == 0
    assert m_empty.total_clusters == 0
    assert m_empty.pairwise_precision == 0.0
    assert m_empty.to_dict()["total_records"] == 0


def test_evaluate_clustering_disjointness_enforcement():
    from src.core.models import EntityCluster, EntityType, ClusterStatus
    from src.core.evaluation import evaluate_clustering

    c1 = EntityCluster(entity_cluster_id="c1", entity_type=EntityType.PERSON, member_record_ids=["r1", "r2"], status=ClusterStatus.ACTIVE, derivation_version="v1")
    c2 = EntityCluster(entity_cluster_id="c2", entity_type=EntityType.PERSON, member_record_ids=["r2", "r3"], status=ClusterStatus.ACTIVE, derivation_version="v1")

    # r2 appears in both c1 and c2 -> must raise ValueError
    with pytest.raises(ValueError) as exc_info:
        evaluate_clustering([c1, c2], {"r1": "E1", "r2": "E1", "r3": "E2"})
    assert "appears in multiple clusters" in str(exc_info.value)
    assert "r2" in str(exc_info.value)


def test_evaluate_clustering_unclustered_ground_truth_records_penalized_as_fn():
    from src.core.models import EntityCluster, EntityType, ClusterStatus
    from src.core.evaluation import evaluate_clustering

    ground_truth = {
        "r1": "E1",
        "r2": "E1",
        "r3": "E2",
        "r4": "E2",
    }

    # Only cluster for E1 is provided; E2 records (r3, r4) were completely omitted/unclustered
    c1 = EntityCluster(entity_cluster_id="c1", entity_type=EntityType.PERSON, member_record_ids=["r1", "r2"], status=ClusterStatus.ACTIVE, derivation_version="v1")

    metrics = evaluate_clustering([c1], ground_truth)
    assert metrics.total_records == 4
    assert metrics.pairwise_true_positives == 1   # r1-r2 correct
    assert metrics.pairwise_false_negatives == 1  # r3-r4 missed because they were unclustered
    assert metrics.pairwise_false_positives == 0  # no erroneous merges
    assert metrics.pairwise_true_negatives == 4   # r1-r3, r1-r4, r2-r3, r2-r4 correctly kept apart
    assert metrics.pairwise_precision == 1.0
    assert metrics.pairwise_recall == 0.5         # 1 / (1 + 1) = 50%
    assert metrics.pairwise_f1 == pytest.approx(2 / 3)
