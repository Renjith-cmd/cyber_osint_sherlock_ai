"""
Security safeguards and input validation for Sherlock AI Investigation API (Milestone 13).

Enforces:
- Strict upload size bounds.
- Extension whitelist and magic-byte / content inspection.
- Path traversal and filename sanitization.
- CORS origin restriction (no wildcard with credentials).
- HTML escaping to protect UI from untrusted extracted content.
"""

import html
import os
import re
import secrets
from typing import Tuple, List, Optional
from fastapi import HTTPException, status


# Max document upload size: 5 MB
MAX_UPLOAD_SIZE_BYTES = int(os.getenv("SHERLOCK_MAX_UPLOAD_SIZE", 5 * 1024 * 1024))

# Whitelist of supported extensions
ALLOWED_EXTENSIONS = {".txt", ".json", ".pdf", ".csv"}

# Permitted CORS origins for local development
ALLOWED_CORS_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def validate_api_token(provided_token: Optional[str], expected_token: str) -> bool:
    """Validate API token using constant-time string comparison to prevent timing attacks."""
    if not provided_token or not expected_token:
        return False
    return secrets.compare_digest(provided_token.strip(), expected_token.strip())


def validate_reviewer_identity(reviewer: str, authenticated_principal: Optional[str] = None) -> str:
    """
    Validate reviewer attribution identifier to prevent spoofing.
    
    If authenticated principal is bound to the request, verifies that the reviewer
    matches the authenticated identity. In local/single-tenant mode, validates that
    the identifier is a well-formed alphanumeric string.
    """
    if not reviewer or not reviewer.strip():
        raise SecurityValidationError("Reviewer identifier cannot be empty.", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    
    cleaned = reviewer.strip()
    if not re.match(r"^[a-zA-Z0-9_\-\.]{2,64}$", cleaned):
        raise SecurityValidationError(
            f"Reviewer identifier '{cleaned}' is invalid. Must be 2-64 alphanumeric characters, dots, dashes, or underscores.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    
    if authenticated_principal and cleaned != authenticated_principal:
        raise SecurityValidationError(
            f"Reviewer identity mismatch: authenticated principal is '{authenticated_principal}', cannot submit review as '{cleaned}'.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    
    return cleaned


async def read_bounded_upload(file, max_bytes: int = MAX_UPLOAD_SIZE_BYTES, chunk_size: int = 64 * 1024) -> bytes:
    """
    Read an uploaded file in bounded chunks.
    Aborts reading immediately and raises HTTP 413 if accumulated size exceeds max_bytes,
    preventing unbounded memory allocation.
    """
    chunks = []
    total = 0
    try:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                max_mb = max_bytes / (1024 * 1024)
                raise SecurityValidationError(
                    f"File upload exceeds maximum allowed limit ({max_mb:.1f} MB / {max_bytes} bytes). Upload aborted early.",
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                )
            chunks.append(chunk)
    finally:
        await file.close()
    
    return b"".join(chunks)


# Permitted CORS origins for local development
ALLOWED_CORS_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


class SecurityValidationError(HTTPException):
    """Domain-specific HTTP exception for security validation errors."""
    def __init__(self, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(status_code=status_code, detail=detail)


def sanitize_filename(raw_filename: str) -> str:
    """
    Sanitize an uploaded filename to prevent path traversal and shell injection.
    
    Rejects:
    - Path traversal sequences (../, ..\\).
    - Null bytes and ASCII control characters.
    - Hidden/dotfiles without basename.
    """
    if not raw_filename or not raw_filename.strip():
        raise SecurityValidationError("Filename cannot be empty.")

    # Reject null bytes and control chars
    if "\x00" in raw_filename or any(ord(c) < 32 for c in raw_filename):
        raise SecurityValidationError("Filename contains invalid or control characters.")

    # Strip directory paths
    base = os.path.basename(raw_filename).strip()
    base = base.replace("\\", "/").split("/")[-1]

    # Reject path traversal
    if ".." in base or "/" in base or "\\" in base:
        raise SecurityValidationError("Path traversal characters detected in filename.")

    # Remove dangerous characters, allow only alphanumeric, underscores, hyphens, dots
    cleaned = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", base)
    cleaned = cleaned.strip("._-")

    if not cleaned:
        raise SecurityValidationError("Filename is invalid after sanitization.")

    if len(cleaned) > 128:
        # Preserve extension if present
        name, ext = os.path.splitext(cleaned)
        cleaned = name[: 128 - len(ext)] + ext

    return cleaned


def validate_upload_content(filename: str, content_bytes: bytes) -> Tuple[str, str]:
    """
    Validate uploaded file size, extension, and content structure.
    
    Returns:
        (sanitized_filename, format_type)
    """
    # 1. Size bounds check
    if len(content_bytes) == 0:
        raise SecurityValidationError("Uploaded document is empty (0 bytes).")

    if len(content_bytes) > MAX_UPLOAD_SIZE_BYTES:
        max_mb = MAX_UPLOAD_SIZE_BYTES / (1024 * 1024)
        raise SecurityValidationError(
            f"File size ({len(content_bytes) / (1024 * 1024):.2f} MB) exceeds maximum allowed limit ({max_mb:.1f} MB).",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )

    # 2. Filename and extension check
    safe_name = sanitize_filename(filename)
    _, ext = os.path.splitext(safe_name)
    ext_lower = ext.lower()

    if ext_lower not in ALLOWED_EXTENSIONS:
        raise SecurityValidationError(
            f"Unsupported document format '{ext_lower}'. Allowed formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )

    # 3. Content inspection by format
    if ext_lower == ".pdf":
        stripped_header = content_bytes.lstrip(b"\xef\xbb\xbf \t\r\n")
        if not stripped_header.startswith(b"%PDF-"):
            raise SecurityValidationError("Invalid PDF document: missing %PDF- header magic bytes.")
        format_type = "pdf"

    elif ext_lower == ".json":
        try:
            decoded = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise SecurityValidationError("Invalid JSON document: file is not valid UTF-8 encoded text.")
        try:
            import json
            json.loads(decoded)
        except Exception as e:
            raise SecurityValidationError(f"Invalid JSON syntax: {str(e)[:100]}")
        format_type = "json"

    elif ext_lower == ".txt":
        # Disallow raw binary / null bytes in plain text
        if b"\x00" in content_bytes:
            raise SecurityValidationError("Plain text file contains invalid binary null bytes.")
        try:
            content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content_bytes.decode("latin-1")
            except Exception:
                raise SecurityValidationError("Unable to decode text document using UTF-8 or Latin-1.")
        format_type = "txt"

    elif ext_lower == ".csv":
        # Disallow raw binary / null bytes in CSV
        if b"\x00" in content_bytes:
            raise SecurityValidationError("CSV file contains invalid binary null bytes.")
        try:
            content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content_bytes.decode("latin-1")
            except Exception:
                raise SecurityValidationError("Unable to decode CSV document using UTF-8 or Latin-1.")
        format_type = "csv"

    else:
        raise SecurityValidationError(f"Unsupported format '{ext_lower}'.")

    return safe_name, format_type


def sanitize_text_for_display(text: str) -> str:
    """
    HTML-escape untrusted extracted text for safe display in UI.
    """
    if not text:
        return ""
    return html.escape(text)
