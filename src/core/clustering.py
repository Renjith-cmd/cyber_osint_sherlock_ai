"""
Constraint-aware, reversible clustering layer for entity resolution.

This module converts pairwise MatchDecision results into derived EntityCluster objects
while strictly preserving raw records and preventing unsafe transitive merges.

Design Principles:
1. Immutability & Non-Destruction: Raw Record objects are never merged, mutated, or deleted.
   Clusters are derived views that can be torn down and rebuilt reversibly at any time.
2. Contradiction Protection: Explicit NON_MATCH decisions, conflicting high-value identifiers,
   and incompatible entity types strictly prevent cluster merges.
3. Ambiguity Preservation: REVIEW decisions are never assumed to be MATCH edges. Missing comparisons
   are not treated as positive evidence.
4. Determinism & Traceability: Clusters have stable identifiers based on member record content,
   and every record assignment records supporting decisions and justification.
"""

from dataclasses import dataclass, field
import hashlib
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from src.core.comparison import PairwiseComparator
from src.core.models import (
    CandidatePair,
    ClusterStatus,
    DecisionType,
    EntityCluster,
    EntityType,
    MatchDecision,
    Record,
)


@dataclass(frozen=True)
class ClusteringPolicy:
    """
    Configuration parameters governing constraint-aware cluster formation.
    """
    allow_review_merges: bool = False
    require_full_clique: bool = False
    route_conflicting_identifiers_to_review: bool = False
    max_cluster_size: int = 100
    min_edge_score_for_merge: float = 0.50
    derivation_version: str = "sherlock_clustering_engine_v1"

    def __post_init__(self):
        if not (0.0 <= self.min_edge_score_for_merge <= 1.0):
            raise ValueError("min_edge_score_for_merge must be between 0.0 and 1.0")
        if self.max_cluster_size < 1:
            raise ValueError("max_cluster_size must be at least 1")


@dataclass(frozen=True)
class RejectedMerge:
    """
    Audit record describing a proposed merge between clusters that was blocked by constraints.
    """
    candidate_pair_id: Optional[str]
    left_record_id: str
    right_record_id: str
    left_cluster_id: str
    right_cluster_id: str
    rejection_reason: str
    conflicting_attribute: Optional[str] = None
    conflicting_decision: Optional[DecisionType] = None

    @property
    def reason(self) -> str:
        return self.rejection_reason

    @property
    def conflicting_record_ids(self) -> Tuple[str, str]:
        return (self.left_record_id, self.right_record_id)


@dataclass(frozen=True)
class ClusterAssignment:
    """
    Provenance explaining why a specific record belongs to a derived entity cluster.
    """
    record_id: str
    cluster_id: str
    justification: str
    supporting_decision_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ClusteringResult:
    """
    Comprehensive, immutable output of a constraint-aware clustering run.
    """
    clusters: Tuple[EntityCluster, ...]
    assignments: Mapping[str, ClusterAssignment]
    rejected_merges: Tuple[RejectedMerge, ...]
    unresolved_candidate_pairs: Tuple[str, ...]

    @property
    def record_to_cluster(self) -> Dict[str, str]:
        """Convenience lookup mapping record_id -> entity_cluster_id."""
        return {r_id: asgn.cluster_id for r_id, asgn in self.assignments.items()}

    @property
    def cluster_by_id(self) -> Dict[str, EntityCluster]:
        """Convenience lookup mapping entity_cluster_id -> EntityCluster."""
        return {c.entity_cluster_id: c for c in self.clusters}


class ConstraintAwareClusterer:
    """
    Generates derived EntityCluster instances from validated records and pairwise decisions.
    
    Prevents unsafe transitive merges through cross-member contradiction checks,
    entity-type compatibility enforcement, and explicit negative constraints.
    """

    def __init__(
        self,
        policy: Optional[ClusteringPolicy] = None,
        comparator: Optional[PairwiseComparator] = None,
    ):
        self.policy = policy or ClusteringPolicy()
        self.comparator = comparator or PairwiseComparator()

    @staticmethod
    def canonical_pair_key(id1: str, id2: str) -> str:
        """Returns deterministic, canonical pair key 'idA::idB' with idA <= idB."""
        left, right = sorted([id1, id2])
        return f"{left}::{right}"

    def _extract_pair_ids(
        self,
        d: MatchDecision,
        records_map: Mapping[str, Record],
        pair_by_id: Optional[Mapping[str, Tuple[str, str]]] = None,
    ) -> Optional[Tuple[str, str]]:
        """
        Robustly extracts the two participating record IDs from a MatchDecision.
        """
        if pair_by_id and d.candidate_pair_id in pair_by_id:
            return pair_by_id[d.candidate_pair_id]

        meta = d.explanation_metadata
        if isinstance(meta, (dict, Mapping)) and "left_record_id" in meta and "right_record_id" in meta:
            return str(meta["left_record_id"]), str(meta["right_record_id"])

        cid = d.candidate_pair_id
        if "::" in cid:
            parts = cid.split("::")
            if len(parts) == 2:
                return parts[0], parts[1]

        if cid.startswith("cp_"):
            tail = cid[3:]
            parts = tail.split("_")
            if len(parts) == 2 and parts[0] in records_map and parts[1] in records_map:
                return parts[0], parts[1]
            for r_id in records_map:
                if tail.startswith(f"{r_id}_"):
                    other_id = tail[len(r_id) + 1:]
                    if other_id in records_map:
                        return r_id, other_id
            if len(parts) == 2:
                return parts[0], parts[1]

        parts = cid.split("_")
        if len(parts) == 2:
            return parts[0], parts[1]

        return None

    def cluster(
        self,
        records: Union[Sequence[Record], Mapping[str, Record]],
        decisions: Sequence[MatchDecision],
        candidate_pairs: Optional[Sequence[CandidatePair]] = None,
    ) -> ClusteringResult:
        """
        Executes constraint-aware clustering over records and pairwise decisions.
        
        Guarantees deterministic, input-order-independent results.
        """
        if isinstance(records, Mapping):
            records_map: Dict[str, Record] = dict(records)
        else:
            records_map = {}
            for r in records:
                records_map.setdefault(r.record_id, r)

        if not records_map:
            return ClusteringResult(
                clusters=(),
                assignments={},
                rejected_merges=(),
                unresolved_candidate_pairs=(),
            )

        pair_by_id: Dict[str, Tuple[str, str]] = {}
        if candidate_pairs:
            for cp in candidate_pairs:
                pair_by_id[cp.candidate_id] = (cp.left_record_id, cp.right_record_id)

        # 1. Index decisions by canonical record pair key.
        # Priority rule: explicit NON_MATCH strictly takes precedence over any duplicate
        # decision for the same pair, regardless of input list order.
        decision_by_pair: Dict[str, MatchDecision] = {}
        for d in decisions:
            pair_ids = self._extract_pair_ids(d, records_map, pair_by_id)
            if pair_ids is not None:
                u, v = pair_ids
                if u in records_map and v in records_map:
                    pair_key = self.canonical_pair_key(u, v)
                    if pair_key in decision_by_pair:
                        existing = decision_by_pair[pair_key]
                        if existing.decision == DecisionType.NON_MATCH:
                            continue
                        elif d.decision == DecisionType.NON_MATCH:
                            decision_by_pair[pair_key] = d
                            continue
                        elif existing.decision == DecisionType.REVIEW and d.decision == DecisionType.MATCH:
                            decision_by_pair[pair_key] = existing
                            continue
                    decision_by_pair[pair_key] = d

        # 2. Initial state: Disjoint-set forest where every record starts in a singleton
        parent: Dict[str, str] = {r_id: r_id for r_id in records_map}
        cluster_members: Dict[str, Set[str]] = {r_id: {r_id} for r_id in records_map}
        cluster_decisions: Dict[str, Set[str]] = {r_id: set() for r_id in records_map}
        cluster_scores: Dict[str, List[float]] = {r_id: [] for r_id in records_map}
        cluster_has_review: Dict[str, bool] = {r_id: False for r_id in records_map}

        def find(item: str) -> str:
            root = item
            while parent[root] != root:
                root = parent[root]
            curr = item
            while curr != root:
                nxt = parent[curr]
                parent[curr] = root
                curr = nxt
            return root

        # 3. Filter and deterministically order positive edges
        positive_edges: List[Tuple[float, str, str, str, MatchDecision]] = []
        for d in decisions:
            is_match = (d.decision == DecisionType.MATCH)
            is_allowed_review = (d.decision == DecisionType.REVIEW and self.policy.allow_review_merges)
            if not (is_match or is_allowed_review):
                continue
            if d.score is not None and d.score < self.policy.min_edge_score_for_merge:
                continue

            pair_ids = self._extract_pair_ids(d, records_map, pair_by_id)
            if pair_ids is None:
                continue
            r_l, r_r = pair_ids
            if r_l not in records_map or r_r not in records_map:
                continue

            pair_key = self.canonical_pair_key(r_l, r_r)
            score = d.score if d.score is not None else (0.65 if is_allowed_review else 1.0)
            positive_edges.append((score, pair_key, r_l, r_r, d))

        # Sort descending by score, tie-break ascending by pair_key for input-order independence
        positive_edges.sort(key=lambda x: (-x[0], x[1]))

        # Deduplicate positive edges by pair_key to avoid double-processing or inflating weights
        seen_positive_pairs: Set[str] = set()
        deduped_positive_edges: List[Tuple[float, str, str, str, MatchDecision]] = []
        for edge_item in positive_edges:
            p_key = edge_item[1]
            if p_key in seen_positive_pairs:
                continue
            seen_positive_pairs.add(p_key)
            deduped_positive_edges.append(edge_item)
        positive_edges = deduped_positive_edges

        rejected_merges: List[RejectedMerge] = []
        unresolved_review_keys: Set[str] = set()

        # 4. Process candidate merges with constraint validation
        for score, pair_key, r_l, r_r, d in positive_edges:
            root_l = find(r_l)
            root_r = find(r_r)

            if root_l == root_r:
                cluster_decisions[root_l].add(d.candidate_pair_id)
                cluster_scores[root_l].append(score)
                if d.decision == DecisionType.REVIEW:
                    cluster_has_review[root_l] = True
                continue

            members_l = cluster_members[root_l]
            members_r = cluster_members[root_r]

            # Constraint Check A: Cluster Size Limit
            if len(members_l) + len(members_r) > self.policy.max_cluster_size:
                rejected_merges.append(
                    RejectedMerge(
                        candidate_pair_id=d.candidate_pair_id,
                        left_record_id=r_l,
                        right_record_id=r_r,
                        left_cluster_id=root_l,
                        right_cluster_id=root_r,
                        rejection_reason=f"Merged cluster size would exceed maximum limit of {self.policy.max_cluster_size}",
                    )
                )
                continue

            # Constraint Check B: Cross-Member Contradiction & Compatibility
            merge_permitted = True
            rejection_event: Optional[RejectedMerge] = None

            for u in sorted(list(members_l)):
                rec_u = records_map[u]
                for v in sorted(list(members_r)):
                    rec_v = records_map[v]

                    # 1. Entity Type Invariance
                    if rec_u.entity_type != rec_v.entity_type:
                        merge_permitted = False
                        rejection_event = RejectedMerge(
                            candidate_pair_id=d.candidate_pair_id,
                            left_record_id=u,
                            right_record_id=v,
                            left_cluster_id=root_l,
                            right_cluster_id=root_r,
                            rejection_reason=f"Incompatible entity types: '{rec_u.entity_type.value}' vs '{rec_v.entity_type.value}'",
                        )
                        break

                    uv_key = self.canonical_pair_key(u, v)
                    pair_decision = decision_by_pair.get(uv_key)

                    if pair_decision is not None:
                        # 2. Explicit NON_MATCH Decision
                        if pair_decision.decision == DecisionType.NON_MATCH:
                            merge_permitted = False
                            rejection_event = RejectedMerge(
                                candidate_pair_id=pair_decision.candidate_pair_id,
                                left_record_id=u,
                                right_record_id=v,
                                left_cluster_id=root_l,
                                right_cluster_id=root_r,
                                rejection_reason=f"Explicit NON_MATCH decision exists between member '{u}' and member '{v}'",
                                conflicting_decision=DecisionType.NON_MATCH,
                            )
                            break

                        # 3. Explicit REVIEW Decision
                        if pair_decision.decision == DecisionType.REVIEW and not self.policy.allow_review_merges:
                            merge_permitted = False
                            rejection_event = RejectedMerge(
                                candidate_pair_id=pair_decision.candidate_pair_id,
                                left_record_id=u,
                                right_record_id=v,
                                left_cluster_id=root_l,
                                right_cluster_id=root_r,
                                rejection_reason=f"Ambiguous REVIEW decision exists between member '{u}' and member '{v}'",
                                conflicting_decision=DecisionType.REVIEW,
                            )
                            unresolved_review_keys.add(pair_decision.candidate_pair_id)
                            break
                    else:
                        # 4. Missing Comparison: Do NOT assume match. Validate direct attribute conflicts
                        if self.policy.require_full_clique:
                            merge_permitted = False
                            rejection_event = RejectedMerge(
                                candidate_pair_id=None,
                                left_record_id=u,
                                right_record_id=v,
                                left_cluster_id=root_l,
                                right_cluster_id=root_r,
                                rejection_reason=f"Missing explicit MATCH decision between '{u}' and '{v}' required by full-clique policy",
                            )
                            break

                        comp_res = self.comparator.compare(rec_u, rec_v)
                        if comp_res.has_fatal_contradiction:
                            if self.policy.route_conflicting_identifiers_to_review:
                                if not self.policy.allow_review_merges:
                                    merge_permitted = False
                                    rejection_event = RejectedMerge(
                                        candidate_pair_id=None,
                                        left_record_id=u,
                                        right_record_id=v,
                                        left_cluster_id=root_l,
                                        right_cluster_id=root_r,
                                        rejection_reason=f"High-value attribute contradiction between '{u}' and '{v}' routed to review under unverified source uncertainty policy",
                                        conflicting_decision=DecisionType.REVIEW,
                                    )
                                    unresolved_review_keys.add(f"cp_{min(u, v)}_{max(u, v)}")
                                    break
                                else:
                                    # Allowed review merge: mark cluster as provisional
                                    unresolved_review_keys.add(f"cp_{min(u, v)}_{max(u, v)}")
                                    cluster_has_review[root_l] = True
                            else:
                                merge_permitted = False
                                rejection_event = RejectedMerge(
                                    candidate_pair_id=None,
                                    left_record_id=u,
                                    right_record_id=v,
                                    left_cluster_id=root_l,
                                    right_cluster_id=root_r,
                                    rejection_reason=f"High-value attribute contradiction between '{u}' and '{v}'",
                                    conflicting_decision=DecisionType.NON_MATCH,
                                )
                                break

                if not merge_permitted:
                    break

            if not merge_permitted and rejection_event is not None:
                rejected_merges.append(rejection_event)
                continue

            # Merge clusters
            merged_members = members_l | members_r
            merged_decisions = cluster_decisions[root_l] | cluster_decisions[root_r] | {d.candidate_pair_id}
            merged_scores = cluster_scores[root_l] + cluster_scores[root_r] + [score]
            merged_review = cluster_has_review[root_l] or cluster_has_review[root_r] or (d.decision == DecisionType.REVIEW)

            new_root = min(merged_members)
            parent[root_l] = new_root
            parent[root_r] = new_root
            parent[new_root] = new_root

            cluster_members[new_root] = merged_members
            cluster_decisions[new_root] = merged_decisions
            cluster_scores[new_root] = merged_scores
            cluster_has_review[new_root] = merged_review

            if root_l != new_root and root_l in cluster_members:
                del cluster_members[root_l]
            if root_r != new_root and root_r in cluster_members:
                del cluster_members[root_r]

        # 5. Build immutable EntityCluster objects and assignments
        final_clusters: List[EntityCluster] = []
        assignments: Dict[str, ClusterAssignment] = {}

        active_roots = sorted(list(cluster_members.keys()))

        for root in active_roots:
            members = sorted(list(cluster_members[root]))
            first_rec = records_map[members[0]]
            entity_type = first_rec.entity_type

            # Stable deterministic cluster ID: ec_{min_id}_{hash}
            hasher = hashlib.sha256("::".join(members).encode("utf-8")).hexdigest()[:8]
            cluster_id = f"ec_{members[0]}_{hasher}"

            dec_ids = sorted(list(cluster_decisions[root]))
            scores = cluster_scores[root]

            candidate_names = [records_map[m].raw_name for m in members if records_map[m].raw_name]
            canonical_name = max(candidate_names, key=len) if candidate_names else records_map[members[0]].raw_name

            min_score = min(scores) if scores else 1.0
            avg_score = (sum(scores) / len(scores)) if scores else 1.0

            # Clique completeness calculation
            pairwise_matches_in_cluster = 0
            total_possible_pairs = len(members) * (len(members) - 1) // 2
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    m_key = self.canonical_pair_key(members[i], members[j])
                    dec_m = decision_by_pair.get(m_key)
                    if dec_m is not None and dec_m.decision == DecisionType.MATCH:
                        pairwise_matches_in_cluster += 1

            is_full_clique = (pairwise_matches_in_cluster == total_possible_pairs)
            clique_ratio = round(pairwise_matches_in_cluster / total_possible_pairs, 4) if total_possible_pairs > 0 else 1.0

            confidence_meta = {
                "member_count": len(members),
                "is_singleton": len(members) == 1,
                "canonical_name": canonical_name,
                "supporting_decision_ids": dec_ids,
                "min_match_score": round(min_score, 4),
                "average_match_score": round(avg_score, 4),
                "is_full_clique": is_full_clique,
                "pairwise_match_edge_count": pairwise_matches_in_cluster,
                "possible_edge_count": total_possible_pairs,
                "clique_completeness_ratio": clique_ratio,
            }

            status = ClusterStatus.PROVISIONAL if cluster_has_review[root] else ClusterStatus.ACTIVE

            cluster = EntityCluster(
                entity_cluster_id=cluster_id,
                entity_type=entity_type,
                member_record_ids=members,
                status=status,
                quality_confidence_metadata=confidence_meta,
                derivation_version=self.policy.derivation_version,
            )
            final_clusters.append(cluster)

            for mid in members:
                if len(members) == 1:
                    justification = f"Singleton record '{mid}' (no valid merges)"
                elif is_full_clique:
                    justification = f"Cluster member in fully-supported pairwise clique via match decisions: {dec_ids}"
                else:
                    justification = (
                        f"Cluster member merged via path connectivity and cross-member consistency checks "
                        f"({pairwise_matches_in_cluster}/{total_possible_pairs} pairwise match edges); supporting decisions: {dec_ids}"
                    )

                assignments[mid] = ClusterAssignment(
                    record_id=mid,
                    cluster_id=cluster_id,
                    justification=justification,
                    supporting_decision_ids=tuple(dec_ids),
                )

        unresolved_reviews = [
            d.candidate_pair_id
            for d in decisions
            if d.decision == DecisionType.REVIEW
        ]
        all_unresolved = sorted(set(unresolved_reviews) | unresolved_review_keys)

        final_clusters.sort(key=lambda c: c.entity_cluster_id)

        return ClusteringResult(
            clusters=tuple(final_clusters),
            assignments=assignments,
            rejected_merges=tuple(rejected_merges),
            unresolved_candidate_pairs=tuple(all_unresolved),
        )

    def rebuild(
        self,
        records: Union[Sequence[Record], Mapping[str, Record]],
        updated_decisions: Sequence[MatchDecision],
        candidate_pairs: Optional[Sequence[CandidatePair]] = None,
    ) -> ClusteringResult:
        """
        Reconstructs all entity clusters from scratch given revised decisions.
        
        Guarantees complete reversibility: if a previously merged pair is marked
        as NON_MATCH, the cluster is immediately dissolved and reconstituted.
        """
        return self.cluster(records=records, decisions=updated_decisions, candidate_pairs=candidate_pairs)
