"""
SQLite Persistence Store for Sherlock AI Investigation Engine (Milestone 13).

Provides durable, local ACID storage for:
1. Investigation metadata and lifecycle states.
2. Ingested documents (raw bytes, normalized text, hashes, processing status).
3. Extracted and provisional entities.
4. Grounded evidence items with character offsets.
5. Claims with epistemic qualifiers, review statuses, and correction history.
6. Derived typed relationships and dispute states.
7. Structured JSON and Markdown reports.

Guarantees:
- Safe local persistence surviving process restarts.
- Strict isolation by investigation_id.
- Full compatibility with core Pydantic domain models.
- Honest reporting: clearly identifies SQLite storage path or in-memory mode.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any, Set
import os

from src.core.models import (
    InvestigationEntity,
    Relationship,
    Claim,
    Evidence,
    Record,
    ReviewStatus,
    RelationshipEpistemicTier,
    EntityType,
    EvidencePolarity,
    ConfidenceSemantics,
    ClaimCorrection,
)
from src.core.document_ingestion import (
    IngestedDocument,
    DocumentFormat,
)
from src.core.investigation_service import (
    InvestigationStatus,
    DocumentProcessingStatus,
    DocumentProcessingRecord,
    InvestigationReport,
)


def _safe_json_dumps(obj: Any) -> str:
    """Serialize object to JSON safely handling mappingproxy and custom objects."""
    def _default(o):
        if hasattr(o, "items"):
            return dict(o)
        if hasattr(o, "model_dump"):
            return o.model_dump()
        return str(o)
    return json.dumps(obj, default=_default)


class SQLiteInvestigationStore:
    """
    Durable SQLite-backed storage engine for Sherlock AI investigations.
    """

    def __init__(self, db_path: str = "data/sherlock_investigations.db"):
        self.db_path = db_path
        self._is_memory = db_path == ":memory:"
        self._keeper_conn = None

        if self._is_memory:
            self._mem_uri = f"file:sherlock_mem_{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._keeper_conn = sqlite3.connect(self._mem_uri, uri=True, check_same_thread=False)
            self._keeper_conn.execute("PRAGMA foreign_keys = ON")
        else:
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        self._init_schema()

    def get_connection(self) -> sqlite3.Connection:
        """Create or return an active connection with Row factory."""
        if self._is_memory:
            conn = sqlite3.connect(self._mem_uri, uri=True, check_same_thread=False)
        else:
            conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def close(self) -> None:
        """Close keeper connection if in-memory store."""
        if self._keeper_conn is not None:
            self._keeper_conn.close()
            self._keeper_conn = None

    def integrity_check(self) -> bool:
        """Run SQLite PRAGMA integrity_check and return True if ok."""
        with self.get_connection() as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return bool(row and row[0] == "ok")

    def backup(self, backup_path: str) -> None:
        """Perform consistent online SQLite database backup."""
        os.makedirs(os.path.dirname(os.path.abspath(backup_path)), exist_ok=True)
        with self.get_connection() as src:
            with sqlite3.connect(backup_path) as dst:
                src.backup(dst)

    def _init_schema(self) -> None:
        """Initialize all relational tables, migrations, and indexes."""
        with self.get_connection() as conn:
            # Check if existing documents table needs migration from single PK to composite PK
            cursor = conn.execute("PRAGMA table_info(documents)")
            cols = cursor.fetchall()
            if cols:
                pk_cols = [c["name"] for c in cols if c["pk"] > 0]
                if pk_cols == ["document_id"]:
                    conn.execute("PRAGMA foreign_keys = OFF")
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS documents_v2 (
                            document_id TEXT NOT NULL,
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
                            PRIMARY KEY (investigation_id, document_id),
                            FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id) ON DELETE CASCADE
                        )
                    """)
                    conn.execute("""
                        INSERT OR IGNORE INTO documents_v2
                        SELECT document_id, investigation_id, source_name, source_uri, content_hash,
                               raw_bytes, normalized_text, doc_format, status, char_count, mention_count,
                               claim_count, evidence_count, error_message, processed_at, metadata_json
                        FROM documents
                    """)
                    conn.execute("DROP TABLE documents")
                    conn.execute("ALTER TABLE documents_v2 RENAME TO documents")
                    conn.execute("PRAGMA foreign_keys = ON")

            # Check if investigations table needs owner_id column migration
            cursor_inv = conn.execute("PRAGMA table_info(investigations)")
            inv_cols = [c["name"] for c in cursor_inv.fetchall()]
            if inv_cols and "owner_id" not in inv_cols:
                conn.execute("ALTER TABLE investigations ADD COLUMN owner_id TEXT")

            conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                hashed_password TEXT NOT NULL,
                full_name TEXT,
                role TEXT NOT NULL DEFAULT 'analyst',
                created_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                username TEXT,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                details_json TEXT,
                ip_address TEXT,
                timestamp TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp);

            CREATE TABLE IF NOT EXISTS investigations (
                investigation_id TEXT PRIMARY KEY,
                description TEXT,
                status TEXT NOT NULL,
                backend_mode TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                owner_id TEXT
            );

            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT NOT NULL,
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
                PRIMARY KEY (investigation_id, document_id),
                FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS entities (
                entity_id TEXT NOT NULL,
                investigation_id TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                cluster_id TEXT,
                member_record_ids_json TEXT,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (investigation_id, entity_id),
                FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS evidence_items (
                evidence_id TEXT NOT NULL,
                investigation_id TEXT NOT NULL,
                document_id TEXT,
                evidence_type TEXT NOT NULL,
                polarity TEXT NOT NULL,
                content TEXT NOT NULL,
                text_span TEXT NOT NULL,
                start_char INTEGER NOT NULL,
                end_char INTEGER NOT NULL,
                content_hash TEXT,
                source_uri TEXT,
                review_status TEXT NOT NULL,
                extraction_method TEXT,
                extractor_version TEXT,
                provenance TEXT NOT NULL,
                metadata_json TEXT,
                PRIMARY KEY (investigation_id, evidence_id),
                FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS claims (
                claim_id TEXT NOT NULL,
                investigation_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object_id TEXT NOT NULL,
                confidence REAL,
                confidence_semantics TEXT,
                review_status TEXT NOT NULL,
                qualifiers_json TEXT,
                supporting_evidence_ids_json TEXT,
                contradicting_evidence_ids_json TEXT,
                correction_history_json TEXT,
                superseded_by_claim_id TEXT,
                retraction_reason TEXT,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (investigation_id, claim_id),
                FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS relationships (
                relationship_id TEXT NOT NULL,
                investigation_id TEXT NOT NULL,
                source_entity_id TEXT NOT NULL,
                target_entity_id TEXT NOT NULL,
                relationship_type TEXT NOT NULL,
                is_directed INTEGER NOT NULL DEFAULT 1,
                epistemic_tier TEXT NOT NULL,
                review_status TEXT NOT NULL,
                supporting_claim_ids_json TEXT,
                supporting_evidence_ids_json TEXT,
                contradicting_claim_ids_json TEXT,
                contradicting_evidence_ids_json TEXT,
                provenance TEXT NOT NULL,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (investigation_id, relationship_id),
                FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS reports (
                investigation_id TEXT PRIMARY KEY,
                generated_at TEXT NOT NULL,
                report_schema_version TEXT NOT NULL,
                report_json TEXT NOT NULL,
                report_markdown TEXT NOT NULL,
                FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_docs_inv ON documents(investigation_id);
            CREATE INDEX IF NOT EXISTS idx_docs_hash ON documents(investigation_id, content_hash);
            CREATE INDEX IF NOT EXISTS idx_entities_inv ON entities(investigation_id);
            CREATE INDEX IF NOT EXISTS idx_evidence_inv ON evidence_items(investigation_id);
            CREATE INDEX IF NOT EXISTS idx_claims_inv ON claims(investigation_id);
            CREATE INDEX IF NOT EXISTS idx_rels_inv ON relationships(investigation_id);
            """)

    # ──── Investigation CRUD ────

    # ──── Investigation CRUD ────

    def _save_investigation_tx(
        self,
        conn: sqlite3.Connection,
        investigation_id: str,
        description: str,
        status: InvestigationStatus,
        backend_mode: str,
        created_at: Optional[datetime] = None,
        owner_id: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        c_at = created_at.isoformat() if created_at else now
        conn.execute(
            """
            INSERT INTO investigations (investigation_id, description, status, backend_mode, created_at, updated_at, owner_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(investigation_id) DO UPDATE SET
                description = excluded.description,
                status = excluded.status,
                backend_mode = excluded.backend_mode,
                updated_at = excluded.updated_at,
                owner_id = COALESCE(excluded.owner_id, investigations.owner_id)
            """,
            (investigation_id, description, status.value, backend_mode, c_at, now, owner_id),
        )

    def save_investigation(
        self,
        investigation_id: str,
        description: str,
        status: InvestigationStatus,
        backend_mode: str,
        created_at: Optional[datetime] = None,
        owner_id: Optional[str] = None,
    ) -> None:
        with self.get_connection() as conn:
            self._save_investigation_tx(
                conn,
                investigation_id=investigation_id,
                description=description,
                status=status,
                backend_mode=backend_mode,
                created_at=created_at,
                owner_id=owner_id,
            )

    def get_investigation(self, investigation_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if row:
                return dict(row)
        return None

    def get_investigation_owner(self, investigation_id: str) -> Optional[str]:
        """Return owner_id of investigation if set."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT owner_id FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if row and row["owner_id"]:
                return str(row["owner_id"])
        return None

    def list_investigations(self, owner_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            if owner_id:
                rows = conn.execute(
                    "SELECT * FROM investigations WHERE owner_id = ? OR owner_id IS NULL ORDER BY created_at DESC",
                    (owner_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM investigations ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    # ──── Users & Audit Logging ────

    def create_user(
        self,
        user_id: str,
        username: str,
        email: str,
        hashed_password: str,
        full_name: Optional[str] = None,
        role: str = "analyst",
    ) -> Dict[str, Any]:
        """Create a new user in the persistent store."""
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (id, username, email, hashed_password, full_name, role, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (user_id, username, email, hashed_password, full_name, role, now),
            )
        return {
            "id": user_id,
            "username": username,
            "email": email,
            "full_name": full_name,
            "role": role,
            "created_at": now,
            "is_active": True,
        }

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve user by ID."""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row:
                return dict(row)
        return None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Retrieve user by username."""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)).fetchone()
            if row:
                return dict(row)
        return None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Retrieve user by email."""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(?)", (email,)).fetchone()
            if row:
                return dict(row)
        return None

    def record_audit_log(
        self,
        user_id: Optional[str],
        username: Optional[str],
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> str:
        """Record an immutable audit log entry."""
        log_id = f"audit_{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        details_json = json.dumps(details or {})
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs (id, user_id, username, action, target_type, target_id, details_json, ip_address, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (log_id, user_id, username, action, target_type, target_id, details_json, ip_address, now),
            )
        return log_id

    def get_audit_logs(
        self,
        user_id: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query audit logs with optional filters."""
        query = "SELECT * FROM audit_logs WHERE 1=1"
        params: List[Any] = []
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        if target_type:
            query += " AND target_type = ?"
            params.append(target_type)
        if target_id:
            query += " AND target_id = ?"
            params.append(target_id)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self.get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                try:
                    d["details"] = json.loads(d.get("details_json") or "{}")
                except Exception:
                    d["details"] = {}
                results.append(d)
            return results

    # ──── Documents CRUD ────

    def _save_document_tx(
        self,
        conn: sqlite3.Connection,
        investigation_id: str,
        doc_record: DocumentProcessingRecord,
        raw_bytes: Optional[bytes] = None,
        normalized_text: Optional[str] = None,
        doc_format: str = "txt",
    ) -> None:
        p_at = doc_record.processed_at.isoformat() if doc_record.processed_at else None
        meta_json = _safe_json_dumps(doc_record.metadata)
        conn.execute(
            """
            INSERT INTO documents (
                document_id, investigation_id, source_name, source_uri, content_hash,
                raw_bytes, normalized_text, doc_format, status, char_count, mention_count,
                claim_count, evidence_count, error_message, processed_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(investigation_id, document_id) DO UPDATE SET
                status = excluded.status,
                char_count = excluded.char_count,
                mention_count = excluded.mention_count,
                claim_count = excluded.claim_count,
                evidence_count = excluded.evidence_count,
                error_message = excluded.error_message,
                processed_at = excluded.processed_at,
                metadata_json = excluded.metadata_json
            """,
            (
                doc_record.document_id,
                investigation_id,
                doc_record.source_name,
                doc_record.source_uri,
                doc_record.content_hash,
                raw_bytes,
                normalized_text,
                doc_format,
                doc_record.status.value,
                doc_record.char_count,
                doc_record.mention_count,
                doc_record.claim_count,
                doc_record.evidence_count,
                doc_record.error_message,
                p_at,
                meta_json,
            ),
        )

    def save_document(
        self,
        investigation_id: str,
        doc_record: DocumentProcessingRecord,
        raw_bytes: Optional[bytes] = None,
        normalized_text: Optional[str] = None,
        doc_format: str = "txt",
    ) -> None:
        with self.get_connection() as conn:
            self._save_document_tx(
                conn,
                investigation_id=investigation_id,
                doc_record=doc_record,
                raw_bytes=raw_bytes,
                normalized_text=normalized_text,
                doc_format=doc_format,
            )

    def get_document(self, investigation_id: str, document_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE investigation_id = ? AND document_id = ?",
                (investigation_id, document_id),
            ).fetchone()
            if row:
                d = dict(row)
                d["metadata"] = json.loads(d.get("metadata_json") or "{}")
                return d
        return None

    def list_documents(self, investigation_id: str) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM documents WHERE investigation_id = ? ORDER BY rowid ASC",
                (investigation_id,),
            ).fetchall()
            docs = []
            for r in rows:
                d = dict(r)
                d["metadata"] = json.loads(d.get("metadata_json") or "{}")
                docs.append(d)
            return docs

    # ──── Entities CRUD ────

    # ──── Entities CRUD ────

    def _save_entity_tx(self, conn: sqlite3.Connection, investigation_id: str, entity: InvestigationEntity) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO entities (
                entity_id, investigation_id, canonical_name, entity_type, cluster_id,
                member_record_ids_json, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(investigation_id, entity_id) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                entity_type = excluded.entity_type,
                cluster_id = excluded.cluster_id,
                member_record_ids_json = excluded.member_record_ids_json,
                metadata_json = excluded.metadata_json
            """,
            (
                entity.entity_id,
                investigation_id,
                entity.canonical_name,
                entity.entity_type.value,
                entity.cluster_id,
                _safe_json_dumps(list(entity.member_record_ids)),
                _safe_json_dumps(dict(entity.metadata)),
                now,
            ),
        )

    def save_entity(self, investigation_id: str, entity: InvestigationEntity) -> None:
        with self.get_connection() as conn:
            self._save_entity_tx(conn, investigation_id, entity)

    def remove_entity(self, investigation_id: str, entity_id: str, cascade_relationships: bool = False) -> bool:
        with self.get_connection() as conn:
            with conn:
                if cascade_relationships:
                    conn.execute(
                        "DELETE FROM relationships WHERE investigation_id = ? AND (source_entity_id = ? OR target_entity_id = ?)",
                        (investigation_id, entity_id, entity_id),
                    )
                cur = conn.execute(
                    "DELETE FROM entities WHERE investigation_id = ? AND entity_id = ?",
                    (investigation_id, entity_id),
                )
                return cur.rowcount > 0

    def list_entities(self, investigation_id: str) -> List[InvestigationEntity]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM entities WHERE investigation_id = ? ORDER BY entity_id ASC",
                (investigation_id,),
            ).fetchall()
            entities = []
            for r in rows:
                members = json.loads(r["member_record_ids_json"] or "[]")
                meta = json.loads(r["metadata_json"] or "{}")
                entities.append(
                    InvestigationEntity(
                        entity_id=r["entity_id"],
                        canonical_name=r["canonical_name"],
                        entity_type=EntityType(r["entity_type"]),
                        cluster_id=r["cluster_id"],
                        member_record_ids=members,
                        metadata=meta,
                    )
                )
            return entities

    # ──── Evidence CRUD ────

    def _save_evidence_tx(self, conn: sqlite3.Connection, investigation_id: str, evidence: Evidence) -> None:
        conn.execute(
            """
            INSERT INTO evidence_items (
                evidence_id, investigation_id, document_id, evidence_type, polarity,
                content, text_span, start_char, end_char, content_hash, source_uri,
                review_status, extraction_method, extractor_version, provenance, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(investigation_id, evidence_id) DO UPDATE SET
                review_status = excluded.review_status,
                metadata_json = excluded.metadata_json
            """,
            (
                evidence.evidence_id,
                investigation_id,
                evidence.document_reference,
                evidence.evidence_type,
                evidence.polarity.value,
                evidence.content,
                evidence.text_span,
                evidence.char_offsets[0] if evidence.char_offsets else 0,
                evidence.char_offsets[1] if evidence.char_offsets else len(evidence.text_span or evidence.content or ""),
                evidence.content_hash,
                evidence.source_uri,
                evidence.review_status.value,
                evidence.extraction_method,
                evidence.extractor_version,
                evidence.provenance,
                _safe_json_dumps(evidence.metadata),
            ),
        )

    def save_evidence(self, investigation_id: str, evidence: Evidence) -> None:
        with self.get_connection() as conn:
            self._save_evidence_tx(conn, investigation_id, evidence)

    def list_evidence(self, investigation_id: str) -> List[Evidence]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_items WHERE investigation_id = ? ORDER BY evidence_id ASC",
                (investigation_id,),
            ).fetchall()
            evs = []
            for r in rows:
                evs.append(
                    Evidence(
                        evidence_id=r["evidence_id"],
                        document_reference=r["document_id"],
                        evidence_type=r["evidence_type"],
                        polarity=EvidencePolarity(r["polarity"]),
                        content=r["content"],
                        text_span=r["text_span"],
                        char_offsets=(r["start_char"], r["end_char"]),
                        content_hash=r["content_hash"],
                        source_uri=r["source_uri"],
                        review_status=ReviewStatus(r["review_status"]),
                        extraction_method=r["extraction_method"] or "rule",
                        extractor_version=r["extractor_version"],
                        provenance=r["provenance"],
                        metadata=json.loads(r["metadata_json"] or "{}"),
                    )
                )
            return evs

    # ──── Claims CRUD ────

    # ──── Claims CRUD ────

    def _save_claim_tx(self, conn: sqlite3.Connection, investigation_id: str, claim: Claim) -> None:
        now = datetime.now(timezone.utc).isoformat()
        c_at = claim.created_at.isoformat() if claim.created_at else now
        u_at = claim.updated_at.isoformat() if claim.updated_at else now

        history_data = []
        for corr in claim.correction_history:
            history_data.append(corr.model_dump())

        conn.execute(
            """
            INSERT INTO claims (
                claim_id, investigation_id, subject_id, predicate, object_id,
                confidence, confidence_semantics, review_status, qualifiers_json,
                supporting_evidence_ids_json, contradicting_evidence_ids_json,
                correction_history_json, superseded_by_claim_id, retraction_reason,
                metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(investigation_id, claim_id) DO UPDATE SET
                subject_id = excluded.subject_id,
                predicate = excluded.predicate,
                object_id = excluded.object_id,
                confidence = excluded.confidence,
                confidence_semantics = excluded.confidence_semantics,
                review_status = CASE 
                    WHEN claims.review_status IN ('VERIFIED', 'RETRACTED', 'REJECTED', 'SUPERSEDED', 'DISPUTED')
                         AND excluded.review_status = 'UNREVIEWED'
                    THEN claims.review_status 
                    ELSE excluded.review_status 
                END,
                qualifiers_json = excluded.qualifiers_json,
                supporting_evidence_ids_json = excluded.supporting_evidence_ids_json,
                contradicting_evidence_ids_json = excluded.contradicting_evidence_ids_json,
                correction_history_json = CASE
                    WHEN claims.review_status IN ('VERIFIED', 'RETRACTED', 'REJECTED', 'SUPERSEDED', 'DISPUTED')
                         AND excluded.review_status = 'UNREVIEWED'
                    THEN claims.correction_history_json
                    ELSE excluded.correction_history_json
                END,
                superseded_by_claim_id = CASE
                    WHEN claims.superseded_by_claim_id IS NOT NULL AND excluded.superseded_by_claim_id IS NULL
                    THEN claims.superseded_by_claim_id
                    ELSE excluded.superseded_by_claim_id
                END,
                retraction_reason = CASE
                    WHEN claims.retraction_reason IS NOT NULL AND excluded.retraction_reason IS NULL
                    THEN claims.retraction_reason
                    ELSE excluded.retraction_reason
                END,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                claim.claim_id,
                investigation_id,
                claim.subject_id,
                claim.predicate,
                claim.object_id,
                claim.confidence,
                claim.confidence_semantics.value if claim.confidence_semantics else None,
                claim.review_status.value,
                _safe_json_dumps(claim.qualifiers),
                _safe_json_dumps(list(claim.supporting_evidence_ids)),
                _safe_json_dumps(list(claim.contradicting_evidence_ids)),
                _safe_json_dumps(history_data),
                claim.superseded_by_claim_id,
                claim.retraction_reason,
                _safe_json_dumps(claim.metadata),
                c_at,
                u_at,
            ),
        )

    def save_claim(self, investigation_id: str, claim: Claim) -> None:
        with self.get_connection() as conn:
            self._save_claim_tx(conn, investigation_id, claim)

    def list_claims(self, investigation_id: str) -> List[Claim]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM claims WHERE investigation_id = ? ORDER BY claim_id ASC",
                (investigation_id,),
            ).fetchall()
            claims = []
            for r in rows:
                history_raw = json.loads(r["correction_history_json"] or "[]")
                history = [ClaimCorrection(**item) for item in history_raw]
                semantics = (
                    ConfidenceSemantics(r["confidence_semantics"])
                    if r["confidence_semantics"]
                    else ConfidenceSemantics.HEURISTIC_SCORE
                )
                claims.append(
                    Claim(
                        claim_id=r["claim_id"],
                        subject_id=r["subject_id"],
                        predicate=r["predicate"],
                        object_id=r["object_id"],
                        confidence=r["confidence"],
                        confidence_semantics=semantics,
                        review_status=ReviewStatus(r["review_status"]),
                        qualifiers=json.loads(r["qualifiers_json"] or "{}"),
                        supporting_evidence_ids=json.loads(r["supporting_evidence_ids_json"] or "[]"),
                        contradicting_evidence_ids=json.loads(r["contradicting_evidence_ids_json"] or "[]"),
                        correction_history=history,
                        superseded_by_claim_id=r["superseded_by_claim_id"],
                        retraction_reason=r["retraction_reason"],
                        metadata=json.loads(r["metadata_json"] or "{}"),
                        created_at=datetime.fromisoformat(r["created_at"]),
                        updated_at=datetime.fromisoformat(r["updated_at"]),
                    )
                )
            return claims

    # ──── Relationships CRUD ────

    # ──── Relationships CRUD ────

    def _save_relationship_tx(self, conn: sqlite3.Connection, investigation_id: str, relationship: Relationship) -> None:
        now = datetime.now(timezone.utc).isoformat()
        c_at = relationship.created_at.isoformat() if relationship.created_at else now
        u_at = relationship.updated_at.isoformat() if relationship.updated_at else now

        conn.execute(
            """
            INSERT INTO relationships (
                relationship_id, investigation_id, source_entity_id, target_entity_id,
                relationship_type, is_directed, epistemic_tier, review_status,
                supporting_claim_ids_json, supporting_evidence_ids_json,
                contradicting_claim_ids_json, contradicting_evidence_ids_json,
                provenance, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(investigation_id, relationship_id) DO UPDATE SET
                review_status = CASE 
                    WHEN relationships.review_status IN ('VERIFIED', 'RETRACTED', 'REJECTED', 'SUPERSEDED', 'DISPUTED')
                         AND excluded.review_status = 'UNREVIEWED'
                    THEN relationships.review_status 
                    ELSE excluded.review_status 
                END,
                supporting_claim_ids_json = excluded.supporting_claim_ids_json,
                supporting_evidence_ids_json = excluded.supporting_evidence_ids_json,
                contradicting_claim_ids_json = excluded.contradicting_claim_ids_json,
                contradicting_evidence_ids_json = excluded.contradicting_evidence_ids_json,
                updated_at = excluded.updated_at
            """,
            (
                relationship.relationship_id,
                investigation_id,
                relationship.source_entity_id,
                relationship.target_entity_id,
                relationship.relationship_type,
                1 if relationship.is_directed else 0,
                relationship.epistemic_tier.value,
                relationship.review_status.value,
                _safe_json_dumps(list(relationship.supporting_claim_ids)),
                _safe_json_dumps(list(relationship.supporting_evidence_ids)),
                _safe_json_dumps(list(relationship.contradicting_claim_ids)),
                _safe_json_dumps(list(relationship.contradicting_evidence_ids)),
                relationship.provenance,
                _safe_json_dumps({
                    **relationship.metadata,
                    "polarity": relationship.polarity,
                    "attribution": relationship.attribution,
                    "unique_source_hashes": list(relationship.unique_source_hashes),
                    "duplicate_evidence_count": relationship.duplicate_evidence_count,
                }),
                c_at,
                u_at,
            ),
        )

    def save_relationship(self, investigation_id: str, relationship: Relationship) -> None:
        with self.get_connection() as conn:
            self._save_relationship_tx(conn, investigation_id, relationship)

    def remove_relationship(self, investigation_id: str, relationship_id: str) -> bool:
        with self.get_connection() as conn:
            with conn:
                cur = conn.execute(
                    "DELETE FROM relationships WHERE investigation_id = ? AND relationship_id = ?",
                    (investigation_id, relationship_id),
                )
                return cur.rowcount > 0

    def list_relationships(self, investigation_id: str) -> List[Relationship]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM relationships WHERE investigation_id = ? ORDER BY relationship_id ASC",
                (investigation_id,),
            ).fetchall()
            rels = []
            for r in rows:
                meta = json.loads(r["metadata_json"] or "{}")
                rels.append(
                    Relationship(
                        relationship_id=r["relationship_id"],
                        source_entity_id=r["source_entity_id"],
                        target_entity_id=r["target_entity_id"],
                        relationship_type=r["relationship_type"],
                        is_directed=bool(r["is_directed"]),
                        epistemic_tier=RelationshipEpistemicTier(r["epistemic_tier"]),
                        review_status=ReviewStatus(r["review_status"]),
                        supporting_claim_ids=json.loads(r["supporting_claim_ids_json"] or "[]"),
                        supporting_evidence_ids=json.loads(r["supporting_evidence_ids_json"] or "[]"),
                        contradicting_claim_ids=json.loads(r["contradicting_claim_ids_json"] or "[]"),
                        contradicting_evidence_ids=json.loads(r["contradicting_evidence_ids_json"] or "[]"),
                        polarity=meta.get("polarity", "POSITIVE"),
                        attribution=meta.get("attribution"),
                        unique_source_hashes=meta.get("unique_source_hashes", []),
                        duplicate_evidence_count=meta.get("duplicate_evidence_count", 0),
                        provenance=r["provenance"],
                        metadata=meta,
                        created_at=datetime.fromisoformat(r["created_at"]),
                        updated_at=datetime.fromisoformat(r["updated_at"]),
                    )
                )
            return rels

    # ──── Reports CRUD ────

    # ──── Reports CRUD ────

    def _save_report_tx(
        self,
        conn: sqlite3.Connection,
        investigation_id: str,
        report_schema_version: str,
        report_json: str,
        report_markdown: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO reports (
                investigation_id, generated_at, report_schema_version, report_json, report_markdown
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(investigation_id) DO UPDATE SET
                generated_at = excluded.generated_at,
                report_schema_version = excluded.report_schema_version,
                report_json = excluded.report_json,
                report_markdown = excluded.report_markdown
            """,
            (investigation_id, now, report_schema_version, report_json, report_markdown),
        )

    def save_report(
        self,
        investigation_id: str,
        report_schema_version: str,
        report_json: str,
        report_markdown: str,
    ) -> None:
        with self.get_connection() as conn:
            self._save_report_tx(conn, investigation_id, report_schema_version, report_json, report_markdown)

    def list_investigation_ids(self, owner_id: Optional[str] = None) -> List[str]:
        """List all known investigation IDs in the database."""
        with self.get_connection() as conn:
            if owner_id:
                rows = conn.execute(
                    "SELECT investigation_id FROM investigations WHERE owner_id = ? OR owner_id IS NULL ORDER BY created_at DESC",
                    (owner_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT investigation_id FROM investigations ORDER BY created_at DESC"
                ).fetchall()
            return [r["investigation_id"] for r in rows]

    def sync_session(self, session: Any) -> None:
        """Synchronize an entire InvestigationSession into SQLite in a single atomic transaction."""
        with self.get_connection() as conn:
            with conn:  # Atomic transaction boundary; rolls back on any exception
                self._save_investigation_tx(
                    conn,
                    investigation_id=session.investigation_id,
                    description=session.description,
                    status=session.status,
                    backend_mode=session.backend_mode,
                    created_at=session.created_at,
                    owner_id=getattr(session, "owner_id", None),
                )

                current_doc_ids = list(session.document_records.keys())
                if current_doc_ids:
                    placeholders = ",".join("?" for _ in current_doc_ids)
                    conn.execute(
                        f"DELETE FROM documents WHERE investigation_id = ? AND document_id NOT IN ({placeholders})",
                        (session.investigation_id, *current_doc_ids),
                    )
                else:
                    conn.execute("DELETE FROM documents WHERE investigation_id = ?", (session.investigation_id,))

                for doc_id, rec in session.document_records.items():
                    raw_bytes = None
                    norm_text = None
                    doc_fmt = "txt"
                    if doc_id in session.documents:
                        doc = session.documents[doc_id]
                        raw_bytes = getattr(doc, "raw_content", getattr(doc, "raw_bytes", None))
                        norm_text = getattr(doc, "normalized_text", getattr(doc, "text", None))
                        fmt_attr = getattr(doc, "format", getattr(doc, "doc_format", "txt"))
                        doc_fmt = fmt_attr.value if hasattr(fmt_attr, "value") else str(fmt_attr)
                    self._save_document_tx(
                        conn,
                        investigation_id=session.investigation_id,
                        doc_record=rec,
                        raw_bytes=raw_bytes,
                        normalized_text=norm_text,
                        doc_format=doc_fmt,
                    )

                current_entities = session.store.list_entities()
                current_ent_ids = [e.entity_id for e in current_entities]
                if current_ent_ids:
                    placeholders = ",".join("?" for _ in current_ent_ids)
                    conn.execute(
                        f"DELETE FROM entities WHERE investigation_id = ? AND entity_id NOT IN ({placeholders})",
                        (session.investigation_id, *current_ent_ids),
                    )
                else:
                    conn.execute("DELETE FROM entities WHERE investigation_id = ?", (session.investigation_id,))

                for entity in current_entities:
                    self._save_entity_tx(conn, session.investigation_id, entity)

                for ev in session.store.list_evidence():
                    self._save_evidence_tx(conn, session.investigation_id, ev)

                for cl in session.store.list_claims():
                    self._save_claim_tx(conn, session.investigation_id, cl)

                current_rels = session.store.list_relationships()
                current_rel_ids = [r.relationship_id for r in current_rels]
                if current_rel_ids:
                    placeholders = ",".join("?" for _ in current_rel_ids)
                    conn.execute(
                        f"DELETE FROM relationships WHERE investigation_id = ? AND relationship_id NOT IN ({placeholders})",
                        (session.investigation_id, *current_rel_ids),
                    )
                else:
                    conn.execute("DELETE FROM relationships WHERE investigation_id = ?", (session.investigation_id,))

                for rel in current_rels:
                    self._save_relationship_tx(conn, session.investigation_id, rel)

    def load_investigation_into_session(self, investigation_id: str, session: Any) -> bool:
        """
        Hydrate an active InvestigationSession from SQLite.
        Restores metadata, documents, entities, evidence, claims, and relationships.
        """
        inv_data = self.get_investigation(investigation_id)
        if not inv_data:
            return False

        session.description = inv_data.get("description", "")
        session.owner_id = inv_data.get("owner_id")
        session.backend_mode = inv_data.get("backend_mode", "rule")
        session.status = InvestigationStatus(inv_data.get("status", "CREATED"))
        if inv_data.get("created_at"):
            session.created_at = datetime.fromisoformat(inv_data["created_at"])

        # 1. Hydrate entities
        entities = self.list_entities(investigation_id)
        for ent in entities:
            if not session.store.has_entity(ent.entity_id):
                session.store.add_entity(ent)
        session.sync_store_entities_to_resolver()

        # 2. Hydrate evidence
        for ev in self.list_evidence(investigation_id):
            if not session.store.get_evidence(ev.evidence_id):
                session.store.add_evidence(ev)

        # 3. Hydrate claims
        for cl in self.list_claims(investigation_id):
            if not session.store.get_claim(cl.claim_id):
                session.store.add_claim(cl)

        # 4. Hydrate relationships
        for rel in self.list_relationships(investigation_id):
            if not session.store.get_relationship(rel.relationship_id):
                session.store.add_relationship(rel)

        # 5. Hydrate documents
        for doc_row in self.list_documents(investigation_id):
            doc_id = doc_row["document_id"]
            p_at = datetime.fromisoformat(doc_row["processed_at"]) if doc_row.get("processed_at") else None
            rec = DocumentProcessingRecord(
                document_id=doc_id,
                source_name=doc_row["source_name"],
                source_uri=doc_row["source_uri"],
                content_hash=doc_row["content_hash"],
                status=DocumentProcessingStatus(doc_row["status"]),
                char_count=doc_row["char_count"],
                mention_count=doc_row["mention_count"],
                relation_candidate_count=0,
                claim_count=doc_row["claim_count"],
                evidence_count=doc_row["evidence_count"],
                error_message=doc_row["error_message"],
                processed_at=p_at,
                metadata=doc_row.get("metadata", {}),
            )
            session.document_records[doc_id] = rec
            session.processed_hashes[doc_row["content_hash"]] = doc_id

            if doc_row.get("raw_bytes") and doc_row.get("normalized_text"):
                fmt = DocumentFormat.TXT
                try:
                    fmt = DocumentFormat(doc_row["doc_format"])
                except Exception:
                    pass
                meta = doc_row.get("metadata", {})
                ingested = IngestedDocument(
                    document_id=doc_id,
                    source_name=doc_row["source_name"],
                    source_uri=doc_row["source_uri"],
                    format=fmt,
                    raw_content=doc_row["raw_bytes"],
                    normalized_text=doc_row["normalized_text"],
                    content_hash=doc_row["content_hash"],
                    char_count=doc_row["char_count"],
                    parser_name=meta.get("parser_name", "txt_parser"),
                    parser_version=meta.get("parser_version", "1.0.0"),
                    ingested_at=p_at or datetime.now(timezone.utc),
                    metadata=meta,
                )
                session.documents[doc_id] = ingested

        return True

    def get_report(self, investigation_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored report for an investigation."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM reports WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if row:
                return dict(row)
        return None

    def get_system_stats(self) -> Dict[str, int]:
        """Get aggregate counts of all entities, documents, investigations, etc. in SQLite."""
        stats = {
            "investigations": 0,
            "documents": 0,
            "entities": 0,
            "evidence": 0,
            "claims": 0,
            "relationships": 0,
            "reports": 0,
        }
        with self.get_connection() as conn:
            for table, stat_key in [
                ("investigations", "investigations"),
                ("documents", "documents"),
                ("entities", "entities"),
                ("evidence_items", "evidence"),
                ("claims", "claims"),
                ("relationships", "relationships"),
                ("reports", "reports"),
            ]:
                try:
                    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    stats[stat_key] = row[0] if row else 0
                except sqlite3.OperationalError:
                    stats[stat_key] = 0
        return stats

    def delete_investigation(self, investigation_id: str) -> Tuple[bool, Dict[str, int]]:
        """
        Safely delete a single investigation and all associated child records.
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
        with self.get_connection() as conn:
            # Check existence
            inv_row = conn.execute(
                "SELECT 1 FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if not inv_row:
                return False, counts

            # Count records prior to deletion for honest audit report
            for table, count_key in [
                ("documents", "documents"),
                ("entities", "entities"),
                ("evidence_items", "evidence"),
                ("claims", "claims"),
                ("relationships", "relationships"),
                ("reports", "reports"),
            ]:
                row = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE investigation_id = ?",
                    (investigation_id,),
                ).fetchone()
                counts[count_key] = row[0] if row else 0

            counts["investigations"] = 1

            # Explicit cascading cleanup
            conn.execute("DELETE FROM reports WHERE investigation_id = ?", (investigation_id,))
            conn.execute("DELETE FROM relationships WHERE investigation_id = ?", (investigation_id,))
            conn.execute("DELETE FROM claims WHERE investigation_id = ?", (investigation_id,))
            conn.execute("DELETE FROM evidence_items WHERE investigation_id = ?", (investigation_id,))
            conn.execute("DELETE FROM entities WHERE investigation_id = ?", (investigation_id,))
            conn.execute("DELETE FROM documents WHERE investigation_id = ?", (investigation_id,))
            conn.execute("DELETE FROM investigations WHERE investigation_id = ?", (investigation_id,))
            conn.commit()

        return True, counts

    def clear_all_data(self) -> Dict[str, int]:
        """
        High-impact transactional clearing of ALL investigation data from SQLite.
        Guarantees complete database reset without orphan records.
        """
        counts = self.get_system_stats()
        # Perform deletion of all data
        with self.get_connection() as conn:
            conn.execute("DELETE FROM reports")
            conn.execute("DELETE FROM relationships")
            conn.execute("DELETE FROM claims")
            conn.execute("DELETE FROM evidence_items")
            conn.execute("DELETE FROM entities")
            conn.execute("DELETE FROM documents")
            conn.execute("DELETE FROM investigations")
            conn.commit()

        # Re-pack database file if non-memory
        if not self._is_memory:
            try:
                vac_conn = sqlite3.connect(self.db_path)
                vac_conn.isolation_level = None
                vac_conn.execute("VACUUM")
                vac_conn.close()
            except Exception:
                pass

        return counts


