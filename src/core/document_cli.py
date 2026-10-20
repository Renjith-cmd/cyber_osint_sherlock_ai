"""
Command-Line Interface and Demonstration for Sherlock AI Document Extraction (Milestone 9).

Usage:
    python -m src.core.document_cli <path-to-document> [--format {txt,json,pdf,auto}] [--json] [--derive-relationships]
    python -m src.core.document_cli --evaluate [--json]
    python -m src.core.document_cli --sample

Exit codes:
    0: Success
    1: File not found, parsing error, or limit exceeded
    2: Extraction capability error (e.g. PDF dependency missing)
"""

import argparse
import json
import os
import sys
from typing import Optional, Dict, Any

# Ensure project root is in sys.path when invoked directly
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.core.document_ingestion import (
    DocumentFormat,
    DocumentParsingError,
    ExtractionCapabilityError,
    DocumentLimitExceededError,
)
from src.core.document_pipeline import DocumentExtractionPipeline
from src.core.document_evaluation import DocumentEvaluationRunner
from src.core.ner import (
    DeterministicRuleNERExtractor,
    ModelBackedNERExtractor,
    HybridNERExtractor,
)
from src.core.relation_extraction import (
    DeterministicRuleRelationExtractor,
    ModelBackedRelationExtractor,
    HybridRelationExtractor,
)


SAMPLE_FICTIONAL_DOCUMENT = """
INVESTIGATION DOSSIER: PROJECT NIGHTFALL (CONFIDENTIAL MEMORANDUM)
Date: 2024-03-15
Location: London

Summary of Findings:
Dr. John Watson works for Sherlock Security.
Sherlock Security is located in London.
The report alleges that Wayne Enterprises owns Globex Corporation.
Alice Smith does not work for Cyberdyne Systems.
James Moriarty founded Stark Industries with $10 million in 2021.
"""


def run_pipeline_on_file(
    file_path: str,
    doc_format: Optional[str] = None,
    backend_mode: str = "rule",
    derive_relationships: bool = False,
    as_json: bool = False,
) -> int:
    """Run extraction pipeline on a specific document file."""
    if not os.path.exists(file_path):
        sys.stderr.write(f"Error: File not found: '{file_path}'\n")
        return 1

    format_hint = None
    if doc_format and doc_format.lower() != "auto":
        try:
            format_hint = DocumentFormat(doc_format.lower())
        except ValueError:
            sys.stderr.write(f"Error: Unsupported format '{doc_format}'. Choose from txt, json, pdf, auto.\n")
            return 1

    try:
        pipeline = DocumentExtractionPipeline(backend_mode=backend_mode)
    except Exception as ex:
        sys.stderr.write(f"Pipeline Initialization Error: {ex}\n")
        return 2

    try:
        result = pipeline.process_file(
            file_path=file_path,
            derive_graph_relationships=derive_relationships,
        )
    except ExtractionCapabilityError as ex:
        sys.stderr.write(f"Capability Error: {ex}\n")
        return 2
    except (DocumentParsingError, DocumentLimitExceededError) as ex:
        sys.stderr.write(f"Ingestion/Parsing Error: {ex}\n")
        return 1
    except Exception as ex:
        if "MLModelUnavailableError" in type(ex).__name__ or "not installed" in str(ex):
            sys.stderr.write(f"ML Model Capability Error: {ex}\n")
            return 2
        sys.stderr.write(f"Unexpected Error during extraction: {ex}\n")
        return 1

    if as_json:
        output_payload = {
            "document": {
                "document_id": result.document.document_id,
                "content_hash": result.document.content_hash,
                "format": result.document.format.value,
                "char_count": result.document.char_count,
                "parser_name": result.document.parser_name,
                "parser_version": result.document.parser_version,
            },
            "backend_mode": result.backend_mode,
            "mentions": [m.model_dump() for m in result.mentions],
            "relation_candidates": [r.model_dump() for r in result.relation_candidates],
            "evidence": [e.model_dump() for e in result.evidence_items],
            "claims": [c.model_dump() for c in result.claims],
            "derived_relationships": [rel.model_dump() for rel in result.derived_relationships],
            "mention_resolutions": [mr.model_dump() for mr in result.mention_resolutions],
            "epistemic_notice": "Extraction is not verification. Automated claims default to UNREVIEWED status.",
        }
        print(json.dumps(output_payload, indent=2, default=str))
    else:
        _print_human_readable_report(result)

    return 0


def run_pipeline_on_sample(
    backend_mode: str = "rule",
    derive_relationships: bool = False,
    as_json: bool = False,
) -> int:
    """Run extraction pipeline on the built-in synthetic demonstration document."""
    try:
        pipeline = DocumentExtractionPipeline(backend_mode=backend_mode)
    except Exception as ex:
        sys.stderr.write(f"Pipeline Initialization Error: {ex}\n")
        return 2

    try:
        result = pipeline.process_document(
            raw_content=SAMPLE_FICTIONAL_DOCUMENT.strip().encode("utf-8"),
            source_name="synthetic_sample_dossier.txt",
            source_uri="internal://synthetic/sample_dossier.txt",
            doc_format=DocumentFormat.TXT,
            derive_graph_relationships=derive_relationships,
        )
    except Exception as ex:
        if "MLModelUnavailableError" in type(ex).__name__ or "not installed" in str(ex):
            sys.stderr.write(f"ML Model Capability Error: {ex}\n")
            return 2
        sys.stderr.write(f"Unexpected Error: {ex}\n")
        return 1

    if as_json:
        output_payload = {
            "document": {
                "document_id": result.document.document_id,
                "content_hash": result.document.content_hash,
                "format": result.document.format.value,
                "char_count": result.document.char_count,
            },
            "backend_mode": result.backend_mode,
            "mentions": [m.model_dump() for m in result.mentions],
            "relation_candidates": [r.model_dump() for r in result.relation_candidates],
            "evidence": [e.model_dump() for e in result.evidence_items],
            "claims": [c.model_dump() for c in result.claims],
            "derived_relationships": [rel.model_dump() for rel in result.derived_relationships],
            "mention_resolutions": [mr.model_dump() for mr in result.mention_resolutions],
            "epistemic_notice": "Extraction is not verification. Automated claims default to UNREVIEWED status.",
        }
        print(json.dumps(output_payload, indent=2, default=str))
    else:
        _print_human_readable_report(result)

    return 0



def run_evaluation(as_json: bool = False, backend: str = "rule") -> int:
    """Run synthetic evaluation suite and print benchmark report."""
    if backend == "ml":
        try:
            import transformers  # type: ignore
        except ImportError:
            msg = (
                "ERROR: Live 'ml' backend requires 'transformers' library and local model weights.\n"
                "Cannot perform live ML evaluation in offline environment without dependencies.\n"
                "Use '--backend mock_ml' or '--benchmark-compare' for deterministic offline simulation."
            )
            print(msg, file=sys.stderr)
            return 1
        runner = DocumentEvaluationRunner(
            ner_extractor=ModelBackedNERExtractor(use_mock_backend=False),
            relation_extractor=ModelBackedRelationExtractor(use_mock_backend=False),
        )
    elif backend == "mock_ml":
        runner = DocumentEvaluationRunner(
            ner_extractor=ModelBackedNERExtractor(use_mock_backend=True),
            relation_extractor=ModelBackedRelationExtractor(use_mock_backend=True),
        )
    elif backend == "hybrid":
        runner = DocumentEvaluationRunner(
            ner_extractor=HybridNERExtractor(allow_rule_fallback=True),
            relation_extractor=HybridRelationExtractor(allow_rule_fallback=True),
        )
    else:
        runner = DocumentEvaluationRunner(
            ner_extractor=DeterministicRuleNERExtractor(),
            relation_extractor=DeterministicRuleRelationExtractor(),
        )

    ner_report = runner.evaluate_ner()
    rel_report = runner.evaluate_relations()

    if as_json:
        eval_payload = {
            "backend": backend,
            "is_mock_simulation": backend == "mock_ml",
            "ner_evaluation": ner_report.model_dump(),
            "relation_evaluation": rel_report.model_dump(),
        }
        print(json.dumps(eval_payload, indent=2))
    else:
        if backend == "rule":
            print("     SHERLOCK AI - MILESTONE 9 EXTRACTION EVALUATION REPORT     ")
        else:
            print(f"     SHERLOCK AI - EXTRACTION EVALUATION REPORT ({backend.upper()})     ")
        if backend == "mock_ml":
            print("PROVENANCE: Simulated mock engine for offline testing; not live model weights.")
        print("\n--- NAMED ENTITY RECOGNITION (NER) ---")
        print(f"Total Gold Entities:        {ner_report.total_gold_entities}")
        print(f"Total Predicted Mentions:   {ner_report.total_predicted_mentions}")
        print(f"Exact Span Matches:         {ner_report.exact_matches}")
        print(f"Partial Span Matches:       {ner_report.partial_span_matches}")
        print(f"Type Errors on Matched:     {ner_report.type_errors}")
        print(f"False Positives:            {ner_report.false_positives}")
        print(f"False Negatives:            {ner_report.false_negatives}")
        print(f"Exact-Span Precision:       {ner_report.exact_precision * 100:.2f}%")
        print(f"Exact-Span Recall:          {ner_report.exact_recall * 100:.2f}%")
        print(f"Exact-Span F1:              {ner_report.exact_f1 * 100:.2f}%")
        print(f"Lenient (Overlap) F1:       {ner_report.lenient_f1 * 100:.2f}%")
        print(f"Entity-Type Accuracy:       {ner_report.type_accuracy_on_matched * 100:.2f}%")
        if ner_report.latency_ms is not None:
            lat_label = "CPU Heuristic Latency:" if backend == "mock_ml" else "Inference Latency:    "
            print(f"{lat_label}      {ner_report.latency_ms:.2f} ms")

        print("\n--- RELATION EXTRACTION (RE) ---")
        print(f"Total Gold Relations:       {rel_report.total_gold_relations}")
        print(f"Total Predicted Relations:  {rel_report.total_predicted_relations}")
        print(f"True Positives:             {rel_report.true_positives}")
        print(f"False Positives:            {rel_report.false_positives}")
        print(f"False Negatives:            {rel_report.false_negatives}")
        print(f"Precision:                  {rel_report.precision * 100:.2f}%")
        print(f"Recall:                     {rel_report.recall * 100:.2f}%")
        print(f"F1 Score:                   {rel_report.f1 * 100:.2f}%")
        print(f"Evidence Span Accuracy:     {rel_report.evidence_span_accuracy * 100:.2f}%")
        print(f"Negation Accuracy:          {rel_report.negation_accuracy * 100:.2f}%")
        print(f"Attribution Accuracy:       {rel_report.attribution_accuracy * 100:.2f}%")
        print(f"Abstentions on Negative:    {rel_report.abstention_count}")
        print(f"Unsupported Candidates:     {rel_report.unsupported_candidates_count}")
        if rel_report.latency_ms is not None:
            lat_label = "CPU Heuristic Latency:" if backend == "mock_ml" else "Inference Latency:    "
            print(f"{lat_label}      {rel_report.latency_ms:.2f} ms")
        print("=================================================================\n")

    return 0


def run_comparative_evaluation(as_json: bool = False, use_real_model: bool = False) -> int:
    """Run full comparative benchmark across Rule, ML, and Hybrid backends."""
    if use_real_model:
        try:
            import transformers  # type: ignore
        except ImportError:
            msg = (
                "ERROR: Real model evaluation requires 'transformers' library and cached weights.\n"
                "Run within the isolated ML environment (e.g., .venv_ml) or provision dependencies."
            )
            print(msg, file=sys.stderr)
            return 1

    runner = DocumentEvaluationRunner()
    report = runner.run_comparative_benchmark(use_real_model=use_real_model)

    if as_json:
        print(json.dumps(report.model_dump(), indent=2))
    else:
        title = "SHERLOCK AI - REAL PRETRAINED MODEL BENCHMARK (M11)" if use_real_model else "SHERLOCK AI - MULTI-BACKEND COMPARATIVE BENCHMARK (M10)"
        ml_col_header = "Real ML (BERT)" if use_real_model else "Mock ML (Sim)"
        print("=================================================================")
        print(f"   {title}       ")
        print("=================================================================")
        print(f"Partition:  {report.partition_label}")
        print(f"Provenance: {report.evaluation_provenance}\n")

        print("--- NER PERFORMANCE COMPARISON ---")
        print(f"{'Metric':<22} {'Rule':<12} {ml_col_header:<16} {'Hybrid':<12}")
        print("-" * 66)
        star = "" if use_real_model else "*"
        print(f"{'Exact-Span F1':<22} {report.rule_ner.exact_f1*100:>6.2f}%      {report.ml_ner.exact_f1*100:>6.2f}%{star:<2}       {report.hybrid_ner.exact_f1*100:>6.2f}%")
        print(f"{'Exact Precision':<22} {report.rule_ner.exact_precision*100:>6.2f}%      {report.ml_ner.exact_precision*100:>6.2f}%{star:<2}       {report.hybrid_ner.exact_precision*100:>6.2f}%")
        print(f"{'Exact Recall':<22} {report.rule_ner.exact_recall*100:>6.2f}%      {report.ml_ner.exact_recall*100:>6.2f}%{star:<2}       {report.hybrid_ner.exact_recall*100:>6.2f}%")
        print(f"{'Latency (ms)':<22} {report.rule_ner.latency_ms:>6.2f} ms    {report.ml_ner.latency_ms:>6.2f} ms{star:<2}     {report.hybrid_ner.latency_ms:>6.2f} ms")

        print("\n--- RELATION EXTRACTION COMPARISON ---")
        print(f"{'Metric':<22} {'Rule':<12} {ml_col_header:<16} {'Hybrid':<12}")
        print("-" * 66)
        print(f"{'Relation F1':<22} {report.rule_relation.f1*100:>6.2f}%      {report.ml_relation.f1*100:>6.2f}%*         {report.hybrid_relation.f1*100:>6.2f}%")
        print(f"{'Negation Acc':<22} {report.rule_relation.negation_accuracy*100:>6.2f}%      {report.ml_relation.negation_accuracy*100:>6.2f}%*         {report.hybrid_relation.negation_accuracy*100:>6.2f}%")
        print(f"{'Attribution Acc':<22} {report.rule_relation.attribution_accuracy*100:>6.2f}%      {report.ml_relation.attribution_accuracy*100:>6.2f}%*         {report.hybrid_relation.attribution_accuracy*100:>6.2f}%")
        print(f"{'Latency (ms)':<22} {report.rule_relation.latency_ms:>6.2f} ms    {report.ml_relation.latency_ms:>6.2f} ms*       {report.hybrid_relation.latency_ms:>6.2f} ms")

        print("\n--- ENTITY RESOLUTION INTEGRATION ---")
        er = report.entity_resolution
        print(f"Total Mentions:           {er.total_mentions_evaluated}")
        print(f"True Matches:             {er.true_matches}")
        print(f"False Merges:             {er.false_merges}")
        print(f"Unresolved (No Cands):    {er.unresolved_no_candidates}")
        print(f"Candidate Recall:         {er.candidate_recall*100:.2f}%")
        print(f"Review Rate:              {er.review_rate*100:.2f}%")
        print(f"Pairwise F1:              {er.pairwise_f1*100:.2f}%")
        print("-" * 66)
        if not use_real_model:
            print("* NOTE: Mock ML columns reflect offline simulated regex engines.")
            print("  Latency and memory measure CPU regex execution, NOT transformer neural inference.")
        print(f"  {report.epistemic_disclaimer}")
        print("=================================================================\n")

    return 0



def _print_human_readable_report(result) -> None:
    doc = result.document
    print("=================================================================")
    print("          SHERLOCK AI - DOCUMENT EXTRACTION DOSSIER              ")
    print("=================================================================")
    print(f"Document ID:   {doc.document_id}")
    print(f"Source Name:   {doc.source_name}")
    print(f"Format:        {doc.format.value.upper()}")
    print(f"Content Hash:  {doc.content_hash}")
    print(f"Character Len: {doc.char_count} chars")
    print(f"Parser Engine: {doc.parser_name} (v{doc.parser_version})")
    print("-----------------------------------------------------------------")
    print(f"\n[1] Extracted Entity Mentions ({len(result.mentions)}):")
    for m in result.mentions:
        norm_str = f" -> Norm: '{m.normalized_value}'" if m.normalized_value else ""
        print(f"  * [{m.entity_type.value:<12}] '{m.surface_text}' (offsets: {m.start_char}-{m.end_char}){norm_str}")

    print(f"\n[2] Grounded Relation Candidates ({len(result.relation_candidates)}):")
    for r in result.relation_candidates:
        qualifiers = []
        if r.is_negated:
            qualifiers.append("NEGATED")
        if r.is_allegation:
            qualifiers.append("ALLEGATION")
        if r.temporal_context:
            qualifiers.append(f"TEMPORAL: {r.temporal_context}")
        qual_str = f" [{', '.join(qualifiers)}]" if qualifiers else ""
        print(f"  * Candidate: ({r.subject_surface}) ==[{r.predicate}]==> ({r.object_surface}){qual_str}")
        print(f"    Evidence Span: \"{r.evidence_span.strip()}\" [{r.evidence_start_char}:{r.evidence_end_char}]")

    print(f"\n[3] Milestone 8 Evidence & Claims ({len(result.claims)} Claims Created):")
    for c in result.claims:
        sup_str = f"Supporting: {c.supporting_evidence_ids}" if c.supporting_evidence_ids else ""
        con_str = f"Contradicting: {c.contradicting_evidence_ids}" if c.contradicting_evidence_ids else ""
        ev_refs = " | ".join(filter(None, [sup_str, con_str]))
        print(f"  * Claim ID: `{c.claim_id}`")
        print(f"    Status:   {c.review_status.value} (Automated Extraction)")
        print(f"    Triple:   (`{c.subject_id}`, `{c.predicate}`, `{c.object_id}`)")
        print(f"    Evidence: {ev_refs}")
        print(f"    Method:   {c.extraction_method}")

    if result.derived_relationships:
        print(f"\n[4] Derived Investigation Relationships ({len(result.derived_relationships)}):")
        for rel in result.derived_relationships:
            print(f"  * Rel ID: `{rel.relationship_id}`: `{rel.source_entity_id}` -> `{rel.relationship_type}` -> `{rel.target_entity_id}`")
            print(f"    Review Status: {rel.review_status.value} | Epistemic Tier: {rel.epistemic_tier.value}")

    print("\n-----------------------------------------------------------------")
    print("EPISTEMIC NOTICE: Extraction is NOT verification.")
    print("All extracted claims default to UNREVIEWED status pending human adjudication.")
    print("=================================================================\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sherlock AI Milestone 10 - Model-Backed NER, Relation Extraction & Entity Resolution CLI"
    )
    parser.add_argument("file_path", nargs="?", help="Path to document file (txt, json, pdf)")
    parser.add_argument("--format", "-f", default="auto", choices=["auto", "txt", "json", "pdf"], help="Input format")
    parser.add_argument("--backend", "-b", default="rule", choices=["rule", "ml", "hybrid", "mock_ml"], help="Extraction backend mode (rule, ml, hybrid, or offline mock_ml)")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output")
    parser.add_argument("--derive-relationships", action="store_true", help="Derive unreviewed graph relationships")
    parser.add_argument("--evaluate", action="store_true", help="Run synthetic evaluation harness")
    parser.add_argument("--benchmark-compare", action="store_true", help="Run comparative benchmark across rule, ML, and hybrid backends")
    parser.add_argument("--benchmark-real", action="store_true", help="Run comparative benchmark using real pretrained transformer model (requires transformers)")
    parser.add_argument("--demo-investigation", action="store_true", help="Run Milestone 12 end-to-end investigation engine demonstration")
    parser.add_argument("--demo-release", action="store_true", help="Run Phase 2 release demonstration covering all 9 evaluation criteria")
    parser.add_argument("--report-output", type=str, default=None, help="File path to save the structured investigation report")
    parser.add_argument("--sample", action="store_true", help="Run extraction on built-in synthetic dossier")

    args = parser.parse_args()

    if args.demo_release:
        from src.core.investigation_demo import run_release_demonstration
        run_release_demonstration(as_json=args.json, output_report_path=args.report_output)
        return 0

    if args.demo_investigation:
        from src.core.investigation_demo import run_end_to_end_investigation_demo
        run_end_to_end_investigation_demo(as_json=args.json, output_report_path=args.report_output)
        return 0

    if args.benchmark_real:
        return run_comparative_evaluation(as_json=args.json, use_real_model=True)

    if args.benchmark_compare:
        return run_comparative_evaluation(as_json=args.json, use_real_model=False)

    if args.evaluate:
        return run_evaluation(as_json=args.json, backend=args.backend)

    if args.sample or not args.file_path:
        if not args.file_path and not args.sample:
            print(f"No file specified. Running demonstration with backend '{args.backend}' on synthetic dossier sample...\n")
        return run_pipeline_on_sample(
            backend_mode=args.backend,
            derive_relationships=args.derive_relationships,
            as_json=args.json,
        )

    return run_pipeline_on_file(
        file_path=args.file_path,
        doc_format=args.format,
        backend_mode=args.backend,
        derive_relationships=args.derive_relationships,
        as_json=args.json,
    )


if __name__ == "__main__":
    sys.exit(main())
