"""
Document-to-Evidence Extraction Pipeline for Sherlock AI (Milestone 9).

Connects:
1. Ingestion: Document -> Normalized Text & Metadata
2. NER: Normalized Text -> Entity Mentions
3. Relation Extraction: Mentions -> Grounded Relation Candidates
4. Milestone 8 Integration:
   - Candidates -> Evidence objects (with exact text spans and offsets)
   - Candidates -> Claim objects (with epistemic qualifiers and UNREVIEWED status)
   - Graph Store -> Registration of unresolved entities, evidence, claims, and optional unreviewed relationships.

Core Invariants:
- Automated extraction defaults to `ReviewStatus.UNREVIEWED`. Extraction is not verification.
- Epistemic discipline: Negated claims route evidence to `contradicting_evidence_ids`.
- Allegations and temporal qualifiers are recorded in claim qualifiers and metadata.
- Missing entity resolution is preserved explicitly (`unresolved_{mention_id}`).
- Human review safeguards: Retracted, rejected, and verified claims are preserved across re-ingestion.
- Idempotent document reprocessing: Content-hash based deduplication without destructive overwrites.
"""

from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime, timezone
from pydantic import Field

from src.core.models import (
    ImmutableBaseModel,
    Evidence,
    Claim,
    Relationship,
    InvestigationEntity,
    ReviewStatus,
    EvidencePolarity,
    RelationshipEpistemicTier,
    ConfidenceSemantics,
    EntityType,
)
from src.core.investigation_graph import BaseInvestigationGraphStore, InMemoryInvestigationGraphStore
from src.core.investigation_lifecycle import InvestigationLifecycleManager
from src.core.document_ingestion import (
    DocumentIngestionService,
    IngestedDocument,
    DocumentFormat,
    IngestionConfig,
)
from src.core.ner import (
    BaseNERExtractor,
    DeterministicRuleNERExtractor,
    ModelBackedNERExtractor,
    HybridNERExtractor,
    EntityMention,
    MLModelUnavailableError,
)
from src.core.relation_extraction import (
    BaseRelationExtractor,
    DeterministicRuleRelationExtractor,
    ModelBackedRelationExtractor,
    HybridRelationExtractor,
    ExtractedRelationCandidate,
)
from src.core.mention_entity_resolution import (
    MentionEntityResolver,
    MentionResolutionResult,
)


class ExtractionPipelineResult(ImmutableBaseModel):
    """Immutable result emitted by DocumentExtractionPipeline."""
    document: IngestedDocument
    mentions: List[EntityMention]
    relation_candidates: List[ExtractedRelationCandidate]
    evidence_items: List[Evidence]
    claims: List[Claim]
    derived_relationships: List[Relationship]
    preserved_reviewed_claims: List[str] = Field(default_factory=list)
    backend_mode: str = "rule"
    mention_resolutions: List[MentionResolutionResult] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DocumentExtractionPipeline:
    """
    End-to-end pipeline orchestrating document ingestion, NER, relation extraction,
    and integration into Milestone 8 investigation stores.

    Supports configurable extraction backends:
    - 'rule': Deterministic regex rules (default).
    - 'ml': Model-backed extraction.
    - 'hybrid': Combined model + deterministic extraction.
    """

    def __init__(
        self,
        backend_mode: str = "rule",
        ingestion_service: Optional[DocumentIngestionService] = None,
        ner_extractor: Optional[BaseNERExtractor] = None,
        relation_extractor: Optional[BaseRelationExtractor] = None,
        mention_entity_resolver: Optional[MentionEntityResolver] = None,
        lifecycle_manager: Optional[InvestigationLifecycleManager] = None,
        store: Optional[BaseInvestigationGraphStore] = None,
    ):
        if backend_mode not in ("rule", "ml", "hybrid", "mock_ml"):
            raise ValueError(f"Invalid backend_mode '{backend_mode}'. Must be 'rule', 'ml', 'hybrid', or 'mock_ml'.")

        self.backend_mode = backend_mode
        self.ingestion_service = ingestion_service or DocumentIngestionService()
        self.mention_entity_resolver = mention_entity_resolver

        # NER extractor configuration
        if ner_extractor is not None:
            self.ner_extractor = ner_extractor
        elif backend_mode == "mock_ml":
            self.ner_extractor = ModelBackedNERExtractor(use_mock_backend=True)
        elif backend_mode == "ml":
            self.ner_extractor = ModelBackedNERExtractor(use_mock_backend=False)
        elif backend_mode == "hybrid":
            self.ner_extractor = HybridNERExtractor(allow_rule_fallback=True)
        else:
            self.ner_extractor = DeterministicRuleNERExtractor()

        # Relation extractor configuration
        if relation_extractor is not None:
            self.relation_extractor = relation_extractor
        elif backend_mode == "mock_ml":
            self.relation_extractor = ModelBackedRelationExtractor(use_mock_backend=True)
        elif backend_mode == "ml":
            self.relation_extractor = ModelBackedRelationExtractor(use_mock_backend=False)
        elif backend_mode == "hybrid":
            self.relation_extractor = HybridRelationExtractor(allow_rule_fallback=True)
        else:
            self.relation_extractor = DeterministicRuleRelationExtractor()

        if lifecycle_manager:
            self.lifecycle_manager = lifecycle_manager
        elif store:
            self.lifecycle_manager = InvestigationLifecycleManager(store)
        else:
            self.lifecycle_manager = InvestigationLifecycleManager(InMemoryInvestigationGraphStore())

    @property
    def store(self) -> BaseInvestigationGraphStore:
        return self.lifecycle_manager.store

    def process_document(
        self,
        raw_content: bytes,
        source_name: str,
        source_uri: Optional[str] = None,
        doc_format: Optional[DocumentFormat] = None,
        derive_graph_relationships: bool = False,
        entity_resolver: Optional[Callable[[EntityMention], Optional[str]]] = None,
    ) -> ExtractionPipelineResult:
        """
        Ingest and process a document end-to-end.
        """
        # 1. Ingestion
        document = self.ingestion_service.ingest(
            raw_content=raw_content,
            source_name=source_name,
            source_uri=source_uri,
            doc_format=doc_format,
        )

        return self.process_ingested_document(
            document=document,
            derive_graph_relationships=derive_graph_relationships,
            entity_resolver=entity_resolver,
        )

    def process_file(
        self,
        file_path: str,
        derive_graph_relationships: bool = False,
        entity_resolver: Optional[Callable[[EntityMention], Optional[str]]] = None,
    ) -> ExtractionPipelineResult:
        """
        Process a file from disk.
        """
        document = self.ingestion_service.ingest_file(file_path=file_path)
        return self.process_ingested_document(
            document=document,
            derive_graph_relationships=derive_graph_relationships,
            entity_resolver=entity_resolver,
        )

    def process_ingested_document(
        self,
        document: IngestedDocument,
        derive_graph_relationships: bool = False,
        entity_resolver: Optional[Callable[[EntityMention], Optional[str]]] = None,
        override_mentions: Optional[List[EntityMention]] = None,
        override_relation_candidates: Optional[List[ExtractedRelationCandidate]] = None,
    ) -> ExtractionPipelineResult:
        """
        Execute NER, relation extraction, and Milestone 8 adapter on an IngestedDocument.
        """
        # 2. Named Entity Recognition
        if override_mentions is not None:
            mentions = list(override_mentions)
        else:
            mentions = self.ner_extractor.extract_entities(document)

        # 3. Grounded Relation Extraction
        if override_relation_candidates is not None:
            relation_candidates = list(override_relation_candidates)
        else:
            relation_candidates = self.relation_extractor.extract_relations(document, mentions)

        # 4. Optional Entity Resolution on Extracted Mentions
        mention_resolutions: List[MentionResolutionResult] = []
        resolved_mention_map: Dict[str, str] = {}
        if self.mention_entity_resolver:
            mention_resolutions = self.mention_entity_resolver.resolve_mentions(mentions)
            for res in mention_resolutions:
                if res.is_resolved and res.resolved_entity_id:
                    resolved_mention_map[res.mention_id] = res.resolved_entity_id

        # Build mention lookup
        mention_by_id = {m.mention_id: m for m in mentions}

        # 5 & 6. Milestone 8 Adapter: Generate Evidence & Claims
        evidence_items: List[Evidence] = []
        claims: List[Claim] = []
        derived_relationships: List[Relationship] = []
        preserved_reviewed_claims: List[str] = []

        doc_hash_prefix = document.content_hash[:8]

        for cand in relation_candidates:
            # Relation Grounding Guard 1: Verify subject & object mention IDs correspond to valid extracted mentions
            m_subj = mention_by_id.get(cand.subject_mention_id)
            m_obj = mention_by_id.get(cand.object_mention_id)
            if m_subj is None or m_obj is None:
                # Abstain on ungrounded mention candidates
                continue

            # Relation Grounding Guard 2: Verify evidence offsets match exact source text
            if not (0 <= cand.evidence_start_char <= cand.evidence_end_char <= len(document.normalized_text)):
                continue
            expected_span = document.normalized_text[cand.evidence_start_char:cand.evidence_end_char]
            if cand.evidence_span != expected_span:
                continue

            # Create Evidence
            polarity = (
                EvidencePolarity.CONTRADICTING
                if cand.is_negated
                else EvidencePolarity.SUPPORTING
            )

            ev_id = f"ev_{doc_hash_prefix}_{cand.candidate_id}"
            evidence = Evidence(
                evidence_id=ev_id,
                evidence_type="DOCUMENT_TEXT_SPAN",
                polarity=polarity,
                value_description=f"{cand.predicate} between '{cand.subject_surface}' and '{cand.object_surface}'",
                content=cand.evidence_span,
                text_span=cand.evidence_span,
                char_offsets=(cand.evidence_start_char, cand.evidence_end_char),
                source_uri=document.source_uri,
                document_reference=document.document_id,
                content_hash=document.content_hash,
                extraction_method=cand.extraction_method,
                extractor_version=cand.extraction_version,
                review_status=ReviewStatus.UNREVIEWED,
                provenance=f"document:{document.document_id}:{cand.evidence_start_char}-{cand.evidence_end_char}",
                metadata={
                    "is_negated": cand.is_negated,
                    "is_allegation": cand.is_allegation,
                    "uncertainty_flag": cand.uncertainty_flag,
                    "attribution_source": cand.attribution_source,
                    "temporal_context": cand.temporal_context,
                    "backend_mode": self.backend_mode,
                },
            )

            # Ingest evidence into store
            self.lifecycle_manager.ingest_evidence(evidence)
            evidence_items.append(evidence)

            # Entity ID resolution (or explicit unresolved registration)
            subj_entity_id = self._resolve_entity_reference(
                m_subj, entity_resolver, resolved_mention_map
            )
            obj_entity_id = self._resolve_entity_reference(
                m_obj, entity_resolver, resolved_mention_map
            )

            # Create Claim
            claim_id = f"claim_{doc_hash_prefix}_{cand.candidate_id}"

            # Human Review Safeguard: Check if claim already exists in store with a reviewed status
            existing_claim = self.store.get_claim(claim_id)
            if existing_claim and existing_claim.review_status in (
                ReviewStatus.RETRACTED,
                ReviewStatus.REJECTED,
                ReviewStatus.VERIFIED,
                ReviewStatus.SUPERSEDED,
            ):
                # Do NOT overwrite human review decision!
                claims.append(existing_claim)
                preserved_reviewed_claims.append(claim_id)
                continue

            sup_ev_ids = [ev_id] if not cand.is_negated else []
            con_ev_ids = [ev_id] if cand.is_negated else []

            claim_qualifiers = {
                "is_negated": cand.is_negated,
                "is_allegation": cand.is_allegation,
                "uncertainty_flag": cand.uncertainty_flag,
            }
            if cand.attribution_source:
                claim_qualifiers["attribution_source"] = cand.attribution_source
            if cand.temporal_context:
                claim_qualifiers["temporal_context"] = cand.temporal_context
            if cand.metadata.get("requires_human_review"):
                claim_qualifiers["requires_human_review"] = True

            claim = Claim(
                claim_id=claim_id,
                subject_id=subj_entity_id,
                predicate=cand.predicate,
                object_id=obj_entity_id,
                supporting_evidence_ids=sup_ev_ids,
                contradicting_evidence_ids=con_ev_ids,
                extraction_method=cand.extraction_method,
                extractor_version=cand.extraction_version,
                confidence=cand.confidence_score,
                confidence_semantics=ConfidenceSemantics.HEURISTIC_SCORE,
                review_status=ReviewStatus.UNREVIEWED,  # Crucial: automated extraction defaults to unreviewed
                qualifiers=claim_qualifiers,
                metadata={
                    "document_id": document.document_id,
                    "candidate_id": cand.candidate_id,
                    "backend_mode": self.backend_mode,
                },
            )

            self.store.add_claim(claim)
            claims.append(claim)

            # Optional Relationship Derivation (Explicitly UNREVIEWED)
            if derive_graph_relationships and not cand.is_negated:
                try:
                    rel = self.lifecycle_manager.derive_relationship_from_claim(
                        claim_id=claim.claim_id,
                        relationship_type=claim.predicate,
                        epistemic_tier=RelationshipEpistemicTier.ASSERTED,
                    )
                    derived_relationships.append(rel)
                except Exception as ex:
                    # Relationship derivation may be deferred if entities are incomplete
                    pass

        return ExtractionPipelineResult(
            document=document,
            mentions=mentions,
            relation_candidates=relation_candidates,
            evidence_items=evidence_items,
            claims=claims,
            derived_relationships=derived_relationships,
            preserved_reviewed_claims=preserved_reviewed_claims,
            backend_mode=self.backend_mode,
            mention_resolutions=mention_resolutions,
            metadata={
                "mention_count": len(mentions),
                "relation_count": len(relation_candidates),
                "evidence_count": len(evidence_items),
                "claim_count": len(claims),
                "resolved_mention_count": len(resolved_mention_map),
                "backend_mode": self.backend_mode,
            },
        )

    def _resolve_entity_reference(
        self,
        mention: Optional[EntityMention],
        custom_resolver: Optional[Callable[[EntityMention], Optional[str]]] = None,
        resolved_mention_map: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Resolve an entity mention to an entity ID.
        Checks resolved_mention_map from MentionEntityResolver first,
        then custom_resolver, then falls back to registering an explicit
        provisional entity to preserve referential integrity.
        """
        if not mention:
            return "unresolved_unknown_entity"

        # 1. MentionEntityResolver output
        if resolved_mention_map and mention.mention_id in resolved_mention_map:
            return resolved_mention_map[mention.mention_id]

        # 2. Custom callable resolver
        if custom_resolver:
            resolved = custom_resolver(mention)
            if resolved and self.store.has_entity(resolved):
                return resolved

        # 3. Deterministic unresolved provisional entity ID
        raw_name = mention.normalized_value or mention.surface_text
        provisional_id = f"unresolved_{mention.mention_id}"

        if not self.store.has_entity(provisional_id):
            self.lifecycle_manager.register_unresolved_entity(
                mention_id=provisional_id,
                raw_name=raw_name,
                entity_type=mention.entity_type,
            )

        return provisional_id

