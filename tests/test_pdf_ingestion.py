"""
Comprehensive Tests for Sherlock AI PDF Document Ingestion, Railway Deployment,
and End-to-End Investigation Lifecycle Protections.

Validates:
1. Valid text-based PDF extracts text and metadata.
2. Multi-page PDF preserves content and page boundaries.
3. Empty PDF returns clear, actionable failure.
4. Scanned / image-only PDF explicitly requires OCR preprocessing without fabricating OCR.
5. Malformed PDF returns safe error without crashing.
6. Encrypted PDF returns safe error.
7. TXT and JSON ingestion remain fully operational.
8. Duplicate uploads remain deduplicated (idempotent, SHA-256).
9. Failed extraction does not create false success states.
10. Retrying a failed document succeeds cleanly without duplicate documents or evidence,
    and removes transient failure state.
11. API upload endpoint handles PDFs with correct filenames and status.
12. Railway deployment settings, port binding, and remote exposure security guards.
"""

import io
import os
import sys
import tempfile
import pytest

pypdf = pytest.importorskip("pypdf", reason="pypdf not installed in this environment.")
pytest.importorskip("fastapi", reason="FastAPI not installed in this environment.")
from fastapi.testclient import TestClient

from src.core.investigation_service import (
    DocumentProcessingRecord,
    DocumentProcessingStatus,
    InvestigationStatus,
    InvestigationOrchestrator,
)
from src.core.document_ingestion import (
    DocumentFormat,
    DocumentParsingError,
    DocumentLimitExceededError,
    ExtractionCapabilityError,
    IngestionConfig,
    PdfDocumentParser,
    DocumentIngestionService,
)
from src.core.investigation_sqlite import SQLiteInvestigationStore
from src.api.app import create_app
from src.api.server import LOOPBACK_HOSTS


def create_minimal_text_pdf(text: str = "Alice Mercer visited London.") -> bytes:
    """Generate a minimal valid single-page text PDF."""
    escaped_text = text.replace("(", "\\(").replace(")", "\\)")
    stream_content = f"BT\n/F1 12 Tf\n72 712 Td\n({escaped_text}) Tj\nET\n"
    stream_len = len(stream_content.encode("latin1"))

    pdf_template = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length {stream_len} >>
stream
{stream_content}endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000224 00000 n 
0000000330 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
400
%%EOF
"""
    return pdf_template.encode("latin1")


def create_multipage_text_pdf(pages_text: list[str]) -> bytes:
    """Generate a multi-page PDF where each page contains distinct text."""
    writer = pypdf.PdfWriter()
    for txt in pages_text:
        single_page_bytes = create_minimal_text_pdf(txt)
        reader = pypdf.PdfReader(io.BytesIO(single_page_bytes))
        writer.add_page(reader.pages[0])

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def create_blank_pdf(num_pages: int = 1) -> bytes:
    """Generate a valid PDF containing only blank pages (simulating scanned/empty PDF)."""
    writer = pypdf.PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def create_encrypted_pdf(text: str = "Confidential dossier", password: str = "secretpass") -> bytes:
    """Generate a password-encrypted PDF."""
    single_page_bytes = create_minimal_text_pdf(text)
    reader = pypdf.PdfReader(io.BytesIO(single_page_bytes))
    writer = pypdf.PdfWriter()
    writer.add_page(reader.pages[0])
    writer.encrypt(password)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TestPdfDocumentParser:
    """Unit tests for PdfDocumentParser and low-level extraction guards."""

    def test_1_valid_text_pdf_extracts_text(self):
        content = create_minimal_text_pdf("Alice Mercer operates in London.")
        parser = PdfDocumentParser()
        doc = parser.parse(content, source_name="report.pdf")

        assert doc.format == DocumentFormat.PDF
        assert doc.source_name == "report.pdf"
        assert "Alice Mercer operates in London." in doc.normalized_text
        assert doc.char_count == len(doc.normalized_text)
        assert doc.page_count == 1
        assert len(doc.page_offsets) == 1
        assert doc.page_offsets[0] == (0, doc.char_count)
        assert doc.parser_name == "sherlock_pdf_parser_pypdf"
        assert len(doc.content_hash) == 64

    def test_2_multipage_pdf_preserves_content_and_boundaries(self):
        page1_text = "Page 1: Alice Mercer transferred funds to BlueStar Capital."
        page2_text = "Page 2: Bob Vance verified receipt of $5,000,000."
        content = create_multipage_text_pdf([page1_text, page2_text])

        parser = PdfDocumentParser()
        doc = parser.parse(content, source_name="multipage.pdf")

        assert doc.page_count == 2
        assert len(doc.page_offsets) == 2
        assert page1_text in doc.normalized_text
        assert page2_text in doc.normalized_text

        # Verify page boundary preservation and character offsets
        start1, end1 = doc.page_offsets[0]
        start2, end2 = doc.page_offsets[1]

        assert doc.normalized_text[start1:end1] == page1_text
        assert doc.normalized_text[start2:end2] == page2_text
        # Pages separated by \n\n
        assert doc.normalized_text[end1:start2] == "\n\n"

    def test_3_empty_pdf_returns_clear_failure(self):
        # Blank PDF with no extractable text
        blank_pdf = create_blank_pdf(num_pages=1)
        parser = PdfDocumentParser()

        with pytest.raises(DocumentParsingError) as exc_info:
            parser.parse(blank_pdf, source_name="blank.pdf")

        err_msg = str(exc_info.value)
        assert "PDF contains no extractable text" in err_msg
        assert "scanned PDFs require optical character recognition (OCR)" in err_msg

    def test_4_scanned_pdf_explicitly_requires_ocr_without_fabrication(self):
        # 3 blank pages simulating scanned documents without OCR layer
        scanned_pdf = create_blank_pdf(num_pages=3)
        parser = PdfDocumentParser()

        with pytest.raises(DocumentParsingError) as exc_info:
            parser.parse(scanned_pdf, source_name="scanned_contract.pdf")

        err_msg = str(exc_info.value)
        assert "OCR is unsupported" in err_msg
        assert "scanned PDFs require optical character recognition (OCR) preprocessing" in err_msg

    def test_5_malformed_pdf_returns_safe_error(self):
        parser = PdfDocumentParser()
        malformed_bytes = b"%PDF-1.4\nCorrupted header and invalid stream without EOF marker\x00\xff"

        with pytest.raises(DocumentParsingError) as exc_info:
            parser.parse(malformed_bytes, source_name="corrupt.pdf")

        assert "Malformed or unreadable PDF document" in str(exc_info.value)

    def test_6_encrypted_pdf_returns_safe_error(self):
        encrypted_pdf = create_encrypted_pdf(text="Top Secret", password="super_secret_password")
        parser = PdfDocumentParser()

        with pytest.raises(DocumentParsingError) as exc_info:
            parser.parse(encrypted_pdf, source_name="encrypted.pdf")

        assert "PDF is encrypted or password-protected" in str(exc_info.value)

    def test_7_oversized_pdf_page_limit_enforced(self):
        cfg = IngestionConfig(max_page_count=2)
        content = create_multipage_text_pdf(["P1", "P2", "P3"])
        parser = PdfDocumentParser()

        with pytest.raises(DocumentLimitExceededError) as exc_info:
            parser.parse(content, source_name="many_pages.pdf", config=cfg)

        assert "PDF page count 3 exceeds limit of 2" in str(exc_info.value)

    def test_8_pdf_capability_error_when_engine_missing(self, monkeypatch):
        parser = PdfDocumentParser()
        monkeypatch.setitem(sys.modules, "pypdf", None)

        with pytest.raises(ExtractionCapabilityError) as exc_info:
            parser.parse(b"%PDF-1.4 dummy", source_name="test.pdf")

        assert "PDF extraction is unavailable because no supported PDF engine" in str(exc_info.value)
        assert "TXT and JSON ingestion remain fully operational" in str(exc_info.value)


class TestInvestigationWorkflowAndLifecycle:
    """Integration tests for investigation service, upload retry, deduplication, and persistence."""

    def test_txt_and_json_ingestion_remain_operational(self):
        orchestrator = InvestigationOrchestrator()
        inv = orchestrator.create_investigation("inv_mixed_types")

        # Ingest TXT
        txt_bytes = b"Alice Mercer founded Apex Global in 2020."
        rec_txt = orchestrator.process_document(
            investigation_id="inv_mixed_types",
            raw_content=txt_bytes,
            source_name="memo.txt",
            doc_format=DocumentFormat.TXT,
        )
        assert rec_txt.status == DocumentProcessingStatus.COMPLETED
        assert rec_txt.mention_count > 0

        # Ingest JSON
        json_bytes = b'{"text": "Bob Vance works for BlueStar Capital in Delaware."}'
        rec_json = orchestrator.process_document(
            investigation_id="inv_mixed_types",
            raw_content=json_bytes,
            source_name="report.json",
            doc_format=DocumentFormat.JSON,
        )
        assert rec_json.status == DocumentProcessingStatus.COMPLETED
        assert rec_json.mention_count > 0

    def test_duplicate_pdf_uploads_remain_deduplicated(self):
        orchestrator = InvestigationOrchestrator()
        orchestrator.create_investigation("inv_dedup_test")

        pdf_bytes = create_minimal_text_pdf("Alice Mercer controls Apex Global Holdings.")

        # First ingestion
        rec1 = orchestrator.process_document(
            investigation_id="inv_dedup_test",
            raw_content=pdf_bytes,
            source_name="evidence_doc.pdf",
            doc_format=DocumentFormat.PDF,
        )
        assert rec1.status == DocumentProcessingStatus.COMPLETED

        # Second ingestion with identical content bytes
        rec2 = orchestrator.process_document(
            investigation_id="inv_dedup_test",
            raw_content=pdf_bytes,
            source_name="duplicate_upload.pdf",
            doc_format=DocumentFormat.PDF,
        )
        assert rec2.status == DocumentProcessingStatus.SKIPPED_DUPLICATE
        assert rec2.metadata.get("idempotent_duplicate") is True
        assert rec2.document_id == rec1.document_id

        # Summary check: total unique documents remains 1
        summary = orchestrator.get_summary("inv_dedup_test")
        assert summary.total_documents == 1
        assert summary.completed_documents == 1

    def test_failed_extraction_does_not_create_false_success(self):
        orchestrator = InvestigationOrchestrator()
        orchestrator.create_investigation("inv_fail_test")

        scanned_bytes = create_blank_pdf(num_pages=1)
        rec = orchestrator.process_document(
            investigation_id="inv_fail_test",
            raw_content=scanned_bytes,
            source_name="scanned_fail.pdf",
            doc_format=DocumentFormat.PDF,
        )

        assert rec.status == DocumentProcessingStatus.FAILED
        assert "OCR is unsupported" in rec.error_message
        assert rec.mention_count == 0
        assert rec.claim_count == 0
        assert rec.evidence_count == 0

        session = orchestrator.get_investigation("inv_fail_test")
        assert session.status == InvestigationStatus.PARTIAL_FAILURE
        # Ensure not stored in processed_hashes
        assert rec.content_hash not in session.processed_hashes
        # Ensure no spurious entities or mentions created
        assert len(session.mentions) == 0

    def test_retrying_failed_document_cleans_transient_failure_and_avoids_duplicates(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            sqlite_store = SQLiteInvestigationStore(db_path=db_path)
            orchestrator = InvestigationOrchestrator(sqlite_store=sqlite_store)
            inv = orchestrator.create_investigation("inv_retry_case")

            # 1. Prepare valid PDF content
            valid_content = create_minimal_text_pdf("Alice Mercer is the CEO of Apex Global Holdings.")
            import hashlib
            content_hash = hashlib.sha256(valid_content).hexdigest()
            err_id = f"doc_err_{content_hash[:8]}"

            # Simulate an initial failure for this content (e.g. engine was down or network interrupted)
            session = orchestrator.get_investigation("inv_retry_case")
            simulated_err_rec = DocumentProcessingRecord(
                document_id=err_id,
                source_name="dossier.pdf",
                source_uri=None,
                content_hash=content_hash,
                status=DocumentProcessingStatus.FAILED,
                error_message="Simulated temporary parsing failure",
            )
            session.document_records[err_id] = simulated_err_rec
            session.status = InvestigationStatus.PARTIAL_FAILURE
            session.warnings.append(f"Processing failed for 'dossier.pdf': Simulated temporary parsing failure")

            # Initial summary has 1 failed document
            summary_initial = orchestrator.get_summary("inv_retry_case")
            assert summary_initial.failed_documents == 1
            assert summary_initial.completed_documents == 0

            # 2. Re-ingest / retry the document now that the issue is fixed
            rec_retry = orchestrator.process_document(
                investigation_id="inv_retry_case",
                raw_content=valid_content,
                source_name="dossier.pdf",
                doc_format=DocumentFormat.PDF,
            )
            assert rec_retry.status == DocumentProcessingStatus.COMPLETED
            assert rec_retry.mention_count > 0

            # 3. Verify clean session state: prior transient error record was purged
            assert err_id not in session.document_records
            assert rec_retry.document_id in session.document_records
            assert session.status == InvestigationStatus.COMPLETED

            summary_after = orchestrator.get_summary("inv_retry_case")
            assert summary_after.total_documents == 1
            assert summary_after.completed_documents == 1
            assert summary_after.failed_documents == 0

            # 4. Third attempt (idempotent duplicate upload) produces duplicate status without duplicating evidence
            initial_ev_count = len(session.store.list_evidence())
            rec_dup = orchestrator.process_document(
                investigation_id="inv_retry_case",
                raw_content=valid_content,
                source_name="dossier.pdf",
                doc_format=DocumentFormat.PDF,
            )
            assert rec_dup.status == DocumentProcessingStatus.SKIPPED_DUPLICATE
            assert len(session.store.list_evidence()) == initial_ev_count
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)


class TestApiDocumentUploadAndRailwayDeployment:
    """Test FastAPI upload route and Railway deployment configurations."""

    def test_api_upload_valid_pdf_success(self):
        app = create_app()
        client = TestClient(app)

        # Create investigation
        res_create = client.post("/api/v1/investigations", json={"investigation_id": "api_test_inv"})
        assert res_create.status_code == 201

        # Upload valid text PDF
        pdf_bytes = create_minimal_text_pdf("Dr. John Watson visited Baker Street.")
        files = {"file": ("case_notes.pdf", pdf_bytes, "application/pdf")}
        data = {"auto_process": "true"}

        res_upload = client.post("/api/v1/investigations/api_test_inv/documents", files=files, data=data)
        assert res_upload.status_code == 201
        doc_json = res_upload.json()
        assert doc_json["status"] == "COMPLETED"
        assert doc_json["source_name"] == "case_notes.pdf"
        assert doc_json["mention_count"] > 0
        assert doc_json["char_count"] > 0

    def test_api_upload_empty_pdf_fails_cleanly(self):
        app = create_app()
        client = TestClient(app)

        client.post("/api/v1/investigations", json={"investigation_id": "api_empty_inv"})
        blank_bytes = create_blank_pdf(num_pages=1)
        files = {"file": ("empty.pdf", blank_bytes, "application/pdf")}

        res_upload = client.post("/api/v1/investigations/api_empty_inv/documents", files=files)
        assert res_upload.status_code == 201
        doc_json = res_upload.json()
        assert doc_json["status"] == "FAILED"
        assert "OCR is unsupported" in doc_json["error_message"]

    def test_railway_procfile_and_manifest_validity(self):
        # 1. Procfile must exist and specify web process running src.api.server
        procfile_path = "Procfile"
        assert os.path.exists(procfile_path), "Procfile must exist for Railway deployment"
        with open(procfile_path, "r") as f:
            procfile_content = f.read().strip()
        assert "web: python -m src.api.server" in procfile_content

        # 2. requirements.txt must contain pypdf, fastapi, uvicorn, python-multipart
        with open("requirements.txt", "r") as f:
            reqs = f.read()
        assert "pypdf" in reqs, "pypdf must be declared in requirements.txt"
        assert "fastapi" in reqs, "fastapi must be declared in requirements.txt"
        assert "uvicorn" in reqs, "uvicorn must be declared in requirements.txt"
        assert "python-multipart" in reqs, "python-multipart must be declared in requirements.txt"

    def test_railway_remote_security_guards_enforced(self, monkeypatch):
        """Verify that remote binding enforces authentication token and rejects weak configurations."""
        import subprocess

        # 1. Remote host without --allow-remote should fail
        cmd_no_allow = [
            sys.executable, "-m", "src.api.server",
            "--host", "0.0.0.0",
            "--port", "8999"
        ]
        proc = subprocess.run(cmd_no_allow, capture_output=True, text=True)
        assert proc.returncode != 0
        assert "Security Refusal: Binding to non-loopback host '0.0.0.0' is prohibited by default" in proc.stderr or "Security Refusal" in proc.stdout

        # 2. Remote host with --allow-remote but short/missing token (< 16 chars) should fail
        cmd_short_token = [
            sys.executable, "-m", "src.api.server",
            "--host", "0.0.0.0",
            "--port", "8999",
            "--allow-remote",
            "--api-token", "weak_token"
        ]
        proc2 = subprocess.run(cmd_short_token, capture_output=True, text=True)
        assert proc2.returncode != 0
        assert "requires an API token with at least 16 characters" in proc2.stderr or "16 characters" in proc2.stdout
