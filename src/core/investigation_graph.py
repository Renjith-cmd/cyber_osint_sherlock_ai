"""
Investigation Graph Abstraction and Storage Layer for Sherlock AI (Milestone 8).

Provides:
1. Backend-independent interface: `BaseInvestigationGraphStore`
2. Deterministic, fully-featured in-memory implementation: `InMemoryInvestigationGraphStore`
3. Optional Neo4j adapter bridge: `Neo4jInvestigationGraphAdapter`

Enforces core invariants:
- Strict separation between raw records, resolved entities, evidence, claims, and relationships.
- Prevention of dangling references (entities must exist prior to relationship registration).
- Immutable domain models and reversible derivation.
- Cycle protection and deterministic graph traversal.
- Complete provenance tracing from relationships down to source evidence.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple, Any, Union
import uuid

from src.core.models import (
    Record,
    EntityCluster,
    InvestigationEntity,
    Evidence,
    Claim,
    ClaimCorrection,
    Relationship,
    ReviewStatus,
    RelationshipEpistemicTier,
    ConfidenceSemantics,
    EntityType,
)


class InvalidLifecycleTransitionError(ValueError):
    """Raised when an illegal status transition is attempted on an investigation claim."""
    pass


VALID_CLAIM_TRANSITIONS: Dict[ReviewStatus, Set[ReviewStatus]] = {
    ReviewStatus.UNREVIEWED: {
        ReviewStatus.VERIFIED,
        ReviewStatus.DISPUTED,
        ReviewStatus.REJECTED,
        ReviewStatus.RETRACTED,
        ReviewStatus.SUPERSEDED,
    },
    ReviewStatus.VERIFIED: {
        ReviewStatus.DISPUTED,
        ReviewStatus.RETRACTED,
        ReviewStatus.SUPERSEDED,
    },
    ReviewStatus.DISPUTED: {
        ReviewStatus.VERIFIED,
        ReviewStatus.REJECTED,
        ReviewStatus.RETRACTED,
        ReviewStatus.SUPERSEDED,
    },
    ReviewStatus.REJECTED: {
        ReviewStatus.DISPUTED,
        ReviewStatus.UNREVIEWED,  # Reopened for review with explicit rationale
    },
    ReviewStatus.RETRACTED: {
        # Explicit reinstatement transitions (requires justification rationale)
        ReviewStatus.VERIFIED,
        ReviewStatus.UNREVIEWED,
        ReviewStatus.DISPUTED,
    },
    ReviewStatus.SUPERSEDED: set(),  # Permanently terminal
}


class BaseInvestigationGraphStore(ABC):
    """Abstract interface for investigation graph persistence and retrieval."""

    # Entity operations
    @abstractmethod
    def add_entity(self, entity: Union[InvestigationEntity, EntityCluster]) -> InvestigationEntity:
        """Register an entity or entity cluster."""
        pass

    @abstractmethod
    def get_entity(self, entity_id: str) -> Optional[InvestigationEntity]:
        """Retrieve an entity by ID."""
        pass

    @abstractmethod
    def has_entity(self, entity_id: str) -> bool:
        """Check if entity exists in store."""
        pass

    @abstractmethod
    def list_entities(self) -> List[InvestigationEntity]:
        """List all registered entities."""
        pass

    @abstractmethod
    def remove_entity(self, entity_id: str, cascade_relationships: bool = False) -> bool:
        """Remove an entity by ID from graph store."""
        pass

    # Record operations
    @abstractmethod
    def add_record(self, record: Record) -> None:
        """Store an observed source record."""
        pass

    @abstractmethod
    def get_record(self, record_id: str) -> Optional[Record]:
        """Retrieve a record by ID."""
        pass

    @abstractmethod
    def list_records(self) -> List[Record]:
        """List all stored records."""
        pass

    # Evidence operations
    @abstractmethod
    def add_evidence(self, evidence: Evidence) -> None:
        """Store an evidence item."""
        pass

    @abstractmethod
    def get_evidence(self, evidence_id: str) -> Optional[Evidence]:
        """Retrieve an evidence item by ID."""
        pass

    @abstractmethod
    def list_evidence(self) -> List[Evidence]:
        """List all stored evidence items."""
        pass

    # Claim operations
    @abstractmethod
    def add_claim(self, claim: Claim) -> None:
        """Store an extracted or asserted claim."""
        pass

    @abstractmethod
    def get_claim(self, claim_id: str) -> Optional[Claim]:
        """Retrieve a claim by ID."""
        pass

    @abstractmethod
    def list_claims(self) -> List[Claim]:
        """List all stored claims."""
        pass

    @abstractmethod
    def update_claim_status(
        self,
        claim_id: str,
        new_status: ReviewStatus,
        rationale: str,
        corrected_by: str,
        replacement_claim_id: Optional[str] = None,
    ) -> Claim:
        """Apply a correction/review decision to a claim while preserving audit history."""
        pass

    # Relationship operations
    @abstractmethod
    def add_relationship(self, relationship: Relationship) -> None:
        """Add a typed relationship between entities."""
        pass

    @abstractmethod
    def get_relationship(self, relationship_id: str) -> Optional[Relationship]:
        """Retrieve a relationship by ID."""
        pass

    @abstractmethod
    def list_relationships(self) -> List[Relationship]:
        """List all relationships."""
        pass

    @abstractmethod
    def get_entity_relationships(
        self, entity_id: str, direction: str = "both"
    ) -> List[Relationship]:
        """Retrieve relationships connected to an entity ('out', 'in', or 'both')."""
        pass

    @abstractmethod
    def remove_relationship(self, relationship_id: str) -> bool:
        """Remove a relationship by ID from graph store."""
        pass

    # Provenance & Traversal
    @abstractmethod
    def get_claim_evidence(self, claim_id: str) -> Dict[str, List[Evidence]]:
        """Retrieve supporting and contradicting evidence for a claim."""
        pass

    @abstractmethod
    def get_relationship_evidence(self, relationship_id: str) -> Dict[str, List[Evidence]]:
        """Retrieve all evidence supporting or contradicting a relationship."""
        pass

    @abstractmethod
    def traverse_bounded_path(
        self, start_entity_id: str, max_depth: int = 2, max_nodes: int = 50
    ) -> Dict[str, Any]:
        """Perform a cycle-safe, bounded traversal from a root entity."""
        pass

    @abstractmethod
    def rebuild_derived_graph(
        self,
        clusters: List[EntityCluster],
        record_to_cluster_map: Dict[str, str],
    ) -> None:
        """Recompute derived relationship endpoints after entity resolution re-clustering."""
        pass


class InMemoryInvestigationGraphStore(BaseInvestigationGraphStore):
    """
    Deterministic, in-memory reference implementation for testing and local analysis.
    Requires no external database infrastructure.
    """

    def __init__(self):
        self._entities: Dict[str, InvestigationEntity] = {}
        self._records: Dict[str, Record] = {}
        self._evidence: Dict[str, Evidence] = {}
        self._claims: Dict[str, Claim] = {}
        self._relationships: Dict[str, Relationship] = {}

        # Indexes for fast deterministic lookup
        self._adj_out: Dict[str, List[str]] = {}  # entity_id -> [rel_id, ...]
        self._adj_in: Dict[str, List[str]] = {}   # entity_id -> [rel_id, ...]
        self._record_to_entity: Dict[str, str] = {}  # record_id -> entity_id

    # --- Entity Methods ---

    def add_entity(self, entity: Union[InvestigationEntity, EntityCluster]) -> InvestigationEntity:
        if isinstance(entity, EntityCluster):
            # Derive canonical name from member records if present
            canonical_name = entity.entity_cluster_id
            for rec_id in entity.member_record_ids:
                if rec_id in self._records:
                    canonical_name = self._records[rec_id].raw_name
                    break
            inv_entity = InvestigationEntity(
                entity_id=entity.entity_cluster_id,
                entity_type=entity.entity_type,
                canonical_name=canonical_name,
                member_record_ids=list(entity.member_record_ids),
                cluster_id=entity.entity_cluster_id,
                metadata={"status": entity.status.value, "version": entity.derivation_version},
            )
        elif isinstance(entity, InvestigationEntity):
            inv_entity = entity
        else:
            raise TypeError(f"Unsupported entity type: {type(entity)}")

        self._entities[inv_entity.entity_id] = inv_entity
        for rec_id in inv_entity.member_record_ids:
            self._record_to_entity[rec_id] = inv_entity.entity_id

        if inv_entity.entity_id not in self._adj_out:
            self._adj_out[inv_entity.entity_id] = []
        if inv_entity.entity_id not in self._adj_in:
            self._adj_in[inv_entity.entity_id] = []

        return inv_entity

    def get_entity(self, entity_id: str) -> Optional[InvestigationEntity]:
        return self._entities.get(entity_id)

    def has_entity(self, entity_id: str) -> bool:
        return entity_id in self._entities

    def list_entities(self) -> List[InvestigationEntity]:
        return [self._entities[k] for k in sorted(self._entities.keys())]

    def remove_entity(self, entity_id: str, cascade_relationships: bool = False) -> bool:
        """
        Remove an entity by ID from store.
        If cascade_relationships is True, removes connected relationships.
        Otherwise, raises ValueError if connected relationships exist to protect referential integrity.
        """
        if entity_id not in self._entities:
            return False

        connected_rels = self.get_entity_relationships(entity_id, direction="both")
        if connected_rels:
            if cascade_relationships:
                for rel in connected_rels:
                    self.remove_relationship(rel.relationship_id)
            else:
                raise ValueError(
                    f"Cannot remove entity '{entity_id}': entity has {len(connected_rels)} connected relationship(s). "
                    "Remove or re-link relationships first, or set cascade_relationships=True."
                )

        ent = self._entities.pop(entity_id)
        for rec_id in ent.member_record_ids:
            if self._record_to_entity.get(rec_id) == entity_id:
                self._record_to_entity.pop(rec_id, None)

        self._adj_out.pop(entity_id, None)
        self._adj_in.pop(entity_id, None)
        return True

    # --- Record Methods ---

    def add_record(self, record: Record) -> None:
        self._records[record.record_id] = record

    def get_record(self, record_id: str) -> Optional[Record]:
        return self._records.get(record_id)

    def list_records(self) -> List[Record]:
        return [self._records[k] for k in sorted(self._records.keys())]

    # --- Evidence Methods ---

    def add_evidence(self, evidence: Evidence) -> None:
        self._evidence[evidence.evidence_id] = evidence

    def get_evidence(self, evidence_id: str) -> Optional[Evidence]:
        return self._evidence.get(evidence_id)

    def list_evidence(self) -> List[Evidence]:
        return [self._evidence[k] for k in sorted(self._evidence.keys())]

    # --- Claim Methods ---

    def add_claim(self, claim: Claim) -> None:
        # Enforce referential integrity: evidence references must exist
        for eid in claim.supporting_evidence_ids:
            if eid not in self._evidence:
                raise ValueError(
                    f"Dangling evidence reference: supporting evidence '{eid}' does not exist in graph store."
                )
        for eid in claim.contradicting_evidence_ids:
            if eid not in self._evidence:
                raise ValueError(
                    f"Dangling evidence reference: contradicting evidence '{eid}' does not exist in graph store."
                )

        # Enforce referential integrity: subject and object entities / records
        is_unresolved_subj = (
            claim.metadata.get("unresolved_subject") is True
            or (claim.subject_id in self._entities and self._entities[claim.subject_id].metadata.get("unresolved") is True)
        )
        if not is_unresolved_subj and claim.subject_id not in self._entities and claim.subject_id not in self._records:
            raise ValueError(
                f"Dangling entity reference: claim subject '{claim.subject_id}' does not exist in graph store "
                "as an entity or record, and is not represented as an explicit unresolved reference."
            )

        is_unresolved_obj = (
            claim.metadata.get("unresolved_object") is True
            or (claim.object_id in self._entities and self._entities[claim.object_id].metadata.get("unresolved") is True)
        )
        if not is_unresolved_obj and claim.object_id not in self._entities and claim.object_id not in self._records:
            raise ValueError(
                f"Dangling entity reference: claim object '{claim.object_id}' does not exist in graph store "
                "as an entity or record, and is not represented as an explicit unresolved reference."
            )

        # Human decision & terminal review preservation:
        # Automated extraction re-ingestion must not silently undo or overwrite human review decisions.
        existing = self._claims.get(claim.claim_id)
        if existing and existing.review_status in (
            ReviewStatus.VERIFIED,
            ReviewStatus.RETRACTED,
            ReviewStatus.REJECTED,
            ReviewStatus.SUPERSEDED,
            ReviewStatus.DISPUTED,
        ):
            if claim.review_status == ReviewStatus.UNREVIEWED:
                # Merge newly extracted evidence while preserving human verdict and audit trail
                merged_supporting = list(dict.fromkeys(existing.supporting_evidence_ids + claim.supporting_evidence_ids))
                merged_contradicting = list(dict.fromkeys(existing.contradicting_evidence_ids + claim.contradicting_evidence_ids))

                preserved_claim = Claim(
                    claim_id=existing.claim_id,
                    subject_id=claim.subject_id or existing.subject_id,
                    predicate=claim.predicate or existing.predicate,
                    object_id=claim.object_id or existing.object_id,
                    valid_from=existing.valid_from,
                    valid_to=existing.valid_to,
                    location=existing.location,
                    qualifiers=existing.qualifiers or claim.qualifiers,
                    supporting_evidence_ids=merged_supporting,
                    contradicting_evidence_ids=merged_contradicting,
                    extraction_method=claim.extraction_method or existing.extraction_method,
                    extractor_version=claim.extractor_version or existing.extractor_version,
                    confidence=claim.confidence if claim.confidence is not None else existing.confidence,
                    confidence_semantics=claim.confidence_semantics or existing.confidence_semantics,
                    review_status=existing.review_status,  # Preserved human review decision
                    superseded_by_claim_id=existing.superseded_by_claim_id,
                    retraction_reason=existing.retraction_reason,
                    correction_history=list(existing.correction_history),
                    created_at=existing.created_at,
                    updated_at=datetime.now(timezone.utc),
                    metadata={**existing.metadata, **claim.metadata, "reingested_at": datetime.now(timezone.utc).isoformat()},
                )
                self._claims[claim.claim_id] = preserved_claim
                return

        self._claims[claim.claim_id] = claim

    def get_claim(self, claim_id: str) -> Optional[Claim]:
        return self._claims.get(claim_id)

    def list_claims(self) -> List[Claim]:
        return [self._claims[k] for k in sorted(self._claims.keys())]

    def update_claim_status(
        self,
        claim_id: str,
        new_status: ReviewStatus,
        rationale: str,
        corrected_by: str,
        replacement_claim_id: Optional[str] = None,
    ) -> Claim:
        if claim_id not in self._claims:
            raise KeyError(f"Claim with ID '{claim_id}' not found.")

        current_claim = self._claims[claim_id]

        if not corrected_by or not corrected_by.strip():
            raise ValueError("Reviewer identity cannot be empty.")

        # Validate lifecycle transition matrix
        if new_status != current_claim.review_status:
            allowed = VALID_CLAIM_TRANSITIONS.get(current_claim.review_status, set())
            if new_status not in allowed:
                raise InvalidLifecycleTransitionError(
                    f"Illegal lifecycle transition: cannot transition claim '{claim_id}' "
                    f"from '{current_claim.review_status.value}' to '{new_status.value}'."
                )

        if new_status == ReviewStatus.RETRACTED:
            if not rationale or len(rationale.strip()) < 5:
                raise ValueError("Retraction requires an explicit audit rationale justifying the decision (minimum 5 chars).")

        if current_claim.review_status == ReviewStatus.RETRACTED and new_status != ReviewStatus.RETRACTED:
            if not rationale or len(rationale.strip()) < 5:
                raise ValueError("Reinstating a retracted claim requires an explicit audit rationale justifying why the retraction is reversed.")

        if new_status == ReviewStatus.SUPERSEDED and not replacement_claim_id:
            raise ValueError("Superseding a claim requires a valid replacement_claim_id.")

        corr = ClaimCorrection(
            correction_id=f"corr_{uuid.uuid4().hex[:8]}",
            corrected_at=datetime.now(timezone.utc),
            corrected_by=corrected_by.strip(),
            previous_status=current_claim.review_status,
            new_status=new_status,
            rationale=rationale.strip(),
            previous_claim_id=claim_id,
            replacement_claim_id=replacement_claim_id,
        )

        history = list(current_claim.correction_history) + [corr]
        updated_claim = Claim(
            claim_id=current_claim.claim_id,
            subject_id=current_claim.subject_id,
            predicate=current_claim.predicate,
            object_id=current_claim.object_id,
            valid_from=current_claim.valid_from,
            valid_to=current_claim.valid_to,
            location=current_claim.location,
            qualifiers=dict(current_claim.qualifiers),
            supporting_evidence_ids=list(current_claim.supporting_evidence_ids),
            contradicting_evidence_ids=list(current_claim.contradicting_evidence_ids),
            extraction_method=current_claim.extraction_method,
            extractor_version=current_claim.extractor_version,
            confidence=current_claim.confidence,
            confidence_semantics=current_claim.confidence_semantics,
            review_status=new_status,
            superseded_by_claim_id=replacement_claim_id or current_claim.superseded_by_claim_id,
            retraction_reason=rationale if new_status == ReviewStatus.RETRACTED else (
                f"Reinstated: {rationale}" if current_claim.review_status == ReviewStatus.RETRACTED else current_claim.retraction_reason
            ),
            correction_history=history,
            created_at=current_claim.created_at,
            updated_at=datetime.now(timezone.utc),
            metadata=dict(current_claim.metadata),
        )

        self._claims[claim_id] = updated_claim

        # Cascade review impact to dependent relationships
        self._sync_relationship_statuses_for_claim(claim_id, updated_claim)

        return updated_claim

    def _sync_relationship_statuses_for_claim(self, claim_id: str, updated_claim: Claim) -> None:
        """Update any relationship whose status depends on this modified claim."""
        for rel_id, rel in list(self._relationships.items()):
            if claim_id in rel.supporting_claim_ids or claim_id in rel.contradicting_claim_ids:
                # Re-evaluate relationship review status based on its supporting claims
                supporting_claims = [self._claims[cid] for cid in rel.supporting_claim_ids if cid in self._claims]
                active_supporting = [
                    c for c in supporting_claims
                    if c.review_status not in (ReviewStatus.REJECTED, ReviewStatus.RETRACTED, ReviewStatus.SUPERSEDED)
                ]

                new_rel_status = rel.review_status
                if not active_supporting:
                    if any(c.review_status == ReviewStatus.RETRACTED for c in supporting_claims):
                        new_rel_status = ReviewStatus.RETRACTED
                    elif any(c.review_status == ReviewStatus.REJECTED for c in supporting_claims):
                        new_rel_status = ReviewStatus.REJECTED
                    elif any(c.review_status == ReviewStatus.SUPERSEDED for c in supporting_claims):
                        new_rel_status = ReviewStatus.SUPERSEDED
                elif any(c.review_status == ReviewStatus.DISPUTED for c in supporting_claims) or len(rel.contradicting_claim_ids) > 0:
                    new_rel_status = ReviewStatus.DISPUTED
                elif all(c.review_status == ReviewStatus.VERIFIED for c in active_supporting):
                    new_rel_status = ReviewStatus.VERIFIED

                if new_rel_status != rel.review_status:
                    updated_rel = Relationship(
                        relationship_id=rel.relationship_id,
                        source_entity_id=rel.source_entity_id,
                        target_entity_id=rel.target_entity_id,
                        relationship_type=rel.relationship_type,
                        is_directed=rel.is_directed,
                        epistemic_tier=rel.epistemic_tier,
                        supporting_claim_ids=list(rel.supporting_claim_ids),
                        supporting_evidence_ids=list(rel.supporting_evidence_ids),
                        contradicting_claim_ids=list(rel.contradicting_claim_ids),
                        contradicting_evidence_ids=list(rel.contradicting_evidence_ids),
                        valid_from=rel.valid_from,
                        valid_to=rel.valid_to,
                        provenance=rel.provenance,
                        review_status=new_rel_status,
                        confidence=rel.confidence,
                        confidence_semantics=rel.confidence_semantics,
                        created_at=rel.created_at,
                        updated_at=datetime.now(timezone.utc),
                        metadata=dict(rel.metadata),
                    )
                    self._relationships[rel_id] = updated_rel

    # --- Relationship Methods ---

    def add_relationship(self, relationship: Relationship) -> None:
        # Enforce referential integrity: Prevent dangling entity references
        if relationship.source_entity_id not in self._entities:
            raise ValueError(
                f"Dangling entity reference: source entity '{relationship.source_entity_id}' "
                "does not exist in graph store."
            )
        if relationship.target_entity_id not in self._entities:
            raise ValueError(
                f"Dangling entity reference: target entity '{relationship.target_entity_id}' "
                "does not exist in graph store."
            )

        # Enforce referential integrity: Prevent dangling claim references
        for cid in relationship.supporting_claim_ids:
            if cid not in self._claims:
                raise ValueError(
                    f"Dangling claim reference: supporting claim '{cid}' does not exist in graph store."
                )
        for cid in relationship.contradicting_claim_ids:
            if cid not in self._claims:
                raise ValueError(
                    f"Dangling claim reference: contradicting claim '{cid}' does not exist in graph store."
                )

        # Enforce referential integrity: Prevent dangling evidence references
        for eid in relationship.supporting_evidence_ids:
            if eid not in self._evidence:
                raise ValueError(
                    f"Dangling evidence reference: supporting evidence '{eid}' does not exist in graph store."
                )
        for eid in relationship.contradicting_evidence_ids:
            if eid not in self._evidence:
                raise ValueError(
                    f"Dangling evidence reference: contradicting evidence '{eid}' does not exist in graph store."
                )

        # Retraction preservation: if existing relationship was RETRACTED, do not resurrect merely by re-deriving
        existing = self._relationships.get(relationship.relationship_id)
        if existing and existing.review_status in (ReviewStatus.RETRACTED, ReviewStatus.REJECTED, ReviewStatus.SUPERSEDED):
            if relationship.review_status == ReviewStatus.UNREVIEWED:
                relationship = Relationship(
                    relationship_id=relationship.relationship_id,
                    source_entity_id=relationship.source_entity_id,
                    target_entity_id=relationship.target_entity_id,
                    relationship_type=relationship.relationship_type,
                    is_directed=relationship.is_directed,
                    epistemic_tier=relationship.epistemic_tier,
                    supporting_claim_ids=list(relationship.supporting_claim_ids),
                    supporting_evidence_ids=list(relationship.supporting_evidence_ids),
                    contradicting_claim_ids=list(relationship.contradicting_claim_ids),
                    contradicting_evidence_ids=list(relationship.contradicting_evidence_ids),
                    valid_from=relationship.valid_from,
                    valid_to=relationship.valid_to,
                    provenance=relationship.provenance,
                    review_status=existing.review_status,
                    confidence=relationship.confidence,
                    confidence_semantics=relationship.confidence_semantics,
                    created_at=existing.created_at,
                    updated_at=datetime.now(timezone.utc),
                    metadata=dict(relationship.metadata),
                )

        self._relationships[relationship.relationship_id] = relationship

        # Update adjacency lists
        src = relationship.source_entity_id
        tgt = relationship.target_entity_id

        if src not in self._adj_out:
            self._adj_out[src] = []
        if relationship.relationship_id not in self._adj_out[src]:
            self._adj_out[src].append(relationship.relationship_id)

        if tgt not in self._adj_in:
            self._adj_in[tgt] = []
        if relationship.relationship_id not in self._adj_in[tgt]:
            self._adj_in[tgt].append(relationship.relationship_id)

    def remove_relationship(self, relationship_id: str) -> bool:
        """Remove a relationship by ID and clean up adjacency indices."""
        if relationship_id not in self._relationships:
            return False
        rel = self._relationships.pop(relationship_id)
        if rel.source_entity_id in self._adj_out and relationship_id in self._adj_out[rel.source_entity_id]:
            self._adj_out[rel.source_entity_id].remove(relationship_id)
        if rel.target_entity_id in self._adj_in and relationship_id in self._adj_in[rel.target_entity_id]:
            self._adj_in[rel.target_entity_id].remove(relationship_id)
        return True

    def get_relationship(self, relationship_id: str) -> Optional[Relationship]:
        return self._relationships.get(relationship_id)

    def list_relationships(self) -> List[Relationship]:
        return [self._relationships[k] for k in sorted(self._relationships.keys())]

    def get_entity_relationships(
        self, entity_id: str, direction: str = "both"
    ) -> List[Relationship]:
        if entity_id not in self._entities:
            return []

        rel_ids: List[str] = []
        if direction in ("out", "both"):
            rel_ids.extend(self._adj_out.get(entity_id, []))
        if direction in ("in", "both"):
            rel_ids.extend(self._adj_in.get(entity_id, []))

        # Deterministic sorting by relationship ID, deduplicating self-loops
        unique_rel_ids = sorted(set(rel_ids))
        return [self._relationships[rid] for rid in unique_rel_ids if rid in self._relationships]

    # --- Provenance Queries ---

    def get_claim_evidence(self, claim_id: str) -> Dict[str, List[Evidence]]:
        claim = self._claims.get(claim_id)
        if not claim:
            return {"supporting": [], "contradicting": []}

        sup = [self._evidence[eid] for eid in claim.supporting_evidence_ids if eid in self._evidence]
        con = [self._evidence[eid] for eid in claim.contradicting_evidence_ids if eid in self._evidence]
        return {
            "supporting": sorted(sup, key=lambda e: e.evidence_id),
            "contradicting": sorted(con, key=lambda e: e.evidence_id),
        }

    def get_relationship_evidence(self, relationship_id: str) -> Dict[str, List[Evidence]]:
        rel = self._relationships.get(relationship_id)
        if not rel:
            return {"supporting": [], "contradicting": []}

        sup_eids = set(rel.supporting_evidence_ids)
        con_eids = set(rel.contradicting_evidence_ids)

        # Also aggregate evidence from supporting claims
        for cid in rel.supporting_claim_ids:
            if cid in self._claims:
                sup_eids.update(self._claims[cid].supporting_evidence_ids)
                con_eids.update(self._claims[cid].contradicting_evidence_ids)

        for cid in rel.contradicting_claim_ids:
            if cid in self._claims:
                con_eids.update(self._claims[cid].supporting_evidence_ids)

        sup = [self._evidence[eid] for eid in sorted(sup_eids) if eid in self._evidence]
        con = [self._evidence[eid] for eid in sorted(con_eids) if eid in self._evidence]

        return {"supporting": sup, "contradicting": con}

    # --- Graph Traversal ---

    def traverse_bounded_path(
        self, start_entity_id: str, max_depth: int = 2, max_nodes: int = 50
    ) -> Dict[str, Any]:
        """
        Cycle-safe, bounded deterministic Breadth-First-Search traversal.
        """
        if start_entity_id not in self._entities:
            return {
                "entities": [],
                "relationships": [],
                "claims": [],
                "evidence": [],
                "paths": [],
            }

        visited_entities: Set[str] = {start_entity_id}
        collected_relationships: Dict[str, Relationship] = {}
        paths: List[Dict[str, Any]] = []

        # Queue contains: (current_entity_id, current_depth, path_tuples)
        # path_tuples: list of (from_entity, rel_id, to_entity)
        queue: List[Tuple[str, int, List[Tuple[str, str, str]]]] = [(start_entity_id, 0, [])]

        while queue and len(visited_entities) <= max_nodes:
            curr_id, depth, curr_path = queue.pop(0)

            if depth >= max_depth:
                continue

            # Deterministic neighbor order
            rels = self.get_entity_relationships(curr_id, direction="both")
            for rel in rels:
                other_id = (
                    rel.target_entity_id
                    if rel.source_entity_id == curr_id
                    else rel.source_entity_id
                )

                # Strict node limit enforcement on branching graphs:
                # If other_id is unvisited and capacity is reached, do not collect it or its edge
                if other_id not in visited_entities:
                    if len(visited_entities) >= max_nodes:
                        continue
                    visited_entities.add(other_id)
                    queue.append((other_id, depth + 1, curr_path + [(rel.source_entity_id, rel.relationship_id, rel.target_entity_id)]))

                step_tuple = (rel.source_entity_id, rel.relationship_id, rel.target_entity_id)
                new_path = curr_path + [step_tuple]
                paths.append({
                    "start": start_entity_id,
                    "target": other_id,
                    "depth": depth + 1,
                    "steps": [
                        {"from": s[0], "rel": s[1], "to": s[2]}
                        for s in new_path
                    ],
                })

                collected_relationships[rel.relationship_id] = rel

        # Collect relevant claims and evidence
        all_claim_ids: Set[str] = set()
        all_evidence_ids: Set[str] = set()

        for rel in collected_relationships.values():
            all_claim_ids.update(rel.supporting_claim_ids)
            all_claim_ids.update(rel.contradicting_claim_ids)
            all_evidence_ids.update(rel.supporting_evidence_ids)
            all_evidence_ids.update(rel.contradicting_evidence_ids)

        for cid in all_claim_ids:
            if cid in self._claims:
                c = self._claims[cid]
                all_evidence_ids.update(c.supporting_evidence_ids)
                all_evidence_ids.update(c.contradicting_evidence_ids)

        return {
            "entities": [self._entities[eid] for eid in sorted(visited_entities) if eid in self._entities],
            "relationships": [collected_relationships[rid] for rid in sorted(collected_relationships.keys())],
            "claims": [self._claims[cid] for cid in sorted(all_claim_ids) if cid in self._claims],
            "evidence": [self._evidence[eid] for eid in sorted(all_evidence_ids) if eid in self._evidence],
            "paths": paths,
        }

    # --- Re-clustering Derived Graph Rebuild ---

    def rebuild_derived_graph(
        self,
        clusters: List[EntityCluster],
        record_to_cluster_map: Dict[str, str],
    ) -> None:
        """
        Recompute derived relationships when entity clusters change without
        mutating historical claims or evidence items.
        """
        # 1. Update entities in store from new clusters
        old_entity_ids = set(self._entities.keys())
        new_entity_ids = set()

        for cluster in clusters:
            new_ent = self.add_entity(cluster)
            new_entity_ids.add(new_ent.entity_id)

        # 2. Re-resolve claim endpoints to current clusters
        updated_relationships: Dict[str, Relationship] = {}
        self._adj_out = {eid: [] for eid in new_entity_ids}
        self._adj_in = {eid: [] for eid in new_entity_ids}

        for rel_id, rel in self._relationships.items():
            # Check if source or target need re-mapping based on records
            # Look up primary claims
            src_cluster_id = rel.source_entity_id
            tgt_cluster_id = rel.target_entity_id

            # If claims point to records, resolve using record_to_cluster_map
            claim_remapping_found = False
            for cid in rel.supporting_claim_ids:
                if cid in self._claims:
                    c = self._claims[cid]
                    remapped_src = record_to_cluster_map.get(c.subject_id)
                    remapped_tgt = record_to_cluster_map.get(c.object_id)
                    if remapped_src:
                        src_cluster_id = remapped_src
                        claim_remapping_found = True
                    if remapped_tgt:
                        tgt_cluster_id = remapped_tgt
                        claim_remapping_found = True
                    if claim_remapping_found:
                        break

            # If endpoints exist in the new clusters, keep/update the relationship
            if src_cluster_id in self._entities and tgt_cluster_id in self._entities:
                rebuilt_rel = Relationship(
                    relationship_id=rel.relationship_id,
                    source_entity_id=src_cluster_id,
                    target_entity_id=tgt_cluster_id,
                    relationship_type=rel.relationship_type,
                    is_directed=rel.is_directed,
                    epistemic_tier=rel.epistemic_tier,
                    supporting_claim_ids=list(rel.supporting_claim_ids),
                    supporting_evidence_ids=list(rel.supporting_evidence_ids),
                    contradicting_claim_ids=list(rel.contradicting_claim_ids),
                    contradicting_evidence_ids=list(rel.contradicting_evidence_ids),
                    valid_from=rel.valid_from,
                    valid_to=rel.valid_to,
                    provenance=f"rebuilt_from_cluster_update_v{datetime.now(timezone.utc).isoformat()}",
                    review_status=rel.review_status,
                    confidence=rel.confidence,
                    confidence_semantics=rel.confidence_semantics,
                    created_at=rel.created_at,
                    updated_at=datetime.now(timezone.utc),
                    metadata=dict(rel.metadata),
                )
                updated_relationships[rel_id] = rebuilt_rel
                self._adj_out[src_cluster_id].append(rel_id)
                self._adj_in[tgt_cluster_id].append(rel_id)

        self._relationships = updated_relationships


class Neo4jInvestigationGraphAdapter(BaseInvestigationGraphStore):
    """
    Offline adapter interface placeholder for Neo4j backend integration.

    Status: Deliberately incomplete interface specification. Operational methods raise 
    NotImplementedError to prevent unverified claims of database integration while 
    allowing typing and dependency verification without a live Neo4j daemon.
    """

    def __init__(self, uri: str = "bolt://localhost:7687", auth: Optional[Tuple[str, str]] = None):
        self.uri = uri
        self.auth = auth
        self._driver = None

    def _get_driver(self):
        if self._driver is None:
            try:
                from neo4j import GraphDatabase
                self._driver = GraphDatabase.driver(self.uri, auth=self.auth)
            except Exception as e:
                raise ConnectionError(
                    f"Neo4j server unavailable at {self.uri}: {e}. "
                    "Use InMemoryInvestigationGraphStore for local offline execution."
                ) from e
        return self._driver

    def add_entity(self, entity: Union[InvestigationEntity, EntityCluster]) -> InvestigationEntity:
        driver = self._get_driver()
        # Fallback / driver execution would occur here in production
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def get_entity(self, entity_id: str) -> Optional[InvestigationEntity]:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def has_entity(self, entity_id: str) -> bool:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def list_entities(self) -> List[InvestigationEntity]:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def add_record(self, record: Record) -> None:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def get_record(self, record_id: str) -> Optional[Record]:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def list_records(self) -> List[Record]:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def add_evidence(self, evidence: Evidence) -> None:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def get_evidence(self, evidence_id: str) -> Optional[Evidence]:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def list_evidence(self) -> List[Evidence]:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def add_claim(self, claim: Claim) -> None:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def get_claim(self, claim_id: str) -> Optional[Claim]:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def list_claims(self) -> List[Claim]:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def update_claim_status(
        self, claim_id: str, new_status: ReviewStatus, rationale: str, corrected_by: str, replacement_claim_id: Optional[str] = None
    ) -> Claim:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def add_relationship(self, relationship: Relationship) -> None:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def get_relationship(self, relationship_id: str) -> Optional[Relationship]:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def list_relationships(self) -> List[Relationship]:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def get_entity_relationships(self, entity_id: str, direction: str = "both") -> List[Relationship]:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def get_claim_evidence(self, claim_id: str) -> Dict[str, List[Evidence]]:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def get_relationship_evidence(self, relationship_id: str) -> Dict[str, List[Evidence]]:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def traverse_bounded_path(self, start_entity_id: str, max_depth: int = 2, max_nodes: int = 50) -> Dict[str, Any]:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def rebuild_derived_graph(self, clusters: List[EntityCluster], record_to_cluster_map: Dict[str, str]) -> None:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def remove_entity(self, entity_id: str, cascade_relationships: bool = False) -> bool:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")

    def remove_relationship(self, relationship_id: str) -> bool:
        raise NotImplementedError("Neo4j persistence adapter requires live server.")
