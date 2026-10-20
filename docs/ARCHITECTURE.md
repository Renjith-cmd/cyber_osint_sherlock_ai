# Sherlock AI — System Architecture & Data Flow

This document details the internal architecture, component boundaries, and lifecycle guarantees of the Sherlock AI research prototype.

---

## 1. Architectural Overview & Design Philosophy

Sherlock AI is designed around a single core tenet: **Forensic Evidence Integrity**.

In open-source intelligence and link-analysis systems, automated algorithms often create false confidence by:
1. Merging distinct entities on ambiguous surface similarities (e.g. homonyms).
2. Fabricating relationships without exact evidential text spans.
3. Treating syndicated or reprinted news articles as independent corroboration.
4. Making irreversible clustering decisions that corrupt graph state.

To prevent these failure modes, Sherlock AI enforces:
- **Strict Immutability:** Raw observations cannot be mutated by downstream processing.
- **Epistemic Traceability:** All graph relationships explicitly track their provenance, source documents, exact character offsets, and epistemic tier.
- **Anti-Corroboration Inflation:** Identical text spans across documents share content hashes to prevent echo-chamber confidence inflation.
- **Reversible Lifecycle:** Any entity merge can be inspected, split, or reversed without data loss.

---

## 2. End-to-End Data Flow

The following diagram illustrates the transformation of unstructured documents into an audit-grade knowledge graph:

```text
[ Raw Document / Text / PDF / JSON ]
                │
                ▼
   [ DocumentIngestionService ]
   ├── Content Hashing (SHA-256)
   ├── Format Validation (TXT, PDF, JSON, HTML)
   └── Text Normalization
                │
                ▼
  [ DocumentExtractionPipeline ]
   ├── Named Entity Recognition (NER) ───────── List[EntityMention]
   ├── Grounded Relation Extraction ─────────── List[ExtractedRelationCandidate]
   └── Intra-Doc Mention Entity Resolution ─── List[MentionResolutionResult]
                │
                ▼
  [ CrossDocumentEntityResolver ]
   ├── Candidate Generation (Blocking Rules)
   ├── Multi-Signal Pairwise Comparison
   ├── Hard Constraint Evaluation (Identifiers, Non-Match Rules)
   └── Three-Tier Outcomes: [ MATCH | NON_MATCH | REVIEW ]
                │
                ▼
  [ InvestigationLifecycleManager ]
   ├── Evidence Ingestion (Normalized Spans + SHA-256 Content Hashes)
   ├── Claim Registration (Subject, Predicate, Object, ReviewStatus)
   └── Epistemic Relationship Derivation (ASSERTED, DENIED, QUOTED, DISPUTED)
                │
                ▼
  [ Storage Subsystem ]
   ├── InMemoryInvestigationGraphStore (Volatile Reference Graph)
   └── SQLiteInvestigationStore (Durable WAL Relational Persistence)
                │
                ▼
  [ API & Presentation Layer ]
   ├── FastAPI REST Service (`/api/v1/...`)
   ├── Dark-Graphite Web Workspace (`/`)
   └── Structured Markdown / JSON Report Generator
```

---

## 3. Major Components & Subsystems

### 3.1 Domain Models (`src/core/models.py`)
All core domain models inherit from `ImmutableBaseModel`, enforcing:
- `ConfigDict(frozen=True, extra="forbid")`.
- Deep payload protection: nested dictionaries are converted to `MappingProxyType`, lists to `tuple`, and sets to `frozenset`.
- Clean serialization back to JSON-compatible primitives without leaking wrapper types.

Key models include:
- **`Record`:** An immutable observation from a data source.
- **`EntityMention`:** A surface text span detected in a document with exact `(start_char, end_char)` offsets.
- **`Evidence`:** An evidential snippet anchored to a source document reference, character span, and SHA-256 content hash. Provenance is mandatory.
- **`Claim`:** An atomic subject-predicate-object statement backed by supporting or contradicting evidence IDs. Maintains full lifecycle correction history (`ClaimCorrection`).
- **`Relationship`:** A typed, directed edge linking two entity IDs with an assigned epistemic tier, polarity, attribution, unique source hashes, and review status.
- **`InvestigationEntity`:** A resolved entity node with a canonical name, entity type, and member record IDs.

### 3.2 Candidate Generation & Blocking (`src/core/blocking.py`)
To avoid $O(N^2)$ Cartesian comparisons, candidate generation indexes records into blocks using deterministic rules:
- **`ExactNameRule`:** Blocks on normalized names.
- **`NameTokenRule`:** Blocks on individual tokens ($\ge 2$ characters).
- **`NameFingerprintRule`:** Order-invariant token fingerprints (e.g. `"Smith, John"` $\leftrightarrow$ `"John Smith"`).
- **`InitialsAcronymRule`:** Token initials and uppercase acronyms (e.g. `"IBM"` $\leftrightarrow$ `"International Business Machines"`).
- **`NameSoundexRule`:** Phonetic Soundex codes for Latin name tokens.
- **`StructuredAttributeRule`:** Exact normalized values of structured attributes (`tax_id`, `city`, `phone`).

### 3.3 Cross-Document Entity Resolver (`src/core/cross_document_resolver.py`)
Operates across documents within an investigation session to evaluate candidate entity pairs:
1. **Decision Outcomes:**
   - **`MATCH`:** High surface similarity ($\ge 0.88$) corroborating with shared organization, location, or matching identifier with zero conflicting attributes.
   - **`NON_MATCH`:** Fatal attribute conflicts (conflicting company registration numbers, conflicting roles, or disjoint organization tokens) or active human-adjudicated non-match constraints.
   - **`REVIEW`:** Ambiguous pairs, high surface similarity lacking corroborating context, or homonyms with partial discrepancies.
2. **Hard Constraints Engine:**
   - `non_match_constraints`: Explicit pairwise constraints prohibiting automated or manual merges between declared distinct entities.
   - `transitive_cascade_prevention`: When merging entity $A$ and entity $B$, if either contains a record with an active non-match constraint against any member of the target, the merge is rejected.
3. **Reversible Lifecycle:**
   - `apply_merge_proposal()`: Re-wires claims and relationships from source to target, archives prior state in entity metadata, and retires the merged source entity.
   - `split_entity()`: Splits composite entities back into separate nodes, recalculates member records, re-wires referencing claims, and registers pairwise non-match constraints.
   - `reverse_merge()`: Completely restores original entities, re-establishes their original member records, and enforces pairwise non-match constraints.

### 3.4 Epistemic Relationship Derivation (`src/core/investigation_lifecycle.py`)
Relationships are not assumed to be objective ground truth. They are classified into epistemic tiers:
- **`ASSERTED`:** Direct affirmative claim supported by verified evidence.
- **`DENIED`:** Explicit negation or refutation (e.g., negative polarity, negation markers).
- **`QUOTED`:** Indirect statements, whistleblower reports, or third-party allegations (with speaker attribution).
- **`INFERRED`:** Derived transitively or via heuristic rule expansion.
- **`DISPUTED`:** Conflicting claims on the same entity pair. Merging an affirmative assertion with a denial automatically transitions status to `DISPUTED`.
- **`HUMAN_VERIFIED`:** Adjudicated by an analyst with reviewer attribution.

#### Anti-Corroboration Inflation (Content Hashing)
When identical text spans appear across multiple documents (e.g., syndicated press releases), they share an identical SHA-256 content hash. The relationship tracks `unique_source_hashes` versus `duplicate_evidence_count`. The corroboration score only increases for distinct content hashes, preventing false confidence from echo chambers.

### 3.5 Persistence & Storage (`src/core/investigation_sqlite.py`)
- **Dual Store Architecture:**
  - `InMemoryInvestigationGraphStore`: Fast, volatile reference store for tests and short-lived analyses.
  - `SQLiteInvestigationStore`: Durable, multi-table relational persistence using SQLite in WAL mode (`PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;`).
- **Relational Tables:**
  - `investigations`, `documents_v2`, `entities`, `evidence_items`, `claims`, `relationships`, `reports`.
- **Integrity Validation:** Every store exposes `integrity_check()`, running `PRAGMA integrity_check` directly against SQLite.

### 3.6 API & Security Architecture (`src/api/`)
- **Framework:** FastAPI with OpenAPI/Swagger documentation at `/docs`.
- **Loopback Enforcement:** By default, binds strictly to loopback interfaces (`127.0.0.1`, `localhost`, `::1`). Remote exposure requires passing `--allow-remote` and configuring an API token of at least 16 characters.
- **Single-Tenant Model:** Designed for single-operator local investigation. Multi-tenant isolation and user authentication roles are not present in this prototype.
- **Web Interface:** Dark-graphite single-page application served from `/static` and `/` without external CDN dependencies.

---

## 4. Error Handling & Invariant Guarantees

1. **Zero-Hallucination Claim Anchoring:**
   - Every claim must reference at least one valid `Evidence` identifier.
   - Every evidence item must specify its provenance source. Creating evidence without provenance raises a `ValidationError`.
2. **Cycle-Safe Graph Queries:**
   - Graph traversals in `InvestigationQueryService.query_entity()` enforce strict `max_depth` and `max_nodes` bounds, maintaining a `visited` set to prevent infinite loops in cyclic subgraphs.
3. **Idempotent Ingestion:**
   - Ingesting a document with a pre-existing SHA-256 hash returns `DocumentProcessingStatus.SKIPPED_DUPLICATE` without mutating graph state or duplicating claims.
4. **Human Review Preservation:**
   - Re-processing an existing document preserves claims marked as `VERIFIED`, `RETRACTED`, `REJECTED`, or `SUPERSEDED`, preventing automated heuristic extractions from overwriting human decisions.
