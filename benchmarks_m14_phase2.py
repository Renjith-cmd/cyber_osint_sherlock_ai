"""
Milestone 14 Phase 2: Comprehensive Performance & Durability Benchmark Harness.

Measures:
1. Document Pipeline Latency & Throughput (Ingest, Extract, Resolve, Sync, End-to-End)
   across multiple deterministic fixture sizes (Small, Medium, Large).
2. Entity Resolution (Candidate Generation, Reduction Ratio, Precision, Recall, F1, Runtime)
   on synthetic scenarios and Zagat-Fodor's restaurant benchmark.
3. SQLite Persistence (Cold sync, Warm sync, Reopen/Hydrate, Read, File Size, PRAGMA integrity_check).
4. Memory RSS (Baseline vs Peak RSS, model-loading overhead).
"""

import gc
import json
import os
import platform
import resource
import statistics
import sys
import tempfile
import time
from typing import Any, Dict, List, Tuple

_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__)))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from src.core.models import (
    EntityType,
    InvestigationEntity,
    ReviewStatus,
)
from src.core.investigation_sqlite import SQLiteInvestigationStore
from src.core.investigation_service import InvestigationOrchestrator, InvestigationStatus
from src.core.benchmark import BenchmarkRunner, BenchmarkRunConfig
from src.core.document_pipeline import DocumentExtractionPipeline


def get_current_rss_mb() -> float:
    """Get current process Resident Set Size (RSS) in Megabytes using Linux /proc/self/status."""
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_maxrss / 1024.0


def get_peak_rss_mb() -> float:
    """Get peak process Resident Set Size (RSS / High Water Mark) in Megabytes."""
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_maxrss / 1024.0


def generate_synthetic_document(size_category: str) -> Tuple[bytes, str]:
    """
    Generate deterministic synthetic investigation text with patterns
    matching the extraction engine at specified scale.
    """
    base_template = (
        "Alice Mercer serves as CEO of Apex Global Holdings. Apex Global Holdings is located in London. "
        "Dr. Marcus Vance founded Vance BioTech in Zurich. Elena Rostova was appointed Director of "
        "Global Finance Corp in 2024. Jonathan Hayes is the primary beneficiary of Hayes Trust. "
        "Acme Industrial Ltd acquired Zenith Robotics in Munich. "
    )
    if size_category == "small":  # ~1 KB
        multiplier = 3
    elif size_category == "medium":  # ~10 KB
        multiplier = 30
    elif size_category == "large":  # ~50 KB
        multiplier = 150
    else:
        multiplier = 5

    text = (base_template * multiplier).strip()
    filename = f"synthetic_{size_category}_{len(text)}_chars.txt"
    return text.encode("utf-8"), filename


def benchmark_document_pipeline(backend_mode: str = "rule", repetitions: int = 5) -> Dict[str, Any]:
    """
    Measure end-to-end and stage-specific document processing latency:
    ingestion, extraction, mention resolution, persistence, and total end-to-end.
    """
    # For ML/transformer models on CPU, keep large size manageable to prevent excessive latency
    sizes = ["small", "medium", "large"]
    if backend_mode in ("ml", "hybrid") and repetitions > 3:
        repetitions = 3

    results = {}

    for size_cat in sizes:
        raw_bytes, filename = generate_synthetic_document(size_cat)
        doc_len_chars = len(raw_bytes.decode("utf-8"))

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, f"bench_{backend_mode}_{size_cat}.db")
            store = SQLiteInvestigationStore(db_path)
            orchestrator = InvestigationOrchestrator(default_backend_mode=backend_mode, sqlite_store=store)

            # Warm-up pass
            inv_warm = f"inv_warm_{backend_mode}_{size_cat}"
            orchestrator.create_investigation(inv_warm, "Warmup")
            orchestrator.process_document(inv_warm, raw_bytes, filename)

            # Timed repetitions
            e2e_timings: List[float] = []
            ingest_timings: List[float] = []
            extract_timings: List[float] = []
            resolve_timings: List[float] = []
            persist_timings: List[float] = []
            char_counts: List[int] = []
            claim_counts: List[int] = []
            entity_counts: List[int] = []

            for rep in range(repetitions):
                inv_id = f"inv_{backend_mode}_{size_cat}_{rep}"
                session = orchestrator.create_investigation(inv_id, f"Bench {rep}")
                pipeline = session.pipeline

                # Stage 1: Ingestion
                t_i0 = time.perf_counter()
                ingested_doc = pipeline.ingestion_service.ingest(
                    raw_content=raw_bytes,
                    source_name=filename,
                )
                t_i1 = time.perf_counter()
                ingest_timings.append((t_i1 - t_i0) * 1000.0)

                # Stage 2: Extraction (NER + Relations)
                t_e0 = time.perf_counter()
                mentions = pipeline.ner_extractor.extract_entities(ingested_doc)
                relations = pipeline.relation_extractor.extract_relations(ingested_doc, mentions)
                t_e1 = time.perf_counter()
                extract_timings.append((t_e1 - t_e0) * 1000.0)

                # Stage 3: Mention Resolution
                t_r0 = time.perf_counter()
                if pipeline.mention_entity_resolver:
                    resolutions = pipeline.mention_entity_resolver.resolve_mentions(mentions)
                else:
                    resolutions = []
                t_r1 = time.perf_counter()
                resolve_timings.append((t_r1 - t_r0) * 1000.0)

                # Stage 4: Store persistence / commit
                t_p0 = time.perf_counter()
                rec = orchestrator.process_document(inv_id, raw_bytes, filename)
                t_p1 = time.perf_counter()
                persist_timings.append((t_p1 - t_p0) * 1000.0)

                # End-to-end timing is captured by the complete process_document call
                e2e_timings.append((t_p1 - t_p0) * 1000.0)
                char_counts.append(rec.char_count)
                claim_counts.append(rec.claim_count)
                entity_counts.append(len(store.list_entities(inv_id)))

            store.close()

        e2e_timings.sort()
        median_ms = statistics.median(e2e_timings)
        p95_idx = min(int(0.95 * len(e2e_timings)), len(e2e_timings) - 1)
        p95_ms = e2e_timings[p95_idx]
        mean_ms = statistics.mean(e2e_timings)
        stdev_ms = statistics.stdev(e2e_timings) if len(e2e_timings) > 1 else 0.0

        throughput_chars_per_sec = (doc_len_chars / (median_ms / 1000.0)) if median_ms > 0 else 0
        throughput_docs_per_sec = (1.0 / (median_ms / 1000.0)) if median_ms > 0 else 0

        results[size_cat] = {
            "size_category": size_cat,
            "char_count": doc_len_chars,
            "repetitions": repetitions,
            "stages_breakdown_median_ms": {
                "ingestion": round(statistics.median(ingest_timings), 3),
                "extraction": round(statistics.median(extract_timings), 3),
                "mention_resolution": round(statistics.median(resolve_timings), 3),
                "persistence_and_sync": round(statistics.median(persist_timings), 3),
            },
            "median_ms": round(median_ms, 2),
            "p95_ms": round(p95_ms, 2),
            "mean_ms": round(mean_ms, 2),
            "stdev_ms": round(stdev_ms, 2),
            "throughput_docs_per_sec": round(throughput_docs_per_sec, 2),
            "throughput_chars_per_sec": round(throughput_chars_per_sec, 2),
            "claims_extracted": claim_counts[0] if claim_counts else 0,
            "entities_resolved": entity_counts[0] if entity_counts else 0,
        }

    return results


def benchmark_entity_resolution() -> Dict[str, Any]:
    """
    Run candidate generation, reduction ratio, and matching quality on
    Zagat-Fodor's benchmark (full and fixture) and synthetic entity scenarios.
    """
    results = {}
    config = BenchmarkRunConfig(seed=42)
    runner = BenchmarkRunner(config=config)

    # 1. Real-World Zagat-Fodor's Benchmark (Full 864 records)
    try:
        t0 = time.perf_counter()
        rw_report = runner.run_real_world_suite(use_fixture=False)
        t_rw = time.perf_counter() - t0
        sc_data = list(rw_report.scenarios.values())[0]
        mm = sc_data["match_metrics"]
        cm = sc_data["candidate_metrics"]
        clm = sc_data["clustering_metrics"]

        results["zagat_fodors_full"] = {
            "dataset_name": "Zagat-Fodor's Restaurant Clean Match (Full)",
            "licensing": "Academic / Non-Commercial Research Benchmark",
            "benchmark_version": rw_report.metadata.get("benchmark_version"),
            "input_records": sc_data.get("record_count", 864),
            "total_possible_pairs": sc_data.get("total_possible_pairs", 372816),
            "candidate_pairs": cm.get("candidate_pairs_count", 0),
            "reduction_ratio_pct": round(cm.get("reduction_ratio", 0.0) * 100.0, 4),
            "candidate_recall": round(cm.get("candidate_recall", 0.0), 4),
            "pairwise_precision": round(mm.get("precision", 0.0), 4),
            "pairwise_recall": round(mm.get("recall", 0.0), 4),
            "pairwise_f1": round(mm.get("f1", 0.0), 4),
            "cluster_purity": round(clm.get("purity", 0.0), 4),
            "runtime_seconds": round(t_rw, 4),
        }
    except Exception as ex:
        results["zagat_fodors_full"] = {"error": str(ex)}

    # 2. Real-World Zagat-Fodor's Offline Fixture (10 records)
    try:
        t0 = time.perf_counter()
        fix_report = runner.run_real_world_suite(use_fixture=True)
        t_fix = time.perf_counter() - t0
        fsc_data = list(fix_report.scenarios.values())[0]
        fmm = fsc_data["match_metrics"]
        fcm = fsc_data["candidate_metrics"]
        fclm = fsc_data["clustering_metrics"]

        results["zagat_fodors_fixture"] = {
            "dataset_name": "Zagat-Fodor's Offline Fixture",
            "licensing": "Deterministic Offline Sample",
            "benchmark_version": fix_report.metadata.get("benchmark_version"),
            "input_records": fsc_data.get("record_count", 10),
            "total_possible_pairs": fsc_data.get("total_possible_pairs", 45),
            "candidate_pairs": fcm.get("candidate_pairs_count", 0),
            "reduction_ratio_pct": round(fcm.get("reduction_ratio", 0.0) * 100.0, 4),
            "candidate_recall": round(fcm.get("candidate_recall", 0.0), 4),
            "pairwise_precision": round(fmm.get("precision", 0.0), 4),
            "pairwise_recall": round(fmm.get("recall", 0.0), 4),
            "pairwise_f1": round(fmm.get("f1", 0.0), 4),
            "cluster_purity": round(fclm.get("purity", 0.0), 4),
            "runtime_seconds": round(t_fix, 4),
        }
    except Exception as ex:
        results["zagat_fodors_fixture"] = {"error": str(ex)}

    # 3. Synthetic Controlled Scenario (Seed 42)
    try:
        synth_report = runner.run_suite(include_edge_cases=False, include_procedural=True, procedural_size=30)
        synth_sc = list(synth_report.scenarios.values())[0]
        scm = synth_sc["candidate_metrics"]
        smm = synth_sc["match_metrics"]
        sclm = synth_sc["clustering_metrics"]

        results["synthetic_scenario"] = {
            "dataset_name": "Deterministic Synthetic Suite (Seed 42)",
            "scenario_id": synth_sc.get("scenario_id"),
            "input_records": synth_sc.get("record_count"),
            "total_possible_pairs": synth_sc.get("total_possible_pairs"),
            "candidate_pairs": scm.get("candidate_pairs_count"),
            "reduction_ratio_pct": round(scm.get("reduction_ratio", 0.0) * 100.0, 4),
            "candidate_recall": round(scm.get("candidate_recall", 0.0), 4),
            "pairwise_precision": round(smm.get("precision", 0.0), 4),
            "pairwise_recall": round(smm.get("recall", 0.0), 4),
            "pairwise_f1": round(smm.get("f1", 0.0), 4),
            "cluster_purity": round(sclm.get("purity", 0.0), 4),
            "runtime_seconds": round(synth_report.metadata.get("elapsed_total_seconds", 0.0), 4),
        }
    except Exception as ex:
        results["synthetic_scenario"] = {"error": str(ex)}

    return results


def benchmark_sqlite_persistence() -> Dict[str, Any]:
    """
    Benchmark SQLite storage performance: cold sync, warm sync, reload/hydrate,
    reopen, database file size, and row counts across practical scales (10, 50, 100, 250).
    """
    scales = [10, 50, 100, 250]
    results = {}

    for scale in scales:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, f"sqlite_bench_{scale}.db")
            store = SQLiteInvestigationStore(db_path)
            orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)
            inv_id = f"inv_scale_{scale}"
            session = orchestrator.create_investigation(inv_id, f"Scale {scale}")

            # Populate entities in session
            for i in range(scale):
                session.store.add_entity(
                    InvestigationEntity(
                        entity_id=f"ent_bench_{i:04d}",
                        entity_type=EntityType.PERSON if i % 2 == 0 else EntityType.ORGANIZATION,
                        canonical_name=f"Entity Person Organization {i}",
                    )
                )

            # Cold sync
            t0 = time.perf_counter()
            store.sync_session(session)
            t_cold_ms = (time.perf_counter() - t0) * 1000.0

            # Warm sync (repeat sync with minor change)
            session.store.add_entity(
                InvestigationEntity(
                    entity_id=f"ent_bench_warm",
                    entity_type=EntityType.LOCATION,
                    canonical_name="London Headquarters",
                )
            )
            t0 = time.perf_counter()
            store.sync_session(session)
            t_warm_ms = (time.perf_counter() - t0) * 1000.0

            # Read latency
            t0 = time.perf_counter()
            ents = store.list_entities(inv_id)
            t_read_ms = (time.perf_counter() - t0) * 1000.0

            # Database file size
            db_size_bytes = os.path.getsize(db_path)

            # Query total row count across all tables
            with store.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM entities WHERE investigation_id = ?", (inv_id,))
                entity_rows = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM investigations WHERE investigation_id = ?", (inv_id,))
                inv_rows = cur.fetchone()[0]
                total_rows = entity_rows + inv_rows

            # Reopen & Hydrate latency
            del orchestrator
            del session
            del store

            t0 = time.perf_counter()
            reopened_store = SQLiteInvestigationStore(db_path)
            reopened_orch = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=reopened_store)
            reopened_session = reopened_orch.create_investigation(inv_id, "Hydrated")
            reopened_store.load_investigation_into_session(inv_id, reopened_session)
            t_reopen_ms = (time.perf_counter() - t0) * 1000.0

            integrity_ok = reopened_store.integrity_check()
            reopened_store.close()

            results[f"scale_{scale}"] = {
                "record_count": scale + 1,
                "total_db_rows": total_rows,
                "cold_sync_ms": round(t_cold_ms, 2),
                "warm_sync_ms": round(t_warm_ms, 2),
                "read_list_ms": round(t_read_ms, 2),
                "reopen_hydrate_ms": round(t_reopen_ms, 2),
                "db_size_bytes": db_size_bytes,
                "integrity_check": integrity_ok,
            }

    return results


def benchmark_model_loading_overhead() -> Dict[str, Any]:
    """Measure model loading latency and RSS memory overhead if transformers/torch installed."""
    results = {}
    try:
        import torch
        from transformers import pipeline
        
        rss_before = get_current_rss_mb()
        t0 = time.perf_counter()
        
        # Load BERT-base NER
        from src.core.ner import ModelBackedNERExtractor
        extractor = ModelBackedNERExtractor(use_mock_backend=False)
        from src.core.document_ingestion import DocumentIngestionService
        test_doc = DocumentIngestionService().ingest(
            raw_content=b"John Doe works at Acme Corp in London.",
            source_name="mem_test.txt",
        )
        extractor.extract_entities(test_doc)
        t_load = time.perf_counter() - t0
        rss_after = get_current_rss_mb()
        
        results = {
            "model_name": "dslim/bert-base-NER",
            "model_loading_latency_sec": round(t_load, 3),
            "rss_before_mb": round(rss_before, 2),
            "rss_after_mb": round(rss_after, 2),
            "rss_delta_mb": round(rss_after - rss_before, 2),
            "loaded_successfully": True,
        }
    except Exception as ex:
        results = {
            "loaded_successfully": False,
            "reason": str(ex),
        }
    return results


def run_all_benchmarks(output_json_path: str):
    """Run all benchmarks and save structured JSON results."""
    print("================================================================")
    print("  Sherlock AI — Milestone 14 Phase 2 Benchmark Harness")
    print(f"  Platform: {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"  CPUs: {os.cpu_count()} cores | Python: {platform.python_version()}")
    print("================================================================")

    gc.collect()
    rss_baseline = get_current_rss_mb()

    # Determine backend modes supported
    has_torch = False
    try:
        import torch
        has_torch = True
    except ImportError:
        pass

    print(f"\n[1/4] Running Document Pipeline Benchmark (Mode: rule)...")
    doc_rule = benchmark_document_pipeline(backend_mode="rule", repetitions=5)

    doc_ml = None
    model_loading_info = None
    if has_torch:
        print(f"[1/4b] Measuring ML Model Loading Overhead...")
        model_loading_info = benchmark_model_loading_overhead()
        print(f"[1/4c] Running Document Pipeline Benchmark (Mode: hybrid)...")
        try:
            doc_ml = benchmark_document_pipeline(backend_mode="hybrid", repetitions=3)
        except Exception as e:
            doc_ml = {"error": str(e)}

    print("\n[2/4] Running Entity Resolution & Blocking Benchmark...")
    er_metrics = benchmark_entity_resolution()

    print("\n[3/4] Running SQLite Persistence Scaling Benchmark...")
    sqlite_metrics = benchmark_sqlite_persistence()

    gc.collect()
    rss_peak = get_peak_rss_mb()
    rss_final = get_current_rss_mb()

    output_data = {
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "os": f"{platform.system()} {platform.release()} {platform.machine()}",
            "cpu_cores": os.cpu_count(),
            "python_version": platform.python_version(),
            "has_pytorch": has_torch,
            "seed": 42,
            "rss_baseline_mb": round(rss_baseline, 2),
            "rss_final_mb": round(rss_final, 2),
            "rss_peak_mb": round(rss_peak, 2),
            "rss_delta_mb": round(rss_peak - rss_baseline, 2),
            "model_loading_overhead": model_loading_info,
        },
        "document_pipeline": {
            "rule_mode": doc_rule,
            "ml_mode": doc_ml,
        },
        "entity_resolution": er_metrics,
        "sqlite_persistence": sqlite_metrics,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_json_path)), exist_ok=True)
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    print(f"\n[4/4] Successfully saved benchmark results to: {output_json_path}")
    return output_data


if __name__ == "__main__":
    out_file = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.path.join(_repo_root, "artifacts", "benchmarks", "milestone_14_phase2_benchmarks.json")
    )
    run_all_benchmarks(out_file)
