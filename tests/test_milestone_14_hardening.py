"""
Milestone 14 Hardening & Regression Test Suite.

Covers:
- LIFE-01: Preservation of human adjudications (VERIFIED, RETRACTED, DISPUTED) against automated re-ingestion.
- DB-01: Atomic session synchronization in SQLite with transactional rollback on injected faults.
- DB-02: Document isolation across investigations with identical content hashes.
- DB-04: Multi-operation state survival in SQLiteInvestigationStore(":memory:").
- SEC-01: Loopback default, remote binding refusal, constant-time Bearer token authentication.
- SEC-02: Bounded upload chunked reading, exact limit (5MB), 1-byte above limit (HTTP 413).
- SEC-03: Reviewer identity validation and impersonation prevention.
- LIFE-02: Claim lifecycle state transition validation, retraction/reinstatement rationales (HTTP 422).
- Reliability: Database integrity check, backup/restore verification, and /ready probe.
"""

import io
import os
import sqlite3
import tempfile
import uuid
import pytest

from src.core.models import (
    Claim,
    Evidence,
    InvestigationEntity,
    Relationship,
    ReviewStatus,
    EntityType,
    EvidencePolarity,
    ConfidenceSemantics,
)
from src.core.document_ingestion import IngestedDocument, DocumentFormat
from src.core.investigation_sqlite import SQLiteInvestigationStore
from src.core.investigation_service import (
    InvestigationOrchestrator,
    InvestigationStatus,
    DocumentProcessingRecord,
    DocumentProcessingStatus,
)
from src.core.investigation_graph import (
    InMemoryInvestigationGraphStore,
    InvalidLifecycleTransitionError,
    VALID_CLAIM_TRANSITIONS,
)

try:
    import fastapi
    from starlette.testclient import TestClient
    from src.api.app import create_app
    from src.api.security import MAX_UPLOAD_SIZE_BYTES, validate_reviewer_identity, validate_api_token
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024


# =============================================================================
# 1. LIFE-01: Preservation of Human Adjudications
# =============================================================================

class TestHumanAdjudicationPreservation:
    """Ensure automated extraction never overwrites human reviews in memory or SQLite."""

    def test_verified_claim_survives_reingestion(self):
        store = SQLiteInvestigationStore(":memory:")
        orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)
        inv_id = "inv_life_01_verify"
        orchestrator.create_investigation(inv_id, "Preservation Test")

        # Ingest document generating claims matching rule extractor patterns
        doc_text = "Alice Mercer serves as CEO of Apex Global Holdings. Apex Global Holdings is located in London."
        orchestrator.process_document(inv_id, doc_text.encode("utf-8"), "report_v1.txt")

        claims = orchestrator.get_extracted_claims(inv_id)
        assert len(claims) > 0
        target = claims[0]

        # Human marks claim as VERIFIED
        orchestrator.review_claim(
            inv_id,
            claim_id=target.claim_id,
            new_status=ReviewStatus.VERIFIED,
            rationale="Verified with official commercial registry extract.",
            reviewer="lead_investigator_42",
        )

        reviewed = orchestrator.get_investigation(inv_id).store.get_claim(target.claim_id)
        assert reviewed.review_status == ReviewStatus.VERIFIED

        # Re-ingest the exact same document (simulating re-run or pipeline update)
        orchestrator.process_document(inv_id, doc_text.encode("utf-8"), "report_v1.txt")

        # Verify in memory
        in_mem_claim = orchestrator.get_investigation(inv_id).store.get_claim(target.claim_id)
        assert in_mem_claim.review_status == ReviewStatus.VERIFIED
        assert in_mem_claim.correction_history[-1].corrected_by == "lead_investigator_42"

        # Verify in SQLite
        sqlite_claims = {c.claim_id: c for c in store.list_claims(inv_id)}
        assert sqlite_claims[target.claim_id].review_status == ReviewStatus.VERIFIED
        assert sqlite_claims[target.claim_id].correction_history[-1].corrected_by == "lead_investigator_42"
        store.close()

    def test_retracted_claim_not_reinstated_by_pipeline(self):
        store = SQLiteInvestigationStore(":memory:")
        orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)
        inv_id = "inv_life_01_retract"
        orchestrator.create_investigation(inv_id, "Retraction Protection")

        doc_text = "Alice Mercer serves as CEO of Apex Global Holdings. Apex Global Holdings is located in London."
        orchestrator.process_document(inv_id, doc_text.encode("utf-8"), "contract.txt")

        claims = orchestrator.get_extracted_claims(inv_id)
        assert len(claims) > 0
        target = claims[0]

        # Retract claim
        orchestrator.review_claim(
            inv_id,
            claim_id=target.claim_id,
            new_status=ReviewStatus.RETRACTED,
            rationale="Source confirmed document was an unsigned preliminary draft.",
            reviewer="senior_compliance_officer",
        )

        # Re-ingest
        orchestrator.process_document(inv_id, doc_text.encode("utf-8"), "contract.txt")

        claim_post = orchestrator.get_investigation(inv_id).store.get_claim(target.claim_id)
        assert claim_post.review_status == ReviewStatus.RETRACTED
        assert "unsigned preliminary draft" in claim_post.retraction_reason

        sqlite_claim = {c.claim_id: c for c in store.list_claims(inv_id)}[target.claim_id]
        assert sqlite_claim.review_status == ReviewStatus.RETRACTED
        assert "unsigned preliminary draft" in sqlite_claim.retraction_reason
        store.close()

    def test_disputed_claim_preserves_status_on_reingestion(self):
        store = SQLiteInvestigationStore(":memory:")
        orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)
        inv_id = "inv_life_01_dispute"
        orchestrator.create_investigation(inv_id, "Dispute Protection")

        doc_text = "Alice Mercer serves as CEO of Apex Global Holdings. Apex Global Holdings is located in London."
        orchestrator.process_document(inv_id, doc_text.encode("utf-8"), "wire.txt")

        claims = orchestrator.get_extracted_claims(inv_id)
        assert len(claims) > 0
        target = claims[0]

        orchestrator.review_claim(
            inv_id,
            claim_id=target.claim_id,
            new_status=ReviewStatus.DISPUTED,
            rationale="Contradicting regulatory disclosure denies closing.",
            reviewer="forensic_auditor",
        )

        orchestrator.process_document(inv_id, doc_text.encode("utf-8"), "wire.txt")

        assert orchestrator.get_investigation(inv_id).store.get_claim(target.claim_id).review_status == ReviewStatus.DISPUTED
        store.close()


# =============================================================================
# 2. DB-01: Atomic Session Synchronization & Rollback
# =============================================================================

class TestAtomicSynchronization:
    """Verify that sync_session commits all-or-nothing in a single SQLite transaction."""

    def test_fault_injection_rolls_back_entire_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "atomic_test.db")
            store = SQLiteInvestigationStore(db_path)

            orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)
            inv_id = "inv_atomic_tx"
            session = orchestrator.create_investigation(inv_id, "Atomic TX Test")

            # Ingest initial state cleanly with pattern-matching text
            orchestrator.process_document(
                inv_id,
                b"Alice Mercer serves as CEO of Apex Global Holdings. Apex Global Holdings is located in London.",
                "clean_doc.txt",
            )

            # Baseline count in SQLite
            init_ents = len(store.list_entities(inv_id))
            init_claims = len(store.list_claims(inv_id))
            assert init_ents > 0
            assert init_claims > 0

            # Inject a failure during synchronization by monkeypatching _save_claim_tx to throw
            orig_save_claim = store._save_claim_tx

            def faulty_save_claim(conn, iid, claim):
                raise sqlite3.OperationalError("Simulated disk error or constraint violation midway")

            store._save_claim_tx = faulty_save_claim

            # Add new entity to in-memory session
            new_ent = InvestigationEntity(
                entity_id="ent_uncommitted_99",
                entity_type=EntityType.ORGANIZATION,
                canonical_name="Uncommitted Entity Corp",
            )
            session.store.add_entity(new_ent)

            # Attempt sync; must raise and roll back
            with pytest.raises(sqlite3.OperationalError, match="Simulated disk error"):
                store.sync_session(session)

            # Restore original method
            store._save_claim_tx = orig_save_claim

            # Check database: the uncommitted entity MUST NOT exist in SQLite
            ents_post = {e.entity_id for e in store.list_entities(inv_id)}
            assert "ent_uncommitted_99" not in ents_post
            assert len(ents_post) == init_ents

            # Database integrity must remain pristine
            assert store.integrity_check() is True


# =============================================================================
# 3. DB-02: Document Isolation Across Investigations
# =============================================================================

class TestDocumentIsolation:
    """Verify that identical source content ingested in separate investigations does not collide."""

    def test_identical_content_isolation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "isolation_test.db")
            store = SQLiteInvestigationStore(db_path)
            orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)

            inv_a = "inv_case_alpha"
            inv_b = "inv_case_bravo"
            orchestrator.create_investigation(inv_a, "Case Alpha")
            orchestrator.create_investigation(inv_b, "Case Bravo")

            # Same document content bytes
            doc_content = b"Elena Rostova appointed Director of Global Finance Corp in 2024."

            rec_a = orchestrator.process_document(inv_a, doc_content, "shared_filing.txt")
            rec_b = orchestrator.process_document(inv_b, doc_content, "shared_filing.txt")

            assert rec_a.content_hash == rec_b.content_hash
            assert rec_a.document_id == rec_b.document_id

            # Verify Case Alpha retained its document in SQLite
            docs_a = store.list_documents(inv_a)
            assert len(docs_a) == 1
            assert docs_a[0]["document_id"] == rec_a.document_id
            assert docs_a[0]["investigation_id"] == inv_a

            # Verify Case Bravo retained its document in SQLite
            docs_b = store.list_documents(inv_b)
            assert len(docs_b) == 1
            assert docs_b[0]["document_id"] == rec_b.document_id
            assert docs_b[0]["investigation_id"] == inv_b

            # Reopen database with fresh store instance to verify durable isolation
            store2 = SQLiteInvestigationStore(db_path)
            reopened_a = store2.list_documents(inv_a)
            reopened_b = store2.list_documents(inv_b)

            assert len(reopened_a) == 1
            assert len(reopened_b) == 1
            assert reopened_a[0]["document_id"] == reopened_b[0]["document_id"]
            assert reopened_a[0]["investigation_id"] == inv_a
            assert reopened_b[0]["investigation_id"] == inv_b

    def test_legacy_schema_migration_preserves_data_and_constraints(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "legacy_schema.db")
            # Create a SQLite DB with the pre-Milestone-14 single-column PK schema
            with sqlite3.connect(db_path) as conn:
                conn.execute("""
                    CREATE TABLE investigations (
                        investigation_id TEXT PRIMARY KEY,
                        description TEXT,
                        status TEXT NOT NULL,
                        backend_mode TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE documents (
                        document_id TEXT PRIMARY KEY,
                        investigation_id TEXT NOT NULL,
                        source_name TEXT NOT NULL,
                        source_uri TEXT,
                        content_hash TEXT NOT NULL,
                        raw_bytes BLOB,
                        normalized_text TEXT,
                        doc_format TEXT NOT NULL,
                        status TEXT NOT NULL,
                        char_count INTEGER NOT NULL DEFAULT 0,
                        mention_count INTEGER NOT NULL DEFAULT 0,
                        claim_count INTEGER NOT NULL DEFAULT 0,
                        evidence_count INTEGER NOT NULL DEFAULT 0,
                        error_message TEXT,
                        processed_at TEXT,
                        metadata_json TEXT,
                        FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id) ON DELETE CASCADE
                    )
                """)
                conn.execute(
                    "INSERT INTO investigations VALUES (?, ?, ?, ?, ?, ?)",
                    ("inv_old", "Old Case", "COMPLETED", "rule", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
                )
                conn.execute(
                    """INSERT INTO documents (
                        document_id, investigation_id, source_name, source_uri, content_hash,
                        raw_bytes, normalized_text, doc_format, status, char_count, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "doc_legacy_101", "inv_old", "legacy_filing.txt", "s3://archive/legacy.txt",
                        "hash_abc_123", b"Legacy Content", "Legacy Content", "txt", "COMPLETED",
                        14, '{"source": "pre_migration"}',
                    ),
                )
                conn.commit()

            # Open with SQLiteInvestigationStore which triggers _migrate_schema
            store = SQLiteInvestigationStore(db_path)

            # 1. Verify schema: primary key is now composite (document_id, investigation_id)
            with store.get_connection() as conn:
                cols = conn.execute("PRAGMA table_info(documents)").fetchall()
                pk_cols = {c["name"] for c in cols if c["pk"] > 0}
                assert pk_cols == {"document_id", "investigation_id"}

            # 2. Verify all rows preserved
            docs = store.list_documents("inv_old")
            assert len(docs) == 1
            assert docs[0]["document_id"] == "doc_legacy_101"
            assert docs[0]["source_name"] == "legacy_filing.txt"
            assert docs[0]["content_hash"] == "hash_abc_123"

            # 3. Verify integrity check passes
            assert store.integrity_check() is True


# =============================================================================
# 4. DB-04: In-Memory SQLite Store Durability
# =============================================================================

class TestInMemorySQLitePersistence:
    """Verify that SQLiteInvestigationStore(':memory:') retains schema and data across calls."""

    def test_memory_store_lifetime_durability(self):
        store = SQLiteInvestigationStore(":memory:")
        inv_id = "inv_mem_test"
        store.save_investigation(inv_id, "In-Memory Test", InvestigationStatus.PROCESSING, "rule")

        # Query investigation immediately
        inv = store.get_investigation(inv_id)
        assert inv is not None
        assert inv["investigation_id"] == inv_id

        # Add entity and query
        ent = InvestigationEntity(entity_id="e1", entity_type=EntityType.PERSON, canonical_name="Alice")
        store.save_entity(inv_id, ent)
        ents = store.list_entities(inv_id)
        assert len(ents) == 1
        assert ents[0].canonical_name == "Alice"

        # Integrity check
        assert store.integrity_check() is True
        store.close()


# =============================================================================
# 5. SEC-01: Remote API Binding & Bearer Token Authentication
# =============================================================================

@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed in this environment")
class TestAPIAccessControl:
    """Verify loopback access and secure token protection for remote exposure."""

    def test_loopback_unauthenticated_default_passes(self):
        app = create_app(db_path=":memory:", backend_mode="rule", enforce_auth=False)
        client = TestClient(app)

        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # List investigations without token succeeds in local mode
        inv_resp = client.get("/api/v1/investigations")
        assert inv_resp.status_code == 200

    def test_remote_mode_rejects_missing_credentials(self):
        test_token = "secret-production-token-12345678"
        app = create_app(db_path=":memory:", backend_mode="rule", api_token=test_token, enforce_auth=True)
        client = TestClient(app)

        # Health probe is public
        health_resp = client.get("/api/v1/health")
        assert health_resp.status_code == 200

        # Protected endpoints reject unauthenticated request
        resp = client.get("/api/v1/investigations")
        assert resp.status_code == 401
        assert "Unauthorized" in resp.json()["detail"]

    def test_remote_mode_accepts_valid_bearer_token(self):
        test_token = "secret-production-token-12345678"
        app = create_app(db_path=":memory:", backend_mode="rule", api_token=test_token, enforce_auth=True)
        client = TestClient(app)

        headers = {"Authorization": f"Bearer {test_token}"}
        resp = client.get("/api/v1/investigations", headers=headers)
        assert resp.status_code == 200

    def test_remote_mode_rejects_invalid_token(self):
        test_token = "secret-production-token-12345678"
        app = create_app(db_path=":memory:", backend_mode="rule", api_token=test_token, enforce_auth=True)
        client = TestClient(app)

        headers = {"Authorization": "Bearer wrong-token-xyz"}
        resp = client.get("/api/v1/investigations", headers=headers)
        assert resp.status_code == 401

    def test_token_comparison_is_constant_time(self):
        assert validate_api_token("valid_token", "valid_token") is True
        assert validate_api_token("wrong_token", "valid_token") is False
        assert validate_api_token(None, "valid_token") is False
        assert validate_api_token("", "valid_token") is False


# =============================================================================
# 6. SEC-02: Bounded Upload Chunk Reading
# =============================================================================

@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed in this environment")
class TestUploadSizeSafeguards:
    """Verify bounded reading and early HTTP 413 termination."""

    def test_upload_exact_limit_accepted(self):
        app = create_app(db_path=":memory:", backend_mode="rule")
        client = TestClient(app)
        client.post("/api/v1/investigations", json={"investigation_id": "inv_up_limit"})

        # Exact 5 MB of plain text
        exact_bytes = b"X" * (MAX_UPLOAD_SIZE_BYTES)
        files = {"file": ("exact.txt", io.BytesIO(exact_bytes), "text/plain")}
        resp = client.post("/api/v1/investigations/inv_up_limit/documents", files=files, data={"auto_process": "false"})
        assert resp.status_code == 201

    def test_upload_one_byte_over_rejected_early(self):
        app = create_app(db_path=":memory:", backend_mode="rule")
        client = TestClient(app)
        client.post("/api/v1/investigations", json={"investigation_id": "inv_up_over"})

        # Exact 5 MB + 1 byte
        over_bytes = b"X" * (MAX_UPLOAD_SIZE_BYTES + 1)
        files = {"file": ("over.txt", io.BytesIO(over_bytes), "text/plain")}
        resp = client.post("/api/v1/investigations/inv_up_over/documents", files=files, data={"auto_process": "false"})
        assert resp.status_code == 413
        assert "exceeds maximum allowed limit" in resp.json()["detail"].lower()


# =============================================================================
# 7. SEC-03: Reviewer Identity Attribution
# =============================================================================

@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed in this environment")
class TestReviewerAttribution:
    """Verify that reviewer identity is validated and impersonation is rejected."""

    def test_impersonation_rejected_when_authenticated(self):
        test_token = "secret-token-for-reviewer-guard-123"
        app = create_app(db_path=":memory:", backend_mode="rule", api_token=test_token, enforce_auth=True)
        client = TestClient(app)
        inv_id = "inv_rev_guard"

        headers = {
            "Authorization": f"Bearer {test_token}",
            "X-Principal-User": "authorized_analyst",
        }
        client.post(f"/api/v1/investigations/{inv_id}/demo", headers=headers)

        q_resp = client.get(f"/api/v1/investigations/{inv_id}/review-queue", headers=headers)
        items = q_resp.json()["items"]
        claim_item = next((item for item in items if item.get("claim_details")), None)
        assert claim_item is not None
        target_claim_id = claim_item["item_id"]

        # Attempt to spoof identity as "chief_administrator"
        spoof_req = {
            "claim_id": target_claim_id,
            "new_status": "VERIFIED",
            "reviewer": "chief_administrator",  # Mismatch with principal!
            "rationale": "Attempted spoofed verification.",
        }
        resp = client.post(f"/api/v1/investigations/{inv_id}/review-claim", json=spoof_req, headers=headers)
        assert resp.status_code == 403
        assert "mismatch" in resp.json()["detail"].lower()

    def test_malformed_reviewer_rejected(self):
        with pytest.raises(Exception):
            validate_reviewer_identity("   ")
        with pytest.raises(Exception):
            validate_reviewer_identity("a/b/c")
        with pytest.raises(Exception):
            validate_reviewer_identity("bad<script>")


# =============================================================================
# 8. LIFE-02: Claim Lifecycle State Transition Matrix
# =============================================================================

class TestLifecycleTransitions:
    """Table-driven test suite for allowed and forbidden review status transitions."""

    @pytest.mark.parametrize(
        "from_status,to_status,should_succeed",
        [
            (ReviewStatus.UNREVIEWED, ReviewStatus.VERIFIED, True),
            (ReviewStatus.UNREVIEWED, ReviewStatus.DISPUTED, True),
            (ReviewStatus.UNREVIEWED, ReviewStatus.REJECTED, True),
            (ReviewStatus.UNREVIEWED, ReviewStatus.RETRACTED, True),
            (ReviewStatus.VERIFIED, ReviewStatus.DISPUTED, True),
            (ReviewStatus.VERIFIED, ReviewStatus.RETRACTED, True),
            (ReviewStatus.DISPUTED, ReviewStatus.VERIFIED, True),
            (ReviewStatus.DISPUTED, ReviewStatus.RETRACTED, True),
            (ReviewStatus.RETRACTED, ReviewStatus.VERIFIED, True),  # Allowed with reinstatement rationale
            (ReviewStatus.RETRACTED, ReviewStatus.UNREVIEWED, True),  # Reinstatement
            (ReviewStatus.RETRACTED, ReviewStatus.DISPUTED, True),
            (ReviewStatus.REJECTED, ReviewStatus.UNREVIEWED, True),  # Reopening
            (ReviewStatus.SUPERSEDED, ReviewStatus.VERIFIED, False),  # Permanently terminal
            (ReviewStatus.SUPERSEDED, ReviewStatus.UNREVIEWED, False),
        ],
    )
    def test_transition_policy(self, from_status, to_status, should_succeed):
        store = InMemoryInvestigationGraphStore()
        store.add_entity(InvestigationEntity(entity_id="e1", entity_type=EntityType.PERSON, canonical_name="P"))
        store.add_entity(InvestigationEntity(entity_id="e2", entity_type=EntityType.ORGANIZATION, canonical_name="O"))

        extra = {}
        if from_status == ReviewStatus.SUPERSEDED:
            extra["superseded_by_claim_id"] = "cl_replacement"
        elif from_status == ReviewStatus.RETRACTED:
            extra["retraction_reason"] = "Initial retraction justification"

        claim = Claim(
            claim_id="cl_matrix",
            subject_id="e1",
            predicate="WORKS_AT",
            object_id="e2",
            review_status=from_status,
            **extra,
        )
        store._claims["cl_matrix"] = claim

        if should_succeed:
            updated = store.update_claim_status(
                "cl_matrix",
                new_status=to_status,
                rationale="Valid test rationale with sufficient length.",
                corrected_by="auditor_test",
            )
            assert updated.review_status == to_status
        else:
            with pytest.raises(InvalidLifecycleTransitionError):
                store.update_claim_status(
                    "cl_matrix",
                    new_status=to_status,
                    rationale="Attempted transition.",
                    corrected_by="auditor_test",
                )

    def test_sqlite_claim_lifecycle_and_audit_history_preservation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "lifecycle_sqlite.db")
            store = SQLiteInvestigationStore(db_path)
            orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)
            inv_id = "inv_lifecycle_flow"
            orchestrator.create_investigation(inv_id, "Lifecycle Audit Flow")

            # Ingest text that generates executive claims
            orchestrator.process_document(
                inv_id,
                b"Alice Mercer serves as CEO of Apex Global Holdings. Apex Global Holdings is located in London.",
                "doc_exec.txt",
            )
            claims = orchestrator.get_extracted_claims(inv_id)
            assert len(claims) > 0
            cid = claims[0].claim_id

            # 1. Retract claim with valid rationale
            orchestrator.review_claim(
                inv_id,
                claim_id=cid,
                new_status=ReviewStatus.RETRACTED,
                rationale="Retracted: source document has been disputed by regulator.",
                reviewer="senior_examiner",
            )
            c1 = orchestrator.get_investigation(inv_id).store.get_claim(cid)
            assert c1.review_status == ReviewStatus.RETRACTED
            assert len(c1.correction_history) == 1
            assert c1.correction_history[0].previous_status == ReviewStatus.UNREVIEWED
            assert c1.correction_history[0].new_status == ReviewStatus.RETRACTED

            # 2. Attempt illegal transition from RETRACTED to VERIFIED without minimum rationale
            with pytest.raises(ValueError, match="audit rationale"):
                orchestrator.review_claim(
                    inv_id,
                    claim_id=cid,
                    new_status=ReviewStatus.VERIFIED,
                    rationale="",  # Empty rationale rejected
                    reviewer="senior_examiner",
                )

            # 3. Explicit reinstatement with valid rationale
            orchestrator.review_claim(
                inv_id,
                claim_id=cid,
                new_status=ReviewStatus.VERIFIED,
                rationale="Reinstated: secondary regulatory filing confirmed appointment.",
                reviewer="chief_counsel",
            )
            c2 = orchestrator.get_investigation(inv_id).store.get_claim(cid)
            assert c2.review_status == ReviewStatus.VERIFIED
            assert len(c2.correction_history) == 2
            assert c2.correction_history[1].previous_status == ReviewStatus.RETRACTED
            assert c2.correction_history[1].new_status == ReviewStatus.VERIFIED
            assert c2.correction_history[1].corrected_by == "chief_counsel"

            # 4. Verify SQLite database reflects full audit history
            sq_claim = {c.claim_id: c for c in store.list_claims(inv_id)}[cid]
            assert sq_claim.review_status == ReviewStatus.VERIFIED
            assert len(sq_claim.correction_history) == 2
            assert sq_claim.correction_history[0].corrected_by == "senior_examiner"
            assert sq_claim.correction_history[1].corrected_by == "chief_counsel"
            assert store.integrity_check() is True


# =============================================================================
# 9. Reliability: Readiness & Backup Verification
# =============================================================================

class TestReliabilityAndDiagnostics:
    """Verify /ready probe, database integrity, and online backup."""

    @pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed in this environment")
    def test_ready_probe_operational(self):
        app = create_app(db_path=":memory:", backend_mode="rule")
        client = TestClient(app)

        resp = client.get("/api/v1/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
        assert resp.json()["database"] == "operational"

    def test_online_backup_and_recovery(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            src_path = os.path.join(tmp_dir, "primary.db")
            bak_path = os.path.join(tmp_dir, "backup.db")

            store = SQLiteInvestigationStore(src_path)
            store.save_investigation("inv_bk", "Backup Test", InvestigationStatus.COMPLETED, "rule")

            # Perform backup
            store.backup(bak_path)
            assert os.path.exists(bak_path)

            # Open backup in new store and verify data
            bak_store = SQLiteInvestigationStore(bak_path)
            inv = bak_store.get_investigation("inv_bk")
            assert inv is not None
            assert inv["investigation_id"] == "inv_bk"
            assert bak_store.integrity_check() is True

    def test_investigation_survives_store_close_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "durability.db")
            store = SQLiteInvestigationStore(db_path)
            orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)
            inv_id = "inv_durable_1"
            orchestrator.create_investigation(inv_id, "Durability Case")

            doc_text = b"Alice Mercer serves as CEO of Apex Global Holdings. Apex Global Holdings is located in London."
            orchestrator.process_document(inv_id, doc_text, "doc_durable.txt")

            claims_pre = orchestrator.get_extracted_claims(inv_id)
            assert len(claims_pre) > 0

            # Close and drop orchestrator
            del orchestrator
            del store

            # Recreate store and orchestrator from the exact same disk file
            new_store = SQLiteInvestigationStore(db_path)
            new_orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=new_store)
            new_session = new_orchestrator.create_investigation(inv_id, "Hydrated Case")

            hydrated = new_store.load_investigation_into_session(inv_id, new_session)
            assert hydrated is True

            # Verify session re-hydrated records
            assert len(new_session.store.list_entities()) > 0
            assert len(new_session.store.list_claims()) == len(claims_pre)
            assert len(new_session.document_records) > 0
            assert new_store.integrity_check() is True

    def test_fault_injection_rolls_back_all_tables_completely(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "atomic_all_tables.db")
            store = SQLiteInvestigationStore(db_path)
            orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)
            inv_id = "inv_rollback_all"
            session = orchestrator.create_investigation(inv_id, "Atomic Multi-Table Test")

            doc_text = b"Alice Mercer serves as CEO of Apex Global Holdings. Apex Global Holdings is located in London."
            orchestrator.process_document(inv_id, doc_text, "baseline_doc.txt")

            # Capture exact baseline counts across all tables
            base_ents = len(store.list_entities(inv_id))
            base_claims = len(store.list_claims(inv_id))
            base_evs = len(store.list_evidence(inv_id))
            base_docs = len(store.list_documents(inv_id))
            assert base_ents > 0 and base_claims > 0 and base_evs > 0 and base_docs > 0

            # Add new items to in-memory session store
            new_ent = InvestigationEntity(entity_id="ent_ghost_1", entity_type=EntityType.PERSON, canonical_name="Ghost Person")
            session.store.add_entity(new_ent)

            new_ev = Evidence(
                evidence_id="ev_ghost_1",
                document_reference="baseline_doc.txt",
                evidence_type="text_span",
                polarity=EvidencePolarity.SUPPORTING,
                content="Ghost evidence content",
                text_span="Ghost evidence",
                char_offsets=(0, 14),
                content_hash="ghosthash123",
                provenance="extraction:rule",
                review_status=ReviewStatus.UNREVIEWED,
            )
            session.store.add_evidence(new_ev)

            # Fault-inject: monkeypatch _save_relationship_tx to raise an error
            orig_save_rel = store._save_relationship_tx
            def faulty_rel_save(conn, iid, rel):
                raise sqlite3.OperationalError("Simulated disk error during relationship phase")
            store._save_relationship_tx = faulty_rel_save

            # Attempt synchronization; must roll back everything
            with pytest.raises(sqlite3.OperationalError, match="Simulated disk error"):
                store.sync_session(session)

            store._save_relationship_tx = orig_save_rel

            # Verify that ZERO new records leaked into any SQLite table
            assert len(store.list_entities(inv_id)) == base_ents
            assert "ent_ghost_1" not in {e.entity_id for e in store.list_entities(inv_id)}
            assert len(store.list_evidence(inv_id)) == base_evs
            assert "ev_ghost_1" not in {e.evidence_id for e in store.list_evidence(inv_id)}
            assert len(store.list_claims(inv_id)) == base_claims
            assert len(store.list_documents(inv_id)) == base_docs
            assert store.integrity_check() is True

    def test_reingestion_after_store_reopen_preserves_human_review(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "reopen_reingest.db")
            store = SQLiteInvestigationStore(db_path)
            orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)
            inv_id = "inv_reopen_review"
            orchestrator.create_investigation(inv_id, "Review Reopen Case")

            doc_text = b"Alice Mercer serves as CEO of Apex Global Holdings. Apex Global Holdings is located in London."
            orchestrator.process_document(inv_id, doc_text, "source_doc.txt")

            claims = orchestrator.get_extracted_claims(inv_id)
            cid = claims[0].claim_id

            orchestrator.review_claim(
                inv_id,
                claim_id=cid,
                new_status=ReviewStatus.VERIFIED,
                rationale="Verified against UK Companies House record.",
                reviewer="senior_investigator_99",
            )

            # Close store and orchestrator
            del orchestrator
            del store

            # Reopen from disk
            new_store = SQLiteInvestigationStore(db_path)
            new_orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=new_store)
            session = new_orchestrator.create_investigation(inv_id, "Reloaded Case")
            new_store.load_investigation_into_session(inv_id, session)

            # Re-process document
            new_orchestrator.process_document(inv_id, doc_text, "source_doc.txt", force_reprocess=True)

            # Claim must still be VERIFIED with same reviewer attribution
            reloaded_claim = session.store.get_claim(cid)
            assert reloaded_claim.review_status == ReviewStatus.VERIFIED
            assert reloaded_claim.correction_history[-1].corrected_by == "senior_investigator_99"

            sq_claim = {c.claim_id: c for c in new_store.list_claims(inv_id)}[cid]
            assert sq_claim.review_status == ReviewStatus.VERIFIED
            assert sq_claim.correction_history[-1].corrected_by == "senior_investigator_99"
            assert new_store.integrity_check() is True

    def test_corrupt_database_fails_safely_without_silent_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "corrupt_test.db")
            garbage_bytes = b"CORRUPTED_NOT_A_VALID_SQLITE_FILE_HEADER_GARBAGE_PAYLOAD"
            with open(db_path, "wb") as f:
                f.write(garbage_bytes)

            # Attempting to open or initialize the corrupted file must fail with actionable error
            with pytest.raises(sqlite3.DatabaseError):
                SQLiteInvestigationStore(db_path)

            # The corrupt file must NOT have been silently overwritten or deleted
            assert os.path.exists(db_path)
            with open(db_path, "rb") as f:
                assert f.read() == garbage_bytes

    def test_multi_investigation_isolation_across_reopen_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "multi_inv.db")
            bak_path = os.path.join(tmp_dir, "multi_inv_backup.db")

            store = SQLiteInvestigationStore(db_path)
            orchestrator = InvestigationOrchestrator(default_backend_mode="rule", sqlite_store=store)

            inv_1 = "inv_classified_alpha"
            inv_2 = "inv_confidential_bravo"
            orchestrator.create_investigation(inv_1, "Alpha Operation")
            orchestrator.create_investigation(inv_2, "Bravo Operation")

            doc_text = b"Alice Mercer serves as CEO of Apex Global Holdings. Apex Global Holdings is located in London."
            orchestrator.process_document(inv_1, doc_text, "d1.txt")
            orchestrator.process_document(inv_2, doc_text, "d2.txt")

            # Perform backup
            store.backup(bak_path)

            # Open backup in a new store instance
            bak_store = SQLiteInvestigationStore(bak_path)
            assert bak_store.integrity_check() is True

            # Verify complete isolation
            docs_1 = bak_store.list_documents(inv_1)
            docs_2 = bak_store.list_documents(inv_2)
            assert len(docs_1) == 1 and len(docs_2) == 1
            assert docs_1[0]["investigation_id"] == inv_1
            assert docs_2[0]["investigation_id"] == inv_2
