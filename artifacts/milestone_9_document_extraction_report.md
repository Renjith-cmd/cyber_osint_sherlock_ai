# Sherlock AI — Milestone 9 Technical Report
## Document Ingestion, Named Entity Recognition & Evidence-Grounded Relation Extraction

**Status:** Completed & Formally Verified  
**Date:** October 12, 2026  
**Environment:** Linux (Python 3.14.7, pytest 9.1.1, pydantic 2.11.0a0)  
**Test Suite Verification:** 225 passing tests (201 regression tests + 24 Milestone 9 unit/integration tests) in 3.03s  

---

### Executive Summary

Milestone 9 extends the Sherlock AI investigation pipeline with a modular, deterministic **document-to-evidence extraction layer**. It transforms unstructured and semi-structured documents into traceable source text, named entity mentions, evidence-grounded relation candidates, and Milestone 8 `Evidence` and `Claim` objects.

Crucially, **extraction is not verification**. Automated extraction produces unreviewed assertions rather than established facts. The pipeline enforces epistemic separation by:
1. Converting raw documents into immutable, SHA-256 hashed source representations with exact character offsets.
2. Extracting entity mentions across `PERSON`, `ORGANIZATION`, `LOCATION`, `DATE`, and `MONEY` without inventing uncalibrated confidence scores.
3. Preserving repeated mentions separately rather than prematurely collapsing them.
4. Extracting supported relation candidates only when grounded in explicit source sentences or text spans.
5. Detecting and propagating sentence-level negation, allegations, and attribution cues.
6. Registering extracted candidate relationships as Milestone 8 `Evidence` and `Claim` instances defaulting strictly to `ReviewStatus.UNREVIEWED`.
7. Preserving prior human review decisions, retractions, and rejections across idempotent re-ingestion.
8. Evaluating extraction precision, recall, and F1 on isolated synthetic gold fixtures without leaking evaluation labels into runtime logic.

---

### 1. Architecture and Data Flow

```
+----------------------------------------------------------------------------------------------------+
|                                    DOCUMENT EXTRACTION PIPELINE                                    |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|  [Source Document] (UTF-8 Plain Text, Structured JSON, PDF capability check)                       |
|         │                                                                                          |
|         ▼                                                                                          |
|  [1. Ingestion Layer] (src/core/document_ingestion.py)                                             |
|     - SHA-256 Content Hashing & Duplicate Detection Registry                                       |
|     - Size, page, and character length guardrails (10MB / 2M chars / 1,000 pages)                  |
|     - Normalized Text with Page & Character Offset Bounds                                          |
|         │                                                                                          |
|         ▼                                                                                          |
|  [2. Named Entity Recognition (NER)] (src/core/ner.py)                                             |
|     - Deterministic baseline supporting PERSON, ORGANIZATION, LOCATION, DATE, MONEY                |
|     - Precise character spans [start_char:end_char) strictly bound to normalized_text              |
|     - Safe value normalization (ISO-8601 dates, currency amounts, honorific stripping)             |
|     - Repeated mentions preserved with distinct mention IDs                                        |
|         │                                                                                          |
|         ▼                                                                                          |
|  [3. Grounded Relation Extraction] (src/core/relation_extraction.py)                                |
|     - Predicates: WORKS_FOR, LOCATED_IN, OWNS, FOUNDED, ASSOCIATED_WITH                            |
|     - Sentence-bounded pattern matching & schema type constraints                                  |
|     - Epistemic qualifiers: is_negated, is_allegation, attribution_source, temporal_context        |
|     - Conservative abstention on ambiguous or ungrounded co-occurrences                            |
|         │                                                                                          |
|         ▼                                                                                          |
|  [4. Milestone 8 Integration Adapter] (src/core/document_pipeline.py)                              |
|     - Evidence objects created with exact source spans and offsets                                 |
|     - Claims created with unreviewed status (ReviewStatus.UNREVIEWED)                              |
|     - Epistemic mapping: Negated relations populate contradicting_evidence_ids                     |
|     - Unresolved entity mentions registered as provisional entities                                |
|     - Human Review Safeguard: Retracted, rejected, and verified claims preserved across re-runs    |
|         │                                                                                          |
|         ▼                                                                                          |
|  [5. Investigation Graph Store] (src/core/investigation_graph.py)                                   |
|     - BaseInvestigationGraphStore / InMemoryInvestigationGraphStore                                |
|     - Optional unreviewed relationship edges (ASSERTED tier)                                       |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

---

### 2. Supported Document Formats and Parser Limitations

| Format | Parser Class | Encoding / Engine | Capabilities & Safeguards | Known Limitations |
| :--- | :--- | :--- | :--- | :--- |
| **Plain Text (`.txt`)** | `TextDocumentParser` | UTF-8 (configurable) | Exact character offsets, newline normalization (`\r\n` $\to$ `\n`), safe character limit enforcement. | Does not preserve bold/italic markup or table columnar layout. |
| **JSON (`.json`)** | `JsonDocumentParser` | Standard `json` library | Configurable text field extraction (`["text", "content", "body", "article"]`), handles dictionaries and lists of records. | Complex deeply nested hierarchies outside configured keys are skipped. |
| **PDF (`.pdf`)** | `PdfDocumentParser` | Optional `pypdf` engine | Page-aware text extraction, per-page offset tracking, page boundary mapping. | If `pypdf` is not installed, raises clear `ExtractionCapabilityError` without failing TXT/JSON ingestion or downloading unverified packages. Does not OCR scanned images. |

---

### 3. Named Entity Recognition (NER) Design

#### 3.1 Entity Types & Normalization Semantics

1. **PERSON**:
   - Detects honorific prefixes (`Dr.`, `Mr.`, `Mrs.`, `Ms.`, `Prof.`, `Agent`, `Senator`, `CEO`, `Director`) and capitalized name sequences.
   - Normalization: Strips honorific prefixes, whitespace, and titles (e.g. `"Dr. John Watson"` $\to$ `"John Watson"`).
   - Safeguard: Patterns are restricted to horizontal whitespace (`[ \t]+`) to prevent spanning across paragraph or line breaks.
2. **ORGANIZATION**:
   - Detects corporate markers (`Inc.`, `LLC`, `Corp.`, `Corporation`, `Ltd.`, `GmbH`, `Group`, `Bank`, `Holdings`, `Enterprises`, `Agency`, `Department of X`).
   - Normalization: Strips trailing punctuation and canonicalizes spacing.
3. **LOCATION**:
   - Detects geographic suffixes (`Street`, `Avenue`, `Boulevard`, `City`, `State`, `River`, `Mountain`) and curated international landmarks/cities.
   - Normalization: Standard titlecase and whitespace trimming.
4. **DATE**:
   - Detects ISO 8601 (`YYYY-MM-DD`), alphanumeric formats (`January 15, 2024`, `15 Jan 2024`), and year-month combinations.
   - Normalization: Canonical ISO 8601 strings (`YYYY-MM-DD` or `YYYY-MM`).
5. **MONEY**:
   - Detects currency symbols (`$`, `€`, `£`, `¥`) and ISO currency codes (`USD`, `EUR`, `GBP`) followed by numerical amounts and scale words (`million`, `billion`, `k`).
   - Normalization: Canonical currency code and integer/float value (e.g. `"$10 million"` $\to$ `"$10000000"`).

#### 3.2 Epistemic Discipline
- **No Fabricated Confidence:** The deterministic rule baseline reports `confidence_score = None` and `confidence_semantics = None` rather than inventing synthetic confidence numbers.
- **Repeated Mentions:** Mention extraction and entity resolution remain distinct operations. Multiple mentions of the same name produce distinct `EntityMention` objects with unique `mention_id`s and individual offsets.

---

### 4. Relation Extraction Schema & Policy

#### 4.1 Supported Relation Schema

| Predicate | Subject Type | Object Type | Example Sentence | Grounded Trigger Patterns |
| :--- | :--- | :--- | :--- | :--- |
| **`WORKS_FOR`** | `PERSON` | `ORGANIZATION` | *"Dr. John Watson works for Sherlock Security."* | `works for`, `worked for`, `work for`, `employed by`, `CEO of`, `director of` |
| **`LOCATED_IN`** | `ORGANIZATION`, `LOCATION` | `LOCATION` | *"Sherlock Security is located in London."* | `located in`, `headquartered in`, `based in`, `operates in`, `situated in` |
| **`OWNS`** | `PERSON`, `ORGANIZATION` | `ORGANIZATION`, `FINANCIAL_INSTRUMENT`, `PRODUCT` | *"Wayne Enterprises owns Globex Corporation."* | `owns`, `owned`, `acquired`, `purchased`, `owner of`, `controlling stake in` |
| **`FOUNDED`** | `PERSON`, `ORGANIZATION` | `ORGANIZATION` | *"James Moriarty founded Stark Industries."* | `founded`, `co-founded`, `established`, `founder of` |
| **`ASSOCIATED_WITH`**| `Any` | `Any` | *"Entity A is associated with Entity B."* | `associated with`, `affiliated with`, `partnered with`, `connected to` |

#### 4.2 Handling Negation, Attribution, and Uncertainty

- **Negation:**
  - Sentences containing negation cues (`not`, `never`, `no longer`, `denies`, `did not`, `does not`, `cannot`) set `is_negated = True`.
  - In the Milestone 8 adapter, this creates an `Evidence` object with `EvidencePolarity.CONTRADICTING` and places the evidence in the claim's `contradicting_evidence_ids` rather than creating a false positive relationship.
- **Attribution & Allegations:**
  - Cues such as `alleges that`, `alleged that`, `allegedly`, `claims that`, `according to`, `reportedly` set `is_allegation = True` and extract `attribution_source`.
  - The claim is recorded with explicit qualifier tags, preventing unsubstantiated accusations from being presented as established facts.
- **Abstention Policy:**
  - The extractor abstains (emits 0 relations) when:
    1. Entities co-occur in the same sentence or document without a matching syntactic predicate trigger.
    2. Multiple subjects and multiple objects appear in a complex sentence without unambiguous syntactic attachment.
    3. Type constraints are violated (e.g. `PERSON` cannot be `LOCATED_IN` another `PERSON`).

---

### 5. Provenance and Span Semantics

Every extracted artifact maintains strict, verifiable provenance:

1. **Character Offsets:**
   - Every `EntityMention` has `[start_char, end_char)` such that `document.normalized_text[start_char:end_char] == mention.surface_text`.
2. **Evidence Spans:**
   - Every `ExtractedRelationCandidate` records `evidence_start_char` and `evidence_end_char` corresponding to the exact sentence supporting the extraction.
3. **Evidence Items:**
   - Converted `Evidence` objects carry:
     - `text_span`: Exact sentence text.
     - `char_offsets`: `(evidence_start_char, evidence_end_char)`.
     - `document_reference`: `document.document_id`.
     - `content_hash`: SHA-256 of the source document.
     - `provenance`: `f"document:{doc_id}:{start}-{end}"`.
4. **Referential Integrity:**
   - Missing entity resolutions are never guessed. Unresolved participants are registered explicitly as provisional entities (`unresolved_men_{mention_id}`) in `BaseInvestigationGraphStore`.
5. **Human Review Preservation:**
   - If an existing claim in the store has been `RETRACTED`, `REJECTED`, or `VERIFIED` by an investigator, reprocessing the same document **never overwrites** the human decision.

---

### 6. Synthetic Extraction Walkthrough

Consider the following input document sentence:

```
"The report alleges that Wayne Enterprises owns Globex Corporation."
```

#### Step 1: Ingestion
- Document ID: `doc_436ec6a88356908f`
- Content SHA-256: `436ec6a88356908f948190ab0554f73d5484a8291aa960b36974d1e540558337`
- Normalized Text Slice: `"The report alleges that Wayne Enterprises owns Globex Corporation."` (offsets: 208 to 274)

#### Step 2: Named Entity Mentions
- Mention 1:
  - Surface Text: `"Wayne Enterprises"`
  - Offsets: `[232, 249]`
  - Entity Type: `EntityType.ORGANIZATION`
  - Normalized: `"Wayne Enterprises"`
  - Mention ID: `men_doc_436ec6a88356908f_6_232_249`
- Mention 2:
  - Surface Text: `"Globex Corporation"`
  - Offsets: `[255, 273]`
  - Entity Type: `EntityType.ORGANIZATION`
  - Normalized: `"Globex Corporation"`
  - Mention ID: `men_doc_436ec6a88356908f_7_255_273`

#### Step 3: Relation Candidate
- Subject: `Wayne Enterprises` (`men_doc_436ec6a88356908f_6_232_249`)
- Predicate: `OWNS`
- Object: `Globex Corporation` (`men_doc_436ec6a88356908f_7_255_273`)
- Evidence Span: `"The report alleges that Wayne Enterprises owns Globex Corporation."` `[208:274]`
- `is_negated`: `False`
- `is_allegation`: `True`
- `attribution_source`: `"alleges that"`

#### Step 4: Milestone 8 Evidence Object
```json
{
  "evidence_id": "ev_436ec6a8_rel_doc_436ec6a88356908f_2_men_doc_436ec6a88356908f_6_232_249_men_doc_436ec6a88356908f_7_255_273",
  "evidence_type": "DOCUMENT_TEXT_SPAN",
  "polarity": "SUPPORTING",
  "text_span": "The report alleges that Wayne Enterprises owns Globex Corporation.",
  "char_offsets": [208, 274],
  "document_reference": "doc_436ec6a88356908f",
  "review_status": "UNREVIEWED",
  "provenance": "document:doc_436ec6a88356908f:208-274"
}
```

#### Step 5: Milestone 8 Claim Object
```json
{
  "claim_id": "claim_436ec6a8_rel_doc_436ec6a88356908f_2_men_doc_436ec6a88356908f_6_232_249_men_doc_436ec6a88356908f_7_255_273",
  "subject_id": "unresolved_men_doc_436ec6a88356908f_6_232_249",
  "predicate": "OWNS",
  "object_id": "unresolved_men_doc_436ec6a88356908f_7_255_273",
  "review_status": "UNREVIEWED",
  "qualifiers": {
    "is_negated": false,
    "is_allegation": true,
    "attribution_source": "alleges that"
  },
  "supporting_evidence_ids": [
    "ev_436ec6a8_rel_doc_436ec6a88356908f_2_men_doc_436ec6a88356908f_6_232_249_men_doc_436ec6a88356908f_7_255_273"
  ],
  "contradicting_evidence_ids": []
}
```

---

### 7. Evaluation Dataset & Benchmark Metrics

#### 7.1 Dataset Construction & Ground Truth Isolation
Evaluation is conducted on a deterministic synthetic benchmark suite containing:
1. Standard positive relations (`WORKS_FOR`, `LOCATED_IN`, `FOUNDED`).
2. Explicitly negated relations (`"Alice Smith does not work for Cyberdyne Systems"`).
3. Attributed / allegation relations (`"The report alleges that Wayne Enterprises owns Globex Corporation"`).
4. Repeated entity mentions across sentences.
5. Ambiguous multi-entity sentences requiring **abstention** (`"In Paris, Agent Smith and Dr. Watson met representatives from Acme Corp and Cyberdyne Systems"`).
6. Non-relational co-occurrences.

**Isolation Safeguard:** All ground-truth fixtures exist exclusively in `src/core/document_evaluation.py`. No evaluation fixtures or labels are accessed by runtime parsers or extractors.

#### 7.2 Measured Benchmark Results

Command:
```bash
.venv/bin/python -m src.core.document_cli --evaluate
```

Actual Output:
```text
=================================================================
     SHERLOCK AI - MILESTONE 9 EXTRACTION EVALUATION REPORT      
=================================================================

--- NAMED ENTITY RECOGNITION (NER) ---
Total Gold Entities:        21
Total Predicted Mentions:   21
Exact Span Matches:         20
Partial Span Matches:       1
Type Errors on Matched:     0
False Positives:            0
False Negatives:            0
Exact-Span Precision:       95.24%
Exact-Span Recall:          95.24%
Exact-Span F1:              95.24%
Lenient (Overlap) F1:       100.00%
Entity-Type Accuracy:       100.00%

--- RELATION EXTRACTION (RE) ---
Total Gold Relations:       5
Total Predicted Relations:  5
True Positives:             5
False Positives:            0
False Negatives:            0
Precision:                  100.00%
Recall:                     100.00%
F1 Score:                   100.00%
Evidence Span Accuracy:     100.00%
Negation Accuracy:          100.00%
Attribution Accuracy:       100.00%
Abstentions on Negative:    2
Unsupported Candidates:     0
=================================================================
```

#### 7.3 Detailed Metric Definitions & Partial Match Policy

1. **Exact-Span Policy:**
   - A predicted mention is an **Exact Match** if and only if:
     $$\text{start\_char}_{\text{pred}} = \text{start\_char}_{\text{gold}} \quad \land \quad \text{end\_char}_{\text{pred}} = \text{end\_char}_{\text{gold}} \quad \land \quad \text{type}_{\text{pred}} = \text{type}_{\text{gold}}$$
   - Any offset mismatch (even by a single trailing punctuation character) is classified as a partial match and counted as a non-match under exact precision/recall.
2. **Partial-Span Policy (Lenient):**
   - Credits any non-zero character overlap:
     $$\max(\text{start}_{\text{pred}}, \text{start}_{\text{gold}}) < \min(\text{end}_{\text{pred}}, \text{end}_{\text{gold}})$$
   - Evaluated as 100.00% lenient F1.
3. **Relation Grounding:**
   - Relation correctness requires matching subject surface, target surface, predicate, and evidence sentence containment.
   - Tested negation accuracy and attribution accuracy both achieved 100.00%.
   - In ambiguous sentences, the extractor recorded **2 abstentions and 0 unsupported candidates**, verifying conservative behavior.

---

### 8. Full Test Suite & Verification Results

All tests across Milestones 1 through 9 pass without regressions.

#### Test Execution:
```bash
.venv/bin/pytest tests/
```

#### Execution Output:
```text
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/renjith-cmd/Documents/sherlock-ai-1/entity_resolution_graph_osint
configfile: pytest.ini
collecting ... collected 225 items                                                            

tests/test_benchmark.py ...................                              [  8%]
tests/test_blocking.py ........................                          [ 19%]
tests/test_clustering.py ......................                          [ 28%]
tests/test_comparison.py .................                               [ 36%]
tests/test_dataset_integrity.py .....                                    [ 38%]
tests/test_datasets.py ............                                      [ 44%]
tests/test_decision.py ........................                          [ 54%]
tests/test_document_pipeline.py ........................                 [ 65%]
tests/test_evaluation.py .............                                   [ 71%]
tests/test_investigation_graph.py ...........................            [ 83%]
tests/test_models.py .........................                           [ 94%]
tests/test_normalization.py .............                                [100%]

============================= 225 passed in 3.03s ==============================
```

#### Summary of Test Coverage:
- **Milestone 1–7 Regression Tests:** 174 passing tests.
- **Milestone 8 Investigation Graph Tests:** 27 passing tests.
- **Milestone 9 Document Ingestion & Extraction Tests:** 24 passing tests.
- **Total:** 225 passing tests, 0 failures, 0 skipped.

---

### 9. CLI Tool Verification

The CLI tool supports direct invocation via module or script, human-readable formatting, structured JSON, sample execution, and exit code validation:

| Command | Exit Code | Purpose / Validated Behavior |
| :--- | :--- | :--- |
| `python -m src.core.document_cli --sample` | `0` | Runs extraction pipeline on built-in synthetic dossier with formatted human dossier output. |
| `python -m src.core.document_cli --sample --json` | `0` | Emits complete machine-readable JSON containing document, mentions, candidates, evidence, and claims. |
| `python -m src.core.document_cli --evaluate` | `0` | Executes synthetic benchmark harness and reports exact NER and relation metrics. |
| `python -m src.core.document_cli /missing/path.txt` | `1` | Fails clearly with message `Error: File not found` and non-zero exit code. |
| Ingestion of PDF when engine is uninstalled | `2` | Fails clearly with `ExtractionCapabilityError` and exit code 2 without crashing. |

---

### 10. Dependencies and Licensing Considerations

- **No Network / Offline Safe:** The entire baseline runs completely offline without network calls or external downloads.
- **Standard Library & Pydantic:** Core ingestion, regex NER, relation extraction, and evaluation use Python standard library modules (`re`, `json`, `hashlib`, `typing`, `datetime`) and `pydantic`.
- **Optional PDF Engine:** PDF ingestion gracefully checks for `pypdf` (BSD-3-Clause). If absent, a clear capability error is raised; no heavyweight dependencies were added to the environment.
- **Intellectual Property & Restricted Data:** All evaluation fixtures use synthetic fictional names (e.g. `Sherlock Security`, `Wayne Enterprises`, `Globex Corporation`, `Dr. John Watson`). No restricted Milestone 7 benchmark data is touched or redistributed.

---

### 11. Known Limitations and Deferred Work

1. **Rule-Based NER Coverage:**
   - The deterministic baseline extractor relies on curated designators, capitalization, honorifics, and date/money patterns. It achieves high precision on structured reports, but does not generalize to informal lower-cased text or complex nicknames. Future milestones can plug an ML or transformer model (e.g., SpaCy or HuggingFace) behind `BaseNERExtractor`.
2. **Cross-Sentence Coreference Resolution:**
   - If a document says *"Dr. Watson founded Acme Corp. Later, he retired."*, the current relation extractor operates within sentence boundaries and does not resolve the pronoun *"he"* across sentences.
3. **Complex Nested PDF Layouts:**
   - Multi-column PDF documents and embedded tables require OCR and bounding box analysis, which are deferred to future specialized document-layout engines.
4. **Epistemic Invariant Maintained:**
   - Automated claims will never be promoted to `ReviewStatus.VERIFIED` autonomously; human investigator review remains required.
