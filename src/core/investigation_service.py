"""
Investigation Query, Explainability, and Orchestration Service for Sherlock AI (Milestones 8 & 12).

Provides:
1. `RelationshipExplanation`: Structured explainability report for each relationship edge.
2. `InvestigationResult`: Immutable comprehensive result containing subgraph, paths, provenance, and narrative.
3. `InvestigationQueryService`: Cycle-safe, bounded query runner producing explainable investigation graphs.
4. `InvestigationStatus`, `DocumentProcessingStatus`, `DocumentProcessingRecord`: Status models for investigations and documents.
5. `InvestigationSummary`: Summary metrics across an entire investigation.
6. `InvestigationReport`: Deterministic, audit-grade structured investigation report (JSON & Markdown).
7. `InvestigationSession`: State container for an active investigation session.
8. `InvestigationOrchestrator`: Unified end-to-end investigation engine integrating document ingestion,
   NER, grounded relation extraction, mention entity resolution, evidence lifecycle, graph reasoning,
   human-in-the-loop review, and report generation.

Enforces:
- Epistemic discipline: distinguishes facts from allegations, asserted vs inferred vs human-verified.
- Clear identification of unsupported, disputed, and unreviewed claims.
- 100% deterministic results for identical inputs and configuration.
- Exact citation of evidence IDs, text spans, character offsets, and source document hashes.
- Referential integrity: no dangling entities or claims.
- Idempotent document reprocessing: re-ingestion does not duplicate claims or evidence or overwrite human review.
"""

from enum import Enum
from datetime import datetime, timezone
import hashlib
import json
import uuid
import html
from typing import Dict, List, Optional, Tuple, Any, Sequence, Set, Callable, Union
from pydantic import Field

from src.core.models import (
    ImmutableBaseModel,
    InvestigationEntity,
    Relationship,
    Claim,
    Evidence,
    Record,
    ReviewStatus,
    RelationshipEpistemicTier,
    EntityType,
    DecisionType,
    ConfidenceSemantics,
)
from src.core.investigation_graph import (
    BaseInvestigationGraphStore,
    InMemoryInvestigationGraphStore,
)
from src.core.investigation_lifecycle import InvestigationLifecycleManager
from src.core.document_ingestion import (
    DocumentIngestionService,
    IngestedDocument,
    DocumentFormat,
    DocumentParsingError,
    ExtractionCapabilityError,
    DocumentLimitExceededError,
)
from src.core.ner import (
    BaseNERExtractor,
    DeterministicRuleNERExtractor,
    EntityMention,
)
from src.core.relation_extraction import (
    BaseRelationExtractor,
    DeterministicRuleRelationExtractor,
    ExtractedRelationCandidate,
)
from src.core.mention_entity_resolution import (
    MentionEntityResolver,
    MentionResolutionResult,
    MentionResolutionStatus,
    mention_to_record,
)
from src.core.document_pipeline import (
    DocumentExtractionPipeline,
    ExtractionPipelineResult,
)
from src.core.cross_document_resolver import (
    CrossDocumentEntityResolver,
    CrossDocumentResolutionResult,
    CrossDocumentDecision,
    EntityMergeProposal,
)


class RelationshipExplanation(ImmutableBaseModel):
    """Structured explainability audit for a single relationship in the investigation graph."""
    relationship_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    epistemic_tier: RelationshipEpistemicTier
    review_status: ReviewStatus
    has_provenance: bool
    is_disputed: bool
    is_unreviewed: bool
    supporting_claim_ids: List[str]
    supporting_evidence_ids: List[str]
    contradicting_claim_ids: List[str]
    contradicting_evidence_ids: List[str]
    summary_text: str


class InvestigationResult(ImmutableBaseModel):
    """Result of an investigation graph query starting from an entity."""
    root_entity_id: str
    max_depth: int
    max_nodes: int
    entities: List[InvestigationEntity]
    relationships: List[Relationship]
    claims: List[Claim]
    evidence: List[Evidence]
    explanations: List[RelationshipExplanation]
    paths: List[Dict[str, Any]]
    disputed_claim_count: int
    unreviewed_claim_count: int
    unsupported_relationship_count: int

    def get_explanation(self, relationship_id: str) -> Optional[RelationshipExplanation]:
        for exp in self.explanations:
            if exp.relationship_id == relationship_id:
                return exp
        return None

    def to_markdown_report(self) -> str:
        """Render a readable human-investigator summary report."""
        lines = [
            f"# Sherlock AI Investigation Report",
            f"**Root Entity ID:** `{self.root_entity_id}`",
            f"**Traversal Constraints:** Max Depth = {self.max_depth}, Max Nodes = {self.max_nodes}",
            f"**Discovered Scope:** {len(self.entities)} Entities, {len(self.relationships)} Relationships, "
            f"{len(self.claims)} Claims, {len(self.evidence)} Evidence Items.",
            "",
            "## Summary Metrics",
            f"- **Disputed Claims:** {self.disputed_claim_count}",
            f"- **Unreviewed Claims:** {self.unreviewed_claim_count}",
            f"- **Unsupported Relationships:** {self.unsupported_relationship_count}",
            "",
            "## Entities",
        ]

        for ent in self.entities:
            mark = " (ROOT)" if ent.entity_id == self.root_entity_id else ""
            lines.append(f"- **`{ent.entity_id}`** [{ent.entity_type.value}]{mark}: {ent.canonical_name} (records: {ent.member_record_ids})")

        lines.extend(["", "## Relationships & Evidence Provenance"])
        if not self.relationships:
            lines.append("*No relationships discovered within traversal depth.*")
        else:
            for exp in self.explanations:
                lines.append(f"### Relationship `{exp.relationship_id}`: `{exp.source_entity_id}` —[{exp.relationship_type}]—> `{exp.target_entity_id}`")
                lines.append(f"- **Epistemic Tier:** `{exp.epistemic_tier.value}`")
                lines.append(f"- **Review Status:** `{exp.review_status.value}`")
                lines.append(f"- **Explanation:** {exp.summary_text}")
                if exp.supporting_evidence_ids:
                    lines.append(f"- **Supporting Evidence:** {', '.join(f'`{eid}`' for eid in exp.supporting_evidence_ids)}")
                if exp.contradicting_evidence_ids:
                    lines.append(f"- **Contradicting Evidence:** {', '.join(f'`{eid}`' for eid in exp.contradicting_evidence_ids)}")
                lines.append("")

        return "\n".join(lines)


class InvestigationQueryService:
    """
    Deterministic investigation graph query engine with cycle safety and explainability.
    """

    def __init__(self, store: BaseInvestigationGraphStore):
        self._store = store

    def query(
        self,
        start_entity_id: str,
        max_depth: int = 2,
        max_nodes: int = 50,
    ) -> InvestigationResult:
        """
        Execute bounded traversal from root entity and generate verifiable explanations.
        """
        subgraph = self._store.traverse_bounded_path(
            start_entity_id=start_entity_id,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )

        entities: List[InvestigationEntity] = subgraph["entities"]
        relationships: List[Relationship] = subgraph["relationships"]
        claims: List[Claim] = subgraph["claims"]
        evidence_items: List[Evidence] = subgraph["evidence"]
        paths: List[Dict[str, Any]] = subgraph["paths"]

        claims_map = {c.claim_id: c for c in claims}
        evidence_map = {e.evidence_id: e for e in evidence_items}

        explanations: List[RelationshipExplanation] = []
        unsupported_count = 0
        disputed_claims = set()
        unreviewed_claims = set()

        # Audit claims in scope
        for c in claims:
            if c.review_status == ReviewStatus.DISPUTED or (
                len(c.contradicting_evidence_ids) > 0
                and c.review_status not in (ReviewStatus.RETRACTED, ReviewStatus.REJECTED, ReviewStatus.SUPERSEDED)
            ):
                disputed_claims.add(c.claim_id)
            if c.review_status == ReviewStatus.UNREVIEWED:
                unreviewed_claims.add(c.claim_id)

        # Audit each relationship
        for rel in relationships:
            rel_ev = self._store.get_relationship_evidence(rel.relationship_id)
            sup_ev_ids = [e.evidence_id for e in rel_ev["supporting"]]
            con_ev_ids = [e.evidence_id for e in rel_ev["contradicting"]]

            has_prov = (len(rel.supporting_claim_ids) > 0 or len(sup_ev_ids) > 0)
            if not has_prov:
                unsupported_count += 1

            has_contradictions = (
                len(rel.contradicting_claim_ids) > 0
                or len(con_ev_ids) > 0
                or any(cid in disputed_claims for cid in rel.supporting_claim_ids)
            )

            is_retracted_or_closed = rel.review_status in (
                ReviewStatus.RETRACTED,
                ReviewStatus.REJECTED,
                ReviewStatus.SUPERSEDED,
            )

            # An edge is currently DISPUTED only if it is active and has unresolved contradictions
            is_disputed = (rel.review_status == ReviewStatus.DISPUTED) or (
                has_contradictions and not is_retracted_or_closed
            )

            is_unreviewed = (
                rel.review_status == ReviewStatus.UNREVIEWED
                and not is_retracted_or_closed
                and any(cid in unreviewed_claims for cid in rel.supporting_claim_ids)
            )

            # Generate narrative explanation
            summary_parts = []
            tier_prefix = f"[{rel.epistemic_tier.value}]"
            summary_parts.append(f"{tier_prefix} Entity `{rel.source_entity_id}` is linked to `{rel.target_entity_id}` via {rel.relationship_type}.")

            if not has_prov:
                summary_parts.append("WARNING: This relationship lacks supporting claims or verified evidence.")
            else:
                sup_claims_str = ", ".join(f"`{cid}`" for cid in rel.supporting_claim_ids) if rel.supporting_claim_ids else "None"
                sup_ev_str = ", ".join(f"`{eid}`" for eid in sup_ev_ids) if sup_ev_ids else "None"
                summary_parts.append(f"Supported by claims: [{sup_claims_str}] and evidence: [{sup_ev_str}].")

            con_claims_str = ", ".join(f"`{cid}`" for cid in rel.contradicting_claim_ids) if rel.contradicting_claim_ids else "None"
            con_ev_str = ", ".join(f"`{eid}`" for eid in con_ev_ids) if con_ev_ids else "None"

            if is_retracted_or_closed:
                summary_parts.append(f"STATUS ALERT: Relationship has been marked {rel.review_status.value}.")
                if has_contradictions:
                    summary_parts.append(
                        f"HISTORICAL CONTRADICTION NOTE: Prior claims were disputed by claims: [{con_claims_str}] and evidence: [{con_ev_str}]. "
                        f"This dispute led to or accompanied the {rel.review_status.value} adjudication; relationship is currently inactive."
                    )
            elif is_disputed:
                summary_parts.append(f"ACTIVE CONTRADICTION DETECTED: Disputed by claims: [{con_claims_str}], evidence: [{con_ev_str}].")

            explanation = RelationshipExplanation(
                relationship_id=rel.relationship_id,
                source_entity_id=rel.source_entity_id,
                target_entity_id=rel.target_entity_id,
                relationship_type=rel.relationship_type,
                epistemic_tier=rel.epistemic_tier,
                review_status=rel.review_status,
                has_provenance=has_prov,
                is_disputed=is_disputed,
                is_unreviewed=is_unreviewed,
                supporting_claim_ids=list(rel.supporting_claim_ids),
                supporting_evidence_ids=sup_ev_ids,
                contradicting_claim_ids=list(rel.contradicting_claim_ids),
                contradicting_evidence_ids=con_ev_ids,
                summary_text=" ".join(summary_parts),
            )
            explanations.append(explanation)

        return InvestigationResult(
            root_entity_id=start_entity_id,
            max_depth=max_depth,
            max_nodes=max_nodes,
            entities=entities,
            relationships=relationships,
            claims=claims,
            evidence=evidence_items,
            explanations=explanations,
            paths=paths,
            disputed_claim_count=len(disputed_claims),
            unreviewed_claim_count=len(unreviewed_claims),
            unsupported_relationship_count=unsupported_count,
        )


# =============================================================================
# Milestone 12: Unified Investigation Orchestration, Status, & Reporting
# =============================================================================


class InvestigationStatus(str, Enum):
    """Lifecycle status of an investigation."""
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    FAILED = "FAILED"


class DocumentProcessingStatus(str, Enum):
    """Lifecycle status of an individual document in an investigation."""
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
    FAILED = "FAILED"


class DocumentProcessingRecord(ImmutableBaseModel):
    """Processing and provenance audit record for a single document."""
    document_id: str
    source_name: str
    source_uri: Optional[str] = None
    content_hash: str
    status: DocumentProcessingStatus
    char_count: int = 0
    mention_count: int = 0
    relation_candidate_count: int = 0
    claim_count: int = 0
    evidence_count: int = 0
    error_message: Optional[str] = None
    processed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class InvestigationSummary(ImmutableBaseModel):
    """Deterministic high-level summary metrics of an investigation."""
    investigation_id: str
    status: InvestigationStatus
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


class InvestigationReport(ImmutableBaseModel):
    """
    Deterministic, audit-grade structured investigation report.
    Provides complete provenance from high-level findings down to raw source spans.
    """
    investigation_id: str
    report_schema_version: str = "v1.2.0"
    generated_at: datetime
    investigation_status: InvestigationStatus
    extraction_backend: str = "rule"
    persistence_backend: str = "in_memory"
    persistence_notice: str = (
        "In-memory reference graph. Graph state is volatile and does not survive "
        "process termination. External durable persistence is not enabled in this prototype."
    )
    documents: List[DocumentProcessingRecord] = Field(default_factory=list)
    entities: List[InvestigationEntity] = Field(default_factory=list)
    evidence_items: List[Evidence] = Field(default_factory=list)
    mention_resolutions: List[MentionResolutionResult] = Field(default_factory=list)
    unresolved_mentions: List[MentionResolutionResult] = Field(default_factory=list)
    claims: List[Claim] = Field(default_factory=list)
    relationships: List[Relationship] = Field(default_factory=list)
    explanations: List[RelationshipExplanation] = Field(default_factory=list)
    disputed_relationships: List[RelationshipExplanation] = Field(default_factory=list)
    retractions_and_supersessions: List[Dict[str, Any]] = Field(default_factory=list)
    human_review_queue: List[Dict[str, Any]] = Field(default_factory=list)
    cross_document_links: List[Dict[str, Any]] = Field(default_factory=list)
    entity_profiles: List[Dict[str, Any]] = Field(default_factory=list)
    reproducibility_summary: Dict[str, Any] = Field(default_factory=dict)
    warnings_and_limitations: List[str] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return self.model_dump()

    def to_json(self, indent: int = 2) -> str:
        """Convert report to deterministic JSON."""
        return json.dumps(self.model_dump(), indent=indent, default=str)

    def to_markdown_report(self) -> str:
        """Render a readable dossier using only records persisted for this investigation."""
        entity_names = {ent.entity_id: ent.canonical_name for ent in self.entities}
        documents_by_id = {doc.document_id: doc for doc in self.documents}
        evidence_by_id = {item.evidence_id: item for item in self.evidence_items}

        def entity_label(entity_id: str) -> str:
            name = entity_names.get(entity_id)
            return f"{name} (`{entity_id}`)" if name else f"Unknown entity (`{entity_id}`)"

        def evidence_reference(evidence_id: str) -> str:
            item = evidence_by_id.get(evidence_id)
            if item is None:
                return f"`{evidence_id}` (record unavailable)"
            doc_id = item.document_reference or getattr(item, "document_id", None)
            document = documents_by_id.get(doc_id or "")
            source = document.source_name if document else (doc_id or "source not recorded")
            span = item.text_span or item.content or item.value_description
            span = " ".join(str(span).split())
            if len(span) > 280:
                span = span[:277] + "..."
            offsets = f"chars {item.char_offsets[0]}-{item.char_offsets[1]}" if item.char_offsets else "span not recorded"
            return f"`{evidence_id}` ({source}, {offsets}): “{span}”"

        findings = [claim for claim in self.claims if claim.review_status not in (ReviewStatus.RETRACTED, ReviewStatus.REJECTED, ReviewStatus.SUPERSEDED)]
        timeline = []
        for document in self.documents:
            if document.processed_at:
                timeline.append((document.processed_at, f"Document processed: {document.source_name} (`{document.document_id}`)"))
        for claim in self.claims:
            for label, value in (("Valid from", claim.valid_from), ("Valid to", claim.valid_to)):
                if value:
                    timeline.append((value, f"{label}: {entity_label(claim.subject_id)} —{claim.predicate}→ {entity_label(claim.object_id)} (`{claim.claim_id}`)"))
        for item in self.evidence_items:
            for label, value in (("Published", item.publication_time), ("Observed", item.observed_at)):
                if value:
                    timeline.append((value, f"Evidence {label.lower()}: {evidence_reference(item.evidence_id)}"))
        timeline.sort(key=lambda entry: (entry[0], entry[1]))

        lines = [
            "# Sherlock AI Investigation Report",
            f"## Investigation Dossier: {self.investigation_id}",
            f"**Investigation ID:** `{self.investigation_id}`",
            f"**Status:** {self.investigation_status.value} | **Generated (UTC):** {self.generated_at.isoformat()}",
            f"**Extraction:** {self.extraction_backend} | **Persistence:** {self.persistence_backend}",
            "",
            f"> **Scope and storage:** {self.persistence_notice}",
            "",
            "## Executive Summary",
            f"This investigation contains {len(self.documents)} document(s), {len(self.entities)} entities, {len(self.claims)} claims, {len(self.relationships)} relationships, and {len(self.evidence_items)} evidence item(s).",
            f"{len(findings)} claim(s) remain active for review; {len(self.disputed_relationships)} relationship(s) are flagged as disputed and {len(self.human_review_queue)} item(s) are in the human review queue.",
            "",
            "## Key Findings",
        ]
        if not findings:
            lines.append("No active claims are recorded in this investigation.")
        else:
            for claim in findings:
                evidence_ids = list(claim.supporting_evidence_ids) + list(claim.contradicting_evidence_ids)
                lines.append(f"- **{entity_label(claim.subject_id)} — {claim.predicate} → {entity_label(claim.object_id)}** (claim `{claim.claim_id}`, {claim.review_status.value}).")
                if claim.qualifiers.get("is_allegation"):
                    lines.append("  - Source text is marked as an allegation; this is not an independently verified fact.")
                for evidence_id in evidence_ids:
                    lines.append(f"  - Evidence: {evidence_reference(evidence_id)}")
                if not evidence_ids:
                    lines.append("  - No evidence is attached to this claim in the stored record.")

        lines.extend([
            "",
            "## Investigation Metrics",
            f"- Documents: {len(self.documents)} ({self.metrics.get('completed_documents', 0)} completed, {self.metrics.get('failed_documents', 0)} failed)",
            f"- Entities: {len(self.entities)} ({self.metrics.get('canonical_entities', 0)} canonical, {self.metrics.get('provisional_entities', 0)} provisional)",
            f"- Claims: {len(self.claims)} | Relationships: {len(self.relationships)} | Evidence items: {len(self.evidence_items)}",
            f"- Review queue: {len(self.human_review_queue)} | Disputed relationships: {len(self.disputed_relationships)}",
            "",
            "## Source Register",
        ])

        if not self.documents:
            lines.append("*No documents registered in this investigation.*")
        else:
            lines.extend([
                "| Document ID | Source Name | SHA-256 Hash | Status | Chars | Mentions | Claims | Evidence |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ])
            for doc in self.documents:
                hash_short = f"`{doc.content_hash[:12]}...`" if doc.content_hash else "N/A"
                lines.append(
                    f"| `{doc.document_id}` | {doc.source_name} | {hash_short} | `{doc.status.value}` | "
                    f"{doc.char_count} | {doc.mention_count} | {doc.claim_count} | {doc.evidence_count} |"
                )

        lines.extend(["", "## Entity Directory"])
        if not self.entities:
            lines.append("*No entities registered in graph.*")
        else:
            for ent in self.entities:
                is_prov = ent.metadata.get("provisional", False)
                status_tag = "[PROVISIONAL UNRESOLVED]" if is_prov else "[CANONICAL]"
                rec_info = f", Member Records: {ent.member_record_ids}" if ent.member_record_ids else ""
                lines.append(f"- **{ent.canonical_name}** ({ent.entity_type.value}; {status_tag}) — entity ID `{ent.entity_id}`{rec_info}.")

        lines.extend(["", "## Unresolved Mentions and Questions"])
        if not self.unresolved_mentions:
            lines.append("*No unresolved mentions pending review.*")
        else:
            lines.extend([
                "> [!NOTE]",
                "> Absence of blocking candidates or insufficient evidence leaves mentions explicitly unresolved.",
                "> An unresolved status is NOT an assertion of non-match.",
                "",
            ])
            for um in self.unresolved_mentions:
                lines.append(
                    f"- Mention `{um.mention_id}`: surface text **\"{um.surface_text}\"** in `{um.document_id}` "
                    f"-> Status: `{um.resolution_status.value}` ({um.explanation})"
                )

        if self.human_review_queue:
            lines.append("### Open Investigator Questions")
            for item in self.human_review_queue:
                lines.append(f"- {item.get('reason', 'Review is required; no reason was recorded.')} (item `{item.get('item_id', 'unknown')}`, {item.get('category', 'review')}).")

        lines.extend(["", "## Timeline"])
        if timeline:
            for when, description in timeline:
                lines.append(f"- {when.isoformat()}: {description}")
        else:
            lines.append("No explicit event or evidence timestamps are stored; no timeline events are inferred from undated text.")

        lines.extend(["", "## Claims and Evidence"])
        if not self.claims:
            lines.append("*No claims recorded in graph.*")
        else:
            for cl in self.claims:
                lines.append(f"### {entity_label(cl.subject_id)} —{cl.predicate}→ {entity_label(cl.object_id)}")
                lines.append(f"Claim reference: `{cl.claim_id}`")
                lines.append(f"- **Status:** `{cl.review_status.value}` | **Method:** `{cl.extraction_method}` ({cl.extractor_version})")
                if cl.confidence is not None:
                    lines.append(f"- **Confidence:** {cl.confidence:.2f} ({cl.confidence_semantics.value})")
                if cl.qualifiers:
                    q_str = ", ".join(f"{k}={v}" for k, v in cl.qualifiers.items())
                    lines.append(f"- **Epistemic Qualifiers:** {q_str}")
                if cl.supporting_evidence_ids:
                    lines.append("- **Supporting Evidence:**")
                    lines.extend(f"  - {evidence_reference(eid)}" for eid in cl.supporting_evidence_ids)
                if cl.contradicting_evidence_ids:
                    lines.append("- **Contradicting Evidence:**")
                    lines.extend(f"  - {evidence_reference(eid)}" for eid in cl.contradicting_evidence_ids)
                if cl.correction_history:
                    lines.append(f"- **Correction History Entries:** {len(cl.correction_history)}")
                lines.append("")

        lines.extend(["## Relationships"])
        if not self.relationships:
            lines.append("*No relationships derived in graph.*")
        else:
            for exp in self.explanations:
                status_badge = f"[{exp.review_status.value}]"
                lines.append(
                    f"### {entity_label(exp.source_entity_id)} —{exp.relationship_type}→ {entity_label(exp.target_entity_id)} {status_badge}"
                )
                lines.append(f"Relationship reference: `{exp.relationship_id}`")
                lines.append(f"- **Epistemic Tier:** `{exp.epistemic_tier.value}`")
                lines.append(f"- **Explanation:** {exp.summary_text}")
                if exp.supporting_evidence_ids:
                    lines.append("- **Supporting Evidence:**")
                    lines.extend(f"  - {evidence_reference(eid)}" for eid in exp.supporting_evidence_ids)
                if exp.contradicting_evidence_ids:
                    lines.append("- **Contradicting Evidence:**")
                    lines.extend(f"  - {evidence_reference(eid)}" for eid in exp.contradicting_evidence_ids)
                lines.append("")

        lines.extend(["## 7. Contradictions, Retractions & Provenance History"])
        if not self.retractions_and_supersessions and not self.disputed_relationships:
            lines.append("*No disputes, retractions, or claim supersessions on record.*")
        else:
            if self.disputed_relationships:
                lines.append("### Active Disputed Relationships")
                for dr in self.disputed_relationships:
                    lines.append(f"- **`{dr.relationship_id}`**: {dr.summary_text}")
                lines.append("")
            if self.retractions_and_supersessions:
                lines.append("### Retractions & Supersessions Audit Log")
                for entry in self.retractions_and_supersessions:
                    lines.append(
                        f"- Item `{entry.get('id')}` ({entry.get('type')}): New Status = `{entry.get('new_status')}`, "
                        f"Rationale = \"{entry.get('rationale')}\", Adjudicated By = `{entry.get('reviewer')}`"
                    )
                lines.append("")

        lines.extend(["## 8. Human Review Queue"])
        if not self.human_review_queue:
            lines.append("*No items currently pending human investigator review.*")
        else:
            for item in self.human_review_queue:
                lines.append(f"- **[{item.get('category')}]** `{item.get('item_id')}`: {item.get('reason')}")

        if self.cross_document_links:
            lines.extend(["", "## 9. Proposed Cross-Document Identity Links"])
            lines.extend([
                "| Entity A | Entity B | Decision | Score | Method | Traceable Explanation |",
                "| :--- | :--- | :--- | :--- | :--- | :--- |",
            ])
            for link in self.cross_document_links:
                lines.append(
                    f"| `{link.get('entity_id_a')}` | `{link.get('entity_id_b')}` | `{link.get('decision')}` | "
                    f"{link.get('score', 0.0):.2f} | `{link.get('policy_version', 'cd-er-v1')}` | {link.get('explanation', '')} |"
                )

        if self.entity_profiles:
            lines.extend(["", "## 10. Entity Profiles & Cross-Document Grounding"])
            for prof in self.entity_profiles:
                aliases_str = ", ".join(prof.get("aliases", [])) if prof.get("aliases") else "None"
                docs_str = ", ".join(f"`{d}`" for d in prof.get("document_sources", [])) if prof.get("document_sources") else "None"
                lines.append(f"### Profile: `{prof.get('entity_id')}` ({prof.get('canonical_name')})")
                lines.append(f"- **Type:** `{prof.get('entity_type')}` | **Provisional:** `{prof.get('is_provisional')}`")
                lines.append(f"- **Source Documents:** [{docs_str}] | **Member Records:** {prof.get('member_record_count', 0)}")
                lines.append(f"- **Known Aliases:** {aliases_str}")
                lines.append("")

        if self.reproducibility_summary:
            lines.extend(["## 11. Reproducibility Summary & System Configuration"])
            for k, v in self.reproducibility_summary.items():
                lines.append(f"- **{k}:** `{v}`")
            lines.append("")

        lines.extend([
            "## Limitations and Methodology",
            "- **Extraction is NOT Verification:** Automated extractions default to `UNREVIEWED` status.",
            f"- **Persistence:** {self.persistence_notice}",
            "- **Relationship Semantics:** A relationship edge establishes source assertion or model inference, NOT proof of identity, guilt, or wrongdoing.",
            "- **Conservative Matching Guard:** High string similarity alone is insufficient for automatic identity merge without contextual corroboration.",
        ])
        for w in self.warnings_and_limitations:
            lines.append(f"- **System Warning:** {w}")

        return "\n".join(lines)

    def to_html_report(self) -> str:
        """Render a deterministic, self-contained, audit-grade HTML report that prints cleanly to PDF."""
        title = html.escape(f"Sherlock AI Investigation Report — {self.investigation_id}")
        gen_time = html.escape(self.generated_at.isoformat())
        inv_status = html.escape(self.investigation_status.value)
        inv_id = html.escape(self.investigation_id)
        entity_names = {ent.entity_id: ent.canonical_name for ent in self.entities}

        def display_entity(entity_id: str) -> str:
            name = entity_names.get(entity_id)
            if name:
                return f"{html.escape(name)} <code>{html.escape(entity_id)}</code>"
            return f"Unknown entity <code>{html.escape(entity_id)}</code>"

        doc_rows = []
        for d in self.documents:
            h_short = html.escape(d.content_hash[:12] + "...") if d.content_hash else "N/A"
            doc_rows.append(
                f"<tr><td><code>{html.escape(d.document_id)}</code></td>"
                f"<td>{html.escape(d.source_name)}</td>"
                f"<td><code>{h_short}</code></td>"
                f"<td><span class='badge'>{html.escape(d.status.value)}</span></td>"
                f"<td>{d.char_count}</td><td>{d.mention_count}</td><td>{d.claim_count}</td><td>{d.evidence_count}</td></tr>"
            )

        ent_items = []
        for e in self.entities:
            is_prov = e.metadata.get("provisional", False)
            tag = "PROVISIONAL" if is_prov else "CANONICAL"
            ent_items.append(
                f"<li><strong>{html.escape(e.canonical_name)}</strong> "
                f"<span class='badge badge-{tag.lower()}'>{tag}</span> "
                f"({html.escape(e.entity_type.value)}) <code>{html.escape(e.entity_id)}</code></li>"
            )

        claim_items = []
        for c in self.claims:
            conf_str = f" | Confidence: {c.confidence:.2f} ({html.escape(c.confidence_semantics.value)})" if c.confidence is not None else ""
            evidence_html = "".join(
                f"<blockquote>{html.escape((ev.text_span or ev.content or ev.value_description)[:400])}<br><small>Evidence <code>{html.escape(eid)}</code> · {html.escape(ev.document_reference or 'source not recorded')}</small></blockquote>"
                for eid in list(c.supporting_evidence_ids) + list(c.contradicting_evidence_ids)
                if (ev := next((item for item in self.evidence_items if item.evidence_id == eid), None)) is not None
            )
            claim_items.append(
                f"<div class='item-card'>"
                f"<h4>{display_entity(c.subject_id)} —{html.escape(c.predicate)}→ {display_entity(c.object_id)}</h4>"
                f"<p>Claim <code>{html.escape(c.claim_id)}</code></p>"
                f"<p>Status: <span class='badge'>{html.escape(c.review_status.value)}</span> | Method: <code>{html.escape(c.extraction_method or 'unknown')}</code>{conf_str}</p>"
                f"{evidence_html}</div>"
            )

        rel_items = []
        for exp in self.explanations:
            status_cls = "badge-disputed" if exp.is_disputed else "badge-match"
            rel_items.append(
                f"<div class='item-card'>"
                f"<h4>{display_entity(exp.source_entity_id)} —{html.escape(exp.relationship_type)}→ {display_entity(exp.target_entity_id)} "
                f"<span class='badge {status_cls}'>{html.escape(exp.review_status.value)}</span></h4>"
                f"<p><strong>Epistemic Tier:</strong> <code>{html.escape(exp.epistemic_tier.value)}</code></p>"
                f"<p><em>{html.escape(exp.summary_text)}</em></p>"
                f"</div>"
            )

        warning_items = [f"<li>{html.escape(w)}</li>" for w in self.warnings_and_limitations]
        timeline_items = [
            f"<li>{html.escape(doc.processed_at.isoformat())}: Processed {html.escape(doc.source_name)} (<code>{html.escape(doc.document_id)}</code>)</li>"
            for doc in self.documents if doc.processed_at
        ]
        for evidence in self.evidence_items:
            for event_label, event_time in (("Published", evidence.publication_time), ("Observed", evidence.observed_at)):
                if event_time:
                    span = html.escape((evidence.text_span or evidence.content or evidence.value_description)[:400])
                    timeline_items.append(f"<li>{html.escape(event_time.isoformat())}: Evidence {event_label.lower()} — {span} (<code>{html.escape(evidence.evidence_id)}</code>)</li>")
        timeline_items.sort()
        question_items = [
            f"<li>{html.escape(str(item.get('reason', 'Review required; no reason recorded.')))} (<code>{html.escape(str(item.get('item_id', 'unknown')))}</code>)</li>"
            for item in self.human_review_queue
        ]

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #F7F1E8; color: #191A2D; margin: 0; padding: 24px; }}
    .container {{ max-width: 960px; margin: 0 auto; background: #FFFDF9; border: 1px solid #E4DCD2; border-radius: 12px; padding: 32px; box-shadow: 0 4px 16px rgba(0,0,0,0.06); }}
    h1, h2, h3, h4 {{ color: #191A2D; margin-top: 1.2em; }}
    .header-bar {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #E4DCD2; padding-bottom: 16px; margin-bottom: 24px; }}
    .print-btn {{ background: #F5AD87; color: #191A2D; border: none; padding: 8px 16px; border-radius: 20px; font-weight: bold; cursor: pointer; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.8rem; background: #E2E8F0; color: #1E293B; }}
    .badge-canonical {{ background: #BFE8D9; color: #064E3B; font-weight: bold; }}
    .badge-provisional {{ background: #FED7AA; color: #7C2D12; }}
    .badge-disputed {{ background: #FECACA; color: #991B1B; font-weight: bold; }}
    .badge-match {{ background: #BFE8D9; color: #064E3B; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; margin-bottom: 20px; font-size: 0.9rem; }}
    th, td {{ border: 1px solid #E2E8F0; padding: 8px 12px; text-align: left; }}
    th {{ background: #F1EBE1; }}
    .item-card {{ background: #FBF8F3; border: 1px solid #E9E1D5; border-radius: 8px; padding: 12px; margin-bottom: 12px; }}
    .notice {{ background: #FFF7ED; border-left: 4px solid #F5AD87; padding: 12px; margin: 16px 0; border-radius: 4px; }}
    @media print {{
      .print-btn {{ display: none; }}
      body {{ background: #FFFFFF; padding: 0; }}
      .container {{ border: none; box-shadow: none; padding: 0; max-width: 100%; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header-bar">
      <div>
        <h1 style="margin: 0;">Sherlock AI Investigation Report</h1>
        <div style="color: #64748B; font-size: 0.9rem; margin-top: 4px;">Investigation ID: <code>{inv_id}</code> | Status: <strong>{inv_status}</strong></div>
        <div style="color: #64748B; font-size: 0.85rem;">Generated (UTC): {gen_time}</div>
      </div>
      <button class="print-btn" onclick="window.print()">Print / Save as PDF</button>
    </div>

    <div class="notice">
      <strong>Epistemic Storage & Audit Notice:</strong> {html.escape(self.persistence_notice)}
    </div>

        <h2>Executive Summary</h2>
        <p>This investigation contains {len(self.documents)} document(s), {len(self.entities)} entities, {len(self.claims)} claims, {len(self.relationships)} relationships, and {len(self.evidence_items)} stored evidence item(s). Automated findings remain subject to their recorded review status.</p>

    <h2>1. Summary Metrics</h2>
    <table>
      <tr><th>Metric</th><th>Count</th></tr>
      <tr><td>Ingested Documents</td><td>{self.metrics.get('total_documents', len(self.documents))}</td></tr>
      <tr><td>Entities in Graph</td><td>{self.metrics.get('total_entities', len(self.entities))}</td></tr>
      <tr><td>Canonical Entities</td><td>{self.metrics.get('canonical_entities', 0)}</td></tr>
      <tr><td>Provisional Entities</td><td>{self.metrics.get('provisional_entities', 0)}</td></tr>
      <tr><td>Total Claims</td><td>{self.metrics.get('total_claims', len(self.claims))}</td></tr>
      <tr><td>Active Relationships</td><td>{self.metrics.get('active_relationships', 0)}</td></tr>
      <tr><td>Disputed Relationships</td><td>{self.metrics.get('disputed_relationships', len(self.disputed_relationships))}</td></tr>
    </table>

    <h2>2. Ingested Documents & Provenance Registry</h2>
    {"<table><thead><tr><th>ID</th><th>Source Name</th><th>Hash</th><th>Status</th><th>Chars</th><th>Mentions</th><th>Claims</th><th>Evidence</th></tr></thead><tbody>" + "".join(doc_rows) + "</tbody></table>" if doc_rows else "<p><em>No documents registered.</em></p>"}

    <h2>3. Entities & Resolution Status</h2>
    {"<ul>" + "".join(ent_items) + "</ul>" if ent_items else "<p><em>No entities recorded.</em></p>"}

    <h2>4. Extracted Claims & Grounded Spans</h2>
    {"".join(claim_items) if claim_items else "<p><em>No claims recorded.</em></p>"}

    <h2>5. Typed Relationships & Epistemic Tiers</h2>
    {"".join(rel_items) if rel_items else "<p><em>No relationships recorded.</em></p>"}

    <h2>Timeline</h2>
    {"<ol>" + "".join(timeline_items) + "</ol>" if timeline_items else "<p><em>No explicit event or evidence timestamps are stored. Undated text is not assigned a date.</em></p>"}

    <h2>Contradictions and Review Questions</h2>
    {"<ul>" + "".join(f"<li>{html.escape(exp.summary_text)} (relationship <code>{html.escape(exp.relationship_id)}</code>)</li>" for exp in self.disputed_relationships) + "</ul>" if self.disputed_relationships else "<p><em>No active disputed relationships are recorded.</em></p>"}
    {"<ul>" + "".join(question_items) + "</ul>" if question_items else "<p><em>No unresolved review questions are recorded.</em></p>"}

    <h2>6. Warnings, Limitations & Epistemic Disclaimers</h2>
    <ul>
      <li><strong>Extraction is NOT Verification:</strong> Automated extractions default to UNREVIEWED status.</li>
      <li><strong>Epistemic Caution:</strong> A relationship edge asserts a textual claim or inference, NOT judicial proof.</li>
      {"".join(warning_items)}
    </ul>

    <footer style="margin-top: 40px; border-top: 1px solid #E2E8F0; padding-top: 12px; font-size: 0.8rem; color: #94A3B8; text-align: center;">
      Sherlock AI Investigation Dossier &bull; Evidence over assumptions. That's how we find the truth.
    </footer>
  </div>
</body>
</html>"""



class InvestigationSession:
    """
    State container for an active investigation session.
    Encapsulates isolated storage, mention resolution, pipeline, and traversal service.
    """

    def __init__(
        self,
        investigation_id: str,
        description: str = "",
        store: Optional[BaseInvestigationGraphStore] = None,
        backend_mode: str = "rule",
        ner_extractor: Optional[BaseNERExtractor] = None,
        relation_extractor: Optional[BaseRelationExtractor] = None,
        mention_entity_resolver: Optional[MentionEntityResolver] = None,
        owner_id: Optional[str] = None,
    ):
        self.investigation_id = investigation_id
        self.description = description
        self.owner_id = owner_id
        self.created_at = datetime.now(timezone.utc)
        self.status = InvestigationStatus.CREATED
        self.backend_mode = backend_mode

        self.store = store or InMemoryInvestigationGraphStore()
        self.lifecycle_manager = InvestigationLifecycleManager(self.store)
        self.resolver = mention_entity_resolver or MentionEntityResolver()
        self.query_service = InvestigationQueryService(self.store)

        self.pipeline = DocumentExtractionPipeline(
            backend_mode=backend_mode,
            ner_extractor=ner_extractor,
            relation_extractor=relation_extractor,
            mention_entity_resolver=self.resolver,
            lifecycle_manager=self.lifecycle_manager,
            store=self.store,
        )

        self.documents: Dict[str, IngestedDocument] = {}
        self.document_records: Dict[str, DocumentProcessingRecord] = {}
        self.processed_hashes: Dict[str, str] = {}  # content_hash -> document_id
        self.extraction_results: Dict[str, ExtractionPipelineResult] = {}
        self.mentions: List[EntityMention] = []
        self.mention_resolutions: List[MentionResolutionResult] = []
        self.warnings: List[str] = []
        self.cross_doc_resolver = CrossDocumentEntityResolver()
        self.cross_doc_resolution_result: Optional[CrossDocumentResolutionResult] = None
        self.cross_doc_merge_proposals: Dict[str, EntityMergeProposal] = {}
        self.non_match_constraints: List[Dict[str, Any]] = []

    def sync_store_entities_to_resolver(self) -> None:
        """Register all non-provisional entities in store as known records in resolver."""
        for ent in self.store.list_entities():
            if not ent.metadata.get("provisional"):
                if ent.entity_id not in self.resolver.known_records:
                    rec = Record(
                        record_id=ent.entity_id,
                        source_id="investigation_store",
                        raw_name=ent.canonical_name,
                        entity_type=ent.entity_type,
                        structured_attributes={"canonical_name": ent.canonical_name},
                        normalized_attributes={"name": ent.canonical_name.lower()},
                    )
                    self.resolver.add_known_record(rec)


class InvestigationOrchestrator:
    """
    Unified end-to-end investigation orchestration engine for Sherlock AI (Milestone 12).

    Connects:
    - Multi-document ingestion and content deduplication.
    - Deterministic NER and Grounded Relation Extraction.
    - Mention-to-Entity Resolution with candidate blocking and pairwise evidence.
    - Evidence and Claim lifecycle management.
    - Investigation graph construction and cycle-safe traversal.
    - Epistemic auditing, contradiction tracking, and human review safeguards.
    - Deterministic, verifiable investigation reporting.
    """

    def __init__(self, default_backend_mode: str = "rule", sqlite_store: Optional[Any] = None):
        if default_backend_mode not in ("rule", "ml", "hybrid", "mock_ml"):
            raise ValueError(f"Invalid default_backend_mode '{default_backend_mode}'.")
        self.default_backend_mode = default_backend_mode
        self.sqlite_store = sqlite_store
        self._sessions: Dict[str, InvestigationSession] = {}

    def create_investigation(
        self,
        investigation_id: str,
        description: str = "",
        store: Optional[BaseInvestigationGraphStore] = None,
        backend_mode: Optional[str] = None,
        ner_extractor: Optional[BaseNERExtractor] = None,
        relation_extractor: Optional[BaseRelationExtractor] = None,
        mention_entity_resolver: Optional[MentionEntityResolver] = None,
        owner_id: Optional[str] = None,
    ) -> InvestigationSession:
        """Create and initialize a new isolated investigation session."""
        if not investigation_id or not investigation_id.strip():
            raise ValueError("investigation_id must be a non-empty string.")

        if investigation_id in self._sessions:
            raise ValueError(f"Investigation session '{investigation_id}' already exists.")

        mode = backend_mode or self.default_backend_mode
        session = InvestigationSession(
            investigation_id=investigation_id.strip(),
            description=description,
            store=store,
            backend_mode=mode,
            ner_extractor=ner_extractor,
            relation_extractor=relation_extractor,
            mention_entity_resolver=mention_entity_resolver,
            owner_id=owner_id,
        )
        self._sessions[session.investigation_id] = session
        if self.sqlite_store:
            self.sqlite_store.save_investigation(
                session.investigation_id,
                description=description,
                status=session.status,
                backend_mode=session.backend_mode,
                created_at=session.created_at,
                owner_id=owner_id,
            )
        return session

    def get_investigation(self, investigation_id: str) -> Optional[InvestigationSession]:
        """Retrieve an investigation session by ID."""
        if investigation_id in self._sessions:
            return self._sessions[investigation_id]
        if self.sqlite_store:
            inv_data = self.sqlite_store.get_investigation(investigation_id)
            if inv_data:
                session = InvestigationSession(
                    investigation_id=investigation_id,
                    description=inv_data.get("description", ""),
                    backend_mode=inv_data.get("backend_mode", self.default_backend_mode),
                    owner_id=inv_data.get("owner_id"),
                )
                self.sqlite_store.load_investigation_into_session(investigation_id, session)
                self._sessions[investigation_id] = session
                return session
        return None

    def get_investigation_or_raise(self, investigation_id: str) -> InvestigationSession:
        """Retrieve an investigation session or raise KeyError."""
        session = self.get_investigation(investigation_id)
        if session is None:
            raise KeyError(f"Investigation session '{investigation_id}' not found.")
        return session

    def list_investigations(self, owner_id: Optional[str] = None) -> List[str]:
        """List all active investigation IDs, optionally scoped to owner_id."""
        if self.sqlite_store:
            return self.sqlite_store.list_investigation_ids(owner_id=owner_id)
        if owner_id:
            ids = [
                s_id for s_id, s in self._sessions.items()
                if getattr(s, "owner_id", None) == owner_id or getattr(s, "owner_id", None) is None
            ]
            return sorted(ids)
        ids = set(self._sessions.keys())
        return sorted(list(ids))

    def delete_investigation(self, investigation_id: str) -> Tuple[bool, Dict[str, int]]:
        """
        Safely delete an investigation from in-memory sessions and durable SQLite store.
        Returns (success_boolean, counts_of_deleted_records).
        """
        counts = {
            "investigations": 0,
            "documents": 0,
            "entities": 0,
            "evidence": 0,
            "claims": 0,
            "relationships": 0,
            "reports": 0,
        }
        if self.sqlite_store:
            db_success, db_counts = self.sqlite_store.delete_investigation(investigation_id)
            if db_success:
                self._sessions.pop(investigation_id, None)
                return True, db_counts

        session = self._sessions.pop(investigation_id, None)
        if session is None:
            return False, counts

        counts["investigations"] = 1
        counts["documents"] = len(session.documents)
        counts["entities"] = len(session.store.list_entities())
        counts["claims"] = len(session.store.list_claims())
        counts["relationships"] = len(session.store.list_relationships())
        counts["evidence"] = len(session.store.list_evidence())
        return True, counts

    def clear_all_data(self) -> Dict[str, int]:
        """
        Clear all investigations and data across in-memory sessions and durable SQLite store.
        Atomically clears persistent store first, then wipes in-memory cache upon success.
        """
        counts = self.get_system_stats()
        if self.sqlite_store:
            db_counts = self.sqlite_store.clear_all_data()
            counts = db_counts
        self._sessions.clear()
        return counts

    def get_system_stats(self) -> Dict[str, int]:
        """
        Get aggregate counts of all investigations, documents, entities, etc.
        """
        if self.sqlite_store:
            return self.sqlite_store.get_system_stats()

        stats = {
            "investigations": len(self._sessions),
            "documents": sum(len(s.documents) for s in self._sessions.values()),
            "entities": sum(len(s.store.list_entities()) for s in self._sessions.values()),
            "evidence": sum(len(s.store.list_evidence()) for s in self._sessions.values()),
            "claims": sum(len(s.store.list_claims()) for s in self._sessions.values()),
            "relationships": sum(len(s.store.list_relationships()) for s in self._sessions.values()),
            "reports": 0,
        }
        return stats


    def register_known_entity(
        self,
        investigation_id: str,
        entity: InvestigationEntity,
    ) -> InvestigationEntity:
        """
        Register a verified known entity into the investigation store and mention resolver.
        """
        session = self.get_investigation_or_raise(investigation_id)
        added_entity = session.store.add_entity(entity)
        rec = Record(
            record_id=added_entity.entity_id,
            source_id="investigation_store",
            raw_name=added_entity.canonical_name,
            entity_type=added_entity.entity_type,
            structured_attributes={"canonical_name": added_entity.canonical_name},
            normalized_attributes={"name": added_entity.canonical_name.lower()},
        )
        session.resolver.add_known_record(rec)
        return added_entity

    def register_known_record(
        self,
        investigation_id: str,
        record: Record,
    ) -> InvestigationEntity:
        """Register a source record and ensure a corresponding entity exists."""
        session = self.get_investigation_or_raise(investigation_id)
        session.store.add_record(record)
        if not session.store.has_entity(record.record_id):
            entity = InvestigationEntity(
                entity_id=record.record_id,
                entity_type=record.entity_type,
                canonical_name=record.raw_name,
                member_record_ids=[record.record_id],
            )
            session.store.add_entity(entity)
        session.resolver.add_known_record(record)
        return session.store.get_entity(record.record_id)

    def add_explicit_non_match(
        self,
        investigation_id: str,
        id_a: str,
        id_b: str,
    ) -> None:
        """Register an explicit non-match constraint between two record IDs."""
        session = self.get_investigation_or_raise(investigation_id)
        session.resolver.add_explicit_non_match(id_a, id_b)

    def ingest_document(
        self,
        investigation_id: str,
        raw_content: bytes,
        source_name: str,
        source_uri: Optional[str] = None,
        doc_format: Optional[DocumentFormat] = None,
    ) -> DocumentProcessingRecord:
        """
        Register and store a document for subsequent processing without extracting immediately.
        """
        session = self.get_investigation_or_raise(investigation_id)
        content_hash = hashlib.sha256(raw_content).hexdigest()

        # Idempotency check
        if content_hash in session.processed_hashes:
            existing_doc_id = session.processed_hashes[content_hash]
            existing_rec = session.document_records.get(existing_doc_id)
            if existing_rec:
                return DocumentProcessingRecord(
                    document_id=existing_rec.document_id,
                    source_name=source_name,
                    source_uri=source_uri or existing_rec.source_uri,
                    content_hash=content_hash,
                    status=DocumentProcessingStatus.SKIPPED_DUPLICATE,
                    char_count=existing_rec.char_count,
                    mention_count=existing_rec.mention_count,
                    relation_candidate_count=existing_rec.relation_candidate_count,
                    claim_count=existing_rec.claim_count,
                    evidence_count=existing_rec.evidence_count,
                    processed_at=datetime.now(timezone.utc),
                    metadata={"idempotent_duplicate": True, "original_document_id": existing_rec.document_id},
                )

        try:
            doc = session.pipeline.ingestion_service.ingest(
                raw_content=raw_content,
                source_name=source_name,
                source_uri=source_uri,
                doc_format=doc_format,
            )
        except Exception as ex:
            err_rec = DocumentProcessingRecord(
                document_id=f"doc_err_{content_hash[:8]}",
                source_name=source_name,
                source_uri=source_uri,
                content_hash=content_hash,
                status=DocumentProcessingStatus.FAILED,
                error_message=str(ex),
                processed_at=datetime.now(timezone.utc),
            )
            session.document_records[err_rec.document_id] = err_rec
            session.status = InvestigationStatus.PARTIAL_FAILURE
            session.warnings.append(f"Ingestion failed for '{source_name}': {str(ex)}")
            if self.sqlite_store:
                self.sqlite_store.sync_session(session)
            return err_rec

        # Clean up any transient error record for the same content_hash from prior failed attempts
        prior_err_id = f"doc_err_{content_hash[:8]}"
        if prior_err_id in session.document_records:
            del session.document_records[prior_err_id]
            session.warnings = [w for w in session.warnings if not (prior_err_id in w or f"'{source_name}'" in w)]

        session.documents[doc.document_id] = doc
        rec = DocumentProcessingRecord(
            document_id=doc.document_id,
            source_name=source_name,
            source_uri=source_uri,
            content_hash=content_hash,
            status=DocumentProcessingStatus.PENDING,
            char_count=doc.char_count,
            processed_at=datetime.now(timezone.utc),
        )
        session.document_records[doc.document_id] = rec

        has_failures = any(r.status == DocumentProcessingStatus.FAILED for r in session.document_records.values())
        if not has_failures and session.status == InvestigationStatus.PARTIAL_FAILURE:
            session.status = InvestigationStatus.ACTIVE

        if self.sqlite_store:
            self.sqlite_store.sync_session(session)

        return rec

    def process_document(
        self,
        investigation_id: str,
        raw_content: bytes,
        source_name: str,
        source_uri: Optional[str] = None,
        doc_format: Optional[DocumentFormat] = None,
        derive_relationships: bool = True,
        force_reprocess: bool = False,
    ) -> DocumentProcessingRecord:
        """
        Ingest and process a document end-to-end idempotently.
        """
        session = self.get_investigation_or_raise(investigation_id)
        content_hash = hashlib.sha256(raw_content).hexdigest()

        # Idempotency guard: If document with identical content was already processed
        if not force_reprocess and content_hash in session.processed_hashes:
            existing_doc_id = session.processed_hashes[content_hash]
            existing_rec = session.document_records.get(existing_doc_id)
            if existing_rec and existing_rec.status == DocumentProcessingStatus.COMPLETED:
                return DocumentProcessingRecord(
                    document_id=existing_rec.document_id,
                    source_name=source_name,
                    source_uri=source_uri or existing_rec.source_uri,
                    content_hash=content_hash,
                    status=DocumentProcessingStatus.SKIPPED_DUPLICATE,
                    char_count=existing_rec.char_count,
                    mention_count=existing_rec.mention_count,
                    relation_candidate_count=existing_rec.relation_candidate_count,
                    claim_count=existing_rec.claim_count,
                    evidence_count=existing_rec.evidence_count,
                    processed_at=datetime.now(timezone.utc),
                    metadata={"idempotent_duplicate": True, "original_document_id": existing_rec.document_id},
                )

        session.sync_store_entities_to_resolver()

        try:
            result = session.pipeline.process_document(
                raw_content=raw_content,
                source_name=source_name,
                source_uri=source_uri,
                doc_format=doc_format,
                derive_graph_relationships=derive_relationships,
            )
        except Exception as ex:
            err_id = f"doc_err_{content_hash[:8]}"
            err_rec = DocumentProcessingRecord(
                document_id=err_id,
                source_name=source_name,
                source_uri=source_uri,
                content_hash=content_hash,
                status=DocumentProcessingStatus.FAILED,
                error_message=str(ex),
                processed_at=datetime.now(timezone.utc),
            )
            session.document_records[err_id] = err_rec
            session.status = InvestigationStatus.PARTIAL_FAILURE
            session.warnings.append(f"Processing failed for '{source_name}': {str(ex)}")
            if self.sqlite_store:
                self.sqlite_store.sync_session(session)
            return err_rec

        # Clean up any transient error record for the same content_hash from prior failed attempts
        prior_err_id = f"doc_err_{content_hash[:8]}"
        if prior_err_id in session.document_records:
            del session.document_records[prior_err_id]
            session.warnings = [w for w in session.warnings if not (prior_err_id in w or f"'{source_name}'" in w)]

        doc = result.document
        session.documents[doc.document_id] = doc
        session.processed_hashes[content_hash] = doc.document_id
        session.extraction_results[doc.document_id] = result
        session.mentions.extend(result.mentions)
        session.mention_resolutions.extend(result.mention_resolutions)

        session.sync_store_entities_to_resolver()

        rec = DocumentProcessingRecord(
            document_id=doc.document_id,
            source_name=source_name,
            source_uri=source_uri,
            content_hash=content_hash,
            status=DocumentProcessingStatus.COMPLETED,
            char_count=doc.char_count,
            mention_count=len(result.mentions),
            relation_candidate_count=len(result.relation_candidates),
            claim_count=len(result.claims),
            evidence_count=len(result.evidence_items),
            processed_at=datetime.now(timezone.utc),
            metadata={"backend_mode": session.backend_mode},
        )
        session.document_records[doc.document_id] = rec

        # Check if there are any failed documents in session
        has_failures = any(r.status == DocumentProcessingStatus.FAILED for r in session.document_records.values())
        session.status = InvestigationStatus.PARTIAL_FAILURE if has_failures else InvestigationStatus.COMPLETED

        if self.sqlite_store:
            self.sqlite_store.sync_session(session)

        return rec

    def process_all_documents(
        self,
        investigation_id: str,
        derive_relationships: bool = True,
    ) -> InvestigationSummary:
        """Process all pending ingested documents in the session."""
        session = self.get_investigation_or_raise(investigation_id)
        for doc_id, doc in list(session.documents.items()):
            rec = session.document_records.get(doc_id)
            if rec and rec.status == DocumentProcessingStatus.PENDING:
                try:
                    res = session.pipeline.process_ingested_document(
                        document=doc,
                        derive_graph_relationships=derive_relationships,
                    )
                    session.extraction_results[doc_id] = res
                    session.processed_hashes[doc.content_hash] = doc_id
                    session.mentions.extend(res.mentions)
                    session.mention_resolutions.extend(res.mention_resolutions)

                    updated_rec = DocumentProcessingRecord(
                        document_id=doc.document_id,
                        source_name=rec.source_name,
                        source_uri=rec.source_uri,
                        content_hash=doc.content_hash,
                        status=DocumentProcessingStatus.COMPLETED,
                        char_count=doc.char_count,
                        mention_count=len(res.mentions),
                        relation_candidate_count=len(res.relation_candidates),
                        claim_count=len(res.claims),
                        evidence_count=len(res.evidence_items),
                        processed_at=datetime.now(timezone.utc),
                    )
                    session.document_records[doc_id] = updated_rec
                except Exception as ex:
                    updated_rec = DocumentProcessingRecord(
                        document_id=doc.document_id,
                        source_name=rec.source_name,
                        source_uri=rec.source_uri,
                        content_hash=doc.content_hash,
                        status=DocumentProcessingStatus.FAILED,
                        error_message=str(ex),
                        processed_at=datetime.now(timezone.utc),
                    )
                    session.document_records[doc_id] = updated_rec
                    session.warnings.append(f"Failed processing document '{doc_id}': {str(ex)}")

        has_failures = any(r.status == DocumentProcessingStatus.FAILED for r in session.document_records.values())
        session.status = InvestigationStatus.PARTIAL_FAILURE if has_failures else InvestigationStatus.COMPLETED
        if self.sqlite_store:
            self.sqlite_store.sync_session(session)
        return self.get_summary(investigation_id)

    def get_document_record(self, investigation_id: str, document_id: str) -> Optional[DocumentProcessingRecord]:
        session = self.get_investigation_or_raise(investigation_id)
        return session.document_records.get(document_id)

    def list_document_records(self, investigation_id: str) -> List[DocumentProcessingRecord]:
        session = self.get_investigation_or_raise(investigation_id)
        return [session.document_records[k] for k in sorted(session.document_records.keys())]

    def get_extracted_mentions(self, investigation_id: str) -> List[EntityMention]:
        session = self.get_investigation_or_raise(investigation_id)
        return list(session.mentions)

    def get_extracted_claims(self, investigation_id: str) -> List[Claim]:
        session = self.get_investigation_or_raise(investigation_id)
        return session.store.list_claims()

    def get_extracted_relationships(self, investigation_id: str) -> List[Relationship]:
        session = self.get_investigation_or_raise(investigation_id)
        return session.store.list_relationships()

    def get_unresolved_mentions(self, investigation_id: str) -> List[MentionResolutionResult]:
        session = self.get_investigation_or_raise(investigation_id)
        return [
            mr for mr in session.mention_resolutions
            if not mr.is_resolved or mr.resolution_status in (
                MentionResolutionStatus.UNRESOLVED_NO_CANDIDATES,
                MentionResolutionStatus.UNRESOLVED_INSUFFICIENT_EVIDENCE,
            )
        ]

    def get_human_review_queue(self, investigation_id: str) -> List[Dict[str, Any]]:
        """
        Assemble the actionable human review queue for the investigation.
        Gathers:
        - Unresolved mentions requiring human entity disambiguation.
        - Claims with uncertainty flags, allegations, or explicit review requirements.
        - Disputed relationships or active contradictions.
        - Unreviewed claims.
        """
        session = self.get_investigation_or_raise(investigation_id)
        queue: List[Dict[str, Any]] = []

        # 1. Unresolved mentions
        for mr in session.mention_resolutions:
            if not mr.is_resolved:
                queue.append({
                    "category": "UNRESOLVED_MENTION",
                    "item_id": mr.mention_id,
                    "surface_text": mr.surface_text,
                    "status": mr.resolution_status.value,
                    "reason": f"Mention '{mr.surface_text}' unresolved ({mr.resolution_status.value}): {mr.explanation}",
                })

        # 2. Claims with review flags
        for cl in session.store.list_claims():
            if cl.review_status == ReviewStatus.DISPUTED:
                queue.append({
                    "category": "DISPUTED_CLAIM",
                    "item_id": cl.claim_id,
                    "reason": f"Claim `{cl.claim_id}` has active contradiction or dispute status.",
                })
            elif cl.qualifiers.get("requires_human_review") or cl.qualifiers.get("uncertainty_flag") or cl.qualifiers.get("is_allegation"):
                flag_desc = []
                if cl.qualifiers.get("is_allegation"):
                    flag_desc.append("allegation")
                if cl.qualifiers.get("uncertainty_flag"):
                    flag_desc.append("uncertainty")
                if cl.qualifiers.get("requires_human_review"):
                    flag_desc.append("review_flag")
                queue.append({
                    "category": "QUALIFIED_CLAIM_REVIEW",
                    "item_id": cl.claim_id,
                    "reason": f"Claim `{cl.claim_id}` has epistemic qualifiers requiring verification: {', '.join(flag_desc)}",
                })
            elif cl.review_status == ReviewStatus.UNREVIEWED:
                queue.append({
                    "category": "UNREVIEWED_CLAIM",
                    "item_id": cl.claim_id,
                    "reason": f"Claim `{cl.claim_id}` is automated extraction without human verification.",
                })

        # 3. Cross-document entity merge proposals requiring human review
        if session.cross_doc_resolution_result:
            for prop in session.cross_doc_resolution_result.proposals:
                if prop.decision == DecisionType.REVIEW and not prop.is_applied:
                    queue.append({
                        "category": "CROSS_DOCUMENT_ENTITY_REVIEW",
                        "item_id": prop.proposal_id,
                        "entity_id_a": prop.entity_id_a,
                        "entity_id_b": prop.entity_id_b,
                        "status": "REVIEW_REQUIRED",
                        "score": prop.confidence_score,
                        "reason": f"Cross-document entity pair ({prop.canonical_name_a} & {prop.canonical_name_b}) requires manual review: {prop.explanation}",
                        "missing_information": prop.missing_information,
                        "conflicting_evidence": prop.negative_evidence,
                    })

        return queue

    def review_claim(
        self,
        investigation_id: str,
        claim_id: str,
        new_status: ReviewStatus,
        rationale: str,
        reviewer: str,
        replacement_claim_id: Optional[str] = None,
    ) -> Claim:
        """
        Apply human review decision (e.g. RETRACTED, VERIFIED, REJECTED) to a claim.
        Preserves complete historical audit trail and cascades to relationships.
        """
        session = self.get_investigation_or_raise(investigation_id)
        claim = session.lifecycle_manager.review_claim(
            claim_id=claim_id,
            new_status=new_status,
            rationale=rationale,
            reviewer=reviewer,
            replacement_claim_id=replacement_claim_id,
        )
        if self.sqlite_store:
            self.sqlite_store.sync_session(session)
        return claim

    def record_contradiction(
        self,
        investigation_id: str,
        relationship_id: str,
        contradicting_claim_id: str,
    ) -> Relationship:
        """Record contradictory claim against relationship and mark as DISPUTED."""
        session = self.get_investigation_or_raise(investigation_id)
        rel = session.lifecycle_manager.record_contradiction(
            relationship_id=relationship_id,
            contradicting_claim_id=contradicting_claim_id,
        )
        if self.sqlite_store:
            self.sqlite_store.sync_session(session)
        return rel

    def query_entity(
        self,
        investigation_id: str,
        entity_id: str,
        max_depth: int = 2,
        max_nodes: int = 50,
    ) -> InvestigationResult:
        """Execute bounded traversal from root entity with complete explainability."""
        session = self.get_investigation_or_raise(investigation_id)
        return session.query_service.query(
            start_entity_id=entity_id,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )

    def get_summary(self, investigation_id: str) -> InvestigationSummary:
        """Compute structured summary metrics for the investigation."""
        session = self.get_investigation_or_raise(investigation_id)

        docs = list(session.document_records.values())
        completed_docs = sum(1 for d in docs if d.status == DocumentProcessingStatus.COMPLETED)
        failed_docs = sum(1 for d in docs if d.status == DocumentProcessingStatus.FAILED)

        entities = session.store.list_entities()
        prov_entities = sum(1 for e in entities if e.metadata.get("provisional", False))
        canon_entities = len(entities) - prov_entities

        claims = session.store.list_claims()
        unrev_claims = sum(1 for c in claims if c.review_status == ReviewStatus.UNREVIEWED)
        ver_claims = sum(1 for c in claims if c.review_status == ReviewStatus.VERIFIED)
        ret_claims = sum(1 for c in claims if c.review_status == ReviewStatus.RETRACTED)
        disp_claims = sum(1 for c in claims if c.review_status == ReviewStatus.DISPUTED or len(c.contradicting_evidence_ids) > 0)

        relationships = session.store.list_relationships()
        act_rels = sum(1 for r in relationships if r.review_status not in (ReviewStatus.RETRACTED, ReviewStatus.REJECTED, ReviewStatus.SUPERSEDED))
        disp_rels = sum(1 for r in relationships if r.review_status == ReviewStatus.DISPUTED or len(r.contradicting_claim_ids) > 0)
        ret_rels = sum(1 for r in relationships if r.review_status == ReviewStatus.RETRACTED)

        ev_count = len(session.store.list_evidence())
        unresolved_m = len(self.get_unresolved_mentions(investigation_id))
        review_q = len(self.get_human_review_queue(investigation_id))

        return InvestigationSummary(
            investigation_id=session.investigation_id,
            status=session.status,
            total_documents=len(docs),
            completed_documents=completed_docs,
            failed_documents=failed_docs,
            total_entities=len(entities),
            canonical_entities=canon_entities,
            provisional_entities=prov_entities,
            total_claims=len(claims),
            unreviewed_claims=unrev_claims,
            verified_claims=ver_claims,
            retracted_claims=ret_claims,
            disputed_claims=disp_claims,
            total_relationships=len(relationships),
            active_relationships=act_rels,
            disputed_relationships=disp_rels,
            retracted_relationships=ret_rels,
            total_evidence_items=ev_count,
            unresolved_mentions=unresolved_m,
            human_review_queue_size=review_q,
            warnings=list(session.warnings),
        )

    def generate_report(self, investigation_id: str) -> InvestigationReport:
        """
        Generate a comprehensive, deterministic structured investigation report.
        Report generation is strictly read-only and does not mutate graph state.
        """
        session = self.get_investigation_or_raise(investigation_id)

        docs = self.list_document_records(investigation_id)
        entities = session.store.list_entities()
        claims = session.store.list_claims()
        relationships = session.store.list_relationships()
        unresolved_mentions = self.get_unresolved_mentions(investigation_id)
        review_queue = self.get_human_review_queue(investigation_id)

        # Build explanations for all relationships
        explanations: List[RelationshipExplanation] = []
        disputed_exps: List[RelationshipExplanation] = []
        retractions: List[Dict[str, Any]] = []

        disputed_claims_set = {
            c.claim_id for c in claims
            if c.review_status == ReviewStatus.DISPUTED or (
                len(c.contradicting_evidence_ids) > 0
                and c.review_status not in (ReviewStatus.RETRACTED, ReviewStatus.REJECTED, ReviewStatus.SUPERSEDED)
            )
        }

        for rel in relationships:
            rel_ev = session.store.get_relationship_evidence(rel.relationship_id)
            sup_ev_ids = [e.evidence_id for e in rel_ev["supporting"]]
            con_ev_ids = [e.evidence_id for e in rel_ev["contradicting"]]

            has_prov = (len(rel.supporting_claim_ids) > 0 or len(sup_ev_ids) > 0)
            has_contradictions = (
                len(rel.contradicting_claim_ids) > 0
                or len(con_ev_ids) > 0
                or any(cid in disputed_claims_set for cid in rel.supporting_claim_ids)
            )

            is_retracted_or_closed = rel.review_status in (
                ReviewStatus.RETRACTED,
                ReviewStatus.REJECTED,
                ReviewStatus.SUPERSEDED,
            )

            is_disputed = (rel.review_status == ReviewStatus.DISPUTED) or (
                has_contradictions and not is_retracted_or_closed
            )

            summary_parts = [
                f"[{rel.epistemic_tier.value}] Entity `{rel.source_entity_id}` is linked to `{rel.target_entity_id}` via {rel.relationship_type}."
            ]
            if not has_prov:
                summary_parts.append("WARNING: Lacks supporting claims or verified evidence.")
            else:
                sup_claims_str = ", ".join(f"`{cid}`" for cid in rel.supporting_claim_ids) if rel.supporting_claim_ids else "None"
                sup_ev_str = ", ".join(f"`{eid}`" for eid in sup_ev_ids) if sup_ev_ids else "None"
                summary_parts.append(f"Supported by claims: [{sup_claims_str}] and evidence: [{sup_ev_str}].")

            con_claims_str = ", ".join(f"`{cid}`" for cid in rel.contradicting_claim_ids) if rel.contradicting_claim_ids else "None"
            con_ev_str = ", ".join(f"`{eid}`" for eid in con_ev_ids) if con_ev_ids else "None"

            if is_retracted_or_closed:
                summary_parts.append(f"STATUS ALERT: Relationship has been marked {rel.review_status.value}.")
                if has_contradictions:
                    summary_parts.append(
                        f"HISTORICAL CONTRADICTION NOTE: Prior claims were disputed by claims: [{con_claims_str}] and evidence: [{con_ev_str}]. "
                        f"This dispute led to or accompanied the {rel.review_status.value} adjudication; relationship is currently inactive."
                    )
            elif is_disputed:
                summary_parts.append(f"ACTIVE CONTRADICTION DETECTED: Disputed by claims: [{con_claims_str}], evidence: [{con_ev_str}].")

            exp = RelationshipExplanation(
                relationship_id=rel.relationship_id,
                source_entity_id=rel.source_entity_id,
                target_entity_id=rel.target_entity_id,
                relationship_type=rel.relationship_type,
                epistemic_tier=rel.epistemic_tier,
                review_status=rel.review_status,
                has_provenance=has_prov,
                is_disputed=is_disputed,
                is_unreviewed=rel.review_status == ReviewStatus.UNREVIEWED,
                supporting_claim_ids=list(rel.supporting_claim_ids),
                supporting_evidence_ids=sup_ev_ids,
                contradicting_claim_ids=list(rel.contradicting_claim_ids),
                contradicting_evidence_ids=con_ev_ids,
                summary_text=" ".join(summary_parts),
            )
            explanations.append(exp)
            if is_disputed:
                disputed_exps.append(exp)

        # Audit retractions from claims
        for cl in claims:
            if cl.review_status in (ReviewStatus.RETRACTED, ReviewStatus.REJECTED, ReviewStatus.SUPERSEDED):
                for corr in cl.correction_history:
                    retractions.append({
                        "id": cl.claim_id,
                        "type": "Claim",
                        "new_status": corr.new_status.value,
                        "rationale": corr.rationale,
                        "reviewer": corr.corrected_by,
                        "timestamp": corr.corrected_at.isoformat(),
                    })
                if not cl.correction_history:
                    retractions.append({
                        "id": cl.claim_id,
                        "type": "Claim",
                        "new_status": cl.review_status.value,
                        "rationale": cl.retraction_reason or "Terminal status applied without rationale entry",
                        "reviewer": "system_or_prior_session",
                        "timestamp": cl.updated_at.isoformat() if cl.updated_at else datetime.now(timezone.utc).isoformat(),
                    })

        summary = self.get_summary(investigation_id)
        metrics_dict = {
            "total_documents": summary.total_documents,
            "completed_documents": summary.completed_documents,
            "failed_documents": summary.failed_documents,
            "total_entities": summary.total_entities,
            "canonical_entities": summary.canonical_entities,
            "provisional_entities": summary.provisional_entities,
            "total_claims": summary.total_claims,
            "unreviewed_claims": summary.unreviewed_claims,
            "verified_claims": summary.verified_claims,
            "retracted_claims": summary.retracted_claims,
            "disputed_claims": summary.disputed_claims,
            "total_relationships": summary.total_relationships,
            "active_relationships": summary.active_relationships,
            "disputed_relationships": summary.disputed_relationships,
            "retracted_relationships": summary.retracted_relationships,
            "total_evidence_items": summary.total_evidence_items,
        }

        persistence_backend = "in_memory"
        persistence_notice = (
            "In-memory reference graph. Graph state is volatile and does not survive "
            "process termination. External durable persistence is not enabled in this prototype."
        )
        if self.sqlite_store:
            persistence_backend = "sqlite"
            persistence_notice = (
                f"SQLite durable database ({self.sqlite_store.db_path}). "
                "Investigation metadata, ingested documents, entities, claims, evidence, "
                "and relationships survive process restarts."
            )

        cross_doc_links: List[Dict[str, Any]] = []
        if session.cross_doc_resolution_result:
            for dec in session.cross_doc_resolution_result.decisions:
                cross_doc_links.append({
                    "entity_id_a": dec.entity_id_a,
                    "entity_id_b": dec.entity_id_b,
                    "decision": dec.decision.value,
                    "score": dec.similarity_score,
                    "explanation": dec.explanation,
                    "positive_evidence": dec.positive_evidence,
                    "negative_evidence": dec.negative_evidence,
                    "missing_information": dec.missing_information,
                    "hard_constraints": dec.hard_constraints,
                    "policy_version": dec.policy_version,
                    "provenance_method": dec.provenance_method,
                    "is_cross_document": dec.is_cross_document,
                })

        entity_profiles: List[Dict[str, Any]] = []
        for ent in entities:
            aliases = list(ent.metadata.get("aliases", []))
            doc_ids = set()
            for rec_id in ent.member_record_ids:
                if rec_id in session.cross_doc_resolver.records:
                    doc_ids.add(session.cross_doc_resolver.records[rec_id].document_id)
            entity_profiles.append({
                "entity_id": ent.entity_id,
                "canonical_name": ent.canonical_name,
                "entity_type": ent.entity_type.value,
                "is_provisional": ent.metadata.get("provisional", False),
                "member_record_count": len(ent.member_record_ids),
                "document_sources": sorted(list(doc_ids)),
                "aliases": aliases,
                "review_status": ent.metadata.get("review_status", "UNREVIEWED"),
            })

        reproducibility_summary = {
            "orchestrator_version": "v1.5.0",
            "cross_document_resolver_version": "v1.5.0-cd-er",
            "extraction_backend": session.backend_mode,
            "similarity_threshold": session.cross_doc_resolver.blocking_token_threshold,
            "non_match_constraints_active": len(session.cross_doc_resolver.non_match_constraints),
            "total_cross_doc_decisions": len(cross_doc_links),
            "generated_timestamp": datetime.now(timezone.utc).isoformat(),
        }

        report = InvestigationReport(
            investigation_id=session.investigation_id,
            report_schema_version="v1.5.0",
            generated_at=datetime.now(timezone.utc),
            investigation_status=session.status,
            extraction_backend=session.backend_mode,
            persistence_backend=persistence_backend,
            persistence_notice=persistence_notice,
            documents=docs,
            entities=entities,
            evidence_items=session.store.list_evidence(),
            mention_resolutions=session.mention_resolutions,
            unresolved_mentions=unresolved_mentions,
            claims=claims,
            relationships=relationships,
            explanations=explanations,
            disputed_relationships=disputed_exps,
            retractions_and_supersessions=retractions,
            human_review_queue=review_queue,
            cross_document_links=cross_doc_links,
            entity_profiles=entity_profiles,
            reproducibility_summary=reproducibility_summary,
            warnings_and_limitations=list(session.warnings),
            metrics=metrics_dict,
        )

        if self.sqlite_store:
            self.sqlite_store.save_report(
                investigation_id=session.investigation_id,
                report_schema_version=report.report_schema_version,
                report_json=report.to_json(),
                report_markdown=report.to_markdown_report(),
            )

        return report

    def resolve_cross_document_entities(
        self,
        investigation_id: str,
        candidate_similarity_threshold: float = 0.55,
        auto_apply_matches: bool = True,
    ) -> CrossDocumentResolutionResult:
        """
        Milestone 15 Phase 1: Deterministic cross-document entity candidate generation
        and pairwise resolution. Evaluates mentions across all documents in the session.
        """
        session = self.get_investigation_or_raise(investigation_id)
        session.cross_doc_resolver.blocking_token_threshold = candidate_similarity_threshold

        # Ingest documents into cross_doc_resolver
        for doc_id, doc in session.documents.items():
            session.cross_doc_resolver.ingest_document(
                doc_id=doc_id,
                content=doc.normalized_text or "",
                source_uri=doc.source_uri,
            )

        # Ingest all extracted mentions
        for mention in session.mentions:
            session.cross_doc_resolver.ingest_mention(mention)

        # Resolve end-to-end on session
        result = session.cross_doc_resolver.resolve_session(session)
        session.cross_doc_resolution_result = result
        session.cross_doc_merge_proposals = {p.proposal_id: p for p in result.proposals}


        if auto_apply_matches:
            for proposal in result.proposals:
                if proposal.decision == DecisionType.MATCH and not proposal.is_applied:
                    self._apply_merge_proposal(session, proposal)

        if self.sqlite_store:
            self.sqlite_store.sync_session(session)

        return result

    def _apply_merge_proposal(
        self,
        session: InvestigationSession,
        proposal: EntityMergeProposal,
    ) -> InvestigationEntity:
        """Apply an approved cross-document merge proposal to the investigation graph."""
        merged_entity = session.cross_doc_resolver.apply_merge_proposal(
            store=session.store,
            proposal=proposal,
        )
        session.sync_store_entities_to_resolver()
        return merged_entity

    def apply_entity_merge(
        self,
        investigation_id: str,
        proposal_id: str,
        reviewer: str,
        rationale: str,
    ) -> InvestigationEntity:
        """
        Human reviewer approves a proposed cross-document merge proposal.
        Preserves reviewer identity and rationale in audit metadata.
        """
        session = self.get_investigation_or_raise(investigation_id)
        proposal = session.cross_doc_merge_proposals.get(proposal_id)
        if not proposal:
            raise KeyError(f"Proposal '{proposal_id}' not found in active investigation session.")

        merged = session.cross_doc_resolver.apply_merge_proposal(
            store=session.store,
            proposal=proposal,
            reviewer=reviewer,
            rationale=rationale,
        )
        # Ensure the in‑memory store reflects any changes made by the merge.
        session.sync_store_entities_to_resolver()

        # If the merged entity is still provisional (created from a mention),
        # replace its generated canonical_name with the original raw_name from
        # the first underlying record. This yields human‑readable names like
        # "Alice Mercer" instead of internal IDs.
        if merged.metadata.get("provisional", False):
            first_record_id = next(iter(merged.member_record_ids), None)
            if first_record_id:
                record = session.store.get_record(first_record_id)
                if record and getattr(record, "raw_name", None):
                    merged.canonical_name = record.raw_name

        if self.sqlite_store:
            self.sqlite_store.sync_session(session)
        return merged

    def split_entity(
        self,
        investigation_id: str,
        entity_id: str,
        split_record_ids: List[str],
        reviewer: str,
        rationale: str,
    ) -> Tuple[InvestigationEntity, InvestigationEntity]:
        """
        Milestone 15 Phase 1 Reversibility: Split an existing composite entity into two entities.
        Restores separate identities without corrupting raw records and registers an explicit
        non-match constraint to prevent re-merging.
        """
        session = self.get_investigation_or_raise(investigation_id)
        ent_a, ent_b = session.cross_doc_resolver.split_entity(
            store=session.store,
            entity_id=entity_id,
            split_member_records=split_record_ids,
            reviewer=reviewer,
            rationale=rationale,
        )
        session.sync_store_entities_to_resolver()
        if self.sqlite_store:
            self.sqlite_store.sync_session(session)
        return ent_a, ent_b

    def reverse_merge(
        self,
        investigation_id: str,
        merged_entity_id: str,
        reviewer: str,
        rationale: str,
    ) -> List[InvestigationEntity]:
        """
        Milestone 15 Phase 1 Reversibility: Reverse a previous entity merge.
        Restores original entities and injects non-match constraints.
        """
        session = self.get_investigation_or_raise(investigation_id)
        restored = session.cross_doc_resolver.reverse_merge(
            store=session.store,
            merged_entity_id=merged_entity_id,
            reviewer=reviewer,
            rationale=rationale,
        )
        session.sync_store_entities_to_resolver()
        if self.sqlite_store:
            self.sqlite_store.sync_session(session)
        return restored

    def add_non_match_constraint(
        self,
        investigation_id: str,
        entity_id_a: str,
        entity_id_b: str,
        rationale: str,
        reviewer: str,
    ) -> None:
        """Record an explicit non-match constraint between two entities."""
        session = self.get_investigation_or_raise(investigation_id)
        session.cross_doc_resolver.add_non_match_constraint(
            entity_id_a=entity_id_a,
            entity_id_b=entity_id_b,
            rationale=rationale,
            reviewer=reviewer,
        )
        session.non_match_constraints.append({
            "entity_id_a": entity_id_a,
            "entity_id_b": entity_id_b,
            "rationale": rationale,
            "reviewer": reviewer,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if self.sqlite_store:
            self.sqlite_store.sync_session(session)
