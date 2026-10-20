"""
Unit and Integration Tests for Sherlock AI Maltego Transforms and Suspicious Pattern Detection.
Verifies:
- CSV document ingestion and offset provenance
- Graph expansion and neighbor discovery
- Ownership chain tracing (parent/subsidiary/beneficial owner)
- Financial transaction flow tracing
- Circular financial flow (cycle detection)
- Shell company cluster detection (shared address, nominee director)
- Shortest path exploration
- Sanctions screening
- Transform API endpoints
"""

import pytest
from starlette.testclient import TestClient

from src.core.document_ingestion import CsvDocumentParser, DocumentFormat
from src.core.models import (
    InvestigationEntity,
    Relationship,
    EntityType,
    ReviewStatus,
    RelationshipEpistemicTier,
)
from src.core.investigation_graph import InMemoryInvestigationGraphStore
from src.core.maltego_transforms import MaltegoTransformEngine
from src.core.investigation_service import InvestigationOrchestrator
from src.core.investigation_sqlite import SQLiteInvestigationStore
from src.api.app import create_app


def test_csv_document_parser():
    """Verify CSV document parsing extracts rows, headers, and offset spans."""
    csv_bytes = (
        b"date,sender,receiver,amount,currency,notes\n"
        b"2026-03-01,Apex Capital LLC,Cyprus Holdings Ltd,1500000,USD,Investment tranche 1\n"
        b"2026-03-05,Cyprus Holdings Ltd,BVI Shell Inc,1480000,USD,Consulting fee\n"
        b"2026-03-10,BVI Shell Inc,Apex Capital LLC,1450000,USD,Repatriated dividend\n"
    )

    parser = CsvDocumentParser()
    doc = parser.parse(csv_bytes, source_name="transactions_ledger.csv")

    assert doc.source_name == "transactions_ledger.csv"
    assert doc.format == DocumentFormat.CSV
    assert doc.page_count == 3  # 3 data rows
    assert "Apex Capital LLC" in doc.normalized_text
    assert "Cyprus Holdings Ltd" in doc.normalized_text
    assert len(doc.page_offsets) == 3


def test_maltego_transform_engine_expansions_and_patterns():
    """Verify Maltego transform operations on an investigation graph."""
    store = InMemoryInvestigationGraphStore()

    # Add entities
    e_apex = "ent_apex"
    e_cyprus = "ent_cyprus"
    e_bvi = "ent_bvi"
    e_director = "ent_director_smith"
    e_addr = "ent_addr_tortola"

    store.add_entity(InvestigationEntity(
        entity_id=e_apex,
        entity_type=EntityType.ORGANIZATION,
        canonical_name="Apex Capital LLC",
    ))
    store.add_entity(InvestigationEntity(
        entity_id=e_cyprus,
        entity_type=EntityType.ORGANIZATION,
        canonical_name="Cyprus Holdings Ltd",
    ))
    store.add_entity(InvestigationEntity(
        entity_id=e_bvi,
        entity_type=EntityType.ORGANIZATION,
        canonical_name="BVI Shell Inc",
    ))
    store.add_entity(InvestigationEntity(
        entity_id=e_director,
        entity_type=EntityType.PERSON,
        canonical_name="John Smith",
    ))
    store.add_entity(InvestigationEntity(
        entity_id=e_addr,
        entity_type=EntityType.LOCATION,
        canonical_name="PO Box 123, Road Town, Tortola",
    ))

    # Add financial transfer edges: Apex -> Cyprus -> BVI -> Apex (Circular loop!)
    store.add_relationship(Relationship(
        relationship_id="edge_t1",
        source_entity_id=e_apex,
        target_entity_id=e_cyprus,
        relationship_type="TRANSFERRED_FUNDS_TO",
    ))
    store.add_relationship(Relationship(
        relationship_id="edge_t2",
        source_entity_id=e_cyprus,
        target_entity_id=e_bvi,
        relationship_type="TRANSFERRED_FUNDS_TO",
    ))
    store.add_relationship(Relationship(
        relationship_id="edge_t3",
        source_entity_id=e_bvi,
        target_entity_id=e_apex,
        relationship_type="TRANSFERRED_FUNDS_TO",
    ))

    # Add nominee director to multiple entities: John Smith directs Cyprus & BVI
    store.add_relationship(Relationship(
        relationship_id="edge_d1",
        source_entity_id=e_director,
        target_entity_id=e_cyprus,
        relationship_type="DIRECTOR_OF",
    ))
    store.add_relationship(Relationship(
        relationship_id="edge_d2",
        source_entity_id=e_director,
        target_entity_id=e_bvi,
        relationship_type="DIRECTOR_OF",
    ))

    # Add shared address: Cyprus & BVI located at same Tortola PO Box
    store.add_relationship(Relationship(
        relationship_id="edge_a1",
        source_entity_id=e_cyprus,
        target_entity_id=e_addr,
        relationship_type="LOCATED_IN",
    ))
    store.add_relationship(Relationship(
        relationship_id="edge_a2",
        source_entity_id=e_bvi,
        target_entity_id=e_addr,
        relationship_type="LOCATED_IN",
    ))

    # Add ownership: Apex OWNS Cyprus
    store.add_relationship(Relationship(
        relationship_id="edge_o1",
        source_entity_id=e_apex,
        target_entity_id=e_cyprus,
        relationship_type="OWNS",
    ))

    engine = MaltegoTransformEngine(store)

    # 1. Expand Neighbors
    neighbors = engine.expand_neighbors(e_apex, max_depth=1)
    node_names = [n["name"] for n in neighbors.added_entities]
    assert "Cyprus Holdings Ltd" in node_names
    assert "BVI Shell Inc" in node_names

    # 2. Trace Ownership Chain
    ownership = engine.trace_ownership_chain(e_apex)
    assert len(ownership.added_relationships) >= 1
    assert ownership.added_relationships[0]["type"] == "OWNS"

    # 3. Trace Financial Transactions
    tx_flow = engine.trace_financial_transactions(e_apex)
    assert len(tx_flow.added_relationships) >= 2

    # 4. Circular Financial Flow Detection
    circular_patterns = engine.detect_circular_financial_flows()
    assert len(circular_patterns) >= 1
    first_cycle = circular_patterns[0]
    assert first_cycle.pattern_type == "CIRCULAR_FLOW"
    assert "Apex Capital LLC" in first_cycle.description
    # Epistemic check: objective typology without unsupported criminal declarations
    assert "circular" in first_cycle.title.lower()
    assert "guilt" in first_cycle.epistemic_disclaimer.lower()

    # 5. Shell Company Cluster Detection
    shell_clusters = engine.detect_shell_company_clusters()
    assert len(shell_clusters) >= 2
    cluster_types = [c.pattern_type for c in shell_clusters]
    assert "SHELL_CLUSTER" in cluster_types
    assert "SHARED_OFFICER" in cluster_types

    # 6. Shortest Path Exploration
    path = engine.find_shortest_path(e_apex, e_addr)
    assert path is not None
    assert path["length"] == 2
    assert path["path_entity_ids"] == [e_apex, e_cyprus, e_addr]

    # 7. Sanctions Screening
    # Test screening a sanctioned name
    sanction_res = engine.screen_entity_against_sanctions("OFAC Nonexistent Clean Entity")
    assert len(sanction_res) == 0
    # Test entity with known simulated watch name
    v_hit = engine.screen_entity_against_sanctions("Guptov Capital Limited")
    assert len(v_hit) >= 1
    assert v_hit[0].matched_name == "Guptov Capital Limited"
    assert v_hit[0].authority == "US Department of the Treasury (OFAC)"


def test_transform_api_endpoints(tmp_path):
    """Verify HTTP API endpoints for Maltego transforms and suspicious pattern detection."""
    db_file = str(tmp_path / "test_transforms.db")
    app = create_app(db_path=db_file, backend_mode="rule", disable_auth=False)
    client = TestClient(app)

    # Register analyst
    reg_resp = client.post(
        "/api/v1/auth/register",
        json={"username": "forensic_analyst", "email": "analyst@firm.org", "password": "SecuredPassword99"},
    )
    token = reg_resp.json()["access_token"]
    auth_header = {"Authorization": f"Bearer {token}"}

    # Create case
    case_id = "case_fin_fraud_001"
    create_resp = client.post(
        "/api/v1/investigations",
        json={"investigation_id": case_id, "description": "Offshore Flow Trace"},
        headers=auth_header,
    )
    assert create_resp.status_code == 201

    # Upload CSV transaction ledger
    csv_payload = (
        b"date,sender,receiver,amount,currency\n"
        b"2026-01-10,Alpha Fund,Beta Holdings,2000000,USD\n"
        b"2026-01-12,Beta Holdings,Gamma Trade,1950000,USD\n"
        b"2026-01-15,Gamma Trade,Alpha Fund,1900000,USD\n"
    )
    up_resp = client.post(
        f"/api/v1/investigations/{case_id}/documents",
        files={"file": ("ledger.csv", csv_payload, "text/csv")},
        data={"auto_process": "true"},
        headers=auth_header,
    )
    assert up_resp.status_code == 201

    # Fetch investigation graph
    g_resp = client.get(f"/api/v1/investigations/{case_id}/graph", headers=auth_header)
    assert g_resp.status_code == 200
    nodes = g_resp.json()["nodes"]
    assert len(nodes) >= 2

    # Run suspicious patterns endpoint
    patterns_resp = client.post(
        f"/api/v1/investigations/{case_id}/transforms/suspicious-patterns",
        json={"scan_types": ["circular_flows", "shell_clusters"]},
        headers=auth_header,
    )
    assert patterns_resp.status_code == 200
    p_data = patterns_resp.json()
    assert "circular_flows" in p_data
    assert "shell_company_clusters" in p_data
    assert "summary" in p_data

    # Test Sanctions screening endpoint
    screen_resp = client.post(
        f"/api/v1/investigations/{case_id}/transforms/sanctions-screen",
        json={"entity_name": "Guptov Capital Limited"},
        headers=auth_header,
    )
    assert screen_resp.status_code == 200
    assert screen_resp.json()["is_flagged"] is True

    # Test Shortest path endpoint with available nodes
    if len(nodes) >= 2:
        src_id = nodes[0]["id"]
        tgt_id = nodes[1]["id"]
        path_resp = client.post(
            f"/api/v1/investigations/{case_id}/transforms/shortest-path",
            json={"source_node_id": src_id, "target_node_id": tgt_id},
            headers=auth_header,
        )
        assert path_resp.status_code == 200
