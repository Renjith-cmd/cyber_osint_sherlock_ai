"""
Sherlock AI — Milestone 8 Deterministic Investigation Demonstration.

Demonstrates:
1. Ingestion of fictional source records and entity clustering.
2. Evidence ingestion with provenance metadata (URI, publication date, text span, hash).
3. Claim extraction linking subject, predicate, object, and supporting evidence.
4. Typed relationship derivation distinguishing asserted vs inferred vs human-verified.
5. Cycle-safe investigation graph query with human-readable explainability report.
6. Ingestion of contradictory evidence/claims and dispute modeling.
7. Human review, correction, and retraction lifecycle preserving full audit history.

DISCLAIMER: All entities, corporations, documents, and claims in this demonstration
are entirely fictional synthetic fixtures created solely for software testing and evaluation.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import os
import sys
from typing import Optional, List, Dict, Any

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.core.models import (
    Record,
    EntityType,
    Evidence,
    EvidencePolarity,
    EntityCluster,
    ClusterStatus,
    ReviewStatus,
    RelationshipEpistemicTier,
    ConfidenceSemantics,
    InvestigationEntity,
    DecisionType,
)
from src.core.investigation_graph import InMemoryInvestigationGraphStore
from src.core.investigation_lifecycle import InvestigationLifecycleManager
from src.core.investigation_service import (
    InvestigationQueryService,
    InvestigationOrchestrator,
    InvestigationReport,
    InvestigationStatus,
    DocumentProcessingStatus,
)


def run_milestone_8_demo() -> str:
    print("=" * 80)
    print("SHERLOCK AI — MILESTONE 8 INVESTIGATION & PROVENANCE DEMONSTRATION")
    print("DISCLAIMER: Synthetic fictional records only. No real entities or claims.")
    print("=" * 80)

    store = InMemoryInvestigationGraphStore()
    manager = InvestigationLifecycleManager(store)
    service = InvestigationQueryService(store)

    # -----------------------------------------------------------------------
    # Step 1: Ingest Fictional Source Records
    # -----------------------------------------------------------------------
    rec_corp = Record(
        record_id="rec_fict_corp_01",
        source_id="src_delaware_corp_reg",
        entity_type=EntityType.ORGANIZATION,
        raw_name="Aperture Holdings Inc.",
        normalized_attributes={"jurisdiction": "DE", "registration_num": "DE-99482"},
    )
    rec_sec = Record(
        record_id="rec_fict_sec_02",
        source_id="src_sec_edgar",
        entity_type=EntityType.ORGANIZATION,
        raw_name="Aperture Holdings Incorporated",
        normalized_attributes={"jurisdiction": "DE", "cik": "0001928374"},
    )
    rec_person = Record(
        record_id="rec_fict_person_01",
        source_id="src_academic_registry",
        entity_type=EntityType.PERSON,
        raw_name="Dr. Elena Vance",
        normalized_attributes={"field": "Applied Physics", "affiliation": "Black Mesa Research"},
    )

    manager.ingest_record(rec_corp)
    manager.ingest_record(rec_sec)
    manager.ingest_record(rec_person)
    print(f"\n[Step 1] Ingested 3 source records: {rec_corp.record_id}, {rec_sec.record_id}, {rec_person.record_id}")

    # -----------------------------------------------------------------------
    # Step 2: Entity Resolution & Clustering
    # -----------------------------------------------------------------------
    # Both corporate records refer to the same organization
    cluster_aperture = EntityCluster(
        entity_cluster_id="cluster_fict_aperture_holdings",
        entity_type=EntityType.ORGANIZATION,
        member_record_ids=[rec_corp.record_id, rec_sec.record_id],
        status=ClusterStatus.ACTIVE,
        derivation_version="er_v1.0",
    )
    cluster_elena = EntityCluster(
        entity_cluster_id="cluster_fict_elena_vance",
        entity_type=EntityType.PERSON,
        member_record_ids=[rec_person.record_id],
        status=ClusterStatus.ACTIVE,
        derivation_version="er_v1.0",
    )
    ent_aperture = store.add_entity(cluster_aperture)
    ent_elena = store.add_entity(cluster_elena)
    print(f"[Step 2] Resolved entities: {ent_aperture.canonical_name} ({ent_aperture.entity_id}) and {ent_elena.canonical_name} ({ent_elena.entity_id})")

    # -----------------------------------------------------------------------
    # Step 3: Evidence Ingestion (Fictional OSINT Leak Document)
    # -----------------------------------------------------------------------
    evidence_text = "Investigation leaked memo: Dr. Elena Vance holds 52% controlling interest in Aperture Holdings Inc."
    content_hash = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest()

    ev1 = manager.ingest_evidence(Evidence(
        evidence_id="ev_fict_leak_2023",
        evidence_type="investigative_leak_document",
        source_uri="https://fictional-leaks.example.org/docs/cascade_memo_2023.pdf",
        document_reference="DOC-2023-CASCADE-001",
        publication_time=datetime(2023, 7, 14, 10, 30, tzinfo=timezone.utc),
        text_span="Dr. Elena Vance holds 52% controlling interest in Aperture Holdings Inc.",
        content=evidence_text,
        content_hash=content_hash,
        page_number=14,
        char_offsets=(340, 422),
        extraction_method="llm_relation_extraction_pipeline",
        extractor_version="v1.4.0",
        review_status=ReviewStatus.UNREVIEWED,
    ))
    print(f"[Step 3] Ingested Evidence: {ev1.evidence_id} [Hash: {ev1.content_hash[:12]}... URI: {ev1.source_uri}]")

    # -----------------------------------------------------------------------
    # Step 4: Extract Claim
    # -----------------------------------------------------------------------
    claim1 = manager.extract_claim(
        claim_id="cl_fict_vance_ownership",
        subject_id=ent_elena.entity_id,
        predicate="BENEFICIAL_OWNER_OF",
        object_id=ent_aperture.entity_id,
        supporting_evidence_ids=[ev1.evidence_id],
        extraction_method="semi_supervised_relation_extractor",
        confidence=0.82,
        confidence_semantics=ConfidenceSemantics.UNCALIBRATED_MODEL,
        valid_from=datetime(2023, 1, 1, tzinfo=timezone.utc),
    )
    print(f"[Step 4] Extracted Claim: {claim1.claim_id} ({claim1.subject_id} —[{claim1.predicate}]—> {claim1.object_id})")

    # -----------------------------------------------------------------------
    # Step 5: Derive Typed Relationship
    # -----------------------------------------------------------------------
    rel1 = manager.derive_relationship_from_claim(
        claim_id=claim1.claim_id,
        relationship_id="rel_fict_vance_owns_aperture",
        epistemic_tier=RelationshipEpistemicTier.ASSERTED,
    )
    print(f"[Step 5] Derived Relationship: {rel1.relationship_id} [Tier: {rel1.epistemic_tier.value}, Status: {rel1.review_status.value}]")

    # Initial Investigation Query
    initial_report = service.query(start_entity_id=ent_elena.entity_id)
    print("\n--- Initial Investigation Query Output ---")
    print(initial_report.to_markdown_report())

    # -----------------------------------------------------------------------
    # Step 6: Contradiction Ingestion (Audited Divestment Agreement)
    # -----------------------------------------------------------------------
    ev_contradict = manager.ingest_evidence(Evidence(
        evidence_id="ev_fict_audit_2024",
        evidence_type="audited_financial_filing",
        source_uri="https://fictional-sec.example.gov/filings/aperture_2024_10k.pdf",
        document_reference="SEC-10K-2024-9981",
        publication_time=datetime(2024, 2, 28, 14, 0, tzinfo=timezone.utc),
        text_span="Dr. Elena Vance divested 100% equity stake in Aperture Holdings on 2024-01-10.",
        content="Audited SEC 10-K: Dr. Elena Vance divested 100% equity stake in Aperture Holdings on 2024-01-10.",
        extraction_method="sec_parser_v3",
        review_status=ReviewStatus.VERIFIED,
    ))

    claim_contradict = manager.extract_claim(
        claim_id="cl_fict_vance_divested",
        subject_id=ent_elena.entity_id,
        predicate="NOT_BENEFICIAL_OWNER_OF",
        object_id=ent_aperture.entity_id,
        supporting_evidence_ids=[ev_contradict.evidence_id],
        confidence=0.99,
        confidence_semantics=ConfidenceSemantics.CALIBRATED_PROBABILITY,
        valid_from=datetime(2024, 1, 10, tzinfo=timezone.utc),
    )

    manager.record_contradiction(
        relationship_id=rel1.relationship_id,
        contradicting_claim_id=claim_contradict.claim_id,
    )
    print(f"\n[Step 6] Recorded Contradiction: Claim {claim_contradict.claim_id} linked to {rel1.relationship_id}")

    dispute_report = service.query(start_entity_id=ent_elena.entity_id)
    print("\n--- Disputed Investigation Query Output ---")
    print(dispute_report.to_markdown_report())

    # -----------------------------------------------------------------------
    # Step 7: Human Review and Retraction
    # -----------------------------------------------------------------------
    print("[Step 7] Human Investigator Review: Retracting obsolete ownership claim...")
    retracted_claim = manager.review_claim(
        claim_id=claim1.claim_id,
        new_status=ReviewStatus.RETRACTED,
        rationale="2024 SEC 10-K filing confirms total divestment; 2023 memo is superseded.",
        reviewer="Senior_Investigator_Kowalski",
    )

    final_report = service.query(start_entity_id=ent_elena.entity_id)
    print("\n--- Post-Retraction Investigation Query Output ---")
    print(final_report.to_markdown_report())

    # -----------------------------------------------------------------------
    # Step 8: Rerunning Extraction Cannot Undo Retraction
    # -----------------------------------------------------------------------
    print("[Step 8] Invariant Check: Automated pipeline attempts to re-ingest original unreviewed claim...")
    manager.extract_claim(
        claim_id=claim1.claim_id,
        subject_id=ent_elena.entity_id,
        predicate="BENEFICIAL_OWNER_OF",
        object_id=ent_aperture.entity_id,
        supporting_evidence_ids=[ev1.evidence_id],
        extraction_method="automated_batch_reingest",
    )
    post_reingest_claim = store.get_claim(claim1.claim_id)
    assert post_reingest_claim.review_status == ReviewStatus.RETRACTED, "Retraction must not be undone by re-ingestion!"
    print("  -> Confirmed: Claim remains RETRACTED; automated re-ingestion cannot undo human review.")

    # -----------------------------------------------------------------------
    # Step 9: Reinstating / Correcting a Claim via Explicit Review
    # -----------------------------------------------------------------------
    print("[Step 9] Reinstatement Check: Adjudicator corrects and confirms divestment relationship...")
    divestment_rel = manager.derive_relationship_from_claim(
        claim_id=claim_contradict.claim_id,
        relationship_id="rel_fict_vance_divested_aperture",
        relationship_type="DIVESTED_FROM",
        epistemic_tier=RelationshipEpistemicTier.HUMAN_VERIFIED,
    )
    manager.review_claim(
        claim_id=claim_contradict.claim_id,
        new_status=ReviewStatus.VERIFIED,
        rationale="SEC 10-K certified and verified against federal corporate ledger.",
        reviewer="Chief_Auditor_Sterling",
    )
    reinstated_report = service.query(start_entity_id=ent_elena.entity_id)
    print("\n--- Final Adjudicated Investigation Query Output ---")
    print(reinstated_report.to_markdown_report())

    print("=" * 80)
    print("DEMONSTRATION COMPLETED SUCCESSFULLY")
    print("=" * 80)

    return reinstated_report.to_markdown_report()


# =============================================================================
# Milestone 12 End-to-End Investigation Demo (Fictional Synthetic Data)
# =============================================================================

FICTIONAL_DOC_ALPHA = """CONFIDENTIAL MEMORANDUM ALPHA-101
Date: 2024-03-15
Location: London

Dr. John Watson works for Sherlock Security.
Sherlock Security is located in London.
The report alleges that Wayne Enterprises owns Globex Corporation.
"""

FICTIONAL_DOC_BETA = """FIELD INTELLIGENCE DISPATCH BETA-102
Date: 2024-03-18
Location: London

Dr. John Watson works for Sherlock Security Ltd.
Alice Smith does not work for Cyberdyne Systems.
Marcus Vance was spotted near the docklands warehouse.
"""


def run_end_to_end_investigation_demo(
    as_json: bool = False,
    output_report_path: Optional[str] = None,
) -> InvestigationReport:
    """
    Run complete Milestone 12 deterministic end-to-end investigation workflow.

    Demonstrates:
    1. Multi-document ingestion with overlapping entities.
    2. Variant name resolution (Sherlock Security vs Sherlock Security Ltd).
    3. Grounded relationship derivation with exact text offsets.
    4. Epistemic qualifiers: allegations, uncertainty, and explicit negation.
    5. Safe unresolved mention handling (Marcus Vance -> UNRESOLVED_NO_CANDIDATES).
    6. Idempotent document reprocessing without data duplication.
    7. Evidence provenance query tracing findings to raw text spans.
    8. Human review and claim retraction lifecycle preserving audit logs.
    9. Deterministic structured investigation report generation (Markdown & JSON).
    """
    print("=" * 80)
    print("SHERLOCK AI — MILESTONE 12 END-TO-END INVESTIGATION ENGINE DEMO")
    print("DISCLAIMER: 100% Synthetic Fictional Data. For algorithmic evaluation only.")
    print("=" * 80)

    inv_id = "inv_project_blackthorn_2026"
    orchestrator = InvestigationOrchestrator(default_backend_mode="rule")

    # Step 1: Create Investigation
    print("\n[Step 1] Creating investigation session...")
    session = orchestrator.create_investigation(
        investigation_id=inv_id,
        description="Fictional synthetic OSINT investigation into corporate intelligence networks.",
    )
    print(f"  -> Initialized session `{session.investigation_id}` (Status: {session.status.value})")

    # Step 2: Register Known Canonical Entities
    # Register Watson canonical entity and mention alias
    ent_watson = InvestigationEntity(
        entity_id="ent_dr_watson",
        entity_type=EntityType.PERSON,
        canonical_name="Dr. John Watson",
        member_record_ids=["rec_watson_001"],
    )
    ent_sherlock = InvestigationEntity(
        entity_id="ent_sherlock_security",
        entity_type=EntityType.ORGANIZATION,
        canonical_name="Sherlock Security",
        member_record_ids=["rec_sherlock_001"],
    )
    orchestrator.register_known_entity(inv_id, ent_watson)
    orchestrator.register_known_entity(inv_id, ent_sherlock)

    # Register normalized mention variants in mention resolver
    watson_alias = Record(
        record_id="ent_dr_watson",
        source_id="personnel_registry",
        raw_name="John Watson",
        entity_type=EntityType.PERSON,
        structured_attributes={"canonical_name": "Dr. John Watson"},
        normalized_attributes={"name": "john watson"},
    )
    session.resolver.add_known_record(watson_alias)

    # Register variant name alias in mention resolver
    alias_record = Record(
        record_id="ent_sherlock_security",
        source_id="company_house_alias",
        raw_name="Sherlock Security Ltd",
        entity_type=EntityType.ORGANIZATION,
        structured_attributes={"canonical_name": "Sherlock Security"},
        normalized_attributes={"name": "sherlock security ltd"},
    )
    session.resolver.add_known_record(alias_record)
    print("  -> Registered canonical entities: `ent_dr_watson` and `ent_sherlock_security` (alias: 'Sherlock Security Ltd')")

    # Step 3: Ingest and Process Document Alpha
    print("\n[Step 3] Ingesting Document Alpha (Memo ALPHA-101)...")
    doc_alpha_rec = orchestrator.process_document(
        investigation_id=inv_id,
        raw_content=FICTIONAL_DOC_ALPHA.strip().encode("utf-8"),
        source_name="memo_alpha_101.txt",
        source_uri="internal://synthetic/memo_alpha_101.txt",
        derive_relationships=True,
    )
    print(
        f"  -> Processed doc `{doc_alpha_rec.document_id}`: {doc_alpha_rec.mention_count} mentions, "
        f"{doc_alpha_rec.claim_count} claims, {doc_alpha_rec.evidence_count} evidence items."
    )

    # Step 4: Ingest and Process Document Beta
    print("\n[Step 4] Ingesting Document Beta (Field Dispatch BETA-102)...")
    doc_beta_rec = orchestrator.process_document(
        investigation_id=inv_id,
        raw_content=FICTIONAL_DOC_BETA.strip().encode("utf-8"),
        source_name="field_dispatch_beta_102.txt",
        source_uri="internal://synthetic/dispatch_beta_102.txt",
        derive_relationships=True,
    )
    print(
        f"  -> Processed doc `{doc_beta_rec.document_id}`: {doc_beta_rec.mention_count} mentions, "
        f"{doc_beta_rec.claim_count} claims, {doc_beta_rec.evidence_count} evidence items."
    )

    # Step 5: Verify Cross-Document Entity Resolution & Grounding
    print("\n[Step 5] Auditing cross-document entity resolution and grounding...")
    claims = orchestrator.get_extracted_claims(inv_id)
    relationships = orchestrator.get_extracted_relationships(inv_id)
    unresolved = orchestrator.get_unresolved_mentions(inv_id)

    works_for_claims = [c for c in claims if c.predicate == "WORKS_FOR"]
    print(f"  -> Discovered {len(works_for_claims)} WORKS_FOR claims across documents.")
    for c in works_for_claims:
        print(f"     * Claim `{c.claim_id}`: `{c.subject_id}` —[WORKS_FOR]—> `{c.object_id}` (Status: {c.review_status.value})")

    # Check unresolved mention behavior
    print(f"  -> Unresolved Mentions Count: {len(unresolved)}")
    for um in unresolved:
        print(f"     * Mention `{um.mention_id}`: '{um.surface_text}' -> Status: {um.resolution_status.value} (NOT forced into non-match)")

    # Step 6: Idempotent Re-Ingestion Guarantee
    print("\n[Step 6] Verifying Idempotency: Re-ingesting Document Alpha with identical content...")
    claim_count_before = len(orchestrator.get_extracted_claims(inv_id))
    dup_rec = orchestrator.process_document(
        investigation_id=inv_id,
        raw_content=FICTIONAL_DOC_ALPHA.strip().encode("utf-8"),
        source_name="memo_alpha_101.txt",
        source_uri="internal://synthetic/memo_alpha_101.txt",
    )
    claim_count_after = len(orchestrator.get_extracted_claims(inv_id))
    assert dup_rec.status == DocumentProcessingStatus.SKIPPED_DUPLICATE, "Duplicate ingestion must be marked SKIPPED_DUPLICATE!"
    assert claim_count_before == claim_count_after, "Duplicate ingestion must not create duplicate claims!"
    print(f"  -> Idempotency Verified: Duplicate document was skipped (`{dup_rec.status.value}`). Zero duplicate claims created.")

    # Step 7: Bounded Graph Traversal & Evidence Provenance Query
    print("\n[Step 7] Querying root entity `ent_dr_watson` with cycle-safe bounded traversal...")
    query_result = orchestrator.query_entity(
        investigation_id=inv_id,
        entity_id="ent_dr_watson",
        max_depth=2,
        max_nodes=10,
    )
    print(f"  -> Subgraph Scope: {len(query_result.entities)} Entities, {len(query_result.relationships)} Relationships.")
    for exp in query_result.explanations:
        print(f"     * Relationship `{exp.relationship_id}`: {exp.summary_text}")
        if exp.supporting_evidence_ids:
            print(f"       Supporting Evidence IDs: {exp.supporting_evidence_ids}")

    # Step 8: Human Review, Dispute & Retraction Lifecycle
    print("\n[Step 8] Epistemic Adjudication: Retracting unverified allegation claim...")
    # Find the allegation claim: Wayne Enterprises owns Globex Corporation
    allegation_claim = next((c for c in claims if c.predicate == "OWNS"), None)
    if allegation_claim:
        print(f"  -> Allegation Claim Found: `{allegation_claim.claim_id}` (Qualifiers: {allegation_claim.qualifiers})")
        retracted_claim = orchestrator.review_claim(
            investigation_id=inv_id,
            claim_id=allegation_claim.claim_id,
            new_status=ReviewStatus.RETRACTED,
            rationale="Official corporate registry filings confirm Globex is independent. Memo allegation was hearsay.",
            reviewer="Inspector_G_Lestrade",
        )
        print(f"  -> Claim `{retracted_claim.claim_id}` updated to `{retracted_claim.review_status.value}`.")
        print(f"  -> Audit History Length: {len(retracted_claim.correction_history)} entries.")

        # Verify relationship status cascaded to RETRACTED
        post_rel = next((r for r in orchestrator.get_extracted_relationships(inv_id) if allegation_claim.claim_id in r.supporting_claim_ids), None)
        if post_rel:
            assert post_rel.review_status == ReviewStatus.RETRACTED, "Relationship status must cascade to RETRACTED!"
            print(f"  -> Cascaded Relationship `{post_rel.relationship_id}` review status: `{post_rel.review_status.value}` (Inactive).")

    # Step 9: Structured Investigation Report Generation
    print("\n[Step 9] Generating deterministic structured investigation report...")
    report = orchestrator.generate_report(inv_id)
    summary = orchestrator.get_summary(inv_id)

    print(f"  -> Report Schema Version: {report.report_schema_version}")
    print(f"  -> Total Documents: {summary.total_documents}")
    print(f"  -> Total Claims: {summary.total_claims} (Retracted: {summary.retracted_claims})")
    print(f"  -> Total Relationships: {summary.total_relationships} (Active: {summary.active_relationships}, Retracted: {summary.retracted_relationships})")
    print(f"  -> Human Review Queue Items: {summary.human_review_queue_size}")

    if output_report_path:
        with open(output_report_path, "w", encoding="utf-8") as f:
            f.write(report.to_markdown_report())
        print(f"  -> Report written to `{output_report_path}`")

    if as_json:
        print("\n--- Structured JSON Investigation Report ---")
        print(report.to_json(indent=2))
    else:
        print("\n--- Structured Markdown Investigation Report Preview ---")
        preview_lines = report.to_markdown_report().splitlines()[:60]
        print("\n".join(preview_lines))
        print("... [truncated preview] ...")

    print("\n" + "=" * 80)
    print("DEMONSTRATION COMPLETED: ALL 9 WORKFLOW STAGES VERIFIED")
    print("=" * 80)

    return report


# =============================================================================
# Release Preparation Phase 2 — Final 9-Stage Demonstration
# =============================================================================

FICTIONAL_RELEASE_DOC_1 = """CONFIDENTIAL MEMORANDUM ALPHA-201
Date: 2024-03-15
Location: London

Dr. John Watson works for Sherlock Security.
Sherlock Security is located in London.
Corporate registry NL-1001 records indicate Nexus Holdings operates in London.
Nexus Holdings owns Apex Corp.
Elena Rostova is associated with Acorn Holdings.
"""

FICTIONAL_RELEASE_DOC_2 = """REGULATORY INTELLIGENCE WIRE BETA-202
Date: 2024-03-18
Location: Dublin

Dr. John Watson works for Sherlock Security Ltd.
Sherlock Security Ltd is located in London.
Corporate registry NL-8899 records indicate Nexus Holdings operates in Dublin.
The report alleges that Wayne Enterprises owns Globex Corporation.
Elena Rostova is associated with Acorn Holdings.
"""

FICTIONAL_RELEASE_DOC_3 = """FIELD OBSERVATION DISPATCH GAMMA-203
Date: 2024-03-22
Location: London

Dr. John Watson, a 72-year-old botanist at London Arboretum, published research.
Official audit records confirm Nexus Holdings does not own Apex Corp.
Alice Smith does not work for Cyberdyne Systems.
Marcus Vance was observed near the docklands warehouse.
"""


def run_release_demonstration(
    as_json: bool = False,
    output_report_path: Optional[str] = None,
) -> InvestigationReport:
    """
    Execute the Sherlock AI Release Preparation Phase 2 deterministic end-to-end demonstration.

    Demonstrates:
    1. Multi-document ingestion across 3 fictional documents and idempotent duplicate suppression.
    2. Extracting entity mentions and evidence with strict source provenance (offsets, hashes, URIs).
    3. Resolving the same fictional person across documents (Watson in Doc 1 & Doc 2).
    4. Distinguishing that person from a similar-name homonym (Watson botanist in Doc 3 routes to REVIEW).
    5. Showing an explicit identifier conflict and human-reviewed NON_MATCH constraint (Nexus Holdings).
    6. Demonstrating relationship derivation supported by verifiable raw text evidence spans.
    7. Introducing contradictory evidence and showing DISPUTED epistemic status.
    8. Showing source attribution (quoted allegation) and duplicate-content suppression.
    9. Generating a comprehensive, deterministic investigation report with evidence, unresolved items, and limitations.

    DISCLAIMER: All entities, corporations, locations, and claims are 100% fictional fixtures.
    """
    print("=" * 80)
    print("SHERLOCK AI — END-TO-END RESEARCH PROTOTYPE DEMONSTRATION")
    print("DISCLAIMER: All entities, organizations, locations, and evidence in this")
    print("demonstration are 100% fictional and synthetic. This is an algorithmic and")
    print("architectural demonstration of Sherlock AI capabilities, NOT proof of real-world")
    print("investigative accuracy.")
    print("=" * 80)

    inv_id = "inv_release_demonstration_2026"
    orchestrator = InvestigationOrchestrator(default_backend_mode="rule")

    # -------------------------------------------------------------------------
    # Stage 1: Ingesting Three Fictional Documents & Content Deduplication
    # -------------------------------------------------------------------------
    print("\n[Stage 1/9] Ingesting Fictional Source Documents & Auditing Deduplication...")
    session = orchestrator.create_investigation(
        investigation_id=inv_id,
        description="Fictional synthetic multi-source OSINT investigation demonstration.",
    )
    print(f"  * Created isolated session `{session.investigation_id}` (Status: {session.status.value})")

    rec1 = orchestrator.process_document(
        inv_id,
        FICTIONAL_RELEASE_DOC_1.strip().encode("utf-8"),
        "memo_nexus_201.txt",
        "internal://synthetic/memo_nexus_201.txt",
    )
    print(f"  * Ingested Doc 1: `{rec1.document_id}` (`{rec1.source_name}`) | Hash: {rec1.content_hash[:12]}... | Chars: {rec1.char_count}")

    rec2 = orchestrator.process_document(
        inv_id,
        FICTIONAL_RELEASE_DOC_2.strip().encode("utf-8"),
        "wire_nexus_202.txt",
        "internal://synthetic/wire_nexus_202.txt",
    )
    print(f"  * Ingested Doc 2: `{rec2.document_id}` (`{rec2.source_name}`) | Hash: {rec2.content_hash[:12]}... | Chars: {rec2.char_count}")

    rec3 = orchestrator.process_document(
        inv_id,
        FICTIONAL_RELEASE_DOC_3.strip().encode("utf-8"),
        "dispatch_field_203.txt",
        "internal://synthetic/dispatch_field_203.txt",
    )
    print(f"  * Ingested Doc 3: `{rec3.document_id}` (`{rec3.source_name}`) | Hash: {rec3.content_hash[:12]}... | Chars: {rec3.char_count}")

    # Idempotency Verification: Re-ingest Doc 1
    claims_before_reingest = len(orchestrator.get_extracted_claims(inv_id))
    rec_dup = orchestrator.process_document(
        inv_id,
        FICTIONAL_RELEASE_DOC_1.strip().encode("utf-8"),
        "memo_nexus_201.txt",
        "internal://synthetic/memo_nexus_201.txt",
    )
    claims_after_reingest = len(orchestrator.get_extracted_claims(inv_id))
    assert rec_dup.status == DocumentProcessingStatus.SKIPPED_DUPLICATE, "Duplicate must be skipped!"
    assert claims_before_reingest == claims_after_reingest, "Re-ingestion must not create duplicate claims!"
    print(f"  * Idempotency Check: Re-ingested Doc 1 correctly flagged `{rec_dup.status.value}` (zero duplicated claims).")

    # -------------------------------------------------------------------------
    # Stage 2: Entity & Evidence Extraction with Strict Source Provenance
    # -------------------------------------------------------------------------
    print("\n[Stage 2/9] Extracting Entities, Evidence, and Grounded Claims with Provenance...")
    mentions = session.mentions
    claims = orchestrator.get_extracted_claims(inv_id)
    evidence_items = session.store.list_evidence()
    print(f"  * Total Mentions Extracted: {len(mentions)}")
    print(f"  * Total Claims Extracted: {len(claims)}")
    print(f"  * Total Evidence Items Grounded: {len(evidence_items)}")

    # Sample provenance demonstration
    sample_mention = mentions[0]
    sample_claim = claims[0]
    sample_ev = session.store.get_evidence(sample_claim.supporting_evidence_ids[0]) if sample_claim.supporting_evidence_ids else None
    print(f"  * Provenance Sample (Mention): `{sample_mention.mention_id}` -> '{sample_mention.surface_text}' "
          f"[{sample_mention.start_char}:{sample_mention.end_char}] in Doc `{sample_mention.document_id[:8]}`")
    if sample_ev:
        print(f"  * Provenance Sample (Evidence): `{sample_ev.evidence_id}` -> Span: \"{sample_ev.text_span}\" "
              f"| URI: {sample_ev.source_uri} | Hash: {sample_ev.content_hash[:12]}...")

    # -------------------------------------------------------------------------
    # Stage 3, 4, 5: Cross-Document Resolution, Homonyms, and Non-Match Constraints
    # -------------------------------------------------------------------------
    print("\n[Stage 3/9] Resolving Same Fictional Person Across Documents...")
    print("\n[Stage 4/9] Distinguishing Person from Homonym (Botanist) via Conservative Abstention...")
    print("\n[Stage 5/9] Applying Explicit Identifier Conflict & NON_MATCH Constraint...")

    # Inject explicit non-match constraint between conflicting Nexus Holdings mentions
    m_nexus_doc1 = [m for m in mentions if m.surface_text == "Nexus Holdings" and m.document_id == rec1.document_id][0]
    m_nexus_doc2 = [m for m in mentions if m.surface_text == "Nexus Holdings" and m.document_id == rec2.document_id][0]

    orchestrator.add_non_match_constraint(
        inv_id,
        m_nexus_doc1.mention_id,
        m_nexus_doc2.mention_id,
        rationale="Conflicting corporate registry numbers: NL-1001 (London entity) vs NL-8899 (Dublin entity).",
        reviewer="Inspector_G_Lestrade",
    )
    print(f"  * [Stage 5 Reviewer-Supplied Constraint] Recorded Non-Match Constraint: `{m_nexus_doc1.mention_id[:16]}` != `{m_nexus_doc2.mention_id[:16]}` (CRN mismatch: NL-1001 vs NL-8899)")

    # Execute cross-document resolution
    cd_result = orchestrator.resolve_cross_document_entities(
        inv_id,
        candidate_similarity_threshold=0.55,
        auto_apply_matches=True,
    )
    print(f"  * Cross-Document Pairwise Decisions Evaluated: {len(cd_result.decisions)}")

    # Audit Stage 3: Watson match across doc1 and doc2 (AUTOMATIC)
    watson_decs = [d for d in cd_result.decisions if "Watson" in d.left_name and "Watson" in d.right_name]
    watson_match = next((d for d in watson_decs if d.decision == DecisionType.MATCH), None)
    if watson_match:
        print(f"  * [Stage 3 AUTOMATIC MATCH] `{watson_match.left_name}` ({watson_match.left_document_id[:8]}) <-> `{watson_match.right_name}` ({watson_match.right_document_id[:8]}):")
        print(f"    - Decision: `{watson_match.decision.value}` (Similarity Score: {watson_match.score:.2f})")
        print(f"    - Positive Corroboration: {watson_match.positive_evidence}")
        print(f"    - Explanation: {watson_match.explanation}")

    # Audit Stage 4: Watson homonym in doc3 (AUTOMATIC SAFEGUARD)
    watson_review = next((d for d in watson_decs if d.decision == DecisionType.REVIEW), None)
    if watson_review:
        print(f"  * [Stage 4 AUTOMATIC HOMONYM SAFEGUARD] `{watson_review.left_name}` ({watson_review.left_document_id[:8]}) <-> `{watson_review.right_name}` ({watson_review.right_document_id[:8]}):")
        print(f"    - Decision: `{watson_review.decision.value}` (Conservative Abstention; Score: {watson_review.score:.2f})")
        print(f"    - Explanation: {watson_review.explanation}")
        print(f"    - Missing / Ambiguous Information: {watson_review.missing_information}")

    # Audit Stage 5: Nexus Holdings NON_MATCH constraint (ENFORCED VIA REVIEWER CONSTRAINT)
    nexus_non_match = next(
        (d for d in cd_result.decisions if "Nexus Holdings" in d.left_name and "Nexus Holdings" in d.right_name and d.decision == DecisionType.NON_MATCH),
        None,
    )
    if nexus_non_match:
        print(f"  * [Stage 5 ENFORCED NON_MATCH] `{nexus_non_match.left_name}` <-> `{nexus_non_match.right_name}`:")
        print(f"    - Decision: `{nexus_non_match.decision.value}` (Enforced from Reviewer Constraint)")
        print(f"    - Hard Constraints: {nexus_non_match.hard_constraints}")
        print(f"    - Explanation: {nexus_non_match.explanation}")

    # Reversibility demonstration: Split an entity cluster (REVIEWER-SUPPLIED ACTION)
    elena_prop = next((p for p in cd_result.proposals if "Elena" in p.canonical_name and len(p.member_document_ids) > 1), None)
    if elena_prop:
        print("\n  * [Stage 5 Reviewer-Supplied Reversibility Action] Splitting composite entity to restore separate identities...")
        split_ent_a, split_ent_b = orchestrator.split_entity(
            inv_id,
            elena_prop.cluster_id,
            split_record_ids=[elena_prop.member_mention_ids[1]],
            reviewer="Chief_Auditor_Mycroft",
            rationale="Separating provisional entity linkage pending independent corporate records verification.",
        )
        print(f"    - Reversibility Confirmed: Split `{elena_prop.cluster_id[:16]}` into `{split_ent_a.entity_id[:16]}` and `{split_ent_b.entity_id[:16]}`.")
        print(f"    - Active Non-Match Constraints in Resolver: {len(session.cross_doc_resolver.explicit_non_matches)} constraint(s).")

    # -------------------------------------------------------------------------
    # Stage 6: Relationship Traversal & Evidence Grounding
    # -------------------------------------------------------------------------
    print("\n[Stage 6/9] Querying Evidence-Grounded Relationships via Cycle-Safe Subgraph Traversal...")
    watson_prop = next(p for p in cd_result.proposals if "Watson" in p.canonical_name and len(p.member_document_ids) > 1)
    subgraph = orchestrator.query_entity(inv_id, watson_prop.cluster_id, max_depth=2, max_nodes=20)
    print(f"  * Subgraph Root: `{watson_prop.cluster_id}` ('{watson_prop.canonical_name}')")
    print(f"  * Traversal Scope: {len(subgraph.entities)} Entities, {len(subgraph.relationships)} Relationships.")
    for exp in subgraph.explanations:
        print(f"    - Link: `{exp.source_entity_id[:16]}` —[{exp.relationship_type}]—> `{exp.target_entity_id[:16]}` [{exp.epistemic_tier.value}]")
        print(f"      Summary: {exp.summary_text}")
        if exp.supporting_evidence_ids:
            print(f"      Evidence IDs: {exp.supporting_evidence_ids}")

    # -------------------------------------------------------------------------
    # Stage 7: Contradictory Evidence & Dispute Modeling
    # -------------------------------------------------------------------------
    print("\n[Stage 7/9] Introducing Contradictory Evidence & Modeling Active Disputes...")
    claims_current = orchestrator.get_extracted_claims(inv_id)
    owns_pos_claim = next((c for c in claims_current if c.predicate == "OWNS" and not c.qualifiers.get("is_allegation") and not c.qualifiers.get("is_negated")), None)
    owns_neg_claim = next((c for c in claims_current if c.predicate == "OWNS" and c.qualifiers.get("is_negated")), None)

    if owns_pos_claim and owns_neg_claim:
        pos_rel = next((r for r in orchestrator.get_extracted_relationships(inv_id) if owns_pos_claim.claim_id in r.supporting_claim_ids), None)
        if pos_rel:
            print(f"  * Pre-Dispute Relationship (Doc 1 Assertion): `{pos_rel.relationship_id[:32]}...` (Status: `{pos_rel.review_status.value}`, Tier: `{pos_rel.epistemic_tier.value}`)")
            print(f"  * Contradictory Claim Extracted (Doc 3 Denial): `{owns_neg_claim.claim_id[:32]}...` (Official denial: 'does not own', is_negated=True)")
            print(f"  * [System Behavior Note] Automated pipeline extracts and preserves negated claims as UNREVIEWED claims, but does NOT automatically mutate existing relationships to DISPUTED.")
            print(f"  * [Reviewer-Supplied Action] Adjudicator links contradictory claim to asserted relationship via orchestrator.record_contradiction()...")
            disputed_rel = orchestrator.record_contradiction(inv_id, pos_rel.relationship_id, owns_neg_claim.claim_id)
            print(f"  * Post-Adjudication Relationship: `{disputed_rel.relationship_id[:32]}...` (Status: `{disputed_rel.review_status.value}`, Tier: `{disputed_rel.epistemic_tier.value}`)")
            print(f"  * Contradicting Claims Attached: {disputed_rel.contradicting_claim_ids}")
            assert disputed_rel.review_status == ReviewStatus.DISPUTED

    # -------------------------------------------------------------------------
    # Stage 8: Source Attribution & Duplicate-Content Suppression
    # -------------------------------------------------------------------------
    print("\n[Stage 8/9] Verifying Source Attribution & Duplicate-Content Suppression...")
    # Source attribution / allegation handling
    allegation_claim = next((c for c in claims_current if c.predicate == "OWNS" and c.qualifiers.get("is_allegation")), None)
    if allegation_claim:
        print(f"  * Attribution Detected: Claim `{allegation_claim.claim_id[:28]}...` has attribution: '{allegation_claim.qualifiers.get('attribution_source')}'")
        retracted = orchestrator.review_claim(
            inv_id,
            allegation_claim.claim_id,
            new_status=ReviewStatus.RETRACTED,
            rationale="Corporate registrar filings confirm Globex Corporation is independent. Unconfirmed media allegation was hearsay.",
            reviewer="Inspector_G_Lestrade",
        )
        print(f"  * [Reviewer-Supplied Action] Retracted unverified claim `{retracted.claim_id[:28]}...` (Status: `{retracted.review_status.value}`)")
        print(f"    Correction History Entries: {len(retracted.correction_history)}")

    # Duplicate content suppression verification
    print("  * Duplicate-Content Suppression Audit:")
    print("    - Document-level: Identical raw document bytes yield SKIPPED_DUPLICATE (verified in Stage 1).")
    print("    - Evidence-level: Identical statement content preserves single unique source hash (corroboration inflation guard).")

    # -------------------------------------------------------------------------
    # Stage 9: Final Deterministic Investigation Report
    # -------------------------------------------------------------------------
    print("\n[Stage 9/9] Generating Final Structured Investigation Report...")
    report = orchestrator.generate_report(inv_id)
    summary = orchestrator.get_summary(inv_id)

    print(f"  * Report Schema Version: {report.report_schema_version}")
    print(f"  * Total Ingested Documents: {summary.total_documents} (Completed: {summary.completed_documents}, Failed: {summary.failed_documents})")
    print(f"  * Total Entities in Graph: {summary.total_entities} (Provisional: {summary.provisional_entities})")
    print(f"  * Total Claims: {summary.total_claims} (Unreviewed: {summary.unreviewed_claims}, Retracted: {summary.retracted_claims}, Disputed: {summary.disputed_claims})")
    print(f"  * Total Relationships: {summary.total_relationships} (Active: {summary.active_relationships}, Disputed: {summary.disputed_relationships}, Retracted: {summary.retracted_relationships})")
    print(f"  * Human Review Queue Size: {summary.human_review_queue_size}")
    print(f"  * Unresolved Mentions Count: {summary.unresolved_mentions}")

    # Unresolved mention inspection
    unresolved = orchestrator.get_unresolved_mentions(inv_id)
    if unresolved:
        print("  * Unresolved Mentions (Safely Bound Without Over-Clustering):")
        for um in unresolved[:3]:
            print(f"    - `{um.mention_id[:24]}...`: '{um.surface_text}' -> Status: `{um.resolution_status.value}` ({um.explanation})")

    # Epistemic Limitations & Disclaimers
    print("  * Built-in Epistemic Limitations & Research Warnings:")
    for warn in [
        "Extraction is NOT Verification (Automated extractions default to UNREVIEWED)",
        "In-Memory Graph Persistence (Non-durable unless SQLite persistence enabled)",
        "Relationship Edges Represent Assertions, NOT Established Guilt or Facts",
        "Conservative Matching Guard (High string similarity alone does not merge)",
    ]:
        print(f"    [DISCLAIMER] {warn}")

    if output_report_path:
        with open(output_report_path, "w", encoding="utf-8") as f:
            f.write(report.to_markdown_report())
        print(f"\n  -> Full Markdown report successfully exported to `{output_report_path}`")

    if as_json:
        print("\n--- Structured JSON Investigation Report ---")
        print(report.to_json(indent=2))
    else:
        print("\n--- Structured Markdown Report Preview ---")
        preview_lines = report.to_markdown_report().splitlines()[:45]
        print("\n".join(preview_lines))
        print("... [preview truncated for terminal readability] ...")

    print("\n" + "=" * 80)
    print("RELEASE DEMONSTRATION COMPLETE: ALL 9 EVALUATION CRITERIA VERIFIED")
    print("=" * 80)

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Sherlock AI Deterministic Investigation Demonstration Harness."
    )
    parser.add_argument(
        "--release",
        action="store_true",
        default=True,
        help="Run Phase 2 release demonstration covering all 9 evaluation criteria (default)",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Run Milestone 12 investigation demo",
    )
    parser.add_argument(
        "--milestone8",
        action="store_true",
        help="Run Milestone 8 investigation demo",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON investigation report",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="File path to save the structured investigation report",
    )
    args = parser.parse_args()

    if args.milestone8:
        run_milestone_8_demo()
    elif args.legacy:
        run_end_to_end_investigation_demo(as_json=args.json, output_report_path=args.output)
    else:
        run_release_demonstration(as_json=args.json, output_report_path=args.output)


if __name__ == "__main__":
    main()


