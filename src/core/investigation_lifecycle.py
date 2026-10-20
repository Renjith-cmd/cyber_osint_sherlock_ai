"""
Deterministic Evidence Lifecycle Engine for Sherlock AI (Milestone 8).

Implements the 9-stage investigation lifecycle:
1. Ingest source record or evidence item.
2. Normalize and validate metadata without altering the original record.
3. Extract claims using an explicitly identified extraction method.
4. Link each claim to its supporting source evidence.
5. Resolve claim participants to existing entities when justified; preserve unresolved references.
6. Create typed relationships from accepted claims without treating extraction as verification.
7. Allow claims to be reviewed, rejected, corrected, or superseded.
8. Rebuild derived graph views after corrections without deleting historical provenance.
9. Produce an investigation explanation that traces relationships back to the source evidence.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable, Any, Union
import uuid
import hashlib

from src.core.models import (
    Record,
    Source,
    Evidence,
    Claim,
    ClaimCorrection,
    Relationship,
    EntityCluster,
    InvestigationEntity,
    ReviewStatus,
    RelationshipEpistemicTier,
    ConfidenceSemantics,
    EntityType,
    EvidencePolarity,
)
from src.core.investigation_graph import (
    BaseInvestigationGraphStore,
    InvalidLifecycleTransitionError,
    VALID_CLAIM_TRANSITIONS,
)


class InvestigationLifecycleManager:
    """Orchestrates deterministic evidence lifecycle and entity-relationship derivation."""

    def __init__(self, store: BaseInvestigationGraphStore):
        self._store = store

    @property
    def store(self) -> BaseInvestigationGraphStore:
        return self._store

    def ingest_record(self, record: Record, source: Optional[Source] = None) -> Record:
        """Stage 1 & 2: Ingest and store immutable record and source."""
        self._store.add_record(record)
        return record

    def ingest_evidence(self, evidence: Evidence) -> Evidence:
        """Stage 1 & 2: Ingest and store evidence item."""
        self._store.add_evidence(evidence)
        return evidence

    def extract_claim(
        self,
        claim_id: str,
        subject_id: str,
        predicate: str,
        object_id: str,
        supporting_evidence_ids: List[str],
        contradicting_evidence_ids: Optional[List[str]] = None,
        extraction_method: str = "structured_parser",
        extractor_version: Optional[str] = "v1.0.0",
        confidence: Optional[float] = None,
        confidence_semantics: ConfidenceSemantics = ConfidenceSemantics.HEURISTIC_SCORE,
        qualifiers: Optional[Dict[str, Any]] = None,
        location: Optional[str] = None,
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Claim:
        """Stage 3 & 4: Create and store claim linked to supporting evidence."""
        # Validate that referenced evidence items exist in store
        for eid in supporting_evidence_ids:
            if not self._store.get_evidence(eid):
                raise ValueError(f"Referenced supporting evidence '{eid}' does not exist in graph store.")

        con_ids = contradicting_evidence_ids or []
        for eid in con_ids:
            if not self._store.get_evidence(eid):
                raise ValueError(f"Referenced contradicting evidence '{eid}' does not exist in graph store.")

        claim = Claim(
            claim_id=claim_id,
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            valid_from=valid_from,
            valid_to=valid_to,
            location=location,
            qualifiers=qualifiers or {},
            supporting_evidence_ids=list(supporting_evidence_ids),
            contradicting_evidence_ids=list(con_ids),
            extraction_method=extraction_method,
            extractor_version=extractor_version,
            confidence=confidence,
            confidence_semantics=confidence_semantics,
            review_status=ReviewStatus.UNREVIEWED,
            metadata=metadata or {},
        )
        self._store.add_claim(claim)
        return claim

    def register_unresolved_entity(
        self,
        mention_id: str,
        raw_name: str,
        entity_type: EntityType = EntityType.ORGANIZATION,
    ) -> InvestigationEntity:
        """Register an unresolved participant reference as a provisional entity."""
        ent = InvestigationEntity(
            entity_id=mention_id,
            entity_type=entity_type,
            canonical_name=raw_name,
            member_record_ids=[],
            metadata={"provisional": True, "unresolved": True},
        )
        return self._store.add_entity(ent)

    def derive_relationship_from_claim(
        self,
        claim_id: str,
        relationship_id: Optional[str] = None,
        relationship_type: Optional[str] = None,
        epistemic_tier: RelationshipEpistemicTier = RelationshipEpistemicTier.ASSERTED,
        cluster_resolver: Optional[Callable[[str], str]] = None,
    ) -> Relationship:
        """
        Stage 5 & 6: Create typed relationship from claim.
        Resolves subject/object references via cluster_resolver if provided.
        Does not treat extraction as established truth.
        """
        claim = self._store.get_claim(claim_id)
        if not claim:
            raise KeyError(f"Claim with ID '{claim_id}' not found.")

        # Resolve subject and object to entities
        src_id = cluster_resolver(claim.subject_id) if cluster_resolver else claim.subject_id
        tgt_id = cluster_resolver(claim.object_id) if cluster_resolver else claim.object_id

        # Verify entities exist in graph store
        if not self._store.has_entity(src_id):
            raise ValueError(
                f"Cannot derive relationship: subject '{src_id}' is not a registered entity in graph."
            )
        if not self._store.has_entity(tgt_id):
            raise ValueError(
                f"Cannot derive relationship: object '{tgt_id}' is not a registered entity in graph."
            )

        rel_type = relationship_type or claim.predicate
        target_rel_id = relationship_id or f"rel_{claim.subject_id}_{rel_type}_{claim.object_id}"

        # Determine polarity and attribution from claim qualifiers and supporting evidence
        def _is_ev_negative(eid: str) -> bool:
            ev = self._store.get_evidence(eid)
            if not ev:
                return False
            if ev.polarity == EvidencePolarity.CONTRADICTING:
                return True
            return str(ev.polarity).strip().upper() in ("NEGATIVE", "CONTRADICTING", "DENIAL", "REFUTING")

        is_negated = (
            claim.qualifiers.get("negated") is True
            or claim.qualifiers.get("polarity") in ("NEGATIVE", "CONTRADICTING", "DENIAL")
            or any(_is_ev_negative(eid) for eid in claim.supporting_evidence_ids)
        )

        is_uncertain = claim.qualifiers.get("uncertainty_flag") is True
        claim_polarity = "NEGATIVE" if is_negated else ("UNCERTAIN" if is_uncertain else "POSITIVE")
        attribution = claim.qualifiers.get("attribution") or claim.qualifiers.get("quoted_speaker") or claim.qualifiers.get("source_attribution")

        # Determine epistemic tier if default was passed
        resolved_tier = epistemic_tier
        if resolved_tier == RelationshipEpistemicTier.ASSERTED:
            if claim.review_status == ReviewStatus.VERIFIED:
                resolved_tier = RelationshipEpistemicTier.HUMAN_VERIFIED
            elif is_negated:
                resolved_tier = RelationshipEpistemicTier.DENIED
            elif claim.qualifiers.get("is_allegation") or attribution is not None:
                resolved_tier = RelationshipEpistemicTier.QUOTED
            elif any(k in (claim.extraction_method or "").lower() for k in ("model", "transformer", "inferred", "ml")):
                resolved_tier = RelationshipEpistemicTier.INFERRED
            else:
                resolved_tier = RelationshipEpistemicTier.ASSERTED

        # Compute content hashes of supporting evidence to detect duplicates and prevent artificial inflation
        claim_evidence_hashes: List[str] = []
        for eid in claim.supporting_evidence_ids:
            ev = self._store.get_evidence(eid)
            if ev:
                raw_span = ev.text_span or getattr(ev, "content", None) or ev.evidence_id
                h = ev.content_hash or hashlib.sha256(str(raw_span).encode("utf-8")).hexdigest()
                claim_evidence_hashes.append(h)

        existing_rel = self._store.get_relationship(target_rel_id)
        if existing_rel:
            # Multi-evidence support: Merge claim into existing relationship
            # Check for polarity conflict: e.g. Positive assertion vs Negative denial
            has_polarity_conflict = (
                (existing_rel.polarity == "POSITIVE" and claim_polarity == "NEGATIVE")
                or (existing_rel.polarity == "NEGATIVE" and claim_polarity == "POSITIVE")
            )

            # Duplicate evidence tracking without artificial corroboration inflation
            existing_hashes = set(existing_rel.unique_source_hashes)
            dup_ev_count = existing_rel.duplicate_evidence_count
            new_hashes = list(existing_rel.unique_source_hashes)
            for h in claim_evidence_hashes:
                if h in existing_hashes:
                    dup_ev_count += 1
                else:
                    existing_hashes.add(h)
                    new_hashes.append(h)

            if has_polarity_conflict:
                # Contradiction between different sources / extractions -> mark as DISPUTED
                sup_claims = list(existing_rel.supporting_claim_ids)
                con_claims = list(set(list(existing_rel.contradicting_claim_ids) + [claim_id]))
                con_ev = list(set(list(existing_rel.contradicting_evidence_ids) + list(claim.supporting_evidence_ids)))
                sup_ev = list(existing_rel.supporting_evidence_ids)
                tier = RelationshipEpistemicTier.DISPUTED
                status = ReviewStatus.DISPUTED
            else:
                sup_claims = list(set(list(existing_rel.supporting_claim_ids) + [claim_id]))
                con_claims = list(existing_rel.contradicting_claim_ids)
                sup_ev = list(set(list(existing_rel.supporting_evidence_ids) + list(claim.supporting_evidence_ids)))
                con_ev = list(existing_rel.contradicting_evidence_ids)
                tier = resolved_tier if existing_rel.epistemic_tier == RelationshipEpistemicTier.ASSERTED else existing_rel.epistemic_tier
                status = existing_rel.review_status

            updated_rel = Relationship(
                relationship_id=existing_rel.relationship_id,
                source_entity_id=existing_rel.source_entity_id,
                target_entity_id=existing_rel.target_entity_id,
                relationship_type=existing_rel.relationship_type,
                is_directed=existing_rel.is_directed,
                epistemic_tier=tier,
                supporting_claim_ids=sorted(sup_claims),
                supporting_evidence_ids=sorted(sup_ev),
                contradicting_claim_ids=sorted(con_claims),
                contradicting_evidence_ids=sorted(con_ev),
                valid_from=existing_rel.valid_from or claim.valid_from,
                valid_to=existing_rel.valid_to or claim.valid_to,
                provenance=existing_rel.provenance,
                review_status=status,
                confidence=existing_rel.confidence,
                confidence_semantics=existing_rel.confidence_semantics,
                polarity=existing_rel.polarity if not has_polarity_conflict else "DISPUTED",
                attribution=existing_rel.attribution or attribution,
                unique_source_hashes=sorted(new_hashes),
                duplicate_evidence_count=dup_ev_count,
                created_at=existing_rel.created_at,
                updated_at=datetime.now(timezone.utc),
                metadata=dict(existing_rel.metadata),
            )
            self._store.add_relationship(updated_rel)
            return updated_rel

        # Create new relationship
        new_rel = Relationship(
            relationship_id=target_rel_id,
            source_entity_id=src_id,
            target_entity_id=tgt_id,
            relationship_type=rel_type,
            is_directed=True,
            epistemic_tier=resolved_tier,
            supporting_claim_ids=[claim_id],
            supporting_evidence_ids=list(claim.supporting_evidence_ids),
            contradicting_claim_ids=[],
            contradicting_evidence_ids=list(claim.contradicting_evidence_ids),
            valid_from=claim.valid_from,
            valid_to=claim.valid_to,
            provenance=f"derived_from_claim:{claim_id}",
            review_status=claim.review_status,
            confidence=claim.confidence,
            confidence_semantics=claim.confidence_semantics,
            polarity=claim_polarity,
            attribution=attribution,
            unique_source_hashes=sorted(list(set(claim_evidence_hashes))),
            duplicate_evidence_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            metadata={"extraction_method": claim.extraction_method},
        )
        self._store.add_relationship(new_rel)
        return new_rel

    def record_contradiction(
        self,
        relationship_id: str,
        contradicting_claim_id: str,
    ) -> Relationship:
        """
        Record a contradictory claim against a relationship.
        Preserves both sides without overwriting or silently deleting either.
        """
        rel = self._store.get_relationship(relationship_id)
        if not rel:
            raise KeyError(f"Relationship with ID '{relationship_id}' not found.")

        cclaim = self._store.get_claim(contradicting_claim_id)
        if not cclaim:
            raise KeyError(f"Claim with ID '{contradicting_claim_id}' not found.")

        con_claims = list(set(list(rel.contradicting_claim_ids) + [contradicting_claim_id]))
        con_ev = list(set(list(rel.contradicting_evidence_ids) + list(cclaim.supporting_evidence_ids)))

        tier = (
            RelationshipEpistemicTier.HUMAN_VERIFIED
            if rel.review_status == ReviewStatus.VERIFIED
            else RelationshipEpistemicTier.DISPUTED
        )
        disputed_rel = Relationship(
            relationship_id=rel.relationship_id,
            source_entity_id=rel.source_entity_id,
            target_entity_id=rel.target_entity_id,
            relationship_type=rel.relationship_type,
            is_directed=rel.is_directed,
            epistemic_tier=tier,
            supporting_claim_ids=list(rel.supporting_claim_ids),
            supporting_evidence_ids=list(rel.supporting_evidence_ids),
            contradicting_claim_ids=sorted(con_claims),
            contradicting_evidence_ids=sorted(con_ev),
            valid_from=rel.valid_from,
            valid_to=rel.valid_to,
            provenance=rel.provenance,
            review_status=ReviewStatus.DISPUTED,
            confidence=rel.confidence,
            confidence_semantics=rel.confidence_semantics,
            polarity="DISPUTED",
            attribution=rel.attribution,
            unique_source_hashes=list(rel.unique_source_hashes),
            duplicate_evidence_count=rel.duplicate_evidence_count,
            created_at=rel.created_at,
            updated_at=datetime.now(timezone.utc),
            metadata=dict(rel.metadata),
        )
        self._store.add_relationship(disputed_rel)
        return disputed_rel

    def review_claim(
        self,
        claim_id: str,
        new_status: ReviewStatus,
        rationale: str,
        reviewer: str,
        replacement_claim_id: Optional[str] = None,
    ) -> Claim:
        """Stage 7: Review, reject, dispute, supersede, or retract a claim."""
        return self._store.update_claim_status(
            claim_id=claim_id,
            new_status=new_status,
            rationale=rationale,
            corrected_by=reviewer,
            replacement_claim_id=replacement_claim_id,
        )

    def recluster_and_rebuild(
        self,
        clusters: List[EntityCluster],
        record_to_cluster_map: Dict[str, str],
    ) -> None:
        """
        Stage 8: Rebuild derived graph views after entity resolution re-clustering.
        Leaves raw records and historical claims intact while updating relationship endpoints.
        """
        self._store.rebuild_derived_graph(clusters, record_to_cluster_map)
