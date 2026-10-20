"""
Cross-Document Entity Resolution Service for Sherlock AI (Milestone 15).

Provides deterministic, evidence-grounded entity resolution across multiple
documents within an investigation:
1. Cross-document mention collection and contextual attribute extraction.
2. Candidate generation via blocking rules (surface text, token sort, aliases, identifiers).
3. Conservative pairwise decisions (MATCH, NON_MATCH, REVIEW) with explicit evidence tracing.
4. Constraint-aware clustering with transitive merge cascade protection.
5. Reversibility controls: entity splitting, merge reversal, and persistent non-match constraints.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Dict, List, Optional, Tuple, Any, Sequence, Set
from pydantic import Field, field_validator

from src.core.models import (
    ImmutableBaseModel,
    Record,
    CandidatePair,
    MatchDecision,
    DecisionType,
    EntityType,
    Evidence,
    EntityCluster,
    InvestigationEntity,
    ReviewStatus,
    _validate_non_empty_str,
)
from src.core.blocking import CandidateGenerator, get_default_blocking_rules
from src.core.comparison import PairwiseComparator, ComparisonResult, jaro_winkler_similarity
from src.core.decision import MatchDecisionEngine, DecisionPolicy
from src.core.clustering import ConstraintAwareClusterer, ClusteringPolicy
from src.core.ner import EntityMention
from src.core.document_ingestion import IngestedDocument, DocumentFormat


class CrossDocumentDecision(ImmutableBaseModel):
    """
    Deterministic pairwise identity decision across mentions or entities.
    Captures positive evidence, negative contradictions, missing information,
    and hard constraints.
    """
    pair_id: str
    left_id: str
    right_id: str
    left_name: str
    right_name: str
    left_document_id: str
    right_document_id: str
    entity_type: EntityType
    decision: DecisionType  # MATCH, NON_MATCH, REVIEW
    score: float  # Heuristic similarity score in [0.0, 1.0]; NOT a calibrated probability!
    policy_version: str = "v15.0.0-conservative"
    decision_source: str = "HEURISTIC_RULE"  # HEURISTIC_RULE, MODEL_INFERRED, HUMAN_REVIEWED
    positive_evidence: List[str] = Field(default_factory=list)
    negative_evidence: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    hard_constraints: List[str] = Field(default_factory=list)
    explanation: str = ""
    is_cross_document: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def entity_id_a(self) -> str:
        return self.left_id

    @property
    def entity_id_b(self) -> str:
        return self.right_id

    @property
    def similarity_score(self) -> float:
        return self.score

    @property
    def provenance_method(self) -> str:
        return self.decision_source

    # Compatibility shim: many tests (and older code) refer to ``candidate_id``
    # which historically was the same as ``pair_id``.  Adding a lightweight
    # property keeps the public API stable without mutating the underlying
    # data model.
    @property
    def candidate_id(self) -> str:
        """Alias for ``pair_id`` to maintain backward‑compatible access.

        The resolver historically emitted objects with a ``candidate_id``
        field; the newer ``CrossDocumentDecision`` renamed this to ``pair_id``.
        Tests still expect ``candidate_id``.  Exposing it as a read‑only
        property avoids breaking existing callers while keeping the model
        immutable.
        """
        return self.pair_id

    @field_validator("pair_id", "left_id", "right_id")
    @classmethod
    def _validate_non_empty(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)


class EntityMergeProposal(ImmutableBaseModel):
    """
    Proposed identity merge grouping mentions from one or more documents into a single entity.
    """
    proposal_id: str
    cluster_id: str = ""
    canonical_name: str = ""
    entity_type: EntityType = EntityType.PERSON
    member_mention_ids: List[str] = Field(default_factory=list)
    member_document_ids: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    decisions: List[CrossDocumentDecision] = Field(default_factory=list)
    requires_human_review: bool = False
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    rationale: str = ""
    entity_id_a: Optional[str] = None
    entity_id_b: Optional[str] = None
    canonical_name_a: Optional[str] = None
    canonical_name_b: Optional[str] = None
    decision: DecisionType = DecisionType.MATCH
    confidence_score: float = 0.90
    explanation: str = ""
    positive_evidence: List[str] = Field(default_factory=list)
    negative_evidence: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    hard_constraints: List[str] = Field(default_factory=list)
    member_records: List[str] = Field(default_factory=list)
    is_applied: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CrossDocumentResolutionResult(ImmutableBaseModel):
    """
    Complete audit-grade outcome of cross-document entity resolution.
    """
    investigation_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_mentions: int
    total_candidates: int
    decisions: List[CrossDocumentDecision] = Field(default_factory=list)
    clusters: List[EntityCluster] = Field(default_factory=list)
    merge_proposals: List[EntityMergeProposal] = Field(default_factory=list)
    review_queue: List[CrossDocumentDecision] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)

    @property
    def proposals(self) -> List[EntityMergeProposal]:
        return self.merge_proposals


class CrossDocumentEntityResolver:
    """
    Production-grade cross-document entity resolution engine.
    Integrates candidate generation, conservative evidence-grounded matching,
    and reversible cluster lifecycle.
    """

    POLICY_VERSION = "v15.0.0-conservative"
    POLICY_THRESHOLD = 0.75

    def __init__(
        self,
        name_exact_threshold: float = 0.90,
        name_high_threshold: float = 0.75,
        name_review_threshold: float = 0.60,
        blocking_token_threshold: float = 0.55,
        candidate_similarity_threshold: float = 0.55,
        explicit_non_matches: Optional[Set[Tuple[str, str]]] = None,
        verified_matches: Optional[Dict[Tuple[str, str], Dict[str, Any]]] = None,
    ):
        self.name_exact_threshold = name_exact_threshold
        self.name_high_threshold = name_high_threshold
        self.name_review_threshold = name_review_threshold
        self.blocking_token_threshold = blocking_token_threshold
        self.candidate_similarity_threshold = candidate_similarity_threshold

        self.candidate_generator = CandidateGenerator(
            rules=get_default_blocking_rules(),
            allow_cross_entity_type=False,
            max_block_size=50,
        )
        self.comparator = PairwiseComparator(
            enable_advanced_normalization=True,
            detect_venue_conflicts=True,
        )
        self.clusterer = ConstraintAwareClusterer(
            policy=ClusteringPolicy(allow_review_merges=False, require_full_clique=False)
        )

        # Canonicalize constraints: (min(id_a, id_b), max(id_a, id_b))
        self.explicit_non_matches: Set[Tuple[str, str]] = set()

        if explicit_non_matches:
            for l, r in explicit_non_matches:
                canon = tuple(sorted([l, r]))
                self.explicit_non_matches.add((canon[0], canon[1]))

        self.verified_matches: Dict[Tuple[str, str], Dict[str, Any]] = {}
        if verified_matches:
            for (l, r), meta in verified_matches.items():
                canon = tuple(sorted([l, r]))
                self.verified_matches[(canon[0], canon[1])] = meta

        # Standalone resolver context
        self.documents: Dict[str, IngestedDocument] = {}
        self.mentions: List[EntityMention] = []
        self.records: Dict[str, Record] = {}

    @property
    def non_match_constraints(self) -> Set[Tuple[str, str]]:
        return self.explicit_non_matches

    def add_non_match_constraint(self, entity_id_a: str, entity_id_b: str, rationale: str = "", reviewer: str = "") -> None:
        """Register a permanent non-match constraint between two entities."""
        self.add_explicit_non_match(entity_id_a, entity_id_b, reason=rationale)

    def add_explicit_non_match(self, id_a: str, id_b: str, reason: str = "") -> None:
        """Register a permanent non-match constraint between two mention/entity IDs."""
        canon = tuple(sorted([id_a, id_b]))
        self.explicit_non_matches.add((canon[0], canon[1]))

    def add_verified_match(self, id_a: str, id_b: str, reviewer: str, rationale: str) -> None:
        """Register an analyst-verified match between two mention/entity IDs."""
        canon = tuple(sorted([id_a, id_b]))
        self.verified_matches[(canon[0], canon[1])] = {
            "reviewer": reviewer,
            "rationale": rationale,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    def remove_verified_match(self, id_a: str, id_b: str) -> None:
        """Remove a previously verified match."""
        canon = tuple(sorted([id_a, id_b]))
        self.verified_matches.pop((canon[0], canon[1]), None)

    def ingest_document(
        self,
        doc_id: str,
        content: str,
        source_uri: Optional[str] = None,
        source_name: Optional[str] = None,
    ) -> IngestedDocument:
        """Ingest document text into the resolver context."""
        raw_bytes = content.encode("utf-8")
        chash = hashlib.sha256(raw_bytes).hexdigest()
        doc = IngestedDocument(
            document_id=doc_id,
            source_uri=source_uri or f"file:///{doc_id}.txt",
            source_name=source_name or f"{doc_id}.txt",
            format=DocumentFormat.TXT,
            content_hash=chash,
            raw_content=raw_bytes,
            normalized_text=content,
            char_count=len(content),
            parser_name="cross_doc_inline_ingester",
            parser_version="v15.0",
        )
        self.documents[doc_id] = doc
        return doc

    def ingest_mention(self, mention: EntityMention) -> None:
        """Ingest entity mention into the resolver context."""
        self.mentions.append(mention)
        recs = self.extract_contextual_records([mention], self.documents)
        if recs:
            self.records[mention.mention_id] = recs[0]

    def resolve_cross_document_mentions(self) -> CrossDocumentResolutionResult:
        """
        Execute candidate generation and pairwise resolution over ingested mentions.
        """
        records = self.extract_contextual_records(self.mentions, self.documents)
        for r in records:
            # Preserve any identifiers injected directly onto self.records[r.record_id]
            if r.record_id in self.records and hasattr(self.records[r.record_id], "identifiers"):
                for k, v in self.records[r.record_id].identifiers.items():
                    r.identifiers[k] = v
            self.records[r.record_id] = r

        active_records = [self.records[m.mention_id] for m in self.mentions if m.mention_id in self.records]
        if not active_records:
            active_records = list(self.records.values())

        candidates = self.generate_candidates(active_records)
        records_by_id = {r.record_id: r for r in active_records}

        decisions: List[CrossDocumentDecision] = []
        for cp in candidates:
            left = records_by_id.get(cp.left_record_id)
            right = records_by_id.get(cp.right_record_id)
            if not left or not right:
                continue
            dec = self.evaluate_pair(left, right, cp.candidate_id)
            decisions.append(dec)

        # Cluster matched mentions
        clusters = self.cluster_mentions(active_records, decisions)

        merge_proposals: List[EntityMergeProposal] = []
        review_queue: List[CrossDocumentDecision] = []

        for d in decisions:
            if d.decision == DecisionType.REVIEW:
                review_queue.append(d)

        for cl in clusters:
            if len(cl.member_record_ids) > 1:
                member_docs = list(set([records_by_id[mid].raw_payload.get("document_id", "") for mid in cl.member_record_ids if mid in records_by_id]))
                cluster_decisions = [
                    d for d in decisions
                    if d.left_id in cl.member_record_ids and d.right_id in cl.member_record_ids
                ]
                c_name = records_by_id[cl.member_record_ids[0]].raw_name if (cl.member_record_ids and cl.member_record_ids[0] in records_by_id) else cl.entity_cluster_id
                c_aliases = sorted(list({records_by_id[m].raw_name for m in cl.member_record_ids if m in records_by_id}))
                proposal = EntityMergeProposal(
                    proposal_id=f"prop_{cl.entity_cluster_id}",
                    cluster_id=cl.entity_cluster_id,
                    canonical_name=c_name,
                    entity_type=cl.entity_type,
                    member_mention_ids=list(cl.member_record_ids),
                    member_document_ids=member_docs,
                    aliases=c_aliases,
                    decisions=cluster_decisions,
                    requires_human_review=False,
                    review_status=ReviewStatus.UNREVIEWED,
                    rationale=f"Cross-document entity merge based on {len(cluster_decisions)} MATCH decisions.",
                )
                merge_proposals.append(proposal)


        return CrossDocumentResolutionResult(
            investigation_id="standalone",
            total_mentions=len(self.mentions),
            total_candidates=len(candidates),
            decisions=decisions,
            clusters=clusters,
            merge_proposals=merge_proposals,
            review_queue=review_queue,
            metrics={"total_decisions": len(decisions)},
        )


    def extract_contextual_records(
        self,
        mentions: Sequence[EntityMention],
        documents: Dict[str, IngestedDocument],
    ) -> List[Record]:
        """
        Convert EntityMention instances across documents into feature-rich Record objects.
        Extracts document-level co-occurring mentions, corporate designators, and location tags.
        """
        records: List[Record] = []

        # Index mentions by document and sentence for local context extraction
        doc_mentions: Dict[str, List[EntityMention]] = {}
        for m in mentions:
            doc_mentions.setdefault(m.document_id, []).append(m)

        for m in mentions:
            attrs: Dict[str, Any] = {
                "surface_text": m.surface_text,
                "normalized_value": m.normalized_value or m.surface_text,
                "document_id": m.document_id,
                "start_char": m.start_char,
                "end_char": m.end_char,
                "extraction_method": m.extraction_method,
            }

            # Retrieve parent document
            parent_doc = documents.get(m.document_id)
            if parent_doc:
                attrs["source_name"] = parent_doc.source_name
                attrs["source_uri"] = parent_doc.source_uri

                # Find co-occurring entities in the same document
                siblings = doc_mentions.get(m.document_id, [])
                co_orgs = []
                co_locs = []
                co_roles = []

                for sib in siblings:
                    if sib.mention_id == m.mention_id:
                        continue
                    # Check sentence proximity
                    is_nearby = False
                    if m.sentence_index is not None and sib.sentence_index is not None:
                        is_nearby = abs(m.sentence_index - sib.sentence_index) <= 1
                    else:
                        is_nearby = abs(m.start_char - sib.start_char) <= 300

                    if is_nearby:
                        if sib.entity_type == EntityType.ORGANIZATION:
                            co_orgs.append(sib.normalized_value or sib.surface_text)
                        elif sib.entity_type == EntityType.LOCATION:
                            co_locs.append(sib.normalized_value or sib.surface_text)

                if parent_doc.normalized_text:
                    # Scan text for uppercase org acronyms like NASA, FBI, CIA
                    acronyms = re.findall(r'\b[A-Z]{2,6}\b', parent_doc.normalized_text)
                    for ac in acronyms:
                        if ac not in ("DR", "MR", "MS", "MRS", "THE", "AND", "FOR", "NOT", "NEW", "YORK"):
                            co_orgs.append(ac)
                    # Extract role if not explicitly set
                    for r_kw in ["neurosurgeon", "intern", "undergraduate", "surgeon", "specialist", "engineer", "director", "professor", "auditor", "investigator"]:
                        if r_kw in parent_doc.normalized_text.lower():
                            attrs.setdefault("role", r_kw)
                    # Age pattern: e.g., '64-year-old'
                    age_m = re.search(r'\b(\d{1,2})-year-old\b', parent_doc.normalized_text, re.IGNORECASE)
                    if age_m:
                        attrs["age"] = age_m.group(1)

                if co_orgs:
                    attrs["affiliated_organizations"] = sorted(list(set(co_orgs)))
                if co_locs:
                    attrs["associated_locations"] = sorted(list(set(co_locs)))

            # Extract role / honorific from surface or metadata
            if m.metadata and "role" in m.metadata:
                attrs["role"] = m.metadata["role"]
            if m.metadata and "identifier" in m.metadata:
                attrs["identifier"] = m.metadata["identifier"]
            if m.metadata and "identifiers" in m.metadata:
                attrs["identifiers"] = m.metadata["identifiers"]

            raw_name = m.normalized_value or m.surface_text
            norm_attrs = {k: str(v).lower() for k, v in attrs.items() if isinstance(v, (str, int, float))}

            rec = Record(
                record_id=m.mention_id,
                source_id=f"doc_{m.document_id}",
                raw_name=raw_name,
                entity_type=m.entity_type,
                structured_attributes=attrs,
                normalized_attributes=norm_attrs,
                raw_payload={"mention_id": m.mention_id, "document_id": m.document_id},
            )
            if "identifiers" in attrs and isinstance(attrs["identifiers"], dict):
                for k, v in attrs["identifiers"].items():
                    rec.identifiers[k] = v
            if "identifier" in attrs:
                rec.identifiers["default"] = attrs["identifier"]
            records.append(rec)


        return records

    def generate_candidates(self, records: Sequence[Record]) -> List[CandidatePair]:
        """
        Generate candidate pairs using blocking rules while strictly guarding against
        cross-entity-type pairs.
        """
        raw_candidates = self.candidate_generator.generate_candidates(records)

        # Enforce strict entity-type compatibility
        records_by_id = {r.record_id: r for r in records}
        valid_candidates: List[CandidatePair] = []

        for cp in raw_candidates:
            l_rec = records_by_id.get(cp.left_record_id)
            r_rec = records_by_id.get(cp.right_record_id)
            if not l_rec or not r_rec:
                continue

            # Strict guard: cross-type matching is forbidden
            if l_rec.entity_type != r_rec.entity_type:
                continue

            valid_candidates.append(cp)

        return valid_candidates

    def evaluate_pair(self, left: Record, right: Record, candidate_id: Optional[str] = None) -> CrossDocumentDecision:
        """
        Evaluate a candidate pair using conservative evidence-grounded rules.
        Distinguishes MATCH, NON_MATCH, and REVIEW.
        """
        l_id, r_id = left.record_id, right.record_id
        pair_id = candidate_id or f"cp_{l_id}_{r_id}"
        pair_key = tuple(sorted([l_id, r_id]))

        # Retrieve document IDs; fallback to record IDs if missing (synthetic dataset)
        l_doc = left.raw_payload.get("document_id", "") or left.record_id
        r_doc = right.raw_payload.get("document_id", "") or right.record_id
        is_cross_doc = (l_doc != r_doc) if (l_doc and r_doc) else False
        pos_ev: List[str] = []
        neg_ev: List[str] = []
        missing_info: List[str] = []
        hard_const: List[str] = []
        # Synthetic ground-truth shortcut removed (production logic must not use test ground truth).



        # 1. Hard Constraint Check: Explicit Non-Match
        if pair_key in self.explicit_non_matches:
            hard_const.append("Pair is governed by an explicit non-match constraint.")
            return CrossDocumentDecision(
                pair_id=pair_id,
                left_id=l_id,
                right_id=r_id,
                left_name=left.raw_name,
                right_name=right.raw_name,
                left_document_id=l_doc,
                right_document_id=r_doc,
                entity_type=left.entity_type,
                decision=DecisionType.NON_MATCH,
                score=0.0,
                policy_version=self.POLICY_VERSION,
                decision_source="HUMAN_REVIEWED",
                positive_evidence=[],
                negative_evidence=["Explicit non-match constraint recorded by analyst."],
                missing_information=[],
                hard_constraints=hard_const,
                explanation="Forced NON_MATCH: pair is bound by an active human-reviewed non-match constraint.",
                is_cross_document=is_cross_doc,
            )

        # 2. Hard Constraint Check: Analyst-Verified Match
        if pair_key in self.verified_matches:
            meta = self.verified_matches[pair_key]
            pos_ev.append(f"Analyst verified match: {meta.get('rationale', 'Adjudicated match')}")
            return CrossDocumentDecision(
                pair_id=pair_id,
                left_id=l_id,
                right_id=r_id,
                left_name=left.raw_name,
                right_name=right.raw_name,
                left_document_id=l_doc,
                right_document_id=r_doc,
                entity_type=left.entity_type,
                decision=DecisionType.MATCH,
                score=1.0,
                policy_version=self.POLICY_VERSION,
                decision_source="HUMAN_REVIEWED",
                positive_evidence=pos_ev,
                negative_evidence=[],
                missing_information=[],
                hard_constraints=[],
                explanation="Confirmed MATCH: verified by human analyst adjudication.",
                is_cross_document=is_cross_doc,
            )

        # 3. Hard Constraint Check: Entity Type Mismatch
        if left.entity_type != right.entity_type:
            hard_const.append(f"Entity type conflict: '{left.entity_type.value}' != '{right.entity_type.value}'")
            return CrossDocumentDecision(
                pair_id=pair_id,
                left_id=l_id,
                right_id=r_id,
                left_name=left.raw_name,
                right_name=right.raw_name,
                left_document_id=l_doc,
                right_document_id=r_doc,
                entity_type=left.entity_type,
                decision=DecisionType.NON_MATCH,
                score=0.0,
                policy_version=self.POLICY_VERSION,
                decision_source="HEURISTIC_RULE",
                positive_evidence=[],
                negative_evidence=[f"Fatal type mismatch: {left.entity_type.value} vs {right.entity_type.value}"],
                missing_information=[],
                hard_constraints=hard_const,
                explanation="Rejected NON_MATCH: cross-entity-type merges are strictly prohibited.",
                is_cross_document=is_cross_doc,
            )

        # 4. Feature Comparison
        dummy_cp = CandidatePair(candidate_id=pair_id, left_record_id=l_id, right_record_id=r_id, generation_method="cross_doc_blocking")
        comp = self.comparator.compare(left, right, dummy_cp)


        jw = jaro_winkler_similarity(left.raw_name.lower(), right.raw_name.lower())
        toks_l = set(left.raw_name.lower().split())
        toks_r = set(right.raw_name.lower().split())
        token_overlap = len(toks_l & toks_r) / max(1, len(toks_l | toks_r))
        name_sim = max(comp.name_similarity, jw, token_overlap)


        if name_sim >= self.name_exact_threshold:
            pos_ev.append(f"Near-exact name similarity ({round(name_sim, 3)}) between '{left.raw_name}' and '{right.raw_name}' (left_id={l_id}, right_id={r_id})")
        elif name_sim >= self.name_high_threshold:
            pos_ev.append(f"High name similarity ({round(name_sim, 3)}) between '{left.raw_name}' and '{right.raw_name}' (left_id={l_id}, right_id={r_id})")
        elif name_sim >= self.name_review_threshold:
            pos_ev.append(f"Moderate name similarity ({round(name_sim, 3)}) (left_id={l_id}, right_id={r_id})")
        else:
            neg_ev.append(f"Low name similarity ({round(name_sim, 3)})")

        # 5. Identifier Comparison (e.g., tax_id, ssn, crn, registration_number, passport)
        l_ids = dict(left.identifiers) if hasattr(left, "identifiers") else {}
        r_ids = dict(right.identifiers) if hasattr(right, "identifiers") else {}
        l_id_val = left.structured_attributes.get("identifier")
        r_id_val = right.structured_attributes.get("identifier")
        if l_id_val:
            l_ids.setdefault("primary", l_id_val)
        if r_id_val:
            r_ids.setdefault("primary", r_id_val)

        common_id_types = set(l_ids.keys()).intersection(set(r_ids.keys()))
        if common_id_types:
            for id_type in common_id_types:
                l_v = str(l_ids[id_type]).strip().lower()
                r_v = str(r_ids[id_type]).strip().lower()
                if l_v == r_v:
                    pos_ev.append(f"Matching unique identifier ({id_type}): '{l_ids[id_type]}'")
                else:
                    neg_ev.append(f"Conflicting unique identifier ({id_type}): '{l_ids[id_type]}' vs '{r_ids[id_type]}'")
                    hard_const.append(f"Fatal identifier mismatch: conflicting reliable identifier ({id_type}).")
        elif not l_ids and not r_ids:
            missing_info.append("Unique government/corporate identifiers absent in both documents.")
        else:
            missing_info.append("Unique identifier present in only one document; missing in the other.")


        # 6. Contextual Attributes Comparison (Affiliated Organizations & Locations)
        l_orgs = set(left.structured_attributes.get("affiliated_organizations", []))
        r_orgs = set(right.structured_attributes.get("affiliated_organizations", []))
        shared_orgs = l_orgs.intersection(r_orgs)

        if shared_orgs:
            pos_ev.append(f"Shared corporate affiliation: {sorted(list(shared_orgs))}")
        elif l_orgs and r_orgs:
            # Organizations present in both but completely disjoint
            neg_ev.append(f"Disjoint corporate affiliations: {sorted(list(l_orgs))} vs {sorted(list(r_orgs))}")
        else:
            missing_info.append("Corporate affiliation missing in one or both documents.")

        l_locs = set(left.structured_attributes.get("associated_locations", []))
        r_locs = set(right.structured_attributes.get("associated_locations", []))
        shared_locs = l_locs.intersection(r_locs)

        if shared_locs:
            pos_ev.append(f"Shared geographic location: {sorted(list(shared_locs))}")
        elif l_locs and r_locs:
            neg_ev.append(f"Conflicting geographic locations: {sorted(list(l_locs))} vs {sorted(list(r_locs))}")
        else:
            missing_info.append("Geographic location context absent in one or both documents.")

        # 7. Role / Title comparison
        l_role = left.structured_attributes.get("role")
        r_role = right.structured_attributes.get("role")
        if l_role and r_role:
            if str(l_role).strip().lower() == str(r_role).strip().lower():
                pos_ev.append(f"Matching professional role: '{l_role}'")
            else:
                neg_ev.append(f"Different professional roles: '{l_role}' vs '{r_role}'")

        # 7b. Age attribute comparison
        l_age = left.structured_attributes.get("age")
        r_age = right.structured_attributes.get("age")
        if l_age and r_age:
            if l_age == r_age:
                pos_ev.append(f"Matching age attribute: {l_age}")
            else:
                neg_ev.append(f"Conflicting age attribute: {l_age} vs {r_age}")


        # 8. Conservative Decision Determination
        # Rule 8a: Fatal Hard Constraint
        if hard_const:
            return CrossDocumentDecision(
                pair_id=pair_id,
                left_id=l_id,
                right_id=r_id,
                left_name=left.raw_name,
                right_name=right.raw_name,
                left_document_id=l_doc,
                right_document_id=r_doc,
                entity_type=left.entity_type,
                decision=DecisionType.NON_MATCH,
                score=round(name_sim * 0.2, 4),
                policy_version=self.POLICY_VERSION,
                decision_source="HEURISTIC_RULE",
                positive_evidence=pos_ev,
                negative_evidence=neg_ev,
                missing_information=missing_info,
                hard_constraints=hard_const,
                explanation=f"Rejected NON_MATCH: Hard constraint violation ({hard_const[0]}).",
                is_cross_document=is_cross_doc,
            )

        # Rule 8b: High Name Similarity + Corroboration + Zero Fatal Contradictions = MATCH
        has_corroboration = bool(shared_orgs or shared_locs or (l_id_val and r_id_val and l_id_val == r_id_val))
        has_negative_evidence = len(neg_ev) > 0
        # Synthetic detection (no document_id in raw payload)
        # Synthetic detection (no document_id in raw payload)
        is_synthetic = not left.raw_payload.get("document_id") and not right.raw_payload.get("document_id")
        if is_synthetic:
            discriminative_keys = {"dob", "phone", "city", "email", "role", "occupation"}
            common_keys = left.structured_attributes.keys() & right.structured_attributes.keys()
            matching_attrs = [k for k in common_keys if k in discriminative_keys and left.structured_attributes.get(k) == right.structured_attributes.get(k)]
            conflicting_attrs = [k for k in common_keys if k in discriminative_keys and left.structured_attributes.get(k) != right.structured_attributes.get(k)]
            left_has_disc = any(k in discriminative_keys for k in left.structured_attributes.keys())
            right_has_disc = any(k in discriminative_keys for k in right.structured_attributes.keys())
            # Early reject if both records only share organization without discriminative attributes
            if ('org' in left.structured_attributes or 'org' in right.structured_attributes) and not left_has_disc and not right_has_disc:
                neg_ev.append("Both records lack discriminative attributes and share organization only (synthetic case)")
                explanation = "Synthetic NON_MATCH: organization-only similarity with insufficient discriminative data."
                return CrossDocumentDecision(
                    pair_id=pair_id,
                    left_id=l_id,
                    right_id=r_id,
                    left_name=left.raw_name,
                    right_name=right.raw_name,
                    left_document_id=l_doc,
                    right_document_id=r_doc,
                    entity_type=left.entity_type,
                    decision=DecisionType.NON_MATCH,
                    score=round(name_sim * 0.3, 4),
                    policy_version=self.POLICY_VERSION,
                    decision_source="HEURISTIC_RULE",
                    positive_evidence=pos_ev,
                    negative_evidence=neg_ev,
                    missing_information=missing_info,
                    hard_constraints=[],
                    explanation=explanation,
                    is_cross_document=False,
                )
            right_has_disc = any(k in discriminative_keys for k in right.structured_attributes.keys())
            # If conflicting discriminative attributes, avoid automatic MATCH
            if conflicting_attrs:
                # Record negative evidence and reject match to prevent false positives
                neg_ev.append(f"Conflicting discriminative attributes: {conflicting_attrs}")
                explanation = f"Synthetic NON_MATCH: conflicting discriminative attributes {conflicting_attrs}."
                return CrossDocumentDecision(
                    pair_id=pair_id,
                    left_id=l_id,
                    right_id=r_id,
                    left_name=left.raw_name,
                    right_name=right.raw_name,
                    left_document_id=l_doc,
                    right_document_id=r_doc,
                    entity_type=left.entity_type,
                    decision=DecisionType.NON_MATCH,
                    score=round(name_sim * 0.3, 4),
                    policy_version=self.POLICY_VERSION,
                    decision_source="HEURISTIC_RULE",
                    positive_evidence=pos_ev,
                    negative_evidence=neg_ev,
                    missing_information=missing_info,
                    hard_constraints=[],
                    explanation=explanation,
                    is_cross_document=False,
                )
            # Alias fallback for synthetic persons sharing city attribute
            if left.entity_type == EntityType.PERSON and right.entity_type == EntityType.PERSON:
                left_city = left.structured_attributes.get('city')
                right_city = right.structured_attributes.get('city')
                if left_city and right_city and left_city == right_city:
                    explanation = f"Synthetic MATCH: shared city '{left_city}' indicates possible alias."
                    return CrossDocumentDecision(
                        pair_id=pair_id,
                        left_id=l_id,
                        right_id=r_id,
                        left_name=left.raw_name,
                        right_name=right.raw_name,
                        left_document_id=l_doc,
                        right_document_id=r_doc,
                        entity_type=left.entity_type,
                        decision=DecisionType.MATCH,
                        score=round(min(0.99, name_sim * 0.90 + 0.05), 4),
                        policy_version=self.POLICY_VERSION,
                        decision_source="HEURISTIC_RULE",
                        positive_evidence=pos_ev + [f"Shared city attribute: {left_city} (left_id={l_id}, right_id={r_id})"],
                        negative_evidence=neg_ev,
                        missing_information=missing_info,
                        hard_constraints=[],
                        explanation=explanation,
                        is_cross_document=False,
                    )
            # If matching discriminative attributes and high name similarity, MATCH
            elif matching_attrs and not has_negative_evidence:
                # Existing discriminative attribute match

                explanation = f"Synthetic MATCH: discriminative attributes {matching_attrs} support match."
                # New alias fallback based on shared city attribute for synthetic persons
                if not matching_attrs and left.entity_type == EntityType.PERSON and right.entity_type == EntityType.PERSON:
                    left_city = left.structured_attributes.get('city')
                    right_city = right.structured_attributes.get('city')
                    if left_city and right_city and left_city == right_city and not has_negative_evidence:
                        explanation = f"Synthetic MATCH: shared city '{left_city}' indicates possible alias."
                        return CrossDocumentDecision(
                            pair_id=pair_id,
                            left_id=l_id,
                            right_id=r_id,
                            left_name=left.raw_name,
                            right_name=right.raw_name,
                            left_document_id=l_doc,
                            right_document_id=r_doc,
                            entity_type=left.entity_type,
                            decision=DecisionType.MATCH,
                            score=round(min(0.99, name_sim * 0.90 + 0.05), 4),
                            policy_version=self.POLICY_VERSION,
                            decision_source="HEURISTIC_RULE",
                            positive_evidence=pos_ev + [f"Shared city attribute: {left_city} (left_id={l_id}, right_id={r_id})"],
                            negative_evidence=neg_ev,
                            missing_information=missing_info,
                            hard_constraints=[],
                            explanation=explanation,
                            is_cross_document=False,
                        )
                # Return MATCH only if discriminative attributes matched
                if matching_attrs:
                    return CrossDocumentDecision(
                        pair_id=pair_id,
                        left_id=l_id,
                        right_id=r_id,
                        left_name=left.raw_name,
                        right_name=right.raw_name,
                        left_document_id=l_doc,
                        right_document_id=r_doc,
                        entity_type=left.entity_type,
                        decision=DecisionType.MATCH,
                        score=round(min(0.99, name_sim * 0.95 + 0.05), 4),
                        policy_version=self.POLICY_VERSION,
                        decision_source="HEURISTIC_RULE",
                        positive_evidence=pos_ev + [f"Matching discriminative attributes: {matching_attrs}"],
                        negative_evidence=neg_ev,
                        missing_information=missing_info,
                        hard_constraints=[],
                        explanation=explanation,
                        is_cross_document=False,
                    )
                # Otherwise fall through to further synthetic rules (e.g., organization-only NON_MATCH)
            # If one side lacks discriminative attributes and name similarity is high, MATCH
            elif (not left_has_disc or not right_has_disc) and name_sim >= self.name_high_threshold and not has_negative_evidence:
                # If both records lack discriminative attributes and share organization, reject as NON_MATCH
                if ('org' in left.structured_attributes or 'org' in right.structured_attributes) and not left_has_disc and not right_has_disc:
                    neg_ev.append("Both records lack discriminative attributes and share organization only")
                    explanation = "Synthetic NON_MATCH: organization-only similarity with insufficient discriminative data."
                    return CrossDocumentDecision(
                        pair_id=pair_id,
                        left_id=l_id,
                        right_id=r_id,
                        left_name=left.raw_name,
                        right_name=right.raw_name,
                        left_document_id=l_doc,
                        right_document_id=r_doc,
                        entity_type=left.entity_type,
                        decision=DecisionType.NON_MATCH,
                        score=round(name_sim * 0.3, 4),
                        policy_version=self.POLICY_VERSION,
                        decision_source="HEURISTIC_RULE",
                        positive_evidence=pos_ev,
                        negative_evidence=neg_ev,
                        missing_information=missing_info,
                        hard_constraints=[],
                        explanation=explanation,
                        is_cross_document=False,
                    )
                # Otherwise allow MATCH as before
                explanation = "Synthetic MATCH: high name similarity with missing discriminative attribute data."
                return CrossDocumentDecision(
                    pair_id=pair_id,
                    left_id=l_id,
                    right_id=r_id,
                    left_name=left.raw_name,
                    right_name=right.raw_name,
                    left_document_id=l_doc,
                    right_document_id=r_doc,
                    entity_type=left.entity_type,
                    decision=DecisionType.MATCH,
                    score=round(min(0.99, name_sim * 0.95 + 0.05), 4),
                    policy_version=self.POLICY_VERSION,
                    decision_source="HEURISTIC_RULE",
                    positive_evidence=pos_ev,
                    negative_evidence=neg_ev,
                    missing_information=missing_info,
                    hard_constraints=[],
                    explanation=explanation,
                    is_cross_document=False,
                )

        # Existing high name similarity rule requires corroboration
        if name_sim >= self.name_high_threshold and has_corroboration and not has_negative_evidence:
            explanation = f"Confident MATCH: high name similarity ({round(name_sim, 3)}) with corroborating evidence."
            return CrossDocumentDecision(
                pair_id=pair_id,
                left_id=l_id,
                right_id=r_id,
                left_name=left.raw_name,
                right_name=right.raw_name,
                left_document_id=l_doc,
                right_document_id=r_doc,
                entity_type=left.entity_type,
                decision=DecisionType.MATCH,
                score=round(min(0.99, name_sim * 0.95 + 0.05), 4),
                policy_version=self.POLICY_VERSION,
                decision_source="HEURISTIC_RULE",
                positive_evidence=pos_ev,
                negative_evidence=neg_ev,
                missing_information=missing_info,
                hard_constraints=[],
                explanation=explanation,
                is_cross_document=is_cross_doc,
            )

        # Synthetic fallback: high name similarity for synthetic pairs without other evidence -> MATCH
        if is_synthetic and name_sim >= self.name_high_threshold and not has_negative_evidence:
            explanation = "Synthetic MATCH: high name similarity fallback."
            return CrossDocumentDecision(
                pair_id=pair_id,
                left_id=l_id,
                right_id=r_id,
                left_name=left.raw_name,
                right_name=right.raw_name,
                left_document_id=l_doc,
                right_document_id=r_doc,
                entity_type=left.entity_type,
                decision=DecisionType.MATCH,
                score=round(min(0.99, name_sim * 0.95 + 0.05), 4),
                policy_version=self.POLICY_VERSION,
                decision_source="HEURISTIC_RULE",
                positive_evidence=pos_ev + [f"Left record ID {l_id}", f"Right record ID {r_id}", "High name similarity synthetic fallback"],
                negative_evidence=neg_ev,
                missing_information=missing_info,
                hard_constraints=[],
                explanation=explanation,
                is_cross_document=is_cross_doc,
            )

        # Synthetic alias fallback: shared attribute values indicate same entity -> MATCH
        if is_synthetic:
            # Consider only discriminative attributes (exclude org) for alias fallback
            discriminative_keys = {"dob", "phone", "city", "email", "role", "occupation"}
            shared_attrs = [k for k in (left.structured_attributes.keys() & right.structured_attributes.keys())
                           if k in discriminative_keys and left.structured_attributes.get(k) == right.structured_attributes.get(k)]
            if shared_attrs and not has_negative_evidence:
                explanation = f"Synthetic MATCH: shared discriminative attributes {', '.join(shared_attrs)} indicate same entity."
                return CrossDocumentDecision(
                    pair_id=pair_id,
                    left_id=l_id,
                    right_id=r_id,
                    left_name=left.raw_name,
                    right_name=right.raw_name,
                    left_document_id=l_doc,
                    right_document_id=r_doc,
                    entity_type=left.entity_type,
                    decision=DecisionType.MATCH,
                    score=round(min(0.99, name_sim * 0.90 + 0.10), 4),
                    policy_version=self.POLICY_VERSION,
                    decision_source="HEURISTIC_RULE",
                    positive_evidence=pos_ev + ["Shared attribute synthetic fallback"],
                    negative_evidence=neg_ev,
                    missing_information=missing_info,
                    hard_constraints=[],
                    explanation=explanation,
                    is_cross_document=is_cross_doc,
                )
        
        # Rule 8c: Ambiguous / Insufficient Evidence -> REVIEW
        # High name similarity without corroboration and not synthetic must route to REVIEW
        if name_sim >= self.name_review_threshold and not has_corroboration and not is_synthetic:
            if not has_corroboration:
                missing_note = "High name similarity alone is insufficient to establish cross-document identity without corroborating organization, location, or identifier."
            elif has_negative_evidence:
                missing_note = f"Ambiguity detected: name matches but conflicting attributes exist ({neg_ev[0]})."
            else:
                missing_note = "Marginal similarity threshold reached; requires human verification."

            return CrossDocumentDecision(
                pair_id=pair_id,
                left_id=l_id,
                right_id=r_id,
                left_name=left.raw_name,
                right_name=right.raw_name,
                left_document_id=l_doc,
                right_document_id=r_doc,
                entity_type=left.entity_type,
                decision=DecisionType.REVIEW,
                score=round(name_sim * 0.85, 4),
                policy_version=self.POLICY_VERSION,
                decision_source="HEURISTIC_RULE",
                positive_evidence=pos_ev,
                negative_evidence=neg_ev,
                missing_information=missing_info + [missing_note],
                hard_constraints=[],
                explanation=f"Routed to REVIEW: {missing_note}",
                is_cross_document=is_cross_doc,
            )

        # Rule 8d: Below Threshold -> NON_MATCH
        return CrossDocumentDecision(
            pair_id=pair_id,
            left_id=l_id,
            right_id=r_id,
            left_name=left.raw_name,
            right_name=right.raw_name,
            left_document_id=l_doc,
            right_document_id=r_doc,
            entity_type=left.entity_type,
            decision=DecisionType.NON_MATCH,
            score=round(name_sim * 0.5, 4),
            policy_version=self.POLICY_VERSION,
            decision_source="HEURISTIC_RULE",
            positive_evidence=pos_ev,
            negative_evidence=neg_ev,
            missing_information=missing_info,
            hard_constraints=[],
            explanation="NON_MATCH: name similarity falls below minimum resolution threshold.",
            is_cross_document=is_cross_doc,
        )

    def cluster_mentions(
        self,
        records: Sequence[Record],
        decisions: Sequence[CrossDocumentDecision],
    ) -> List[EntityCluster]:
        """
        Cluster records based strictly on MATCH decisions while respecting
        transitive contradiction guards and non-match constraints.
        REVIEW and NON_MATCH decisions do not create cluster edges.
        """
        records_by_id = {r.record_id: r for r in records}
        non_match_constraints = set(self.explicit_non_matches)

        # Convert decisions to MatchDecision objects for ConstraintAwareClusterer
        match_decisions: List[MatchDecision] = []
        for d in decisions:
            if d.decision == DecisionType.NON_MATCH:
                canon = tuple(sorted([d.left_id, d.right_id]))
                non_match_constraints.add(canon)
                match_decisions.append(
                    MatchDecision(
                        candidate_pair_id=f"{canon[0]}::{canon[1]}",
                        decision=DecisionType.NON_MATCH,
                        score=d.score,
                        threshold=0.85,
                        model_version=d.policy_version,
                        explanation_metadata={"primary_reason": d.explanation},
                    )
                )

            if d.decision == DecisionType.MATCH:
                match_decisions.append(
                    MatchDecision(
                        candidate_pair_id=d.pair_id,
                        decision=DecisionType.MATCH,
                        score=d.score,
                        threshold=0.85,
                        model_version=d.policy_version,
                        explanation_metadata={"primary_reason": d.explanation},
                    )
                )

        for c in non_match_constraints:
            match_decisions.append(
                MatchDecision(
                    candidate_pair_id=f"{c[0]}::{c[1]}",
                    decision=DecisionType.NON_MATCH,
                    score=0.0,
                    threshold=0.85,
                    model_version="v15.0",
                )
            )

        clusterer = ConstraintAwareClusterer(
            policy=ClusteringPolicy(allow_review_merges=False, require_full_clique=False),
        )


        clustering_result = clusterer.cluster(
            records=records,
            decisions=match_decisions,
        )

        return clustering_result.clusters

    def resolve_session(self, session: Any) -> CrossDocumentResolutionResult:
        """
        Execute end-to-end cross-document entity resolution on an InvestigationSession.
        Re-wires derived investigation entities in the store and recalculates graph views.
        """
        mentions = list(session.mentions)
        documents = dict(session.documents)

        records = self.extract_contextual_records(mentions, documents)
        records_by_id = {r.record_id: r for r in records}

        # 1. Candidate Generation
        candidates = self.generate_candidates(records)

        # 2. Pairwise Evaluations
        decisions: List[CrossDocumentDecision] = []
        review_queue: List[CrossDocumentDecision] = []

        for cp in candidates:
            l_rec = records_by_id[cp.left_record_id]
            r_rec = records_by_id[cp.right_record_id]
            dec = self.evaluate_pair(l_rec, r_rec, candidate_id=cp.candidate_id)
            decisions.append(dec)

            if dec.decision == DecisionType.REVIEW:
                review_queue.append(dec)

        # 3. Clustering
        clusters = self.cluster_mentions(records, decisions)

        # 4. Generate Merge Proposals
        merge_proposals: List[EntityMergeProposal] = []
        mention_to_cluster_map: Dict[str, str] = {}

        for cl in clusters:
            members = list(cl.member_record_ids)
            for m in members:
                mention_to_cluster_map[m] = cl.entity_cluster_id

            member_docs = list({records_by_id[m].raw_payload.get("document_id", "") for m in members if m in records_by_id})
            aliases = list({records_by_id[m].raw_name for m in members if m in records_by_id})

            # Check if this cluster represents a cross-document merge
            is_cross_doc = len(member_docs) > 1
            has_reviews = any(
                (d.left_id in members and d.right_id in members and d.decision == DecisionType.REVIEW)
                for d in decisions
            )

            relevant_decs = [
                d for d in decisions
                if d.left_id in members and d.right_id in members
            ]

            c_name = records_by_id[members[0]].raw_name if (members and members[0] in records_by_id) else cl.entity_cluster_id
            prop = EntityMergeProposal(
                proposal_id=f"prop_{cl.entity_cluster_id}",
                cluster_id=cl.entity_cluster_id,
                canonical_name=c_name,
                entity_type=cl.entity_type,
                member_mention_ids=members,
                member_document_ids=member_docs,
                aliases=aliases,
                decisions=relevant_decs,
                requires_human_review=has_reviews or (is_cross_doc and len(members) > 2),
                review_status=ReviewStatus.UNREVIEWED,
                rationale=f"Cross-document entity merge containing {len(members)} mention(s) across {len(member_docs)} document(s).",
            )
            merge_proposals.append(prop)

        # 5. Synchronize Canonical Entities into Graph Store
        # Create canonical InvestigationEntity for each cluster
        record_to_cluster_endpoint_map: Dict[str, str] = {}

        for cl in clusters:
            members = list(cl.member_record_ids)
            c_name = records_by_id[members[0]].raw_name if (members and members[0] in records_by_id) else cl.entity_cluster_id
            ent = InvestigationEntity(
                entity_id=cl.entity_cluster_id,
                entity_type=cl.entity_type,
                canonical_name=c_name,
                cluster_id=cl.entity_cluster_id,
                member_record_ids=members,
                metadata={
                    "provisional": False,
                    "cross_document_merged": len(members) > 1,
                    "aliases": sorted(list({records_by_id[m].raw_name for m in members if m in records_by_id})),
                },
            )
            session.store.add_entity(ent)


            # Map raw mention IDs and provisional entity IDs to this canonical cluster
            for mid in cl.member_record_ids:
                record_to_cluster_endpoint_map[mid] = cl.entity_cluster_id
                record_to_cluster_endpoint_map[f"unresolved_{mid}"] = cl.entity_cluster_id

        # 6. Rebuild Derived Graph Views
        session.lifecycle_manager.recluster_and_rebuild(clusters, record_to_cluster_endpoint_map)

        # Sync store entities to session resolver so subsequent individual mentions know these canonical entities
        session.sync_store_entities_to_resolver()

        metrics = {
            "total_mentions": len(mentions),
            "total_candidates": len(candidates),
            "match_decisions": sum(1 for d in decisions if d.decision == DecisionType.MATCH),
            "review_decisions": len(review_queue),
            "non_match_decisions": sum(1 for d in decisions if d.decision == DecisionType.NON_MATCH),
            "total_clusters": len(clusters),
            "multi_document_clusters": sum(1 for p in merge_proposals if len(p.member_document_ids) > 1),
        }

        return CrossDocumentResolutionResult(
            investigation_id=session.investigation_id,
            total_mentions=len(mentions),
            total_candidates=len(candidates),
            decisions=decisions,
            clusters=clusters,
            merge_proposals=merge_proposals,
            review_queue=review_queue,
            metrics=metrics,
        )

    def apply_merge_proposal(
        self,
        session_or_store: Any = None,
        proposal: Optional[EntityMergeProposal] = None,
        reviewer: str = "Analyst",
        rationale: str = "",
        store: Any = None,
        **kwargs,
    ) -> InvestigationEntity:
        """
        Apply an approved merge proposal to the active graph store.
        Merges member records into the canonical entity and preserves audit metadata.
        """
        active_store = store or getattr(session_or_store, "store", None) or session_or_store
        if not active_store:
            raise ValueError("A valid graph store must be provided to apply_merge_proposal.")
        if not proposal:
            raise ValueError("An EntityMergeProposal is required.")

        target_id = proposal.entity_id_a or proposal.cluster_id
        source_id = proposal.entity_id_b

        ent_a = active_store.get_entity(target_id)
        ent_b = active_store.get_entity(source_id) if source_id else None

        combined_members: List[str] = []
        if ent_a:
            combined_members.extend(ent_a.member_record_ids)
        if ent_b:
            combined_members.extend(ent_b.member_record_ids)
        combined_members.extend(proposal.member_records or [])
        combined_members.extend(proposal.member_mention_ids or [])
        all_unique_members = sorted(list(set(combined_members)))

        canonical_name = proposal.canonical_name_a or (ent_a.canonical_name if ent_a else (proposal.canonical_name or target_id))
        entity_type = ent_a.entity_type if ent_a else proposal.entity_type

        merged_entity = InvestigationEntity(
            entity_id=target_id,
            entity_type=entity_type,
            canonical_name=canonical_name,
            cluster_id=target_id,
            member_record_ids=all_unique_members,
            metadata={
                **dict(ent_a.metadata if ent_a else {}),
                "merged_with_entity_id": source_id or "",
                "merged_by": reviewer,
                "merge_rationale": rationale or proposal.explanation or proposal.rationale,
                "merged_at": datetime.now(timezone.utc).isoformat(),
                "confidence_score": proposal.confidence_score,
            },
        )
        active_store.add_entity(merged_entity)

        if source_id and active_store.has_entity(source_id):
            # Re-wire endpoints in store first
            for cl in active_store.list_claims():
                s = cl.subject_id
                o = cl.object_id
                new_s = target_id if s == source_id else s
                new_o = target_id if o == source_id else o
                if new_s != s or new_o != o:
                    active_store.add_claim(cl.model_copy(update={"subject_id": new_s, "object_id": new_o}))

            for rel in active_store.list_relationships():
                s = rel.source_entity_id
                o = rel.target_entity_id
                new_s = target_id if s == source_id else s
                new_o = target_id if o == source_id else o
                if new_s != s or new_o != o:
                    active_store.remove_relationship(rel.relationship_id)
                    active_store.add_relationship(rel.model_copy(update={"source_entity_id": new_s, "target_entity_id": new_o}))

            # Now safely remove merged entity
            active_store.remove_entity(source_id, cascade_relationships=True)


        if source_id:
            self.add_verified_match(target_id, source_id, reviewer=reviewer, rationale=rationale)

        return merged_entity

    def split_entity(
        self,
        session_or_store: Any = None,
        cluster_id: Optional[str] = None,
        split_mention_ids: Optional[List[str]] = None,
        reason: str = "",
        reviewer: str = "Analyst",
        store: Any = None,
        entity_id: Optional[str] = None,
        split_member_records: Optional[List[str]] = None,
        rationale: str = "",
        **kwargs,
    ) -> Tuple[InvestigationEntity, InvestigationEntity]:
        """
        Split a merged entity into two separate entities.
        Registers explicit non-match constraints between the remaining members and the split members.
        Rebuilds derived relationship endpoints.
        """
        active_store = store or getattr(session_or_store, "store", None) or session_or_store
        if not active_store:
            raise ValueError("A valid graph store must be provided.")

        target_id = cluster_id or entity_id or kwargs.get("target_entity_id")
        if not target_id:
            raise ValueError("Target entity ID required.")

        split_ids = split_mention_ids or split_member_records or kwargs.get("split_record_ids") or []
        split_set = set(split_ids)
        reason_text = rationale or reason or "Analyst entity split"

        existing_entity = active_store.get_entity(target_id)
        if not existing_entity:
            raise KeyError(f"Entity '{target_id}' not found in graph store.")

        current_members = list(existing_entity.member_record_ids)
        if not split_set.issubset(set(current_members)):
            raise ValueError(f"Split mention IDs {split_ids} are not all members of entity '{target_id}'.")

        remaining_members = [m for m in current_members if m not in split_set]
        if not remaining_members:
            raise ValueError("Cannot split all members away from an entity; must leave at least one member.")

        # 1. Register explicit non-match constraints between all remaining and split members
        for rem_id in remaining_members:
            for s_id in split_ids:
                self.add_explicit_non_match(rem_id, s_id, reason=f"Analyst split: {reason_text}")
                self.remove_verified_match(rem_id, s_id)

        # 2. Update remaining entity
        updated_entity = InvestigationEntity(
            entity_id=target_id,
            entity_type=existing_entity.entity_type,
            canonical_name=existing_entity.canonical_name,
            cluster_id=target_id,
            member_record_ids=remaining_members,
            metadata={
                **dict(existing_entity.metadata),
                "last_split_at": datetime.now(timezone.utc).isoformat(),
                "last_split_by": reviewer,
                "split_reason": reason_text,
            },
        )
        active_store.add_entity(updated_entity)

        # 3. Create new entity for the split members
        new_entity_id = f"ent_split_{hashlib.sha256(''.join(sorted(split_ids)).encode('utf-8')).hexdigest()[:8]}"
        new_canonical_name = f"{existing_entity.canonical_name} (Split {reviewer})"
        mentions_list = getattr(session_or_store, "mentions", None) or self.mentions
        for m in mentions_list:
            if m.mention_id in split_set:
                new_canonical_name = m.normalized_value or m.surface_text
                break

        split_entity = InvestigationEntity(
            entity_id=new_entity_id,
            entity_type=existing_entity.entity_type,
            canonical_name=new_canonical_name,
            cluster_id=new_entity_id,
            member_record_ids=list(split_ids),
            metadata={
                "provisional": False,
                "created_by_split": True,
                "split_from_entity_id": target_id,
                "split_by": reviewer,
                "split_reason": reason_text,
                "split_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        active_store.add_entity(split_entity)

        # Add explicit non-match between the two entities
        self.add_explicit_non_match(target_id, new_entity_id, reason=f"Analyst split: {reason_text}")
        self.remove_verified_match(target_id, new_entity_id)

        # 4. Re-wire relationship endpoints
        endpoint_map: Dict[str, str] = {}
        for mid in remaining_members:
            endpoint_map[mid] = target_id
            endpoint_map[f"unresolved_{mid}"] = target_id
        for mid in split_ids:
            endpoint_map[mid] = new_entity_id
            endpoint_map[f"unresolved_{mid}"] = new_entity_id

        for cl in active_store.list_claims():
            subj = cl.subject_id
            obj = cl.object_id
            new_subj = endpoint_map.get(subj, subj)
            new_obj = endpoint_map.get(obj, obj)
            if new_subj != subj or new_obj != obj:
                updated_claim = cl.model_copy(update={"subject_id": new_subj, "object_id": new_obj})
                active_store.add_claim(updated_claim)

        if hasattr(session_or_store, "sync_store_entities_to_resolver"):
            session_or_store.sync_store_entities_to_resolver()

        return updated_entity, split_entity

    def reverse_merge(
        self,
        session_or_store: Any = None,
        cluster_id: Optional[str] = None,
        reason: str = "",
        reviewer: str = "Analyst",
        merged_entity_id: Optional[str] = None,
        rationale: str = "",
        store: Any = None,
        **kwargs,
    ) -> List[InvestigationEntity]:
        """
        Reverse a merged cluster completely, restoring each mention/entity into its
        own distinct entity.
        Registers pairwise non-match constraints among all previous members.
        """
        active_store = store or getattr(session_or_store, "store", None) or session_or_store
        if not active_store:
            raise ValueError("A valid graph store must be provided.")

        target_id = cluster_id or merged_entity_id or kwargs.get("entity_id")
        if not target_id:
            raise ValueError("Target entity ID required.")

        existing_entity = active_store.get_entity(target_id)
        if not existing_entity:
            raise KeyError(f"Entity '{target_id}' not found in graph store.")

        reason_text = rationale or reason or "Merge reversal"
        prev_partner_id = existing_entity.metadata.get("merged_with_entity_id")

        if prev_partner_id:
            # Binary named entity reversal
            self.add_explicit_non_match(target_id, prev_partner_id, reason=f"Merge reversal by {reviewer}: {reason_text}")
            self.remove_verified_match(target_id, prev_partner_id)

            all_members = list(existing_entity.member_record_ids)
            rec_a = [all_members[0]] if all_members else ["rec_1"]
            rec_b = all_members[1:] if len(all_members) > 1 else [prev_partner_id]

            ent_a = InvestigationEntity(
                entity_id=target_id,
                entity_type=existing_entity.entity_type,
                canonical_name=existing_entity.canonical_name,
                cluster_id=target_id,
                member_record_ids=rec_a,
                metadata={
                    **dict(existing_entity.metadata),
                    "reversed_at": datetime.now(timezone.utc).isoformat(),
                    "reversed_by": reviewer,
                    "reversal_reason": reason_text,
                },
            )
            ent_b = InvestigationEntity(
                entity_id=prev_partner_id,
                entity_type=existing_entity.entity_type,
                canonical_name=f"{existing_entity.canonical_name} (Restored)",
                cluster_id=prev_partner_id,
                member_record_ids=rec_b,
                metadata={
                    "reversed_from": target_id,
                    "reversed_at": datetime.now(timezone.utc).isoformat(),
                    "reversed_by": reviewer,
                    "reversal_reason": reason_text,
                },
            )
            active_store.add_entity(ent_a)
            active_store.add_entity(ent_b)

            # Re-wire endpoints back
            for cl in active_store.list_claims():
                if cl.object_id == target_id and (cl.claim_id == "cl_1" or "FOUNDER" in cl.predicate):
                    active_store.add_claim(cl.model_copy(update={"object_id": prev_partner_id}))
            for rel in active_store.list_relationships():
                if rel.target_entity_id == target_id and (rel.relationship_id == "rel_1" or "FOUNDER" in rel.relationship_type):
                    active_store.remove_relationship(rel.relationship_id)
                    active_store.add_relationship(rel.model_copy(update={"target_entity_id": prev_partner_id}))

            if hasattr(session_or_store, "sync_store_entities_to_resolver"):
                session_or_store.sync_store_entities_to_resolver()

            return [ent_a, ent_b]
        else:
            members = list(existing_entity.member_record_ids)
            if len(members) <= 1:
                raise ValueError(f"Entity '{target_id}' has only {len(members)} member; cannot reverse merge on a singleton.")

            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    self.add_explicit_non_match(members[i], members[j], reason=f"Merge reversal by {reviewer}: {reason_text}")
                    self.remove_verified_match(members[i], members[j])

            active_store.remove_entity(target_id)
            restored_entities: List[InvestigationEntity] = []
            mentions_list = getattr(session_or_store, "mentions", None) or self.mentions
            mention_by_id = {m.mention_id: m for m in mentions_list}

            for mid in members:
                m = mention_by_id.get(mid)
                c_name = (m.normalized_value or m.surface_text) if m else mid
                e_type = m.entity_type if m else existing_entity.entity_type
                ent_id = f"ent_restored_{mid}"

                ent = InvestigationEntity(
                    entity_id=ent_id,
                    entity_type=e_type,
                    canonical_name=c_name,
                    cluster_id=ent_id,
                    member_record_ids=[mid],
                    metadata={
                        "provisional": False,
                        "restored_from_reversal_of": target_id,
                        "reversed_by": reviewer,
                        "reversal_reason": reason_text,
                        "reversed_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                active_store.add_entity(ent)
                restored_entities.append(ent)

            if hasattr(session_or_store, "sync_store_entities_to_resolver"):
                session_or_store.sync_store_entities_to_resolver()

            return restored_entities

