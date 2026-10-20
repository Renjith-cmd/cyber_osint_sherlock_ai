# Core package initialization
from src.core.models import (
    EntityType,
    EvidencePolarity,
    DecisionType,
    SourceType,
    ClusterStatus,
    Source,
    Record,
    CandidatePair,
    Evidence,
    MatchDecision,
    EntityCluster,
    ReviewStatus,
    RelationshipEpistemicTier,
    ConfidenceSemantics,
    InvestigationEntity,
    ClaimCorrection,
    Claim,
    Relationship,
)
from src.core.investigation_graph import (
    BaseInvestigationGraphStore,
    InMemoryInvestigationGraphStore,
    Neo4jInvestigationGraphAdapter,
)
from src.core.investigation_service import (
    RelationshipExplanation,
    InvestigationResult,
    InvestigationQueryService,
)
from src.core.investigation_lifecycle import (
    InvestigationLifecycleManager,
)
from src.core.document_ingestion import (
    DocumentFormat,
    DocumentParsingError,
    ExtractionCapabilityError,
    DocumentLimitExceededError,
    IngestionConfig,
    IngestedDocument,
    BaseDocumentParser,
    TextDocumentParser,
    JsonDocumentParser,
    PdfDocumentParser,
    DocumentIngestionService,
)
from src.core.ner import (
    EntityMention,
    BaseNERExtractor,
    DeterministicRuleNERExtractor,
    split_sentences_with_spans,
)
from src.core.relation_extraction import (
    ExtractedRelationCandidate,
    BaseRelationExtractor,
    DeterministicRuleRelationExtractor,
)
from src.core.document_pipeline import (
    ExtractionPipelineResult,
    DocumentExtractionPipeline,
)
from src.core.document_evaluation import (
    GoldEntity,
    GoldRelation,
    GoldDocumentFixture,
    NEREvaluationReport,
    RelationEvaluationReport,
    DocumentEvaluationRunner,
)
from src.core.evaluation import (
    UnknownPredictionPolicy,
    EvaluationMetrics,
    PairwiseEvaluator,
    CandidateEvaluationMetrics,
    evaluate_candidate_generation,
    MatchEvaluationMetrics,
    EndToEndEvaluationMetrics,
    evaluate_match_decisions,
    evaluate_end_to_end_pipeline,
    ClusteringMetrics,
    evaluate_clustering,
)
from src.core.normalization import (
    normalize_text,
    strip_punctuation,
    tokenize_name,
    extract_initials,
    name_fingerprint,
    soundex,
    normalize_attribute_value,
)
from src.core.blocking import (
    BlockingRule,
    ExactNameRule,
    NameTokenRule,
    NameFingerprintRule,
    InitialsAcronymRule,
    NameSoundexRule,
    StructuredAttributeRule,
    CandidateGenerator,
    get_default_blocking_rules,
)
from src.core.comparison import (
    ComparisonResult,
    PairwiseComparator,
    jaro_similarity,
    jaro_winkler_similarity,
    token_jaccard_similarity,
    token_containment,
)
from src.core.decision import (
    DecisionPolicy,
    MatchDecisionEngine,
)
from src.core.clustering import (
    ClusteringPolicy,
    RejectedMerge,
    ClusterAssignment,
    ClusteringResult,
    ConstraintAwareClusterer,
)
_BENCHMARK_EXPORTS = {
    "BenchmarkScenario",
    "BenchmarkRunConfig",
    "BenchmarkRunner",
    "BenchmarkReport",
    "PipelineExecutionResult",
    "EvaluatedScenario",
    "BaselineResult",
    "execute_pipeline",
    "evaluate_pipeline_run",
    "build_standard_synthetic_scenario",
    "build_controlled_edge_case_scenarios",
    "build_master_controlled_scenario",
    "build_real_world_restaurant_scenario",
    "generate_real_world_error_analysis",
    "generate_procedural_scenario",
}

_DATASET_EXPORTS = {
    "DatasetManifest",
    "DatasetLoadingReport",
    "RestaurantDatasetAdapter",
    "RESTAURANT_DATASET_MANIFEST",
    "acquire_restaurant_dataset",
    "get_offline_restaurant_fixture_rows",
}

def __getattr__(name: str):
    if name in _BENCHMARK_EXPORTS:
        import src.core.benchmark as bm
        return getattr(bm, name)
    if name in _DATASET_EXPORTS:
        import src.core.datasets as ds
        return getattr(ds, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Models
    "EntityType",
    "EvidencePolarity",
    "DecisionType",
    "SourceType",
    "ClusterStatus",
    "Source",
    "Record",
    "CandidatePair",
    "Evidence",
    "MatchDecision",
    "EntityCluster",
    "ReviewStatus",
    "RelationshipEpistemicTier",
    "ConfidenceSemantics",
    "InvestigationEntity",
    "ClaimCorrection",
    "Claim",
    "Relationship",
    # Investigation Graph & Lifecycle (Milestone 8)
    "BaseInvestigationGraphStore",
    "InMemoryInvestigationGraphStore",
    "Neo4jInvestigationGraphAdapter",
    "RelationshipExplanation",
    "InvestigationResult",
    "InvestigationQueryService",
    "InvestigationLifecycleManager",
    # Document Ingestion, NER & Relations (Milestone 9)
    "DocumentFormat",
    "DocumentParsingError",
    "ExtractionCapabilityError",
    "DocumentLimitExceededError",
    "IngestionConfig",
    "IngestedDocument",
    "BaseDocumentParser",
    "TextDocumentParser",
    "JsonDocumentParser",
    "PdfDocumentParser",
    "DocumentIngestionService",
    "EntityMention",
    "BaseNERExtractor",
    "DeterministicRuleNERExtractor",
    "split_sentences_with_spans",
    "ExtractedRelationCandidate",
    "BaseRelationExtractor",
    "DeterministicRuleRelationExtractor",
    "ExtractionPipelineResult",
    "DocumentExtractionPipeline",
    "GoldEntity",
    "GoldRelation",
    "GoldDocumentFixture",
    "NEREvaluationReport",
    "RelationEvaluationReport",
    "DocumentEvaluationRunner",
    # Evaluation
    "UnknownPredictionPolicy",
    "EvaluationMetrics",
    "PairwiseEvaluator",
    "CandidateEvaluationMetrics",
    "evaluate_candidate_generation",
    "MatchEvaluationMetrics",
    "EndToEndEvaluationMetrics",
    "evaluate_match_decisions",
    "evaluate_end_to_end_pipeline",
    "ClusteringMetrics",
    "evaluate_clustering",
    # Normalization
    "normalize_text",
    "strip_punctuation",
    "tokenize_name",
    "extract_initials",
    "name_fingerprint",
    "soundex",
    "normalize_attribute_value",
    # Blocking
    "BlockingRule",
    "ExactNameRule",
    "NameTokenRule",
    "NameFingerprintRule",
    "InitialsAcronymRule",
    "NameSoundexRule",
    "StructuredAttributeRule",
    "CandidateGenerator",
    "get_default_blocking_rules",
    # Comparison
    "ComparisonResult",
    "PairwiseComparator",
    "jaro_similarity",
    "jaro_winkler_similarity",
    "token_jaccard_similarity",
    "token_containment",
    # Decision
    "DecisionPolicy",
    "MatchDecisionEngine",
    # Clustering
    "ClusteringPolicy",
    "RejectedMerge",
    "ClusterAssignment",
    "ClusteringResult",
    "ConstraintAwareClusterer",
    # Benchmark (Milestone 5)
    "BenchmarkScenario",
    "BenchmarkRunConfig",
    "BenchmarkRunner",
    "BenchmarkReport",
    "PipelineExecutionResult",
    "EvaluatedScenario",
    "BaselineResult",
    "execute_pipeline",
    "evaluate_pipeline_run",
    "build_standard_synthetic_scenario",
    "build_controlled_edge_case_scenarios",
    "build_master_controlled_scenario",
    "generate_procedural_scenario",
]
