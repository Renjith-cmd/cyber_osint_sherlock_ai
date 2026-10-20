"""
API v1 Route Handlers for Sherlock AI Investigation Engine (Milestone 13).

Provides versioned endpoints under `/api/v1` for:
- Investigations lifecycle & summary metrics
- Document uploads with strict size, format, and path validation
- Entity and Relationship queries with bounded traversal
- Epistemic evidence spans and claim audits
- Human-in-the-loop review queue and consequential decisions
- Deterministic structured reports (JSON & Markdown)
- Safe fictional demo loading
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Request, status, Header, Body
from pydantic import BaseModel
from fastapi.responses import PlainTextResponse, Response

from src.core.models import ReviewStatus
from src.core.document_ingestion import DocumentFormat
from src.core.investigation_service import (
    InvestigationOrchestrator,
    InvestigationStatus,
    DocumentProcessingStatus,
)
from src.api.schemas import (
    HealthResponse,
    InvestigationCreateRequest,
    InvestigationResponse,
    InvestigationListResponse,
    InvestigationSummaryResponse,
    DocumentSummaryResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    EntityResponse,
    EntityListResponse,
    EvidenceResponse,
    EvidenceListResponse,
    ClaimResponse,
    ClaimListResponse,
    RelationshipResponse,
    RelationshipListResponse,
    GraphNode,
    GraphEdge,
    GraphQueryResponse,
    ReviewQueueItemResponse,
    ReviewQueueResponse,
    ReviewClaimRequest,
    ReportResponse,
    CrossDocumentResolutionResponse,
    EntityMergeRequest,
    EntitySplitRequest,
    EntityReverseMergeRequest,
    NonMatchConstraintRequest,
    SystemStatsResponse,
    ClearInvestigationRequest,
    ClearInvestigationResponse,
    ClearAllDataRequest,
    ClearAllDataResponse,
    TransformExpandRequest,
    TransformOwnershipRequest,
    TransformFinancialFlowRequest,
    TransformSanctionsScreenRequest,
    TransformResultResponse,
    SuspiciousPatternsResponse,
    ShortestPathResponse,
)


from src.core.models import DecisionType
from src.core.investigation_graph import InvalidLifecycleTransitionError
from src.core.auth import UserRecord
from src.core.maltego_transforms import MaltegoTransformEngine
from src.api.auth_routes import get_current_user, enforce_investigation_access
from src.api.security import (
    validate_upload_content,
    sanitize_filename,
    sanitize_text_for_display,
    MAX_UPLOAD_SIZE_BYTES,
    read_bounded_upload,
    validate_reviewer_identity,
)


router = APIRouter(prefix="/api/v1", tags=["sherlock-investigations"])

def get_orchestrator() -> InvestigationOrchestrator:
    if _global_orchestrator is None:
        raise RuntimeError("Global InvestigationOrchestrator has not been initialized.")
    return _global_orchestrator

def set_orchestrator(orchestrator: InvestigationOrchestrator) -> None:
    global _global_orchestrator
    _global_orchestrator = orchestrator


class ShortestPathRequest(BaseModel):
    source_node_id: str
    target_node_id: str

@router.post("/investigations/{investigation_id}/transforms/shortest-path", response_model=ShortestPathResponse)
def find_shortest_path(
    investigation_id: str,
    req: ShortestPathRequest,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Find shortest path between two entities in the knowledge graph."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    engine = MaltegoTransformEngine(session.store)
    path_result = engine.find_shortest_path(req.source_node_id, req.target_node_id)
    return ShortestPathResponse(
        found=bool(path_result),
        source_entity_id=req.source_node_id,
        target_entity_id=req.target_node_id,
        path=path_result,
    )


# Dependency injection for orchestrator
_global_orchestrator: Optional[InvestigationOrchestrator] = None


def _to_plain_dict(val: Any) -> Dict[str, Any]:
    """Convert mappingproxy or nested metadata to standard serializable dict."""
    if val is None:
        return {}
    if hasattr(val, "items"):
        return {str(k): (v.value if hasattr(v, "value") else v) for k, v in val.items()}
    return dict(val)


def get_orchestrator() -> InvestigationOrchestrator:
    if _global_orchestrator is None:
        raise RuntimeError("Global InvestigationOrchestrator has not been initialized.")
    return _global_orchestrator


def set_orchestrator(orchestrator: InvestigationOrchestrator) -> None:
    global _global_orchestrator
    _global_orchestrator = orchestrator


# =============================================================================
# System Health & Info
# =============================================================================

@router.get("/health", response_model=HealthResponse)
def get_health(orchestrator: InvestigationOrchestrator = Depends(get_orchestrator)):
    """Health check and persistence engine disclosure."""
    db_path = orchestrator.sqlite_store.db_path if orchestrator.sqlite_store else "in_memory"
    persistence_mode = "sqlite" if orchestrator.sqlite_store else "in_memory"
    return HealthResponse(
        status="ok",
        version="v1.0.0",
        backend_mode=orchestrator.default_backend_mode,
        persistence_backend=persistence_mode,
        persistence_db_path=db_path,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/ready")
def get_readiness(orchestrator: InvestigationOrchestrator = Depends(get_orchestrator)):
    """Readiness probe verifying operational state and integrity of persistence store."""
    db_ok = True
    db_status = "operational"
    if orchestrator.sqlite_store is not None:
        try:
            db_ok = orchestrator.sqlite_store.integrity_check()
            if not db_ok:
                db_status = "integrity_check_failed"
        except Exception as e:
            db_ok = False
            db_status = f"unhealthy: {str(e)[:100]}"

    if not db_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "database": db_status},
        )

    return {
        "status": "ready",
        "database": db_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# Investigations
# =============================================================================

@router.post("/investigations", response_model=InvestigationResponse, status_code=status.HTTP_201_CREATED)
def create_investigation(
    req: InvestigationCreateRequest,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Create a new isolated investigation."""
    try:
        session = orchestrator.create_investigation(
            investigation_id=req.investigation_id,
            description=req.description or "",
            backend_mode=req.backend_mode,
            owner_id=current_user.id if current_user else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    summary = orchestrator.get_summary(session.investigation_id)
    return InvestigationResponse(
        investigation_id=session.investigation_id,
        description=session.description,
        status=session.status.value,
        backend_mode=session.backend_mode,
        created_at=session.created_at.isoformat(),
        summary=InvestigationSummaryResponse(**summary.model_dump()),
    )


@router.get("/investigations", response_model=InvestigationListResponse)
def list_investigations(
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """List all registered investigations visible to the authenticated user."""
    owner_id = current_user.id if (current_user and current_user.role != "admin") else None
    ids = orchestrator.list_investigations(owner_id=owner_id)
    investigations: List[InvestigationResponse] = []
    for inv_id in ids:
        session = orchestrator.get_investigation(inv_id)
        if session:
            # Skip if user is authenticated and session is owned by someone else
            if owner_id and getattr(session, "owner_id", None) and getattr(session, "owner_id", None) != owner_id:
                continue
            summary = orchestrator.get_summary(inv_id)
            investigations.append(
                InvestigationResponse(
                    investigation_id=session.investigation_id,
                    description=session.description,
                    status=session.status.value,
                    backend_mode=session.backend_mode,
                    created_at=session.created_at.isoformat(),
                    summary=InvestigationSummaryResponse(**summary.model_dump()),
                )
            )
    return InvestigationListResponse(total=len(investigations), investigations=investigations)


@router.get("/investigations/{investigation_id}", response_model=InvestigationResponse)
def get_investigation(
    investigation_id: str,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Retrieve details and summary metrics for an investigation."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    summary = orchestrator.get_summary(investigation_id)
    return InvestigationResponse(
        investigation_id=session.investigation_id,
        description=session.description,
        status=session.status.value,
        backend_mode=session.backend_mode,
        created_at=session.created_at.isoformat(),
        summary=InvestigationSummaryResponse(**summary.model_dump()),
    )


@router.api_route("/investigations/{investigation_id}/demo", response_model=InvestigationResponse, methods=["GET", "POST"])
def load_fictional_demo(
    investigation_id: str,
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """
    Load fictional Milestone 12 intelligence scenario for safe demonstration.
    Notice: Documents are explicitly marked as synthetic training benchmarks.
    """
    session = orchestrator.get_investigation(investigation_id)
    if not session:
        session = orchestrator.create_investigation(
            investigation_id=investigation_id,
            description="Synthetic OSINT benchmark demonstration scenario (Milestone 12 dataset).",
            backend_mode="rule",
        )

    # Document 1: Corporate Registry
    doc1_content = (
        "CONFIDENTIAL CORPORATE REPORT\n"
        "Apex Global Holdings is a transnational conglomerate incorporated in Delaware.\n"
        "Alice Mercer serves as Chief Executive Officer of Apex Global Holdings.\n"
        "Apex Global Holdings has headquarters in London and offices in New York.\n"
    ).encode("utf-8")

    # Document 2: Offshore Leak Document
    doc2_content = (
        "FINANCIAL INTELLIGENCE DISCLOSURE - SYNTHETIC DATASET\n"
        "Alice Mercer holds controlling interest in shell entity BlueStar Capital.\n"
        "Bob Vance is listed as Managing Director of BlueStar Capital.\n"
        "BlueStar Capital transferred $4,500,000 to Apex Global Holdings in 2024.\n"
    ).encode("utf-8")

    orchestrator.process_document(
        investigation_id=investigation_id,
        raw_content=doc1_content,
        source_name="synthetic_corporate_registry_2024.txt",
        doc_format=DocumentFormat.TXT,
    )
    orchestrator.process_document(
        investigation_id=investigation_id,
        raw_content=doc2_content,
        source_name="synthetic_offshore_disclosures_2024.txt",
        doc_format=DocumentFormat.TXT,
    )

    summary = orchestrator.get_summary(investigation_id)
    return InvestigationResponse(
        investigation_id=session.investigation_id,
        description=session.description,
        status=session.status.value,
        backend_mode=session.backend_mode,
        created_at=session.created_at.isoformat(),
        summary=InvestigationSummaryResponse(**summary.model_dump()),
    )


# =============================================================================
# Documents
# =============================================================================

@router.post(
    "/investigations/{investigation_id}/documents",
    response_model=DocumentSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    investigation_id: str,
    file: UploadFile = File(...),
    auto_process: bool = Form(default=True),
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """
    Upload and optionally process an investigation document.
    Enforces size limits, extension whitelisting, and path traversal guards.
    """
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)

    content_bytes = await read_bounded_upload(file)
    safe_name, format_str = validate_upload_content(file.filename or "uploaded_doc.txt", content_bytes)

    fmt = DocumentFormat.TXT
    if format_str == "json":
        fmt = DocumentFormat.JSON
    elif format_str == "pdf":
        fmt = DocumentFormat.PDF
    elif format_str == "csv":
        fmt = DocumentFormat.CSV

    # Process document based on auto_process flag
    if auto_process:
        rec = orchestrator.process_document(
            investigation_id=investigation_id,
            raw_content=content_bytes,
            source_name=safe_name,
            doc_format=fmt,
        )
    else:
        rec = orchestrator.ingest_document(
            investigation_id=investigation_id,
            raw_content=content_bytes,
            source_name=safe_name,
            doc_format=fmt,
        )
    # Automatic graph seeding for CSV transaction ledgers
    if fmt == DocumentFormat.CSV and rec is not None:
            session = enforce_investigation_access(
                orchestrator, investigation_id, current_user, orchestrator.sqlite_store
            )
            doc_obj = session.documents.get(rec.document_id)
            if doc_obj:
                import csv, hashlib
                from io import StringIO
                from src.core.models import InvestigationEntity, EntityType, Relationship

                csv_bytes = doc_obj.raw_content
                csv_text = csv_bytes.decode('utf-8-sig')
                reader = csv.DictReader(StringIO(csv_text))
                for row in reader:
                    sender = row.get("sender") or row.get("Sender")
                    receiver = row.get("receiver") or row.get("Receiver")
                    if sender:
                        sender_id = f"entity_{hashlib.sha256(sender.encode()).hexdigest()[:8]}"
                        if not session.store.get_entity(sender_id):
                            session.store.add_entity(
                                InvestigationEntity(
                                    entity_id=sender_id,
                                    entity_type=EntityType.ORGANIZATION,
                                    canonical_name=sender,
                                )
                            )
                    if receiver:
                        receiver_id = f"entity_{hashlib.sha256(receiver.encode()).hexdigest()[:8]}"
                        if not session.store.get_entity(receiver_id):
                            session.store.add_entity(
                                InvestigationEntity(
                                    entity_id=receiver_id,
                                    entity_type=EntityType.ORGANIZATION,
                                    canonical_name=receiver,
                                )
                            )
                    if sender and receiver:
                        rel_id = f"rel_{hashlib.sha256((sender+receiver).encode()).hexdigest()[:8]}"
                        if not session.store.get_relationship(rel_id):
                            session.store.add_relationship(
                                Relationship(
                                    relationship_id=rel_id,
                                    source_entity_id=sender_id,
                                    target_entity_id=receiver_id,
                                    relationship_type="TRANSFERRED_FUNDS_TO",
                                )
                            )
    return DocumentSummaryResponse(
        document_id=rec.document_id,
        source_name=rec.source_name,
        source_uri=rec.source_uri,
        content_hash=rec.content_hash,
        status=rec.status.value,
        char_count=rec.char_count,
        mention_count=rec.mention_count,
        claim_count=rec.claim_count,
        evidence_count=rec.evidence_count,
        error_message=rec.error_message,
        processed_at=rec.processed_at.isoformat() if rec.processed_at else None,
        metadata=_to_plain_dict(rec.metadata),
    )

    # -----------------------------------------------------------------
    # Batch document upload – accept multiple files in one request.
    # -----------------------------------------------------------------
    @router.post(
        "/investigations/{investigation_id}/documents/batch",
        response_model=List[DocumentSummaryResponse],
        status_code=status.HTTP_201_CREATED,
    )
    async def batch_upload_documents(
        investigation_id: str,
        files: List[UploadFile] = File(...),
        current_user: Optional[UserRecord] = Depends(get_current_user),
        orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
    ):
        """Upload multiple document files together. Each file is processed according to the
        same rules as the single‑file endpoint. Returns a list of document summaries.
        """
        session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
        summaries: List[DocumentSummaryResponse] = []
        for file in files:
            content_bytes = await read_bounded_upload(file)
            safe_name, fmt_str = validate_upload_content(
                file.filename or "uploaded_doc.txt", content_bytes
            )
            fmt = DocumentFormat.TXT
            if fmt_str == "json":
                fmt = DocumentFormat.JSON
            elif fmt_str == "pdf":
                fmt = DocumentFormat.PDF
            elif fmt_str == "csv":
                fmt = DocumentFormat.CSV
            rec = orchestrator.process_document(
                investigation_id=investigation_id,
                raw_content=content_bytes,
                source_name=safe_name,
                doc_format=fmt,
            )
            summaries.append(
                DocumentSummaryResponse(
                    document_id=rec.document_id,
                    source_name=rec.source_name,
                    source_uri=rec.source_uri,
                    content_hash=rec.content_hash,
                    status=rec.status.value,
                    char_count=rec.char_count,
                    mention_count=rec.mention_count,
                    claim_count=rec.claim_count,
                    evidence_count=rec.evidence_count,
                    error_message=rec.error_message,
                    processed_at=rec.processed_at.isoformat() if rec.processed_at else None,
                    metadata=_to_plain_dict(rec.metadata),
                )
            )
        return summaries

@router.get("/investigations/{investigation_id}/documents", response_model=DocumentListResponse)
def list_documents(
    investigation_id: str,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """List all documents registered in an investigation."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)

    docs = orchestrator.list_document_records(investigation_id)
    resp_docs = [
        DocumentSummaryResponse(
            document_id=d.document_id,
            source_name=d.source_name,
            source_uri=d.source_uri,
            content_hash=d.content_hash,
            status=d.status.value,
            char_count=d.char_count,
            mention_count=d.mention_count,
            claim_count=d.claim_count,
            evidence_count=d.evidence_count,
            error_message=d.error_message,
            processed_at=d.processed_at.isoformat() if d.processed_at else None,
            metadata=_to_plain_dict(d.metadata),
        )
        for d in docs
    ]
    return DocumentListResponse(total=len(resp_docs), documents=resp_docs)


@router.get("/investigations/{investigation_id}/documents/{document_id}", response_model=DocumentDetailResponse)
def get_document(
    investigation_id: str,
    document_id: str,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Retrieve document metadata and text content."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)

    rec = orchestrator.get_document_record(investigation_id, document_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found in investigation '{investigation_id}'.",
        )

    text_content = None
    if document_id in session.documents:
        doc_obj = session.documents[document_id]
        text_content = getattr(doc_obj, "normalized_text", getattr(doc_obj, "text", None))
    elif orchestrator.sqlite_store:
        doc_data = orchestrator.sqlite_store.get_document(investigation_id, document_id)
        if doc_data:
            text_content = doc_data.get("normalized_text")

    return DocumentDetailResponse(
        document_id=rec.document_id,
        source_name=rec.source_name,
        source_uri=rec.source_uri,
        content_hash=rec.content_hash,
        status=rec.status.value,
        char_count=rec.char_count,
        mention_count=rec.mention_count,
        claim_count=rec.claim_count,
        evidence_count=rec.evidence_count,
        error_message=rec.error_message,
        processed_at=rec.processed_at.isoformat() if rec.processed_at else None,
        metadata=_to_plain_dict(rec.metadata),
        text_content=text_content,
    )


@router.post("/investigations/{investigation_id}/documents/{document_id}/process", response_model=DocumentSummaryResponse)
def process_single_document(
    investigation_id: str,
    document_id: str,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Process or re-process a specific document."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    if document_id not in session.documents:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' raw bytes not available for reprocessing.",
        )

    doc = session.documents[document_id]
    raw_content = getattr(doc, "raw_content", getattr(doc, "raw_bytes", None))
    doc_format = getattr(doc, "format", getattr(doc, "doc_format", None))
    rec = orchestrator.process_document(
        investigation_id=investigation_id,
        raw_content=raw_content,
        source_name=doc.source_name,
        source_uri=doc.source_uri,
        doc_format=doc_format,
        force_reprocess=True,
    )

    return DocumentSummaryResponse(
        document_id=rec.document_id,
        source_name=rec.source_name,
        source_uri=rec.source_uri,
        content_hash=rec.content_hash,
        status=rec.status.value,
        char_count=rec.char_count,
        mention_count=rec.mention_count,
        claim_count=rec.claim_count,
        evidence_count=rec.evidence_count,
        error_message=rec.error_message,
        processed_at=rec.processed_at.isoformat() if rec.processed_at else None,
        metadata=_to_plain_dict(rec.metadata),
    )


@router.post("/investigations/{investigation_id}/process-all", response_model=InvestigationSummaryResponse)
def process_all_documents(
    investigation_id: str,
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Process all pending documents in the investigation."""
    session = orchestrator.get_investigation(investigation_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    summary = orchestrator.process_all_documents(investigation_id)
    return InvestigationSummaryResponse(**summary.model_dump())


# =============================================================================
# Entities & Relationships
# =============================================================================

@router.get("/investigations/{investigation_id}/entities", response_model=EntityListResponse)
def list_entities(
    investigation_id: str,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """List all entities discovered in the investigation."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    if not session:
        # Auto-create synthetic demo investigation for demo IDs
        if investigation_id.startswith("demo_"):
            # Reuse demo logic to create investigation and ingest synthetic docs
            # Create investigation
            session = orchestrator.create_investigation(
                investigation_id=investigation_id,
                description="Synthetic OSINT benchmark demonstration scenario (Milestone 12 dataset).",
                backend_mode="rule",
            )
            # Ingest synthetic documents (same as demo endpoint)
            doc1_content = (
                "CONFIDENTIAL CORPORATE REPORT\\n"
                "Apex Global Holdings is a transnational conglomerate incorporated in Delaware.\\n"
                "Alice Mercer serves as Chief Executive Officer of Apex Global Holdings.\\n"
                "Apex Global Holdings has headquarters in London and offices in New York.\\n"
            ).encode("utf-8")
            doc2_content = (
                "FINANCIAL INTELLIGENCE DISCLOSURE - SYNTHETIC DATASET\\n"
                "Alice Mercer holds controlling interest in shell entity BlueStar Capital.\\n"
                "Bob Vance is listed as Managing Director of BlueStar Capital.\\n"
                "BlueStar Capital transferred $4,500,000 to Apex Global Holdings in 2024.\\n"
            ).encode("utf-8")
            orchestrator.process_document(
                investigation_id=investigation_id,
                raw_content=doc1_content,
                source_name="synthetic_corporate_registry_2024.txt",
                doc_format=DocumentFormat.TXT,
            )
            orchestrator.process_document(
                investigation_id=investigation_id,
                raw_content=doc2_content,
                source_name="synthetic_offshore_disclosures_2024.txt",
                doc_format=DocumentFormat.TXT,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Investigation '{investigation_id}' not found.",
            )

    entities = session.store.list_entities()
    resp_ents = [
        EntityResponse(
            entity_id=e.entity_id,
            canonical_name=e.canonical_name,
            entity_type=e.entity_type.value,
            cluster_id=e.cluster_id,
            member_record_ids=list(e.member_record_ids),
            is_provisional=bool(e.metadata.get("provisional", False)),
            metadata=_to_plain_dict(e.metadata),
        )
        for e in entities
    ]
    return EntityListResponse(total=len(resp_ents), entities=resp_ents)


@router.get("/investigations/{investigation_id}/entities/{entity_id}", response_model=EntityResponse)
def get_entity(
    investigation_id: str,
    entity_id: str,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Retrieve details for a single entity."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    if not session.store.has_entity(entity_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity '{entity_id}' not found in investigation '{investigation_id}'.",
        )

    e = session.store.get_entity(entity_id)
    return EntityResponse(
        entity_id=e.entity_id,
        canonical_name=e.canonical_name,
        entity_type=e.entity_type.value,
        cluster_id=e.cluster_id,
        member_record_ids=list(e.member_record_ids),
        is_provisional=bool(e.metadata.get("provisional", False)),
        metadata=_to_plain_dict(e.metadata),
    )


@router.get("/investigations/{investigation_id}/relationships", response_model=RelationshipListResponse)
def list_relationships(
    investigation_id: str,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """List derived relationships between entities."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    rels = session.store.list_relationships()
    resp_rels = []
    for r in rels:
        resp_rels.append(
            RelationshipResponse(
                relationship_id=r.relationship_id,
                source_entity_id=r.source_entity_id,
                target_entity_id=r.target_entity_id,
                relationship_type=r.relationship_type,
                is_directed=r.is_directed,
                epistemic_tier=r.epistemic_tier.value,
                review_status=r.review_status.value,
                supporting_claim_ids=list(r.supporting_claim_ids),
                supporting_evidence_ids=list(r.supporting_evidence_ids),
                contradicting_claim_ids=list(r.contradicting_claim_ids),
                contradicting_evidence_ids=list(r.contradicting_evidence_ids),
                provenance=r.provenance,
            )
        )
    return RelationshipListResponse(total=len(resp_rels), relationships=resp_rels)


# =============================================================================
# Graph Exploration
# =============================================================================

@router.get("/investigations/{investigation_id}/graph", response_model=GraphQueryResponse)
def get_investigation_graph(
    investigation_id: str,
    max_nodes: int = Query(default=100, ge=1, le=200),
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Retrieve the entire investigation graph bounded by node limits."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    entities = session.store.list_entities()[:max_nodes]
    ent_ids = {e.entity_id for e in entities}
    relationships = [r for r in session.store.list_relationships() if r.source_entity_id in ent_ids and r.target_entity_id in ent_ids]

    # Compute node degrees
    degree_map: Dict[str, int] = {e.entity_id: 0 for e in entities}
    for r in relationships:
        degree_map[r.source_entity_id] = degree_map.get(r.source_entity_id, 0) + 1
        degree_map[r.target_entity_id] = degree_map.get(r.target_entity_id, 0) + 1

    nodes = [
        GraphNode(
            id=e.entity_id,
            label=e.canonical_name,
            entity_type=e.entity_type.value,
            is_provisional=bool(e.metadata.get("provisional", False)),
            degree=degree_map.get(e.entity_id, 0),
        )
        for e in entities
    ]

    edges = [
        GraphEdge(
            id=r.relationship_id,
            source=r.source_entity_id,
            target=r.target_entity_id,
            relationship_type=r.relationship_type,
            epistemic_tier=r.epistemic_tier.value,
            review_status=r.review_status.value,
            is_directed=r.is_directed,
            supporting_claim_count=len(r.supporting_claim_ids),
            contradicting_claim_count=len(r.contradicting_claim_ids),
            source_label=session.store.get_entity(r.source_entity_id).canonical_name,
            target_label=session.store.get_entity(r.target_entity_id).canonical_name,
            supporting_claim_ids=list(r.supporting_claim_ids),
            supporting_evidence_ids=list(r.supporting_evidence_ids),
            contradicting_claim_ids=list(r.contradicting_claim_ids),
            contradicting_evidence_ids=list(r.contradicting_evidence_ids),
            supporting_evidence=[
                {"evidence_id": ev.evidence_id, "document_id": ev.document_reference, "text": ev.text_span or ev.content or ev.value_description, "polarity": ev.polarity.value, "review_status": ev.review_status.value}
                for evidence_id in r.supporting_evidence_ids
                if (ev := session.store.get_evidence(evidence_id)) is not None
            ],
            contradicting_evidence=[
                {"evidence_id": ev.evidence_id, "document_id": ev.document_reference, "text": ev.text_span or ev.content or ev.value_description, "polarity": ev.polarity.value, "review_status": ev.review_status.value}
                for evidence_id in r.contradicting_evidence_ids
                if (ev := session.store.get_evidence(evidence_id)) is not None
            ],
        )
        for r in relationships
    ]

    claims = session.store.list_claims()
    disp_claims = sum(1 for c in claims if c.review_status == ReviewStatus.DISPUTED or len(c.contradicting_evidence_ids) > 0)
    unrev_claims = sum(1 for c in claims if c.review_status == ReviewStatus.UNREVIEWED)
    unsupported_rels = sum(1 for r in relationships if len(r.supporting_claim_ids) == 0 and len(r.supporting_evidence_ids) == 0)

    return GraphQueryResponse(
        root_entity_id=None,
        max_depth=0,
        max_nodes=max_nodes,
        nodes=nodes,
        edges=edges,
        disputed_claim_count=disp_claims,
        unreviewed_claim_count=unrev_claims,
        unsupported_relationship_count=unsupported_rels,
    )


@router.get("/investigations/{investigation_id}/graph/query", response_model=GraphQueryResponse)
def query_graph_neighborhood(
    investigation_id: str,
    start_entity_id: str = Query(..., min_length=1),
    max_depth: int = Query(default=2, ge=1, le=5),
    max_nodes: int = Query(default=50, ge=1, le=100),
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Execute cycle-safe bounded traversal starting from a root entity."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    if not session.store.has_entity(start_entity_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Root entity '{start_entity_id}' not found.",
        )

    result = orchestrator.query_entity(
        investigation_id=investigation_id,
        entity_id=start_entity_id,
        max_depth=max_depth,
        max_nodes=max_nodes,
    )

    degree_map: Dict[str, int] = {e.entity_id: 0 for e in result.entities}
    for r in result.relationships:
        degree_map[r.source_entity_id] = degree_map.get(r.source_entity_id, 0) + 1
        degree_map[r.target_entity_id] = degree_map.get(r.target_entity_id, 0) + 1

    nodes = [
        GraphNode(
            id=e.entity_id,
            label=e.canonical_name,
            entity_type=e.entity_type.value,
            is_provisional=bool(e.metadata.get("provisional", False)),
            degree=degree_map.get(e.entity_id, 0),
        )
        for e in result.entities
    ]

    edges = [
        GraphEdge(
            id=r.relationship_id,
            source=r.source_entity_id,
            target=r.target_entity_id,
            relationship_type=r.relationship_type,
            epistemic_tier=r.epistemic_tier.value,
            review_status=r.review_status.value,
            is_directed=r.is_directed,
            supporting_claim_count=len(r.supporting_claim_ids),
            contradicting_claim_count=len(r.contradicting_claim_ids),
            source_label=session.store.get_entity(r.source_entity_id).canonical_name,
            target_label=session.store.get_entity(r.target_entity_id).canonical_name,
            supporting_claim_ids=list(r.supporting_claim_ids),
            supporting_evidence_ids=list(r.supporting_evidence_ids),
            contradicting_claim_ids=list(r.contradicting_claim_ids),
            contradicting_evidence_ids=list(r.contradicting_evidence_ids),
            supporting_evidence=[
                {"evidence_id": ev.evidence_id, "document_id": ev.document_reference, "text": ev.text_span or ev.content or ev.value_description, "polarity": ev.polarity.value, "review_status": ev.review_status.value}
                for evidence_id in r.supporting_evidence_ids
                if (ev := session.store.get_evidence(evidence_id)) is not None
            ],
            contradicting_evidence=[
                {"evidence_id": ev.evidence_id, "document_id": ev.document_reference, "text": ev.text_span or ev.content or ev.value_description, "polarity": ev.polarity.value, "review_status": ev.review_status.value}
                for evidence_id in r.contradicting_evidence_ids
                if (ev := session.store.get_evidence(evidence_id)) is not None
            ],
        )
        for r in result.relationships
    ]

    return GraphQueryResponse(
        root_entity_id=start_entity_id,
        max_depth=max_depth,
        max_nodes=max_nodes,
        nodes=nodes,
        edges=edges,
        disputed_claim_count=result.disputed_claim_count,
        unreviewed_claim_count=result.unreviewed_claim_count,
        unsupported_relationship_count=result.unsupported_relationship_count,
    )


# =============================================================================
# Claims & Evidence
# =============================================================================

@router.get("/investigations/{investigation_id}/claims", response_model=ClaimListResponse)
def list_claims(
    investigation_id: str,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """List all extracted claims and their epistemic statuses."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    claims = session.store.list_claims()
    resp_claims = []
    for c in claims:
        history = [corr.model_dump() for corr in c.correction_history]
        resp_claims.append(
            ClaimResponse(
                claim_id=c.claim_id,
                subject_id=c.subject_id,
                predicate=c.predicate,
                object_id=c.object_id,
                confidence=c.confidence,
                confidence_semantics=c.confidence_semantics.value if c.confidence_semantics else None,
                review_status=c.review_status.value,
                qualifiers=_to_plain_dict(c.qualifiers),
                supporting_evidence_ids=list(c.supporting_evidence_ids),
                contradicting_evidence_ids=list(c.contradicting_evidence_ids),
                correction_history=history,
                superseded_by_claim_id=c.superseded_by_claim_id,
                retraction_reason=c.retraction_reason,
                created_at=c.created_at.isoformat() if c.created_at else datetime.now(timezone.utc).isoformat(),
                updated_at=c.updated_at.isoformat() if c.updated_at else datetime.now(timezone.utc).isoformat(),
            )
        )
    return ClaimListResponse(total=len(resp_claims), claims=resp_claims)


@router.get("/investigations/{investigation_id}/evidence", response_model=EvidenceListResponse)
def list_evidence(
    investigation_id: str,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """List all evidence snippets with exact character offsets."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    ev_list = session.store.list_evidence()
    resp_ev = [
        EvidenceResponse(
            evidence_id=e.evidence_id,
            document_id=e.document_reference,
            evidence_type=e.evidence_type,
            polarity=e.polarity.value,
            content=e.content,
            text_span=e.text_span,
            start_char=e.char_offsets[0],
            end_char=e.char_offsets[1],
            review_status=e.review_status.value,
            extraction_method=e.extraction_method,
            extractor_version=e.extractor_version,
            provenance=e.provenance,
            metadata=_to_plain_dict(e.metadata),
        )
        for e in ev_list
    ]
    return EvidenceListResponse(total=len(resp_ev), evidence=resp_ev)


@router.get("/investigations/{investigation_id}/evidence/{evidence_id}", response_model=EvidenceResponse)
def get_evidence_item(
    investigation_id: str,
    evidence_id: str,
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Retrieve single evidence item."""
    session = orchestrator.get_investigation(investigation_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    e = session.store.get_evidence(evidence_id)
    if not e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evidence '{evidence_id}' not found.",
        )
    return EvidenceResponse(
        evidence_id=e.evidence_id,
        document_id=e.document_reference,
        evidence_type=e.evidence_type,
        polarity=e.polarity.value,
        content=e.content,
        text_span=e.text_span,
        start_char=e.char_offsets[0],
        end_char=e.char_offsets[1],
        review_status=e.review_status.value,
        extraction_method=e.extraction_method,
        extractor_version=e.extractor_version,
        provenance=e.provenance,
        metadata=_to_plain_dict(e.metadata),
    )


# =============================================================================
# Human Review Queue & Decisions
# =============================================================================

@router.get("/investigations/{investigation_id}/review-queue", response_model=ReviewQueueResponse)
def get_review_queue(
    investigation_id: str,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Retrieve active items requiring human review and verification."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    raw_queue = orchestrator.get_human_review_queue(investigation_id)
    resp_items: List[ReviewQueueItemResponse] = []

    for item in raw_queue:
        cat = item.get("category", "UNKNOWN")
        item_id = item.get("item_id", "")
        reason = item.get("reason", "")

        claim_details = None
        sup_ev: List[EvidenceResponse] = []
        con_ev: List[EvidenceResponse] = []

        c = session.store.get_claim(item_id)
        if c is not None:
            claim_details = {
                "claim_id": c.claim_id,
                "subject_id": c.subject_id,
                "predicate": c.predicate,
                "object_id": c.object_id,
                "confidence": c.confidence,
                "review_status": c.review_status.value,
                "qualifiers": _to_plain_dict(c.qualifiers),
            }
            for eid in c.supporting_evidence_ids:
                e = session.store.get_evidence(eid)
                if e is not None:
                    sup_ev.append(
                        EvidenceResponse(
                            evidence_id=e.evidence_id,
                            document_id=e.document_reference,
                            evidence_type=e.evidence_type,
                            polarity=e.polarity.value,
                            content=e.content,
                            text_span=e.text_span,
                            start_char=e.char_offsets[0],
                            end_char=e.char_offsets[1],
                            review_status=e.review_status.value,
                            extraction_method=e.extraction_method,
                            extractor_version=e.extractor_version,
                            provenance=e.provenance,
                            metadata=_to_plain_dict(e.metadata),
                        )
                    )
            for eid in c.contradicting_evidence_ids:
                e = session.store.get_evidence(eid)
                if e is not None:
                    con_ev.append(
                        EvidenceResponse(
                            evidence_id=e.evidence_id,
                            document_id=e.document_reference,
                            evidence_type=e.evidence_type,
                            polarity=e.polarity.value,
                            content=e.content,
                            text_span=e.text_span,
                            start_char=e.char_offsets[0],
                            end_char=e.char_offsets[1],
                            review_status=e.review_status.value,
                            extraction_method=e.extraction_method,
                            extractor_version=e.extractor_version,
                            provenance=e.provenance,
                            metadata=_to_plain_dict(e.metadata),
                        )
                    )

        resp_items.append(
            ReviewQueueItemResponse(
                category=cat,
                item_id=item_id,
                reason=reason,
                surface_text=item.get("surface_text"),
                status=item.get("status"),
                claim_details=claim_details,
                supporting_evidence=sup_ev,
                contradicting_evidence=con_ev,
            )
        )

    return ReviewQueueResponse(total=len(resp_items), items=resp_items)


@router.post("/investigations/{investigation_id}/review-claim", response_model=ClaimResponse)
def review_claim_action(
    investigation_id: str,
    req: ReviewClaimRequest,
    request: Request,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """
    Execute consequential human review action on a claim.
    Requires validated reviewer identity and audit rationale; enforces lifecycle transition rules.
    """
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    if session.store.get_claim(req.claim_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim '{req.claim_id}' not found.",
        )

    # Validate reviewer attribution against authenticated principal or local format
    authenticated_principal = getattr(request.state, "authenticated_principal", None)
    clean_reviewer = validate_reviewer_identity(req.reviewer, authenticated_principal)

    try:
        target_status = ReviewStatus(req.new_status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid review status '{req.new_status}'.",
        )

    try:
        updated_claim = orchestrator.review_claim(
            investigation_id=investigation_id,
            claim_id=req.claim_id,
            new_status=target_status,
            rationale=req.rationale.strip(),
            reviewer=clean_reviewer,
            replacement_claim_id=req.replacement_claim_id,
        )
    except InvalidLifecycleTransitionError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Review transition rejected by lifecycle safeguards: {str(e)}",
        )

    history = [corr.model_dump() for corr in updated_claim.correction_history]
    return ClaimResponse(
        claim_id=updated_claim.claim_id,
        subject_id=updated_claim.subject_id,
        predicate=updated_claim.predicate,
        object_id=updated_claim.object_id,
        confidence=updated_claim.confidence,
        confidence_semantics=updated_claim.confidence_semantics.value if updated_claim.confidence_semantics else None,
        review_status=updated_claim.review_status.value,
        qualifiers=_to_plain_dict(updated_claim.qualifiers),
        supporting_evidence_ids=list(updated_claim.supporting_evidence_ids),
        contradicting_evidence_ids=list(updated_claim.contradicting_evidence_ids),
        correction_history=history,
        superseded_by_claim_id=updated_claim.superseded_by_claim_id,
        retraction_reason=updated_claim.retraction_reason,
        created_at=updated_claim.created_at.isoformat() if updated_claim.created_at else datetime.now(timezone.utc).isoformat(),
        updated_at=updated_claim.updated_at.isoformat() if updated_claim.updated_at else datetime.now(timezone.utc).isoformat(),
    )


# =============================================================================
# Reports
# =============================================================================

@router.get("/investigations/{investigation_id}/report", response_model=ReportResponse)
def get_investigation_report(
    investigation_id: str,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Retrieve structured audit-grade investigation report (JSON)."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    report = orchestrator.generate_report(investigation_id)
    return ReportResponse(
        investigation_id=report.investigation_id,
        report_schema_version=report.report_schema_version,
        generated_at=report.generated_at.isoformat(),
        investigation_status=report.investigation_status.value,
        extraction_backend=report.extraction_backend,
        persistence_backend=report.persistence_backend,
        persistence_notice=report.persistence_notice,
        metrics=report.metrics,
        warnings=report.warnings_and_limitations,
        raw_json=report.to_dict(),
        markdown_report=report.to_markdown_report(),
    )


@router.get("/investigations/{investigation_id}/report/markdown", response_class=PlainTextResponse)
def get_investigation_report_markdown(
    investigation_id: str,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Retrieve audit-grade Markdown report export."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    report = orchestrator.generate_report(investigation_id)
    return PlainTextResponse(content=report.to_markdown_report(), media_type="text/markdown")


@router.get("/investigations/{investigation_id}/report/download")
def download_investigation_report(
    investigation_id: str,
    format: str = Query(default="markdown", pattern=r"^(markdown|json|html)$"),
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Download investigation report as markdown, json, or self-contained HTML file attachment."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    report = orchestrator.generate_report(investigation_id)
    timestamp_slug = report.generated_at.strftime("%Y%m%d_%H%M%S")

    if format == "json":
        content = report.to_json(indent=2)
        media_type = "application/json"
        filename = f"sherlock_report_{investigation_id}_{timestamp_slug}.json"
    elif format == "html":
        content = report.to_html_report()
        media_type = "text/html"
        filename = f"sherlock_report_{investigation_id}_{timestamp_slug}.html"
    else:
        content = report.to_markdown_report()
        media_type = "text/markdown"
        filename = f"sherlock_report_{investigation_id}_{timestamp_slug}.md"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# =============================================================================
# Milestone 15: Cross-Document Entity Resolution & Reversibility Routes
# =============================================================================

@router.post(
    "/investigations/{investigation_id}/cross-document-resolution",
    response_model=CrossDocumentResolutionResponse,
)
def run_cross_document_resolution(
    investigation_id: str,
    threshold: float = 0.55,
    auto_apply: bool = True,
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Run deterministic cross-document candidate generation and resolution."""
    if threshold < 0.10 or threshold > 0.99:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Candidate similarity threshold {threshold:.2f} out of allowed range [0.10, 0.99].",
        )

    session = orchestrator.get_investigation(investigation_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )
    res = orchestrator.resolve_cross_document_entities(
        investigation_id=investigation_id,
        candidate_similarity_threshold=threshold,
        auto_apply_matches=auto_apply,
    )
    matches = sum(1 for d in res.decisions if d.decision == DecisionType.MATCH)
    non_matches = sum(1 for d in res.decisions if d.decision == DecisionType.NON_MATCH)
    reviews = sum(1 for d in res.decisions if d.decision == DecisionType.REVIEW)

    proposals_data = [
        {
            "proposal_id": p.proposal_id,
            "entity_id_a": p.entity_id_a,
            "entity_id_b": p.entity_id_b,
            "decision": p.decision.value,
            "score": p.confidence_score,
            "explanation": p.explanation,
            "positive_evidence": p.positive_evidence,
            "negative_evidence": p.negative_evidence,
            "missing_information": p.missing_information,
            "hard_constraints": p.hard_constraints,
            "is_applied": p.is_applied,
        }
        for p in res.proposals
    ]

    return CrossDocumentResolutionResponse(
        investigation_id=investigation_id,
        total_decisions=len(res.decisions),
        matches=matches,
        non_matches=non_matches,
        reviews_required=reviews,
        proposals=proposals_data,
    )


@router.post(
    "/investigations/{investigation_id}/entities/merge",
    response_model=EntityResponse,
)
def merge_entities(
    investigation_id: str,
    req: EntityMergeRequest,
    principal_user: Optional[str] = Header(None, alias="X-Principal-User"),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Apply an approved cross-document entity merge."""
    session = orchestrator.get_investigation(investigation_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )
    reviewer = validate_reviewer_identity(principal_user or req.reviewer)
    try:
        merged = orchestrator.apply_entity_merge(
            investigation_id=investigation_id,
            proposal_id=req.proposal_id,
            reviewer=reviewer,
            rationale=sanitize_text_for_display(req.rationale),
        )
    except KeyError as ex:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))
    except ValueError as ex:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ex))

    return EntityResponse(
        entity_id=merged.entity_id,
        canonical_name=merged.canonical_name,
        entity_type=merged.entity_type.value,
        cluster_id=merged.cluster_id,
        member_record_ids=list(merged.member_record_ids),
        is_provisional=merged.metadata.get("provisional", False),
        metadata=_to_plain_dict(merged.metadata),
    )


@router.post(
    "/investigations/{investigation_id}/entities/split",
    response_model=List[EntityResponse],
)
def split_entity_route(
    investigation_id: str,
    req: EntitySplitRequest,
    principal_user: Optional[str] = Header(None, alias="X-Principal-User"),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Split an entity into two separate entities and record non-match constraint."""
    session = orchestrator.get_investigation(investigation_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )
    reviewer = validate_reviewer_identity(principal_user or req.reviewer)
    try:
        ent_a, ent_b = orchestrator.split_entity(
            investigation_id=investigation_id,
            entity_id=req.entity_id,
            split_record_ids=req.split_member_records,
            reviewer=reviewer,
            rationale=sanitize_text_for_display(req.rationale),
        )
    except (KeyError, ValueError) as ex:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ex))

    return [
        EntityResponse(
            entity_id=e.entity_id,
            canonical_name=e.canonical_name,
            entity_type=e.entity_type.value,
            cluster_id=e.cluster_id,
            member_record_ids=list(e.member_record_ids),
            is_provisional=e.metadata.get("provisional", False),
            metadata=_to_plain_dict(e.metadata),
        )
        for e in (ent_a, ent_b)
    ]


@router.post(
    "/investigations/{investigation_id}/entities/reverse-merge",
    response_model=List[EntityResponse],
)
def reverse_entity_merge_route(
    investigation_id: str,
    req: EntityReverseMergeRequest,
    principal_user: Optional[str] = Header(None, alias="X-Principal-User"),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Reverse a previous entity merge and restore original entities."""
    session = orchestrator.get_investigation(investigation_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )
    reviewer = validate_reviewer_identity(principal_user or req.reviewer)
    try:
        restored = orchestrator.reverse_merge(
            investigation_id=investigation_id,
            merged_entity_id=req.merged_entity_id,
            reviewer=reviewer,
            rationale=sanitize_text_for_display(req.rationale),
        )
    except (KeyError, ValueError) as ex:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ex))

    return [
        EntityResponse(
            entity_id=e.entity_id,
            canonical_name=e.canonical_name,
            entity_type=e.entity_type.value,
            cluster_id=e.cluster_id,
            member_record_ids=list(e.member_record_ids),
            is_provisional=e.metadata.get("provisional", False),
            metadata=_to_plain_dict(e.metadata),
        )
        for e in restored
    ]


@router.post(
    "/investigations/{investigation_id}/non-match-constraints",
    status_code=status.HTTP_201_CREATED,
)
def add_non_match_constraint_route(
    investigation_id: str,
    req: NonMatchConstraintRequest,
    principal_user: Optional[str] = Header(None, alias="X-Principal-User"),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Declare an explicit non-match constraint between two entities."""
    session = orchestrator.get_investigation(investigation_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )
    reviewer = validate_reviewer_identity(principal_user or req.reviewer)
    orchestrator.add_non_match_constraint(
        investigation_id=investigation_id,
        entity_id_a=req.entity_id_a,
        entity_id_b=req.entity_id_b,
        rationale=sanitize_text_for_display(req.rationale),
        reviewer=reviewer,
    )
    return {
        "status": "created",
        "entity_id_a": req.entity_id_a,
        "entity_id_b": req.entity_id_b,
        "reviewer": reviewer,
    }


# =============================================================================
# Milestone 16 / Repair: Data Management & Safe Deletion Routes
# =============================================================================

@router.get("/system/stats", response_model=SystemStatsResponse)
def get_system_stats_route(
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Retrieve system-wide entity, document, and investigation record counts."""
    stats = orchestrator.get_system_stats()
    return SystemStatsResponse(
        investigations=stats.get("investigations", 0),
        documents=stats.get("documents", 0),
        entities=stats.get("entities", 0),
        evidence=stats.get("evidence", 0),
        claims=stats.get("claims", 0),
        relationships=stats.get("relationships", 0),
        reports=stats.get("reports", 0),
    )


@router.delete("/investigations/{investigation_id}", response_model=ClearInvestigationResponse)
def delete_investigation_route(
    investigation_id: str,
    confirmed_name: Optional[str] = Query(None, description="Must match investigation_id if provided"),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Safely delete an investigation and all associated child data."""
    if confirmed_name is not None and confirmed_name.strip() != investigation_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Confirmation name '{confirmed_name}' does not match investigation ID '{investigation_id}'.",
        )

    deleted, counts = orchestrator.delete_investigation(investigation_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    return ClearInvestigationResponse(
        status="cleared",
        investigation_id=investigation_id,
        deleted_counts=counts,
    )


@router.post("/investigations/{investigation_id}/clear", response_model=ClearInvestigationResponse)
def clear_investigation_route(
    investigation_id: str,
    req: ClearInvestigationRequest,
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Safely clear a single investigation with explicit confirmation payload."""
    if not req or not req.confirmed_name or req.confirmed_name.strip() != investigation_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Confirmation name '{req.confirmed_name if req else None}' does not match investigation ID '{investigation_id}'.",
        )

    deleted, counts = orchestrator.delete_investigation(investigation_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' not found.",
        )

    return ClearInvestigationResponse(
        status="cleared",
        investigation_id=investigation_id,
        deleted_counts=counts,
    )


@router.post("/system/clear-all", response_model=ClearAllDataResponse)
def clear_all_data_route(
    req: ClearAllDataRequest,
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """High-impact transactional clearing of ALL investigation data across the system."""
    valid_phrases = {"DELETE ALL SHERLOCK DATA", "CLEAR ALL DATA"}
    phrase = req.confirmation_phrase.strip() if (req and req.confirmation_phrase) else ""
    if phrase not in valid_phrases:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation phrase must be exactly 'DELETE ALL SHERLOCK DATA' or 'CLEAR ALL DATA'.",
        )

    counts = orchestrator.clear_all_data()
    return ClearAllDataResponse(
        status="cleared",
        deleted_counts=counts,
        message="All investigation data successfully cleared. System state reset.",
    )


# =============================================================================
# Maltego Graph Transforms & Forensic Link Analysis
# =============================================================================

@router.post("/investigations/{investigation_id}/transforms/expand", response_model=TransformResultResponse)
def run_transform_expand(
    investigation_id: str,
    req: TransformExpandRequest,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Maltego Transform: Expand direct or multi-hop neighbor connections."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    engine = MaltegoTransformEngine(session.store)
    result = engine.expand_neighbors(
        entity_id=req.entity_id,
        direction=req.direction,
        max_depth=req.max_depth,
    )
    return TransformResultResponse(
        transform_name=result.transform_name,
        source_entity_id=result.source_entity_id,
        added_entities=result.added_entities,
        added_relationships=result.added_relationships,
        summary=result.summary,
    )


@router.post("/investigations/{investigation_id}/transforms/ownership-chain", response_model=TransformResultResponse)
def run_transform_ownership_chain(
    investigation_id: str,
    req: TransformOwnershipRequest,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Maltego Transform: Trace upstream parent companies, holding structures, and beneficial owners."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    engine = MaltegoTransformEngine(session.store)
    result = engine.trace_ownership_chain(
        entity_id=req.entity_id,
        max_depth=req.max_depth,
    )
    return TransformResultResponse(
        transform_name=result.transform_name,
        source_entity_id=result.source_entity_id,
        added_entities=result.added_entities,
        added_relationships=result.added_relationships,
        summary=result.summary,
    )


@router.post("/investigations/{investigation_id}/transforms/financial-flow", response_model=TransformResultResponse)
def run_transform_financial_flow(
    investigation_id: str,
    req: TransformFinancialFlowRequest,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Maltego Transform: Trace transactional payments and money transfers."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    engine = MaltegoTransformEngine(session.store)
    result = engine.trace_financial_transactions(
        entity_id=req.entity_id,
        max_depth=req.max_depth,
    )
    return TransformResultResponse(
        transform_name=result.transform_name,
        source_entity_id=result.source_entity_id,
        added_entities=result.added_entities,
        added_relationships=result.added_relationships,
        summary=result.summary,
    )


@router.post("/investigations/{investigation_id}/transforms/suspicious-patterns", response_model=SuspiciousPatternsResponse)
def detect_suspicious_patterns(
    investigation_id: str,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Forensic link analysis: Detect circular money flows and shell company clusters."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    engine = MaltegoTransformEngine(session.store)
    circ_flows = engine.detect_circular_financial_flows()
    shell_clusters = engine.detect_shell_company_clusters()
    all_findings = circ_flows + shell_clusters
    return {
        "investigation_id": investigation_id,
        "total_findings": len(all_findings),
        "findings": [f.model_dump() for f in all_findings],
        "epistemic_disclaimer": (
            "Forensic algorithmic detection only. Demonstrates network topology and flow symmetry; "
            "does not establish legal wrongdoing, guilt, or illicit intent without independent corroboration."
        ),
        "circular_flows": [f.model_dump() for f in circ_flows],
        "shell_company_clusters": [f.model_dump() for f in shell_clusters],
        "summary": "Suspicious patterns detection completed",
    }


@router.get("/investigations/{investigation_id}/transforms/shortest-path", response_model=ShortestPathResponse)
def find_shortest_path(
    investigation_id: str,
    source_id: str = Query(...),
    target_id: str = Query(...),
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Find shortest path between two entities in the knowledge graph."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    engine = MaltegoTransformEngine(session.store)
    path_result = engine.find_shortest_path(source_id, target_id)
    return ShortestPathResponse(
        found=bool(path_result),
        source_entity_id=source_id,
        target_entity_id=target_id,
        path=path_result,
    )


@router.post("/investigations/{investigation_id}/transforms/sanctions-screen")
def screen_sanctions(
    investigation_id: str,
    req: TransformSanctionsScreenRequest,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    orchestrator: InvestigationOrchestrator = Depends(get_orchestrator),
):
    """Screen an entity name against international open sanctions and PEP registers."""
    session = enforce_investigation_access(orchestrator, investigation_id, current_user, orchestrator.sqlite_store)
    engine = MaltegoTransformEngine(session.store)
    hits = engine.screen_entity_against_sanctions(req.entity_name)
    return {
        "entity_name": req.entity_name,
        "is_flagged": len(hits) > 0,
        "total_hits": len(hits),
        "hits": [h.model_dump() for h in hits],
    }

