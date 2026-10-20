"""
Unit and integration tests for Milestone 5: Reproducible End-to-End Evaluation & Benchmarking.

Verifies:
1. End-to-end pipeline execution sequence
2. Strict determinism across repeated runs with identical seed
3. Seed variability producing distinct procedural scenarios
4. Leakage prevention and ground-truth isolation
5. Adversarial unconfigured alias protection
6. Full coverage of all 14 controlled benchmark edge cases
7. Conservative full-clique vs default clustering on missing transitive pairs
8. Fair baseline comparison (Exhaustive, Blocking, Conservative, Default)
9. Diagnostics completeness (false matches, missed matches, clustering errors)
10. Zero-denominator safeguards
11. Duplicate and invalid decision detection
12. JSON artifact serialization and round-trip validity
13. CLI execution and argument handling
14. Immutability and preservation of raw input records
"""

import json
import os
import subprocess
import sys
import tempfile
import pytest

from src.core.benchmark import (
    BenchmarkReport,
    BenchmarkRunConfig,
    BenchmarkRunner,
    BenchmarkScenario,
    PipelineExecutionResult,
    build_controlled_edge_case_scenarios,
    build_master_controlled_scenario,
    build_real_world_restaurant_scenario,
    build_standard_synthetic_scenario,
    execute_pipeline,
    evaluate_pipeline_run,
    format_console_summary,
    generate_procedural_scenario,
    generate_real_world_error_analysis,
    run_baseline_conservative_clustering,
    run_baseline_default_clustering,
    run_baseline_exhaustive,
    run_baseline_blocking_pipeline,
    save_benchmark_artifact,
)
from src.core.blocking import CandidateGenerator
from src.core.clustering import ConstraintAwareClusterer, ClusteringPolicy
from src.core.comparison import PairwiseComparator
from src.core.decision import DecisionPolicy, MatchDecisionEngine
from src.core.evaluation import (
    PairwiseEvaluator,
    UnknownPredictionPolicy,
    evaluate_match_decisions,
)
from src.core.models import (
    CandidatePair,
    DecisionType,
    EntityType,
    MatchDecision,
    Record,
)


def test_pipeline_execution_sequence():
    """Verifies that execute_pipeline executes candidate generation, comparison, decision, and clustering in sequence."""
    scenario = build_standard_synthetic_scenario()
    res = execute_pipeline(scenario.records, known_aliases=scenario.known_aliases)

    assert isinstance(res, PipelineExecutionResult)
    assert len(res.records) == 21
    assert len(res.candidate_pairs) > 0
    assert len(res.match_decisions) == len(res.candidate_pairs)
    assert len(res.clustering_result.clusters) > 0
    assert "candidate_generation_seconds" in res.timings_seconds
    assert "pairwise_matching_seconds" in res.timings_seconds
    assert "clustering_seconds" in res.timings_seconds
    assert "total_pipeline_seconds" in res.timings_seconds


def test_benchmark_determinism():
    """Verifies that two runs with the same seed yield identical predictions, clusters, metrics, and fingerprints."""
    config1 = BenchmarkRunConfig(seed=42)
    config2 = BenchmarkRunConfig(seed=42)

    runner1 = BenchmarkRunner(config1)
    runner2 = BenchmarkRunner(config2)

    report1 = runner1.run_suite(include_edge_cases=True, include_procedural=True, procedural_size=10)
    report2 = runner2.run_suite(include_edge_cases=True, include_procedural=True, procedural_size=10)

    # Master deterministic fingerprints must be strictly identical
    assert report1.deterministic_fingerprint == report2.deterministic_fingerprint

    # Scenario fingerprints and metric values must match
    for s_id in report1.scenarios:
        assert s_id in report2.scenarios
        sc1 = report1.scenarios[s_id]
        sc2 = report2.scenarios[s_id]
        assert sc1["deterministic_fingerprint"] == sc2["deterministic_fingerprint"]
        assert sc1["candidate_metrics"] == sc2["candidate_metrics"]
        assert sc1["match_metrics"] == sc2["match_metrics"]
        assert sc1["clustering_metrics"] == sc2["clustering_metrics"]
        assert sc1["end_to_end_metrics"] == sc2["end_to_end_metrics"]


def test_benchmark_seed_variability():
    """Verifies that different seeds produce distinct procedural scenarios and distinct fingerprints."""
    proc1 = generate_procedural_scenario(seed=42, num_base_entities=12)
    proc2 = generate_procedural_scenario(seed=99, num_base_entities=12)

    assert proc1.scenario_id != proc2.scenario_id
    # Names and IDs should differ between seeds
    names1 = [r.raw_name for r in proc1.records]
    names2 = [r.raw_name for r in proc2.records]
    assert names1 != names2

    config1 = BenchmarkRunConfig(seed=42)
    config2 = BenchmarkRunConfig(seed=99)
    res1 = BenchmarkRunner(config1).run_scenario(proc1)
    res2 = BenchmarkRunner(config2).run_scenario(proc2)
    assert res1.deterministic_fingerprint != res2.deterministic_fingerprint


def test_leakage_resilience_ground_truth_isolation():
    """
    Verifies that ground truth is strictly isolated from pipeline execution.
    Altering ground-truth labels has ZERO effect on generated candidate pairs, decisions, or clusters.
    """
    scenario = build_standard_synthetic_scenario()
    res1 = execute_pipeline(scenario.records, known_aliases=scenario.known_aliases)

    # Invert ground-truth pairs and change ground-truth entities
    inverted_gt_pairs = {k: not v for k, v in scenario.ground_truth_pairs.items()}
    modified_gt_entities = {k: "corrupted_entity_id" for k in scenario.ground_truth_entities}

    corrupted_scenario = BenchmarkScenario(
        scenario_id="corrupted_oracle",
        name="Corrupted Oracle Scenario",
        description="Scenario with corrupted ground truth to verify zero leakage.",
        records=scenario.records,
        ground_truth_entities=modified_gt_entities,
        ground_truth_pairs=inverted_gt_pairs,
        known_aliases=scenario.known_aliases,
    )

    res2 = execute_pipeline(corrupted_scenario.records, known_aliases=corrupted_scenario.known_aliases)

    # Pipeline output must be 100% identical
    assert len(res1.candidate_pairs) == len(res2.candidate_pairs)
    assert [d.decision for d in res1.match_decisions] == [d.decision for d in res2.match_decisions]
    assert [d.score for d in res1.match_decisions] == [d.score for d in res2.match_decisions]
    assert res1.clustering_result.record_to_cluster == res2.clustering_result.record_to_cluster


def test_adversarial_unconfigured_alias_prevention():
    """
    Adversarial test: verifies that aliases without explicit configuration fail to match,
    proving alias mappings are not leaked from ground truth.
    """
    edge_cases = build_controlled_edge_case_scenarios()

    # 1. Configured alias scenario (Twain / Clemens)
    sc_cfg = edge_cases["aliases_with_config"]
    res_cfg = execute_pipeline(sc_cfg.records, known_aliases=sc_cfg.known_aliases)
    assert len(res_cfg.match_decisions) == 1
    assert res_cfg.match_decisions[0].decision == DecisionType.MATCH

    # 2. Unconfigured alias scenario (Orwell / Blair)
    sc_nocfg = edge_cases["aliases_without_config"]
    res_nocfg = execute_pipeline(sc_nocfg.records, known_aliases=sc_nocfg.known_aliases)
    # Because names are completely disparate ("Eric Arthur Blair" vs "George Orwell") and no alias configured,
    # candidate generation should either block it or the decision engine must reject it
    if res_nocfg.match_decisions:
        assert res_nocfg.match_decisions[0].decision != DecisionType.MATCH


def test_all_14_controlled_edge_case_scenarios_presence_and_execution():
    """Verifies that all 14 required controlled benchmark scenarios exist and evaluate properly."""
    edge_cases = build_controlled_edge_case_scenarios()
    expected_scenarios = [
        "exact_duplicates",
        "spelling_variations",
        "initials_and_abbreviations",
        "aliases_with_config",
        "aliases_without_config",
        "missing_attributes",
        "common_names",
        "shared_context",
        "conflicting_attributes",
        "cross_entity_types",
        "transitive_chain",
        "contradiction_in_component",
        "unrelated_singletons",
        "mixed_cluster_sizes",
    ]

    for s_name in expected_scenarios:
        assert s_name in edge_cases, f"Scenario '{s_name}' missing from controlled benchmark fixtures"

    runner = BenchmarkRunner()
    for s_name, sc in edge_cases.items():
        evaluated = runner.run_scenario(sc)
        assert evaluated.record_count == len(sc.records)
        assert evaluated.deterministic_fingerprint != ""
        assert "candidate_metrics" in evaluated.__dict__ or hasattr(evaluated, "candidate_metrics")


def test_transitive_chain_conservative_vs_default_clustering():
    """
    Verifies that on a transitive chain with missing A-C comparison:
    - Default clustering merges all 3 records into a single cluster.
    - Conservative clustering (require_full_clique=True) refuses to merge all 3 records.
    """
    edge_cases = build_controlled_edge_case_scenarios()
    sc = edge_cases["transitive_chain"]

    # Default clustering
    pipe_res = execute_pipeline(sc.records, known_aliases=sc.known_aliases)
    eval_def = evaluate_pipeline_run(pipe_res, sc, BenchmarkRunConfig())

    # Conservative clustering
    clusterer_con = ConstraintAwareClusterer(
        policy=ClusteringPolicy(require_full_clique=True),
        comparator=PairwiseComparator(known_aliases=sc.known_aliases),
    )
    pipe_con = execute_pipeline(sc.records, known_aliases=sc.known_aliases, clusterer=clusterer_con)
    eval_con = evaluate_pipeline_run(pipe_con, sc, BenchmarkRunConfig())

    # Default should merge into 1 cluster of 3
    assert eval_def.clustering_metrics["total_clusters"] == 1
    assert eval_def.clustering_metrics["largest_cluster_size"] == 3
    assert eval_def.clustering_metrics["pairwise_recall"] == 1.0

    # Conservative should have 2 clusters because clique is incomplete
    assert eval_con.clustering_metrics["total_clusters"] == 2
    assert eval_con.clustering_metrics["largest_cluster_size"] == 2
    assert eval_con.clustering_metrics["pairwise_recall"] < eval_def.clustering_metrics["pairwise_recall"]


def test_four_baselines_fairness_and_execution():
    """
    Verifies that all 4 baselines run under fair, identical conditions:
    1. Exhaustive pair evaluation
    2. Blocking pipeline
    3. Conservative clustering
    4. Default clustering
    """
    master_sc = build_master_controlled_scenario()
    config = BenchmarkRunConfig(seed=42)

    b1 = run_baseline_exhaustive(master_sc, config)
    b2 = run_baseline_blocking_pipeline(master_sc, config)
    b3 = run_baseline_conservative_clustering(master_sc, config)
    b4 = run_baseline_default_clustering(master_sc, config)

    # 1. Exhaustive compares all compatible pairs
    assert b1.metrics["candidate_pairs_evaluated"] == master_sc_compatible_pairs_count(master_sc)
    assert b1.metrics["candidate_pairs_evaluated"] > b2.metrics["candidate_pairs_evaluated"]

    # 2. Blocking reduces candidates significantly
    assert b2.metrics["reduction_ratio"] > 0.90

    # 3. Conservative clustering has lower or equal cluster recall than default clustering
    assert b3.metrics["cluster_recall"] <= b4.metrics["cluster_recall"]
    assert b3.metrics["total_clusters"] >= b4.metrics["total_clusters"]

    # 4. Each baseline provides a deterministic fingerprint
    assert b1.deterministic_fingerprint != ""
    assert b2.deterministic_fingerprint != ""
    assert b3.deterministic_fingerprint != ""
    assert b4.deterministic_fingerprint != ""


def master_sc_compatible_pairs_count(sc: BenchmarkScenario) -> int:
    from collections import Counter
    counts = Counter(r.entity_type for r in sc.records)
    return sum(c * (c - 1) // 2 for c in counts.values())


def test_diagnostics_completeness():
    """Verifies that evaluation diagnostics capture error examples and documented denominators."""
    master_sc = build_master_controlled_scenario()
    runner = BenchmarkRunner()
    evaluated = runner.run_scenario(master_sc)

    diag = evaluated.diagnostics
    assert "missed_candidate_positives" in diag
    assert "false_matches" in diag
    assert "missed_matches" in diag
    assert "clustering_incorrect_merges" in diag
    assert "clustering_missed_comemberships" in diag
    assert "rejected_merges" in diag
    assert "unresolved_candidate_pairs" in diag
    assert "omitted_ground_truth_records" in diag
    assert "metric_denominators" in diag

    denoms = diag["metric_denominators"]
    assert "precision_denom" in denoms
    assert "recall_denom" in denoms
    assert "zero_denominator_behavior" in denoms


def test_zero_denominator_safeguards():
    """Verifies that evaluation handles scenarios with zero positives or zero candidates without crashing."""
    r_empty1 = Record(record_id="e1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Zero Positives A")
    r_empty2 = Record(record_id="e2", source_id="s2", entity_type=EntityType.PERSON, raw_name="Zero Positives B")

    empty_sc = BenchmarkScenario(
        scenario_id="zero_pos",
        name="Zero Positives Scenario",
        description="Scenario with no true matches",
        records=(r_empty1, r_empty2),
        ground_truth_entities={"e1": "ent_1", "e2": "ent_2"},
        ground_truth_pairs={"cp_e1_e2": False},
    )

    runner = BenchmarkRunner()
    evaluated = runner.run_scenario(empty_sc)

    assert evaluated.candidate_metrics["ground_truth_positives_count"] == 0
    assert evaluated.candidate_metrics["candidate_recall"] == 0.0
    assert evaluated.match_metrics["true_positives"] == 0
    assert evaluated.match_metrics["recall"] == 0.0


def test_duplicate_and_invalid_decision_detection():
    """Verifies that duplicate candidate pair predictions or invalid types are rejected."""
    r1 = Record(record_id="r1", source_id="s1", entity_type=EntityType.PERSON, raw_name="Test One")
    r2 = Record(record_id="r2", source_id="s2", entity_type=EntityType.PERSON, raw_name="Test Two")

    d1 = MatchDecision(candidate_pair_id="cp_r1_r2", decision=DecisionType.MATCH, score=0.9, threshold=0.75, model_version="v1")
    d2 = MatchDecision(candidate_pair_id="cp_r1_r2", decision=DecisionType.NON_MATCH, score=0.1, threshold=0.75, model_version="v1")

    # Duplicate prediction detection
    with pytest.raises(ValueError, match="Duplicate predictions detected"):
        PairwiseEvaluator.validate_and_build_predictions([d1, d2])

    # Invalid type detection
    with pytest.raises(TypeError):
        PairwiseEvaluator.validate_and_build_predictions(["invalid_decision_object"])


def test_json_artifact_serialization_and_roundtrip(tmp_path):
    """Verifies that benchmark results serialize to valid JSON and round-trip without loss."""
    runner = BenchmarkRunner(BenchmarkRunConfig(seed=42))
    report = runner.run_suite(include_edge_cases=False, include_procedural=False)

    out_file = str(tmp_path / "test_report.json")
    save_benchmark_artifact(report, out_file)

    assert os.path.exists(out_file)

    with open(out_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    assert "metadata" in loaded
    assert "scenarios" in loaded
    assert "baselines" in loaded
    assert "deterministic_fingerprint" in loaded
    assert loaded["deterministic_fingerprint"] == report.deterministic_fingerprint


def test_raw_records_immutability():
    """Verifies that raw Record models are preserved completely intact and never mutated."""
    scenario = build_standard_synthetic_scenario()
    initial_dumps = [r.model_dump_json() for r in scenario.records]

    runner = BenchmarkRunner()
    runner.run_scenario(scenario)

    post_dumps = [r.model_dump_json() for r in scenario.records]
    assert initial_dumps == post_dumps


def test_cli_execution_subprocess():
    """Verifies running the benchmark CLI as a Python module via command-line."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_out = tf.name

    try:
        cmd = [
            sys.executable,
            "-m",
            "src.core.benchmark",
            "--seed",
            "42",
            "--output",
            temp_out,
            "--quiet",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        assert res.returncode == 0
        assert os.path.exists(temp_out)
        with open(temp_out, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "deterministic_fingerprint" in data
        assert data["metadata"]["seed"] == 42
    finally:
        if os.path.exists(temp_out):
            os.remove(temp_out)


def test_build_real_world_restaurant_scenario_fixture():
    """Verifies building the real-world scenario using the offline 10-record fixture."""
    scenario = build_real_world_restaurant_scenario(use_fixture=True)
    assert scenario.scenario_id == "real_world_restaurant"
    assert len(scenario.records) == 10
    # 10 records -> 45 total pairs
    assert len(scenario.ground_truth_pairs) == 45
    # 3 duplicate pairs (entities 0, 1, 2)
    positives = [p for p, is_pos in scenario.ground_truth_pairs.items() if is_pos]
    assert len(positives) == 3
    # Ground truth isolation: known_aliases must be strictly empty
    assert scenario.known_aliases == {}
    assert scenario.metadata.get("is_offline_fixture") is True


def test_real_world_suite_runner_fixture():
    """Verifies executing all 4 baselines on the real-world scenario with offline fixture."""
    runner = BenchmarkRunner(BenchmarkRunConfig(seed=42))
    report = runner.run_real_world_suite(use_fixture=True, max_block_size=50)

    assert "real_world_restaurant" in report.scenarios
    assert "exhaustive_pairs" in report.baselines
    assert "blocking_pipeline" in report.baselines
    assert "conservative_clustering" in report.baselines
    assert "default_clustering" in report.baselines
    assert report.deterministic_fingerprint
    assert len(report.deterministic_fingerprint) == 64

    sc = report.scenarios["real_world_restaurant"]
    assert sc["record_count"] == 10
    assert sc["total_possible_pairs"] == 45
    assert sc["candidate_metrics"]["ground_truth_positives_count"] == 3


def test_generate_real_world_error_analysis():
    """Verifies that Markdown error analysis report is correctly generated with grounded case studies."""
    runner = BenchmarkRunner(BenchmarkRunConfig(seed=42))
    report = runner.run_real_world_suite(use_fixture=True, max_block_size=50)

    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tf:
        temp_md = tf.name

    try:
        md_text = generate_real_world_error_analysis(report, output_md_path=temp_md)
        assert os.path.exists(temp_md)
        assert "# Sherlock AI — Milestone 6: Real-World Dataset Integration & Error Analysis" in md_text
        assert "Zagat-Fodor's" in md_text
        assert "CC0 1.0 Universal" in md_text
        assert "Case Study 1" in md_text
        assert "Case Study 2" in md_text
        assert "Case Study 3" in md_text
        assert "FAIR BASELINE COMPARISON" in format_console_summary(report)
    finally:
        if os.path.exists(temp_md):
            os.remove(temp_md)


def test_cli_real_world_fixture_subprocess():
    """Verifies running the real-world benchmark CLI via command line with offline fixture."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf1:
        temp_json = tf1.name
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tf2:
        temp_md = tf2.name

    try:
        cmd = [
            sys.executable,
            "-m",
            "src.core.benchmark",
            "--real-world",
            "--use-fixture",
            "--output",
            temp_json,
            "--report-md",
            temp_md,
            "--quiet",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        assert res.returncode == 0
        assert os.path.exists(temp_json)
        assert os.path.exists(temp_md)

        with open(temp_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "deterministic_fingerprint" in data
        assert "real_world_restaurant" in data["scenarios"]

        with open(temp_md, "r", encoding="utf-8") as f:
            md_content = f.read()
        assert "Zagat-Fodor's Restaurant" in md_content
    finally:
        if os.path.exists(temp_json):
            os.remove(temp_json)
        if os.path.exists(temp_md):
            os.remove(temp_md)


def test_cli_milestone_7_execution():
    """Verifies that python src/core/benchmark.py --milestone-7 --use-fixture runs and produces valid artifacts."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fj, tempfile.NamedTemporaryFile(suffix=".md", delete=False) as fmd:
        temp_json = fj.name
        temp_md = fmd.name

    try:
        cmd = [
            sys.executable,
            "src/core/benchmark.py",
            "--milestone-7",
            "--use-fixture",
            "--output",
            temp_json,
            "--report-md",
            temp_md,
            "--quiet",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        assert res.returncode == 0
        assert os.path.exists(temp_json)
        assert os.path.exists(temp_md)

        with open(temp_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["milestone"] == "Milestone 7"
        assert "master_deterministic_fingerprint" in data
        assert "dev" in data["splits"]
        assert "val" in data["splits"]
        assert "test" in data["splits"]
        assert "calibrated_evidence" in data["splits"]["val"]["policies"]

        with open(temp_md, "r", encoding="utf-8") as f:
            md_content = f.read()
        assert "Milestone 7: Production-Grade Entity Resolution" in md_content
        assert "Executive Summary & Baseline Reconciled Comparison" in md_content
    finally:
        if os.path.exists(temp_json):
            os.remove(temp_json)
        if os.path.exists(temp_md):
            os.remove(temp_md)


