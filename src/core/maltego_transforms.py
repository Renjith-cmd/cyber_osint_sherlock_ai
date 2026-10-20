"""
Maltego-Inspired Graph Transforms, Network Analysis, and Suspicious Pattern Detection.
Provides graph exploration, relationship expansion, circular fund flow detection,
shell company clustering, and sanctions/PEP screening for Sherlock AI.
"""

from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple, Any
from pydantic import BaseModel, Field

from src.core.models import (
    InvestigationEntity,
    Relationship,
    EntityType,
    ReviewStatus,
    RelationshipEpistemicTier,
)


class SuspiciousPatternFinding(BaseModel):
    """Structured forensic finding of a detected network anomaly or suspicious pattern."""
    finding_id: str
    pattern_type: str  # CIRCULAR_FLOW, SHELL_CLUSTER, RAPID_DISPERSION, SHARED_OFFICER
    title: str
    severity: str  # "INFO", "MEDIUM", "HIGH"
    entities_involved: List[str]
    relationships_involved: List[str]
    description: str
    epistemic_disclaimer: str = (
        "Forensic algorithmic detection only. Demonstrates network topology and flow symmetry; "
        "does not establish legal wrongdoing, guilt, or illicit intent without independent corroboration."
    )
    metrics: Dict[str, Any] = Field(default_factory=dict)


class MaltegoTransformResult(BaseModel):
    """Result of running a Maltego-style transform on an entity."""
    transform_name: str
    source_entity_id: str
    added_entities: List[Dict[str, Any]]
    added_relationships: List[Dict[str, Any]]
    summary: str


class SanctionsHit(BaseModel):
    """Sanctions and PEP screening match record."""
    entity_name: str
    matched_name: str
    similarity_score: float
    list_name: str  # e.g., OFAC SDN, EU Consolidated, UN Sanctions, PEP
    category: str  # SANCTIONED_ENTITY, PEP, WATCHLIST
    authority: str
    reason: str
    source_url: Optional[str] = None


# Reference dataset of international sanctions & PEP entries for offline screening
REFERENCE_SANCTIONS_LIST = [
    {
        "name": "Apex Holdings Offshore Ltd",
        "aliases": ["Apex Offshore", "Apex Holdings Ltd"],
        "category": "WATCHLIST",
        "list_name": "Offshore Secrecy Jurisdiction Entity",
        "authority": "Financial Conduct Watch",
        "reason": "Entity identified in Panama/BVI registry leaks with bearer shares",
    },
    {
        "name": "Meridian Capital Trust",
        "aliases": ["Meridian Trust", "MCT Overseas"],
        "category": "SANCTIONED_ENTITY",
        "list_name": "OFAC Specially Designated Nationals (Simulated Reference)",
        "authority": "US Treasury / EU Sanctions List",
        "reason": "Designated for illicit proliferation financing networks",
    },
    {
        "name": "Viktor Vance",
        "aliases": ["Victor Vance", "V. Vance"],
        "category": "PEP",
        "list_name": "Politically Exposed Persons Registry",
        "authority": "Global PEP Watch",
        "reason": "Former Deputy Minister of Trade & Natural Resources",
    },
    {
        "name": "Global Horizon Trade Corp",
        "aliases": ["Horizon Global Trading", "GHT Corp"],
        "category": "SANCTIONED_ENTITY",
        "list_name": "EU Consolidated Sanctions List",
        "authority": "European External Action Service",
        "reason": "Subject to restrictive measures regarding trade circumvention",
    },
    {
        "name": "Elena Rostova",
        "aliases": ["Elena Rostov", "Helena Rostova"],
        "category": "PEP",
        "list_name": "Politically Exposed Persons Registry",
        "authority": "State Commercial Oversight Agency",
        "reason": "Close associate of state energy conglomerate board member",
    },
    {
        "name": "Guptov Capital Limited",
        "aliases": ["Guptov Capital", "Guptov Holdings"],
        "category": "SANCTIONED_ENTITY",
        "list_name": "OFAC Specially Designated Nationals (Simulated Reference)",
        "authority": "US Department of the Treasury (OFAC)",
        "reason": "Designated for illicit state-sponsored financial facilitation networks",
    },
]


class MaltegoTransformEngine:
    """
    Maltego-inspired transform execution engine and graph pattern detector.
    """

    def __init__(self, store: Any):
        self.store = store

    def expand_neighbors(
        self,
        entity_id: str,
        direction: str = "both",  # "out", "in", "both"
        max_depth: int = 1,
    ) -> MaltegoTransformResult:
        """
        Maltego Transform: 'To Related Entities'
        Expands all adjacent entities and relationships within max_depth hops.
        """
        all_entities = {e.entity_id: e for e in self.store.list_entities()}
        all_rels = self.store.list_relationships()

        visited_entities: Set[str] = {entity_id}
        result_entities: Dict[str, Dict[str, Any]] = {}
        result_rels: List[Dict[str, Any]] = []

        queue = deque([(entity_id, 0)])

        while queue:
            curr_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            for rel in all_rels:
                matched = False
                neighbor_id = None

                if direction in ("out", "both") and rel.source_entity_id == curr_id:
                    matched = True
                    neighbor_id = rel.target_entity_id
                elif direction in ("in", "both") and rel.target_entity_id == curr_id:
                    matched = True
                    neighbor_id = rel.source_entity_id

                if matched and neighbor_id:
                    rel_dict = {
                        "relationship_id": rel.relationship_id,
                        "source": rel.source_entity_id,
                        "target": rel.target_entity_id,
                        "type": rel.relationship_type,
                        "tier": rel.epistemic_tier.value if hasattr(rel.epistemic_tier, "value") else str(rel.epistemic_tier),
                        "review_status": rel.review_status.value if hasattr(rel.review_status, "value") else str(rel.review_status),
                    }
                    if rel_dict not in result_rels:
                        result_rels.append(rel_dict)

                    if neighbor_id not in visited_entities:
                        visited_entities.add(neighbor_id)
                        queue.append((neighbor_id, depth + 1))
                        if neighbor_id in all_entities:
                            ent = all_entities[neighbor_id]
                            result_entities[neighbor_id] = {
                                "entity_id": ent.entity_id,
                                "name": ent.canonical_name,
                                "type": ent.entity_type.value if hasattr(ent.entity_type, "value") else str(ent.entity_type),
                            }

        return MaltegoTransformResult(
            transform_name="Expand Neighbors",
            source_entity_id=entity_id,
            added_entities=list(result_entities.values()),
            added_relationships=result_rels,
            summary=f"Found {len(result_entities)} connected entities and {len(result_rels)} relationships.",
        )

    def trace_ownership_chain(
        self,
        entity_id: str,
        max_depth: int = 6,
    ) -> MaltegoTransformResult:
        """
        Maltego Transform: 'To Ownership Chain'
        Traces parent holding entities, subsidiaries, and beneficial owners.
        """
        ownership_predicates = {
            "OWNS", "BENEFICIAL_OWNER_OF", "SUBSIDIARY_OF", "CONTROLS",
            "PARENT_COMPANY_OF", "HOLDING_COMPANY_OF", "INVESTED_IN",
        }
        all_entities = {e.entity_id: e for e in self.store.list_entities()}
        all_rels = self.store.list_relationships()

        result_entities: Dict[str, Dict[str, Any]] = {}
        result_rels: List[Dict[str, Any]] = []
        visited = {entity_id}
        queue = deque([(entity_id, 0)])

        while queue:
            curr_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            for rel in all_rels:
                pred = rel.relationship_type.upper()
                if pred not in ownership_predicates:
                    continue

                neighbor_id = None
                if rel.source_entity_id == curr_id:
                    neighbor_id = rel.target_entity_id
                elif rel.target_entity_id == curr_id:
                    neighbor_id = rel.source_entity_id

                if neighbor_id:
                    rel_dict = {
                        "relationship_id": rel.relationship_id,
                        "source": rel.source_entity_id,
                        "target": rel.target_entity_id,
                        "type": rel.relationship_type,
                    }
                    if rel_dict not in result_rels:
                        result_rels.append(rel_dict)

                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        queue.append((neighbor_id, depth + 1))
                        if neighbor_id in all_entities:
                            ent = all_entities[neighbor_id]
                            result_entities[neighbor_id] = {
                                "entity_id": ent.entity_id,
                                "name": ent.canonical_name,
                                "type": ent.entity_type.value if hasattr(ent.entity_type, "value") else str(ent.entity_type),
                            }

        return MaltegoTransformResult(
            transform_name="Trace Ownership Chain",
            source_entity_id=entity_id,
            added_entities=list(result_entities.values()),
            added_relationships=result_rels,
            summary=f"Traced ownership chain with {len(result_entities)} entities across {len(result_rels)} ownership links.",
        )

    def trace_financial_transactions(
        self,
        entity_id: str,
        max_depth: int = 4,
    ) -> MaltegoTransformResult:
        """
        Maltego Transform: 'To Financial Transactions'
        Traces monetary flows, wire payments, account transfers, and circular loops.
        """
        transaction_predicates = {
            "TRANSFERRED_FUNDS_TO", "PAID", "PAYMENT_TO", "WIRED_TO", "FUNDED",
            "TRANSFERRED_TO", "SENT_FUNDS_TO", "RECEIVED_FUNDS_FROM",
        }
        all_entities = {e.entity_id: e for e in self.store.list_entities()}
        all_rels = self.store.list_relationships()

        result_entities: Dict[str, Dict[str, Any]] = {}
        result_rels: List[Dict[str, Any]] = []
        visited = {entity_id}
        queue = deque([(entity_id, 0)])

        while queue:
            curr_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            for rel in all_rels:
                pred = rel.relationship_type.upper()
                if pred not in transaction_predicates and "TRANSFER" not in pred and "PAY" not in pred:
                    continue

                neighbor_id = None
                if rel.source_entity_id == curr_id:
                    neighbor_id = rel.target_entity_id
                elif rel.target_entity_id == curr_id:
                    neighbor_id = rel.source_entity_id

                if neighbor_id:
                    rel_dict = {
                        "relationship_id": rel.relationship_id,
                        "source": rel.source_entity_id,
                        "target": rel.target_entity_id,
                        "type": rel.relationship_type,
                    }
                    if rel_dict not in result_rels:
                        result_rels.append(rel_dict)

                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        queue.append((neighbor_id, depth + 1))
                        if neighbor_id in all_entities:
                            ent = all_entities[neighbor_id]
                            result_entities[neighbor_id] = {
                                "entity_id": ent.entity_id,
                                "name": ent.canonical_name,
                                "type": ent.entity_type.value if hasattr(ent.entity_type, "value") else str(ent.entity_type),
                            }

        return MaltegoTransformResult(
            transform_name="Trace Financial Transactions",
            source_entity_id=entity_id,
            added_entities=list(result_entities.values()),
            added_relationships=result_rels,
            summary=f"Traced {len(result_rels)} transactions touching {len(result_entities)} entities.",
        )

    def detect_circular_financial_flows(self) -> List[SuspiciousPatternFinding]:
        """
        Forensic link analysis: Detects circular transactions (A -> B -> C -> A)
        or circular control loops in the investigation knowledge graph.
        """
        all_entities = {e.entity_id: e for e in self.store.list_entities()}
        all_rels = self.store.list_relationships()

        transaction_predicates = {
            "TRANSFERRED_FUNDS_TO", "PAID", "PAYMENT_TO", "WIRED_TO", "FUNDED",
            "TRANSFERRED_TO", "SENT_FUNDS_TO", "OWNS", "CONTROLS", "SUBSIDIARY_OF",
        }

        # Build directed graph
        adj: Dict[str, List[Tuple[str, str, str]]] = {}  # u -> list of (v, rel_id, rel_type)
        for rel in all_rels:
            pred = rel.relationship_type.upper()
            if pred in transaction_predicates or "TRANSFER" in pred or "PAY" in pred or "OWN" in pred:
                src = rel.source_entity_id
                tgt = rel.target_entity_id
                if src not in adj:
                    adj[src] = []
                adj[src].append((tgt, rel.relationship_id, rel.relationship_type))

        findings: List[SuspiciousPatternFinding] = []
        visited_cycles: Set[Tuple[str, ...]] = set()

        # Simple cycle detection using DFS
        def dfs(start: str, current: str, path: List[str], rel_path: List[str], max_len: int = 6):
            if len(path) > max_len:
                return

            for neighbor, rel_id, rel_type in adj.get(current, []):
                if neighbor == start and len(path) >= 2:
                    # Found a cycle! Normalize cycle order
                    cycle_nodes = path[:]
                    min_idx = cycle_nodes.index(min(cycle_nodes))
                    normalized_cycle = tuple(cycle_nodes[min_idx:] + cycle_nodes[:min_idx])
                    if normalized_cycle not in visited_cycles:
                        visited_cycles.add(normalized_cycle)

                        entity_names = [all_entities.get(nid, InvestigationEntity(entity_id=nid, canonical_name=nid, entity_type=EntityType.ORGANIZATION)).canonical_name for nid in cycle_nodes]
                        cycle_desc = " ➔ ".join(entity_names) + f" ➔ {entity_names[0]}"

                        findings.append(SuspiciousPatternFinding(
                            finding_id=f"circ_flow_{len(findings)+1}",
                            pattern_type="CIRCULAR_FLOW",
                            title=f"Circular Transaction or Control Loop ({len(cycle_nodes)} Hops)",
                            severity="HIGH" if len(cycle_nodes) <= 4 else "MEDIUM",
                            entities_involved=cycle_nodes,
                            relationships_involved=rel_path + [rel_id],
                            description=(
                                f"A closed financial or control loop was detected across {len(cycle_nodes)} entities: "
                                f"{cycle_desc}. Circular topologies can indicate round-tripping, carousel transactions, "
                                f"or layered corporate veil insulation."
                            ),
                            metrics={
                                "hop_count": len(cycle_nodes),
                                "flow_sequence": entity_names,
                            },
                        ))
                elif neighbor not in path and len(path) < max_len:
                    dfs(start, neighbor, path + [neighbor], rel_path + [rel_id], max_len)

        for node_id in adj:
            dfs(node_id, node_id, [node_id], [], max_len=5)

        return findings

    def detect_shell_company_clusters(self) -> List[SuspiciousPatternFinding]:
        """
        Forensic link analysis: Detects clusters of multiple corporate entities
        sharing the same registered address, registered agent, or nominee director.
        """
        all_entities = {e.entity_id: e for e in self.store.list_entities()}
        all_rels = self.store.list_relationships()

        # Group companies by shared address or shared director
        shared_address_map: Dict[str, List[str]] = {}
        shared_director_map: Dict[str, List[str]] = {}
        rel_evidence_map: Dict[str, List[str]] = {}

        for rel in all_rels:
            pred = rel.relationship_type.upper()
            if pred in ("LOCATED_IN", "REGISTERED_AT", "SHARES_ADDRESS_WITH"):
                addr = rel.target_entity_id
                shared_address_map.setdefault(addr, []).append(rel.source_entity_id)
                rel_evidence_map.setdefault(addr, []).append(rel.relationship_id)
            elif pred in ("DIRECTOR_OF", "MANAGING_DIRECTOR_OF", "OFFICER_OF", "CONTROLS"):
                director = rel.source_entity_id
                company = rel.target_entity_id
                shared_director_map.setdefault(director, []).append(company)
                rel_evidence_map.setdefault(director, []).append(rel.relationship_id)

        findings: List[SuspiciousPatternFinding] = []

        # 1. Flag addresses with >= 3 distinct registered entities
        for addr_id, comp_ids in shared_address_map.items():
            unique_comps = list(set(comp_ids))
            if len(unique_comps) >= 2:
                addr_name = all_entities.get(addr_id, InvestigationEntity(entity_id=addr_id, canonical_name=addr_id, entity_type=EntityType.LOCATION)).canonical_name
                comp_names = [all_entities.get(cid, InvestigationEntity(entity_id=cid, canonical_name=cid, entity_type=EntityType.ORGANIZATION)).canonical_name for cid in unique_comps]
                findings.append(SuspiciousPatternFinding(
                    finding_id=f"shell_cluster_addr_{len(findings)+1}",
                    pattern_type="SHELL_CLUSTER",
                    title=f"Shared Registered Address Cluster ({len(unique_comps)} Entities)",
                    severity="MEDIUM" if len(unique_comps) < 4 else "HIGH",
                    entities_involved=unique_comps + [addr_id],
                    relationships_involved=rel_evidence_map.get(addr_id, []),
                    description=(
                        f"Location '{addr_name}' serves as the registered address for {len(unique_comps)} distinct entities "
                        f"({', '.join(comp_names)}). Shared corporate service addresses are common in shell company formation "
                        f"and secrecy jurisdictions."
                    ),
                    metrics={
                        "company_count": len(unique_comps),
                        "address": addr_name,
                        "companies": comp_names,
                    },
                ))

        # 2. Flag officers who direct >= 3 corporate entities
        for dir_id, comp_ids in shared_director_map.items():
            unique_comps = list(set(comp_ids))
            if len(unique_comps) >= 2:
                dir_name = all_entities.get(dir_id, InvestigationEntity(entity_id=dir_id, canonical_name=dir_id, entity_type=EntityType.PERSON)).canonical_name
                comp_names = [all_entities.get(cid, InvestigationEntity(entity_id=cid, canonical_name=cid, entity_type=EntityType.ORGANIZATION)).canonical_name for cid in unique_comps]
                findings.append(SuspiciousPatternFinding(
                    finding_id=f"shared_director_{len(findings)+1}",
                    pattern_type="SHARED_OFFICER",
                    title=f"Common Corporate Officer / Director ({len(unique_comps)} Entities)",
                    severity="MEDIUM",
                    entities_involved=unique_comps + [dir_id],
                    relationships_involved=rel_evidence_map.get(dir_id, []),
                    description=(
                        f"Individual '{dir_name}' is recorded as an officer/director across {len(unique_comps)} separate corporate entities "
                        f"({', '.join(comp_names)}). Multiple directorships can indicate professional nominee services or centralized control."
                    ),
                    metrics={
                        "directorship_count": len(unique_comps),
                        "officer": dir_name,
                        "companies": comp_names,
                    },
                ))

        return findings

    def find_shortest_path(self, source_entity_id: str, target_entity_id: str) -> Optional[Dict[str, Any]]:
        """
        Finds the shortest investigative path between two entities using BFS.
        Returns the ordered list of entities and connecting relationships.
        """
        all_entities = {e.entity_id: e for e in self.store.list_entities()}
        all_rels = self.store.list_relationships()

        adj: Dict[str, List[Tuple[str, Any]]] = {}
        for rel in all_rels:
            adj.setdefault(rel.source_entity_id, []).append((rel.target_entity_id, rel))
            adj.setdefault(rel.target_entity_id, []).append((rel.source_entity_id, rel))

        queue = deque([(source_entity_id, [source_entity_id], [])])
        visited = {source_entity_id}

        while queue:
            curr_id, path, rel_path = queue.popleft()
            if curr_id == target_entity_id:
                path_entities = [
                    {
                        "entity_id": eid,
                        "name": all_entities[eid].canonical_name if eid in all_entities else eid,
                        "type": all_entities[eid].entity_type.value if eid in all_entities and hasattr(all_entities[eid].entity_type, "value") else "UNKNOWN",
                    }
                    for eid in path
                ]
                return {
                    "source": source_entity_id,
                    "target": target_entity_id,
                    "length": len(path) - 1,
                    "path_entity_ids": path,
                    "entities": path_entities,
                    "relationships": [
                        {
                            "relationship_id": r.relationship_id,
                            "source": r.source_entity_id,
                            "target": r.target_entity_id,
                            "type": r.relationship_type,
                        }
                        for r in rel_path
                    ],
                }

            for neighbor, rel in adj.get(curr_id, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor], rel_path + [rel]))

        return None

    def screen_entity_against_sanctions(self, entity_name: str) -> List[SanctionsHit]:
        """
        Screens an entity name against the reference open sanctions & PEP watchlist
        using fuzzy string comparison and exact token matching.
        """
        from src.core.normalization import normalize_text, tokenize_name
        hits: List[SanctionsHit] = []

        norm_query = normalize_text(entity_name)
        tokens_query = set(tokenize_name(norm_query))

        for entry in REFERENCE_SANCTIONS_LIST:
            names_to_check = [entry["name"]] + entry.get("aliases", [])
            best_score = 0.0
            matched_candidate = entry["name"]

            for candidate in names_to_check:
                norm_cand = normalize_text(candidate)
                if norm_query == norm_cand:
                    best_score = 1.0
                    matched_candidate = candidate
                    break

                cand_tokens = set(tokenize_name(norm_cand))
                if tokens_query and cand_tokens:
                    # Token overlap
                    overlap = len(tokens_query & cand_tokens) / max(len(tokens_query), len(cand_tokens))
                    if overlap > best_score:
                        best_score = overlap
                        matched_candidate = candidate

            if best_score >= 0.70:
                hits.append(SanctionsHit(
                    entity_name=entity_name,
                    matched_name=matched_candidate,
                    similarity_score=round(best_score, 3),
                    list_name=entry["list_name"],
                    category=entry["category"],
                    authority=entry["authority"],
                    reason=entry["reason"],
                ))

        return hits
