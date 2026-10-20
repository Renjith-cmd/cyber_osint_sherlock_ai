"""
Document Ingestion Layer for Sherlock AI (Milestone 9).

Supports:
- UTF-8 Plain text (.txt)
- Structured JSON documents (.json) with configurable text-field extraction
- PDF extraction with page-aware spans when an installed library is present,
  or clear, informative capability error when unavailable.

Enforces:
- SHA-256 content hashing and duplicate detection.
- Safe size, page, and character limits.
- Preservation of raw source data alongside normalized text.
- Character offsets tied strictly to the normalized text.
- No silent failures or silent empty document creation.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Dict, List, Optional, Tuple, Any, Set
from pydantic import Field, field_validator

from src.core.models import ImmutableBaseModel, _validate_non_empty_str


class DocumentFormat(str, Enum):
    TXT = "txt"
    JSON = "json"
    PDF = "pdf"
    CSV = "csv"
    UNKNOWN = "unknown"


class DocumentParsingError(Exception):
    """Raised when document content fails decoding or syntax validation."""
    pass


class ExtractionCapabilityError(Exception):
    """Raised when a document format requires an uninstalled optional engine."""
    pass


class DocumentLimitExceededError(Exception):
    """Raised when document exceeds size, text, or page limits."""
    pass


class IngestionConfig(ImmutableBaseModel):
    """Configuration and guardrail limits for document ingestion."""
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10 MB default
    max_text_length_chars: int = 2_000_000       # 2 million characters default
    max_page_count: int = 1000
    default_encoding: str = "utf-8"
    json_text_keys: List[str] = Field(default_factory=lambda: ["text", "content", "body", "article"])


class IngestedDocument(ImmutableBaseModel):
    """
    Immutable representation of an ingested document with traceable metadata.
    """
    document_id: str
    source_uri: Optional[str] = None
    source_name: str
    format: DocumentFormat
    content_hash: str
    raw_content: bytes
    normalized_text: str
    char_count: int
    page_count: Optional[int] = 1
    page_offsets: List[Tuple[int, int]] = Field(default_factory=list)
    parser_name: str
    parser_version: str
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("document_id", "source_name", "content_hash", "parser_name", "parser_version")
    @classmethod
    def _validate_strings(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)


class BaseDocumentParser(ABC):
    """Abstract interface for format-specific document parsers."""

    @abstractmethod
    def parse(
        self,
        raw_content: bytes,
        source_uri: Optional[str] = None,
        source_name: Optional[str] = None,
        config: Optional[IngestionConfig] = None,
    ) -> IngestedDocument:
        pass


class TextDocumentParser(BaseDocumentParser):
    """Parser for plain text documents (.txt)."""

    PARSER_NAME = "sherlock_text_parser"
    PARSER_VERSION = "1.0.0"

    def parse(
        self,
        raw_content: bytes,
        source_uri: Optional[str] = None,
        source_name: Optional[str] = None,
        config: Optional[IngestionConfig] = None,
    ) -> IngestedDocument:
        cfg = config or IngestionConfig()

        if len(raw_content) > cfg.max_file_size_bytes:
            raise DocumentLimitExceededError(
                f"File size {len(raw_content)} bytes exceeds limit of {cfg.max_file_size_bytes} bytes."
            )

        try:
            decoded = raw_content.decode(cfg.default_encoding)
        except UnicodeDecodeError as e:
            raise DocumentParsingError(
                f"Failed to decode text document using {cfg.default_encoding}: {e}"
            ) from e

        # Normalize line endings deterministically
        normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")

        if not normalized.strip():
            raise DocumentParsingError("Document text is empty or contains no extractable characters.")

        if len(normalized) > cfg.max_text_length_chars:
            raise DocumentLimitExceededError(
                f"Normalized text length {len(normalized)} exceeds character limit {cfg.max_text_length_chars}."
            )

        content_hash = hashlib.sha256(raw_content).hexdigest()
        name = source_name or (source_uri.split("/")[-1] if source_uri else "untitled.txt")
        doc_id = f"doc_{content_hash[:16]}"
        char_count = len(normalized)
        page_offsets = [(0, char_count)]

        return IngestedDocument(
            document_id=doc_id,
            source_uri=source_uri,
            source_name=name,
            format=DocumentFormat.TXT,
            content_hash=content_hash,
            raw_content=raw_content,
            normalized_text=normalized,
            char_count=char_count,
            page_count=1,
            page_offsets=page_offsets,
            parser_name=self.PARSER_NAME,
            parser_version=self.PARSER_VERSION,
            metadata={"encoding": cfg.default_encoding},
        )


class JsonDocumentParser(BaseDocumentParser):
    """Parser for structured JSON documents (.json)."""

    PARSER_NAME = "sherlock_json_parser"
    PARSER_VERSION = "1.0.0"

    def _extract_recursive_texts(self, obj: Any, target_keys: List[str]) -> List[str]:
        """Recursively traverse JSON objects to find strings under target keys."""
        texts: List[str] = []
        if isinstance(obj, dict):
            for k in target_keys:
                if k in obj and isinstance(obj[k], str) and obj[k].strip():
                    texts.append(obj[k].strip())
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    texts.extend(self._extract_recursive_texts(v, target_keys))
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, str) and item.strip():
                    texts.append(item.strip())
                elif isinstance(item, (dict, list)):
                    texts.extend(self._extract_recursive_texts(item, target_keys))
        return texts

    def parse(
        self,
        raw_content: bytes,
        source_uri: Optional[str] = None,
        source_name: Optional[str] = None,
        config: Optional[IngestionConfig] = None,
    ) -> IngestedDocument:
        cfg = config or IngestionConfig()

        if len(raw_content) > cfg.max_file_size_bytes:
            raise DocumentLimitExceededError(
                f"File size {len(raw_content)} bytes exceeds limit of {cfg.max_file_size_bytes} bytes."
            )

        try:
            decoded = raw_content.decode(cfg.default_encoding)
            data = json.loads(decoded)
        except UnicodeDecodeError as e:
            raise DocumentParsingError(f"Failed to decode JSON using {cfg.default_encoding}: {e}") from e
        except json.JSONDecodeError as e:
            raise DocumentParsingError(f"Invalid JSON syntax in source content: {e}") from e

        if not isinstance(data, (dict, list)):
            raise DocumentParsingError(f"Unsupported JSON root type: {type(data).__name__}")

        extracted_texts: List[str] = self._extract_recursive_texts(data, cfg.json_text_keys)
        meta_extracted: Dict[str, Any] = {}

        if not extracted_texts and isinstance(data, dict):
            # Fallback for key-value dictionaries where strings are values
            for k, v in data.items():
                if isinstance(v, str) and v.strip() and k not in ("id", "doc_id", "url"):
                    extracted_texts.append(f"{k}: {v.strip()}")
            meta_extracted = {k: v for k, v in data.items() if not isinstance(v, (dict, list))}

        if not extracted_texts:
            raise DocumentParsingError(
                f"No extractable text found in JSON using target keys {cfg.json_text_keys}."
            )

        normalized = "\n\n".join(extracted_texts)
        if len(normalized) > cfg.max_text_length_chars:
            raise DocumentLimitExceededError(
                f"Extracted JSON text length {len(normalized)} exceeds limit {cfg.max_text_length_chars}."
            )

        content_hash = hashlib.sha256(raw_content).hexdigest()
        name = source_name or (source_uri.split("/")[-1] if source_uri else "untitled.json")
        doc_id = f"doc_{content_hash[:16]}"
        char_count = len(normalized)

        return IngestedDocument(
            document_id=doc_id,
            source_uri=source_uri,
            source_name=name,
            format=DocumentFormat.JSON,
            content_hash=content_hash,
            raw_content=raw_content,
            normalized_text=normalized,
            char_count=char_count,
            page_count=1,
            page_offsets=[(0, char_count)],
            parser_name=self.PARSER_NAME,
            parser_version=self.PARSER_VERSION,
            metadata=meta_extracted,
        )


class PdfDocumentParser(BaseDocumentParser):
    """
    Parser for PDF documents (.pdf).
    Checks for available PDF extraction engines. If none are installed, raises
    an explicit ExtractionCapabilityError without crashing the application.
    """

    PARSER_NAME = "sherlock_pdf_parser"
    PARSER_VERSION = "1.0.0"

    def parse(
        self,
        raw_content: bytes,
        source_uri: Optional[str] = None,
        source_name: Optional[str] = None,
        config: Optional[IngestionConfig] = None,
    ) -> IngestedDocument:
        cfg = config or IngestionConfig()

        if len(raw_content) > cfg.max_file_size_bytes:
            raise DocumentLimitExceededError(
                f"File size {len(raw_content)} bytes exceeds limit of {cfg.max_file_size_bytes} bytes."
            )

        # Check for installed PDF engines in order of preference
        # 1. pypdf
        try:
            import pypdf
            import io
        except ImportError:
            raise ExtractionCapabilityError(
                "PDF extraction is unavailable because no supported PDF engine (pypdf, pdfplumber, fitz) "
                "is installed. TXT and JSON ingestion remain fully operational. "
                "To enable PDF parsing, install 'pypdf'."
            )

        try:
            stream = io.BytesIO(raw_content)
            reader = pypdf.PdfReader(stream)

            # Check encryption
            if reader.is_encrypted:
                try:
                    decrypted = reader.decrypt("")
                except Exception:
                    decrypted = 0
                if decrypted == 0 and reader.is_encrypted:
                    raise DocumentParsingError(
                        "PDF is encrypted or password-protected and cannot be parsed without credentials."
                    )

            pages = reader.pages
            if len(pages) == 0:
                raise DocumentParsingError("PDF contains no pages or is empty.")

            if len(pages) > cfg.max_page_count:
                raise DocumentLimitExceededError(
                    f"PDF page count {len(pages)} exceeds limit of {cfg.max_page_count}."
                )

            page_texts = []
            page_offsets = []
            curr_pos = 0

            for p in pages:
                raw_page_txt = p.extract_text() or ""
                txt = raw_page_txt.replace("\r\n", "\n").replace("\r", "\n")
                start = curr_pos
                end = curr_pos + len(txt)
                page_offsets.append((start, end))
                page_texts.append(txt)
                curr_pos = end + 2  # account for \n\n page separator

            normalized = "\n\n".join(page_texts)

            if not normalized.strip():
                raise DocumentParsingError(
                    "PDF contains no extractable text. The document may be empty or contain only scanned "
                    "images/bitmaps. OCR is unsupported; scanned PDFs require optical character recognition (OCR) "
                    "preprocessing before ingestion."
                )

            if len(normalized) > cfg.max_text_length_chars:
                raise DocumentLimitExceededError(
                    f"Extracted PDF text length {len(normalized)} exceeds character limit {cfg.max_text_length_chars}."
                )

            content_hash = hashlib.sha256(raw_content).hexdigest()
            name = source_name or (source_uri.split("/")[-1] if source_uri else "untitled.pdf")
            doc_id = f"doc_{content_hash[:16]}"

            return IngestedDocument(
                document_id=doc_id,
                source_uri=source_uri,
                source_name=name,
                format=DocumentFormat.PDF,
                content_hash=content_hash,
                raw_content=raw_content,
                normalized_text=normalized,
                char_count=len(normalized),
                page_count=len(pages),
                page_offsets=page_offsets,
                parser_name=f"{self.PARSER_NAME}_pypdf",
                parser_version=getattr(pypdf, "__version__", "unknown"),
                metadata={"page_count": len(pages)},
            )
        except (DocumentParsingError, DocumentLimitExceededError):
            raise
        except Exception as e:
            raise DocumentParsingError(f"Malformed or unreadable PDF document: {e}") from e


class CsvDocumentParser(BaseDocumentParser):
    """
    Parser for Comma-Separated Values (.csv) documents.
    Converts tabular financial and entity records into structured, offset-traceable text.
    """
    PARSER_NAME = "sherlock_csv_parser"
    PARSER_VERSION = "1.0.0"

    def parse(
        self,
        raw_content: bytes,
        source_uri: Optional[str] = None,
        source_name: Optional[str] = None,
        config: Optional[IngestionConfig] = None,
    ) -> IngestedDocument:
        import csv

        cfg = config or IngestionConfig()
        if len(raw_content) > cfg.max_file_size_bytes:
            raise DocumentLimitExceededError(
                f"File size {len(raw_content)} bytes exceeds limit of {cfg.max_file_size_bytes} bytes."
            )

        try:
            text = raw_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw_content.decode("latin-1")
            except Exception as e:
                raise DocumentParsingError(f"Failed to decode CSV content: {e}") from e

        if not text.strip():
            raise DocumentParsingError("CSV file is empty or contains only whitespace.")

        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            raise DocumentParsingError("CSV file contains no valid rows.")

        try:
            reader = csv.reader(lines)
            rows = list(reader)
        except Exception as e:
            raise DocumentParsingError(f"Malformed CSV formatting: {e}") from e

        if not rows:
            raise DocumentParsingError("No CSV records could be parsed.")

        header = rows[0]
        data_rows = rows[1:] if len(rows) > 1 else []

        normalized_lines = []
        page_offsets = []
        curr_pos = 0

        header_line = f"Table Document: {source_name or 'data.csv'} with columns: {', '.join(header)}."
        normalized_lines.append(header_line)
        curr_pos += len(header_line) + 2

        for i, row in enumerate(data_rows, start=1):
            if not any(cell.strip() for cell in row):
                continue
            parts = []
            for col_name, val in zip(header, row):
                c = col_name.strip()
                v = val.strip()
                if v:
                    parts.append(f"{c}: {v}")
            row_str = f"Row {i}: " + "; ".join(parts) + "."
            start = curr_pos
            end = curr_pos + len(row_str)
            page_offsets.append((start, end))
            normalized_lines.append(row_str)
            curr_pos = end + 2

        normalized = "\n\n".join(normalized_lines)
        if len(normalized) > cfg.max_text_length_chars:
            raise DocumentLimitExceededError(
                f"Normalized CSV text length {len(normalized)} exceeds limit {cfg.max_text_length_chars}."
            )

        content_hash = hashlib.sha256(raw_content).hexdigest()
        name = source_name or (source_uri.split("/")[-1] if source_uri else "untitled.csv")
        doc_id = f"doc_{content_hash[:16]}"

        return IngestedDocument(
            document_id=doc_id,
            source_uri=source_uri,
            source_name=name,
            format=DocumentFormat.CSV,
            content_hash=content_hash,
            raw_content=raw_content,
            normalized_text=normalized,
            char_count=len(normalized),
            page_count=max(1, len(data_rows)),
            page_offsets=page_offsets,
            parser_name=self.PARSER_NAME,
            parser_version=self.PARSER_VERSION,
            metadata={
                "row_count": len(data_rows),
                "columns": header,
            },
        )


class DocumentIngestionService:
    """
    Coordinates document ingestion across formats, manages limits, and handles deduplication.
    """

    def __init__(self, config: Optional[IngestionConfig] = None):
        self.config = config or IngestionConfig()
        self._parsers: Dict[DocumentFormat, BaseDocumentParser] = {
            DocumentFormat.TXT: TextDocumentParser(),
            DocumentFormat.JSON: JsonDocumentParser(),
            DocumentFormat.PDF: PdfDocumentParser(),
            DocumentFormat.CSV: CsvDocumentParser(),
        }
        self._hash_registry: Dict[str, str] = {}  # content_hash -> document_id
        self._documents: Dict[str, IngestedDocument] = {}

    def detect_format(self, raw_content: bytes, filename_or_uri: Optional[str] = None) -> DocumentFormat:
        """Deterministically detect format from filename extension or content signatures."""
        if filename_or_uri:
            lower = filename_or_uri.lower()
            if lower.endswith(".txt"):
                return DocumentFormat.TXT
            if lower.endswith(".json"):
                return DocumentFormat.JSON
            if lower.endswith(".pdf"):
                return DocumentFormat.PDF
            if lower.endswith(".csv"):
                return DocumentFormat.CSV

        # Magic signature check
        if raw_content.startswith(b"%PDF"):
            return DocumentFormat.PDF

        # Try JSON parsing
        try:
            first_chars = raw_content[:100].strip()
            if (first_chars.startswith(b"{") and first_chars.endswith(b"}")) or first_chars.startswith(b"["):
                json.loads(raw_content.decode(self.config.default_encoding))
                return DocumentFormat.JSON
        except Exception:
            pass

        return DocumentFormat.TXT

    def ingest_bytes(
        self,
        raw_content: bytes,
        source_uri: Optional[str] = None,
        source_name: Optional[str] = None,
        format_hint: Optional[DocumentFormat] = None,
    ) -> Tuple[IngestedDocument, bool]:
        """
        Ingest raw document bytes.
        Returns: (IngestedDocument, is_duplicate: bool)
        """
        content_hash = hashlib.sha256(raw_content).hexdigest()
        is_dup = content_hash in self._hash_registry

        fmt = format_hint or self.detect_format(raw_content, source_uri or source_name)
        parser = self._parsers.get(fmt)
        if not parser:
            raise DocumentParsingError(f"No parser available for format: {fmt}")

        doc = parser.parse(
            raw_content=raw_content,
            source_uri=source_uri,
            source_name=source_name,
            config=self.config,
        )

        if not is_dup:
            self._hash_registry[content_hash] = doc.document_id
            self._documents[doc.document_id] = doc

        return doc, is_dup

    def ingest_text(
        self,
        text: str,
        source_uri: Optional[str] = None,
        source_name: Optional[str] = None,
    ) -> Tuple[IngestedDocument, bool]:
        """Convenience method to ingest in-memory plain text string."""
        raw_bytes = text.encode(self.config.default_encoding)
        return self.ingest_bytes(
            raw_content=raw_bytes,
            source_uri=source_uri,
            source_name=source_name,
            format_hint=DocumentFormat.TXT,
        )

    def ingest(
        self,
        raw_content: bytes,
        source_name: Optional[str] = None,
        source_uri: Optional[str] = None,
        doc_format: Optional[DocumentFormat] = None,
    ) -> IngestedDocument:
        """Convenience method returning IngestedDocument directly."""
        doc, _ = self.ingest_bytes(
            raw_content=raw_content,
            source_uri=source_uri,
            source_name=source_name,
            format_hint=doc_format,
        )
        return doc

    def ingest_file(
        self,
        file_path: str,
        format_hint: Optional[DocumentFormat] = None,
    ) -> IngestedDocument:
        """Ingest a document file directly from filesystem path."""
        import os
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Document file not found: {file_path}")
        file_size = os.path.getsize(file_path)
        if file_size > self.config.max_file_size_bytes:
            raise DocumentLimitExceededError(
                f"File size ({file_size} bytes) exceeds limit ({self.config.max_file_size_bytes} bytes)."
            )
        with open(file_path, "rb") as f:
            raw_content = f.read()
        return self.ingest(
            raw_content=raw_content,
            source_name=os.path.basename(file_path),
            source_uri=f"file://{os.path.abspath(file_path)}",
            doc_format=format_hint,
        )

    def get_document(self, document_id: str) -> Optional[IngestedDocument]:
        return self._documents.get(document_id)

    def is_duplicate_content(self, content_hash: str) -> bool:
        return content_hash in self._hash_registry
