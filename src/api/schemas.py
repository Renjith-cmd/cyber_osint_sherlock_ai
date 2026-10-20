"""
Pydantic Schemas for Sherlock AI Investigation API (Milestone 13).

Provides typed, validated request and response definitions for:
- Investigations lifecycle & summaries.
- Document uploads and processing audits.
- Entities, Evidence, Claims, and Relationships.
- Bounded graph visualization structures.
- Human review queue and consequential decisions.
- Investigation reports and Markdown exports.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "v1.0.0"
    backend_mode: str = "rule"
    persistence_backend: str = "sqlite"
    persistence_db_path: str = "data/sherlock_investigations.db"
    timestamp: str


class InvestigationCreateRequest(BaseModel):
    investigation_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Unique identifier for the investigation (alphanumeric, dashes, underscores).",
    )
    description: Optional[str] = Field(
        default="",
        max_length=500,
        description="Optional human-readable description of investigation scope.",
    )
    backend_mode: Optional[str] = Field(
        default="rule",
        pattern=r"^(rule|ml|hybrid|mock_ml)$",
        description="Extraction backend engine mode ('rule', 'ml', 'hybrid', 'mock_ml').",
    )


class InvestigationSummaryResponse(BaseModel):
    investigation_id: str
    status: str
    total_documents: int
    completed_documents: int
    failed_documents: int
    total_entities: int
    canonical_entities: int
    provisional_entities: int
    total_claims: int
    unreviewed_claims: int
    verified_claims: int
    retracted_claims: int
    disputed_claims: int
    total_relationships: int
    active_relationships: int
    disputed_relationships: int
    retracted_relationships: int
    total_evidence_items: int
    unresolved_mentions: int
    human_review_queue_size: int
    warnings: List[str] = Field(default_factory=list)


class InvestigationResponse(BaseModel):
    investigation_id: str
    description: str
    status: str
    backend_mode: str
    created_at: str
    summary: Optional[InvestigationSummaryResponse] = None


class InvestigationListResponse(BaseModel):
    total: int
    investigations: List[InvestigationResponse]


class DocumentSummaryResponse(BaseModel):
    document_id: str
    source_name: str
    source_uri: Optional[str] = None
    content_hash: str
    status: str
    char_count: int
    mention_count: int
    claim_count: int
    evidence_count: int
    error_message: Optional[str] = None
    processed_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DocumentDetailResponse(DocumentSummaryResponse):
    text_content: Optional[str] = None


class DocumentListResponse(BaseModel):
    total: int
    documents: List[DocumentSummaryResponse]


class EntityResponse(BaseModel):
    entity_id: str
    canonical_name: str
    entity_type: str
    cluster_id: Optional[str] = None
    member_record_ids: List[str] = Field(default_factory=list)
    is_provisional: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EntityListResponse(BaseModel):
    total: int
    entities: List[EntityResponse]


class EvidenceResponse(BaseModel):
    evidence_id: str
    document_id: Optional[str] = None
    evidence_type: str
    polarity: str
    content: str
    text_span: str
    start_char: int
    end_char: int
    review_status: str
    extraction_method: str
    extractor_version: Optional[str] = None
    provenance: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvidenceListResponse(BaseModel):
    total: int
    evidence: List[EvidenceResponse]


class ClaimResponse(BaseModel):
    claim_id: str
    subject_id: str
    predicate: str
    object_id: str
    confidence: Optional[float] = None
    confidence_semantics: Optional[str] = None
    review_status: str
    qualifiers: Dict[str, Any] = Field(default_factory=dict)
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    contradicting_evidence_ids: List[str] = Field(default_factory=list)
    correction_history: List[Dict[str, Any]] = Field(default_factory=list)
    superseded_by_claim_id: Optional[str] = None
    retraction_reason: Optional[str] = None
    created_at: str
    updated_at: str


class ClaimListResponse(BaseModel):
    total: int
    claims: List[ClaimResponse]


class RelationshipResponse(BaseModel):
    relationship_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    is_directed: bool
    epistemic_tier: str
    review_status: str
    supporting_claim_ids: List[str] = Field(default_factory=list)
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    contradicting_claim_ids: List[str] = Field(default_factory=list)
    contradicting_evidence_ids: List[str] = Field(default_factory=list)
    provenance: str
    explanation_summary: Optional[str] = None


class RelationshipListResponse(BaseModel):
    total: int
    relationships: List[RelationshipResponse]


class GraphNode(BaseModel):
    id: str
    label: str
    entity_type: str
    is_provisional: bool = False
    degree: int = 0


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relationship_type: str
    epistemic_tier: str
    review_status: str
    is_directed: bool = True
    supporting_claim_count: int = 0
    contradicting_claim_count: int = 0
    source_label: str = ""
    target_label: str = ""
    supporting_claim_ids: List[str] = Field(default_factory=list)
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    contradicting_claim_ids: List[str] = Field(default_factory=list)
    contradicting_evidence_ids: List[str] = Field(default_factory=list)
    supporting_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    contradicting_evidence: List[Dict[str, Any]] = Field(default_factory=list)


class GraphQueryResponse(BaseModel):
    root_entity_id: Optional[str] = None
    max_depth: int
    max_nodes: int
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    disputed_claim_count: int = 0
    unreviewed_claim_count: int = 0
    unsupported_relationship_count: int = 0


class ReviewQueueItemResponse(BaseModel):
    category: str
    item_id: str
    reason: str
    surface_text: Optional[str] = None
    status: Optional[str] = None
    claim_details: Optional[Dict[str, Any]] = None
    supporting_evidence: List[EvidenceResponse] = Field(default_factory=list)
    contradicting_evidence: List[EvidenceResponse] = Field(default_factory=list)


class ReviewQueueResponse(BaseModel):
    total: int
    items: List[ReviewQueueItemResponse]


class ReviewClaimRequest(BaseModel):
    claim_id: str = Field(..., min_length=1)
    new_status: str = Field(
        ...,
        pattern=r"^(VERIFIED|RETRACTED|REJECTED|DISPUTED)$",
        description="Target lifecycle review status.",
    )
    reviewer: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description="Identifier of the human investigator taking this consequential decision.",
    )
    rationale: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Verifiable audit rationale justifying the status transition.",
    )
    replacement_claim_id: Optional[str] = Field(
        default=None,
        description="Optional ID of replacement claim when superseding.",
    )


class ReportResponse(BaseModel):
    investigation_id: str
    report_schema_version: str
    generated_at: str
    investigation_status: str
    extraction_backend: str
    persistence_backend: str
    persistence_notice: str
    metrics: Dict[str, Any]
    warnings: List[str]
    raw_json: Dict[str, Any]
    markdown_report: str


class CrossDocumentResolutionResponse(BaseModel):
    investigation_id: str
    total_decisions: int
    matches: int
    non_matches: int
    reviews_required: int
    proposals: List[Dict[str, Any]]


class EntityMergeRequest(BaseModel):
    proposal_id: str = Field(..., min_length=1)
    reviewer: str = Field(..., min_length=2, max_length=64)
    rationale: str = Field(..., min_length=5, max_length=500)


class EntitySplitRequest(BaseModel):
    entity_id: str = Field(..., min_length=1)
    split_member_records: List[str] = Field(..., min_length=1)
    reviewer: str = Field(..., min_length=2, max_length=64)
    rationale: str = Field(..., min_length=5, max_length=500)


class EntityReverseMergeRequest(BaseModel):
    merged_entity_id: str = Field(..., min_length=1)
    reviewer: str = Field(..., min_length=2, max_length=64)
    rationale: str = Field(..., min_length=5, max_length=500)


class NonMatchConstraintRequest(BaseModel):
    entity_id_a: str = Field(..., min_length=1)
    entity_id_b: str = Field(..., min_length=1)
    reviewer: str = Field(..., min_length=2, max_length=64)
    rationale: str = Field(..., min_length=5, max_length=500)


# =============================================================================
# System Stats & Safe Data Management Schemas
# =============================================================================

class SystemStatsResponse(BaseModel):
    investigations: int
    documents: int
    entities: int
    evidence: int
    claims: int
    relationships: int
    reports: int


class ClearInvestigationRequest(BaseModel):
    confirmed_name: str = Field(..., description="Exact investigation ID to confirm deletion.")


class ClearInvestigationResponse(BaseModel):
    status: str = "cleared"
    investigation_id: str
    deleted_counts: Dict[str, int]


class ClearAllDataRequest(BaseModel):
    confirmation_phrase: str = Field(..., description="Must be exactly 'DELETE ALL SHERLOCK DATA' or 'CLEAR ALL DATA'.")


class ClearAllDataResponse(BaseModel):
    status: str = "cleared"
    deleted_counts: Dict[str, int]
    message: str


# =============================================================================
# Maltego Transforms & Suspicious Patterns Schemas
# =============================================================================

class TransformExpandRequest(BaseModel):
    entity_id: str = Field(..., min_length=1)
    direction: str = Field("both", pattern=r"^(in|out|both)$")
    max_depth: int = Field(1, ge=1, le=5)


class TransformOwnershipRequest(BaseModel):
    entity_id: str = Field(..., min_length=1)
    max_depth: int = Field(5, ge=1, le=10)


class TransformFinancialFlowRequest(BaseModel):
    entity_id: str = Field(..., min_length=1)
    max_depth: int = Field(4, ge=1, le=8)


class TransformSanctionsScreenRequest(BaseModel):
    entity_name: str = Field(..., min_length=2)


class TransformResultResponse(BaseModel):
    transform_name: str
    source_entity_id: str
    added_entities: List[Dict[str, Any]]
    added_relationships: List[Dict[str, Any]]
    summary: str


class SuspiciousPatternsResponse(BaseModel):
    investigation_id: str
    total_findings: int
    findings: List[Dict[str, Any]]
    epistemic_disclaimer: str
    circular_flows: List[Dict[str, Any]] = Field(default_factory=list)
    shell_company_clusters: List[Dict[str, Any]] = Field(default_factory=list)
    summary: str = ""


class ShortestPathResponse(BaseModel):
    found: bool
    source_entity_id: str
    target_entity_id: str
    path: Optional[Dict[str, Any]] = None

