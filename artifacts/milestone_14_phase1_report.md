# SHERLOCK AI — Milestone 14, Phase 1 Remediation Report

**Reliability, Security, and Data-Integrity Remediation**  
**Role:** Senior Application-Security Engineer, SQLite Specialist, and Reliability Engineer  
**Date:** October 12, 2026  
**Status:** COMPLETE (Phase 1 Remediation & Final Gate)

---

## 1. Reproduction Matrix

Every finding identified in the Milestone 14 Phase 0 audit was independently verified and reproduced against the active codebase prior to applying remediations.

| Finding ID | Severity | Category | Description | Reproduction Status | Verified Root Cause | Final Status |
| :--- | :---: | :---: | :--- | :---: | :--- | :---: |
| **LIFE-01** | **CRITICAL** | Data Integrity | Automated claim re-ingestion overwrites human review adjudications | **CONFIRMED** | `save_claim` in `src/core/investigation_sqlite.py:463` executed an unconditional SQL upsert replacing `review_status = excluded.review_status`. In-memory `add_claim` in `src/core/investigation_graph.py:293` did not protect existing verified/retracted/disputed statuses against incoming unreviewed claims. | **FIXED** |
| **DB-01** | **HIGH** | Database Integrity | `sync_session()` can leave partially synchronized state on failures | **CONFIRMED** | `sync_session()` in `src/core/investigation_sqlite.py:640` invoked individual helper methods, each creating its own independent connection and committing independently. A failure midway left previous items permanently committed with no rollback. | **FIXED** |
| **DB-02** | **HIGH** | Investigation Isolation | Identical document content collides across investigations | **CONFIRMED** | `documents` table schema in `src/core/investigation_sqlite.py:97` defined `PRIMARY KEY (document_id)`. Content-hashed IDs caused document records to collide on `ON CONFLICT(document_id)`, effectively moving or sharing records between distinct investigations. | **FIXED** |
| **SEC-01** | **HIGH** | Security Exposure | Remote API binding exposes investigations without authentication | **CONFIRMED** | `src/api/server.py:15` accepted arbitrary `--host 0.0.0.0` with no loopback check or mandatory token enforcement. Sensitive investigation, document, claim, and review endpoints were openly accessible. | **FIXED** |
| **SEC-02** | **HIGH** | Denial of Service | Upload handling reads entire file into memory before checking size limit | **CONFIRMED** | `src/api/routes.py:263` called `content_bytes = await file.read()`, buffering arbitrarily large bodies into server RAM before evaluating `MAX_UPLOAD_SIZE_BYTES`. | **FIXED** |
| **SEC-03** | **MEDIUM** | Identity Attribution | Reviewer identity accepted directly from untrusted request body | **CONFIRMED** | `src/api/routes.py:941` used `reviewer = req.reviewer.strip()`, allowing client callers to forge forensic review attributions and impersonate administrators or other analysts. | **PARTIALLY FIXED (PROTOTYPE TRUST BOUNDARY)** |
| **LIFE-02** | **MEDIUM** | Lifecycle Policy | Invalid claim-status transitions accepted without validation | **CONFIRMED** | `update_claim_status` in `src/core/investigation_graph.py:305` accepted arbitrary status assignments without validating allowed transitions or enforcing required rationales. Routes caught `ValueError` as HTTP 400 instead of HTTP 422. | **FIXED** |
| **DB-04** | **MEDIUM** | Database Durability | `SQLiteInvestigationStore(":memory:")` loses schema/state across operations | **CONFIRMED** | `get_connection()` in `src/core/investigation_sqlite.py:78` created a new unshared `:memory:` connection on every operation. Each connection received a separate blank database, losing initialized tables immediately. | **FIXED** |

---

## 2. Baseline Test Execution Results

Prior to making any code edits, baseline test execution was recorded across both virtual environments:

- **`.venv` (FastAPI / Starlette Environment):**
  - Command: `.venv/bin/pytest tests/`
  - Result: **307 passed, 5 skipped, 1 warning** in 4.09s (Exit Code: 0)
- **`.venv_ml` (Machine Learning / PyTorch Environment):**
  - Command: `.venv_ml/bin/pytest tests/`
  - Result: **297 passed, 1 skipped** in 23.97s (Exit Code: 0)
- **Git Baseline Status:**
  - `git status --short`: Tracked modifications in `src/core/benchmark.py`, `src/core/models.py`, `tests/test_clustering.py`, and benchmark json artifacts preserved. Zero commits or pushes.

---

## 3. Remediation Details & Design Decisions

### 3.1. LIFE-01: Preservation of Human Adjudications (CRITICAL)

- **Problem:** When a document was re-ingested or a session re-synchronized, newly extracted claims (which default to `UNREVIEWED`) overwrote human adjudication decisions (`VERIFIED`, `RETRACTED`, `DISPUTED`, `REJECTED`, `SUPERSEDED`), wiping out reviewer identity, review notes, and timestamps.
- **Root Cause:**
  - SQL upsert in `src/core/investigation_sqlite.py` unconditionally replaced `review_status = excluded.review_status` without checking current review status.
  - In-memory `InMemoryInvestigationGraphStore.add_claim` in `src/core/investigation_graph.py` checked only if `existing.review_status == ReviewStatus.VERIFIED` before ignoring, and did not protect `RETRACTED`, `DISPUTED`, `REJECTED`, or `SUPERSEDED`, nor did it merge new evidence references.
- **Remediation Implementation:**
  1. **SQLite Guarded Upsert:** In `src/core/investigation_sqlite.py` (`_save_claim_tx` and `_save_relationship_tx`), implemented conditional SQL upsert logic:
     ```sql
     review_status = CASE
         WHEN claims.review_status IN ('VERIFIED', 'RETRACTED', 'REJECTED', 'SUPERSEDED', 'DISPUTED')
              AND excluded.review_status = 'UNREVIEWED'
         THEN claims.review_status
         ELSE excluded.review_status
     END,
     correction_history_json = CASE
         WHEN claims.review_status IN ('VERIFIED', 'RETRACTED', 'REJECTED', 'SUPERSEDED', 'DISPUTED')
              AND excluded.review_status = 'UNREVIEWED'
         THEN claims.correction_history_json
         ELSE excluded.correction_history_json
     END,
     retraction_reason = CASE
         WHEN claims.retraction_reason IS NOT NULL AND excluded.retraction_reason IS NULL
         THEN claims.retraction_reason
         ELSE excluded.retraction_reason
     END
     ```
  2. **In-Memory Graph Merging:** In `src/core/investigation_graph.py` (`add_claim`), if an existing claim has a reviewed status (`VERIFIED`, `RETRACTED`, `DISPUTED`, `REJECTED`, `SUPERSEDED`) and the incoming claim is `UNREVIEWED`, the human adjudication status, correction history, and retraction reason are strictly preserved, while newly discovered evidence IDs are safely merged into `supporting_evidence_ids`.
- **Status:** **FIXED** (Verified by end-to-end re-ingestion regression tests).

---

### 3.2. DB-01: Atomic Session Synchronization (HIGH)

- **Problem:** `sync_session()` executed multiple independent writes across entities, claims, relationships, and documents using separate connections. If a constraint or disk failure occurred midway through synchronization, the database was left in an inconsistent, partially updated state.
- **Root Cause:** Helper methods `save_entity`, `save_evidence`, `save_claim`, and `save_relationship` each invoked `get_connection()`, created individual transactions, and committed independently.
- **Remediation Implementation:**
  1. Created transactional worker methods `_save_entity_tx`, `_save_evidence_tx`, `_save_claim_tx`, and `_save_relationship_tx` that accept an active SQLite connection `conn`.
  2. Refactored `sync_session(session)` to use a single connection wrapped in an atomic transaction context:
     ```python
     with self.get_connection() as conn:
         with conn:  # Atomic SQLite transaction context
             # Sync all documents
             # Sync all entities
             # Sync all evidence
             # Sync all claims
             # Sync all relationships
     ```
  3. Foreign-key constraints (`PRAGMA foreign_keys = ON`) are enforced throughout.
  4. Injected errors during any point of the synchronization trigger an immediate `conn.rollback()`, ensuring all writes across all tables are rolled back together.
- **Status:** **FIXED** (Verified by fault-injection regression tests deliberately raising exceptions during sync).

---

### 3.3. DB-02: Multi-Investigation Document Isolation & Migration (HIGH)

- **Problem:** If Investigation A and Investigation B ingested identical documents (e.g. identical source text with hash `abc`), the `documents` table primary key collided, causing Investigation B to overwrite or steal Investigation A's document mapping.
- **Root Cause:** Table `documents` had `PRIMARY KEY (document_id)`. The `document_id` was computed deterministically from the content hash (`f"doc_{hash}"`). When investigation B inserted the same document, `ON CONFLICT(document_id)` did not update `investigation_id`, leading to data leakage or missing documents.
- **Remediation Implementation:**
  1. Updated table schema to use a composite primary key: `PRIMARY KEY (investigation_id, document_id)`.
  2. Added an index on `(investigation_id, content_hash)` for high-throughput lookup within investigations.
  3. Updated `_init_schema()` with automatic migration logic that detects older single-column primary key schemas via `PRAGMA table_info(documents)` and migrates them safely via table-copy (`documents` -> `documents_v2` -> `documents`) without deleting or corrupting existing rows.
  4. Updated all queries in `get_document`, `list_documents`, `save_document` to always bind `(investigation_id, document_id)`.
- **Status:** **FIXED** (Verified by multi-investigation ingestion tests and raw legacy schema migration regression tests).

---

### 3.4. SEC-01: Remote API Exposure & Token Authentication (HIGH)

- **Problem:** The CLI server allowed binding to `0.0.0.0` or any public IP without authentication, exposing investigation data and claim manipulation endpoints to the network.
- **Root Cause:** `src/api/server.py` had no loopback enforcement, and `src/api/app.py` had no authentication middleware or token verification.
- **Remediation Implementation:**
  1. **Strict Loopback Default:** In `src/api/server.py`, loopback hosts (`127.0.0.1`, `localhost`, `::1`) are allowed by default. Any non-loopback host requires the explicit flag `--allow-remote`.
  2. **Mandatory Remote Token:** If `--allow-remote` is passed, the server requires an API token configured via `--api-token` or environment variable `SHERLOCK_API_TOKEN` of at least 16 characters. If missing or insecure, server startup aborts immediately.
  3. **Constant-Time Comparison:** In `src/api/security.py`, `validate_api_token()` utilizes `secrets.compare_digest` to prevent timing attacks.
  4. **Authentication Middleware:** In `src/api/app.py`, requests in remote mode are validated for `Authorization: Bearer <token>` or `X-API-Key: <token>`. Public diagnostic endpoints (`/api/v1/health`, `/api/v1/ready`, `/docs`, `/openapi.json`) remain accessible for health checkers, while all investigation endpoints return HTTP 401 Unauthorized if credentials are missing or invalid.
  5. **No Token Leaks:** The token is never printed in server logs, exception messages, or diagnostics.
- **Status:** **FIXED** (Verified by 5 API access control tests).

---

### 3.5. SEC-02: Bounded Chunked Upload Streaming (HIGH)

- **Problem:** Calling `await file.read()` buffered the entire request payload into system memory before checking file size limits, opening the service to memory-exhaustion DoS attacks.
- **Root Cause:** In `src/api/routes.py`, `content_bytes = await file.read()` was executed before `validate_upload_content()`.
- **Remediation Implementation:**
  1. Implemented `read_bounded_upload(file, max_bytes=MAX_UPLOAD_SIZE_BYTES, chunk_size=65536)` in `src/api/security.py`.
  2. The function reads uploads in 64 KB chunks, maintaining an exact byte counter.
  3. The moment accumulated bytes exceed `MAX_UPLOAD_SIZE_BYTES` (5 MB), it stops reading immediately, raises `HTTPException(status_code=413, detail=...)`, and cleans up.
  4. Files at exactly 5 MB are processed successfully; files at 5 MB + 1 byte are aborted without buffering excess bytes.
- **Status:** **FIXED** (Verified by exact-boundary, 1-byte-over, and large upload regression tests).

---

### 3.6. SEC-03: Reviewer Identity Attribution & Explicit Security Decision (MEDIUM)

- **Problem:** Client callers could supply an arbitrary string in the JSON payload `{"reviewer": "admin"}` to attribute consequential human review decisions to other analysts.
- **Implementation:**
  1. Added `validate_reviewer_identity(reviewer)` in `src/api/security.py` enforcing regex `^[a-zA-Z0-9_\-\.]{2,64}$` and rejecting empty strings, spaces, and script tags (HTTP 422).
  2. In `src/api/routes.py`, if an authenticated principal is registered on request state, `validate_reviewer_identity` checks that `req.reviewer == authenticated_principal` (HTTP 403 on mismatch).
- **Explicit Security Decision & Prototype Trust Boundary:**
  - **Sherlock AI remains a local, single-operator intelligence prototype.**
  - The shared Bearer token authenticates an **API client / process**, but does **not** establish individual human analyst identity.
  - The header `X-Principal-User` is supplied by the HTTP client. While the API enforces internal consistency between `X-Principal-User` and `req.reviewer`, **it is an untrusted attribution field unless provided by a trusted upstream authentication reverse proxy or API gateway**.
  - **This is NOT described as secure multi-user authentication.**
  - **Production Multi-User Implementation Plan (Future Scope):**
    For enterprise multi-user deployments, Sherlock AI must integrate:
    1. An OpenID Connect (OIDC) / OAuth2 JWT bearer token validation flow, where `reviewer` identity is derived directly from verified JWT claims (`sub` or `preferred_username`).
    2. Session-based authentication with cryptographically signed cookies and a local SQLite users table with bcrypt password hashing.
    3. Mutual TLS (mTLS) client certificate verification where client identity is extracted from the Subject Common Name (CN).
- **Status:** **PARTIALLY FIXED (PROTOTYPE TRUST BOUNDARY ACCEPTED)**.

---

### 3.7. LIFE-02: Claim Lifecycle Transition Policy (MEDIUM)

- **Problem:** Claims could be transitioned directly between arbitrary states (e.g. from `REJECTED` to `UNREVIEWED`), and retractions or reinstatements lacked mandatory rationales.
- **Root Cause:** `update_claim_status` did not validate transitions against a domain state machine, and routes did not map invalid transitions to HTTP 422.
- **Remediation Implementation:**
  1. Defined `VALID_CLAIM_TRANSITIONS` dictionary in `src/core/investigation_graph.py` mapping each source `ReviewStatus` to allowed destination statuses:
     - `UNREVIEWED` -> `VERIFIED`, `REJECTED`, `DISPUTED`, `RETRACTED`, `SUPERSEDED`
     - `VERIFIED` -> `RETRACTED`, `DISPUTED`, `SUPERSEDED`
     - `DISPUTED` -> `VERIFIED`, `REJECTED`, `RETRACTED`, `SUPERSEDED`
     - `RETRACTED` -> `VERIFIED`, `UNREVIEWED`, `DISPUTED` (Reinstatement, requiring explicit audit rationale)
     - `REJECTED` -> `DISPUTED`, `UNREVIEWED` (Reopening)
     - `SUPERSEDED` -> (terminal)
  2. Defined `InvalidLifecycleTransitionError` raised when an illegal transition is attempted.
  3. Enforced mandatory audit rationale (minimum 5 characters) for `RETRACTED` and `VERIFIED` reinstatement transitions.
  4. In `src/api/routes.py`, mapped `InvalidLifecycleTransitionError` and rationale validation errors to `HTTP 422 Unprocessable Entity`.
  5. Verified that both in-memory and SQLite-backed operations preserve the entire `ClaimCorrection` history chain.
- **Status:** **FIXED** (Verified by 14 table-driven matrix tests and full SQLite lifecycle audit test).

---

### 3.8. DB-04: In-Memory SQLite Store Durability (MEDIUM)

- **Problem:** Using `SQLiteInvestigationStore(":memory:")` caused tables and schema created during initialization to be immediately lost on the next method call.
- **Root Cause:** In SQLite, `:memory:` opens a brand-new, private database per connection. Every call to `get_connection()` opened a new `:memory:` connection, discarding the previous schema.
- **Remediation Implementation:**
  1. In `src/core/investigation_sqlite.py`, when `db_path == ":memory:"`, the store creates a unique shared in-memory URI: `file:sherlock_mem_{uuid}?mode=memory&cache=shared`.
  2. The store opens and holds a "keeper connection" (`self._keeper_conn`) for the lifetime of the `SQLiteInvestigationStore` instance, preventing SQLite from discarding the shared memory database when individual operation connections close.
  3. Subsequent calls to `get_connection()` connect to the shared memory URI with `check_same_thread=False` and `PRAGMA foreign_keys = ON`.
  4. Added `close()` to explicitly close the keeper connection when the store is torn down.
- **Status:** **FIXED** (Verified by multi-operation lifetime durability test).

---

## 4. Reliability Enhancements: Integrity Check, Backup, and Diagnostics

1. **Integrity Check:** Added `store.integrity_check()` executing `PRAGMA integrity_check` on the SQLite database, returning `True` if "ok" or raising detailed diagnostics on corruption.
2. **Online Backup:** Added `store.backup(backup_path)` using SQLite's native Online Backup API (`src_conn.backup(dst_conn)`) to safely generate consistent snapshots of running databases without locking readers.
3. **Readiness Probe:** Added `/api/v1/ready` endpoint in `src/api/routes.py` that verifies the SQLite database is reachable and operational, distinct from the liveness probe `/api/v1/health`.

---

## 5. Regression & Hardening Test Suite

The test suite in [`tests/test_milestone_14_hardening.py`](file:///home/renjith-cmd/Documents/sherlock-ai-1/entity_resolution_graph_osint/tests/test_milestone_14_hardening.py) contains **33 focused tests**:

1. `test_verified_claim_survives_reingestion`: Asserts human verified claim is not demoted on re-ingestion.
2. `test_retracted_claim_not_reinstated_by_pipeline`: Confirms retracted claim remains retracted.
3. `test_disputed_claim_preserves_status_on_reingestion`: Confirms reviewer notes and attribution survive re-extraction.
4. `test_fault_injection_rolls_back_entire_session`: Validates complete transactional rollback on injected fault midway through sync.
5. `test_identical_content_isolation`: Verifies independent document ownership for identical hashes across investigations.
6. `test_legacy_schema_migration_preserves_data_and_constraints`: Verifies automatic migration from legacy single-PK `documents` table to composite PK, preserving all rows and integrity.
7. `test_memory_store_lifetime_durability`: Confirms in-memory store persists across multiple sequential operations.
8. `test_loopback_unauthenticated_default_passes`: Verifies local-first unauthenticated development workflow.
9. `test_remote_mode_rejects_missing_credentials`: Verifies remote access rejection (HTTP 401) without token.
10. `test_remote_mode_accepts_valid_bearer_token`: Verifies authorized remote requests with Bearer token.
11. `test_remote_mode_rejects_invalid_token`: Verifies rejection of incorrect tokens.
12. `test_token_comparison_is_constant_time`: Verifies `secrets.compare_digest` constant-time verification.
13. `test_upload_exact_limit_accepted`: Verifies 5 MB upload succeeds.
14. `test_upload_one_byte_over_rejected_early`: Verifies 5 MB + 1 byte triggers HTTP 413.
15. `test_impersonation_rejected_when_authenticated`: Verifies HTTP 403 on reviewer body/header mismatch.
16. `test_malformed_reviewer_rejected`: Verifies HTTP 422 on invalid/script reviewer names.
17. `test_transition_policy[UNREVIEWED-VERIFIED-True]`: Table-driven transition test.
18. `test_transition_policy[UNREVIEWED-DISPUTED-True]`: Table-driven transition test.
19. `test_transition_policy[UNREVIEWED-REJECTED-True]`: Table-driven transition test.
20. `test_transition_policy[UNREVIEWED-RETRACTED-True]`: Table-driven transition test.
21. `test_transition_policy[VERIFIED-DISPUTED-True]`: Table-driven transition test.
22. `test_transition_policy[VERIFIED-RETRACTED-True]`: Table-driven transition test.
23. `test_transition_policy[DISPUTED-VERIFIED-True]`: Table-driven transition test.
24. `test_transition_policy[DISPUTED-RETRACTED-True]`: Table-driven transition test.
25. `test_transition_policy[RETRACTED-VERIFIED-True]`: Table-driven transition test (reinstatement).
26. `test_transition_policy[RETRACTED-UNREVIEWED-True]`: Table-driven transition test.
27. `test_transition_policy[RETRACTED-DISPUTED-True]`: Table-driven transition test.
28. `test_transition_policy[REJECTED-UNREVIEWED-True]`: Table-driven transition test.
29. `test_transition_policy[SUPERSEDED-VERIFIED-False]`: Table-driven transition test (terminal state).
30. `test_transition_policy[SUPERSEDED-UNREVIEWED-False]`: Table-driven transition test (terminal state).
31. `test_sqlite_claim_lifecycle_and_audit_history_preservation`: Validates retraction, illegal reinstatement rejection without rationale, valid reinstatement, and full `ClaimCorrection` history chain survival in SQLite.
32. `test_ready_probe_operational`: Verifies `/api/v1/ready` probe.
33. `test_online_backup_and_recovery`: Verifies online backup and restore.

---

## 6. Focused Test Suite Execution Results

### 6.1. Environment `.venv` (FastAPI / Starlette)
- **Command:** `.venv/bin/pytest tests/test_milestone_14_hardening.py -v`
- **Exit Code:** `0`
- **Result:** **33 passed, 4 warnings in 0.44s**

### 6.2. Environment `.venv_ml` (Machine Learning / PyTorch)
- **Command:** `.venv_ml/bin/pytest tests/test_milestone_14_hardening.py -v`
- **Exit Code:** `0`
- **Result:** **23 passed, 10 skipped in 0.12s**
- **Collection Difference:** 10 API-layer tests skipped cleanly because FastAPI is not installed in `.venv_ml`. All 23 core SQLite, lifecycle, migration, and data integrity tests passed.

### 6.3. Quality & Compilation Checks
- **Command:** `.venv/bin/python -m compileall -q src tests`
  - **Exit Code:** `0` (Zero compilation errors)
- **Command:** `git diff --check`
  - **Exit Code:** `0` (Zero whitespace or diff format violations)
- **Command:** `git status --short`
  - **Exit Code:** `0` (All tracked files preserved, untracked milestone work preserved)

---

## 7. Audit Classification & Trust Boundaries

| Category | Finding ID | Status | Description |
| :--- | :---: | :---: | :--- |
| **Code Fixes & Verified Behaviors** | **LIFE-01** | **FIXED** | Human reviews strictly survive automated re-ingestion in memory & SQLite. |
| | **DB-01** | **FIXED** | Single-connection atomic transactions roll back on injected faults. |
| | **DB-02** | **FIXED** | Composite PK isolates documents; legacy schema migrates without data loss. |
| | **SEC-01** | **FIXED** | Loopback binding default; remote requires 16+ char Bearer token. |
| | **SEC-02** | **FIXED** | Bounded 64 KB chunk reading terminates immediately at 5 MB (HTTP 413). |
| | **LIFE-02** | **FIXED** | Central state machine rejects invalid transitions; rationales enforced. |
| | **DB-04** | **FIXED** | Shared memory URI + keeper connection preserves schema for store lifetime. |
| **Accepted Prototype Limitations** | **SEC-03** | **ACCEPTED** | Single-tenant API token authenticates client application. Client-supplied `X-Principal-User` header is an untrusted attribution field, not multi-user identity authentication. |
| **Production Blockers for Public Multi-User Deployments** | **AUTH** | **OPEN** | Prior to multi-user public deployment, implement cryptographic OIDC JWT or session authentication. |

---

## 8. Final Gate Recommendation

**Recommendation: APPROVE PHASE 2**

All critical and high-severity data-integrity, transaction-atomicity, and database-isolation findings are confirmed fixed and tested. The reviewer identity trust boundary is explicitly defined and documented. No blockers exist for proceeding to Phase 2 (Performance Benchmarking, Durability & Recovery Hardening).
