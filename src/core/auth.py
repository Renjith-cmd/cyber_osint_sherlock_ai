"""
Authentication, Password Hashing, JWT Tokens, and Audit Logging for Sherlock AI.
Provides server-side authentication with salted password hashing, JWT bearer tokens,
and an immutable security audit trail.
"""

from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from typing import Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field

# Security configuration from environment
SECRET_KEY = os.getenv("SHERLOCK_SECRET_KEY", "sherlock-ai-epistemic-secret-key-change-in-prod-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = int(os.getenv("SHERLOCK_JWT_EXPIRATION_MINUTES", "1440"))  # 24 hours
SALT_BYTES = 16
PBKDF2_ITERATIONS = 600_000


class UserRecord(BaseModel):
    """User account model."""
    id: str
    username: str
    email: str
    hashed_password: str
    full_name: Optional[str] = None
    role: str = "analyst"  # "analyst", "senior_investigator", "admin"
    created_at: str
    is_active: bool = True

    def to_public_dict(self) -> Dict[str, Any]:
        """Return user dict without sensitive credentials."""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "created_at": self.created_at,
            "is_active": self.is_active,
        }


class AuditLogEntry(BaseModel):
    """Audit log entry for security and forensic compliance."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Optional[str] = None
    username: Optional[str] = None
    action: str  # USER_REGISTER, USER_LOGIN, INVESTIGATION_CREATE, DOCUMENT_UPLOAD, etc.
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    ip_address: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def hash_password(password: str) -> str:
    """
    Hash a password securely using PBKDF2-HMAC-SHA256 with 600,000 iterations
    and a cryptographically random 16-byte salt. Format: salt$hash
    """
    if not password or len(password) < 6:
        raise ValueError("Password must be at least 6 characters long.")
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against the stored salt$hash format using constant-time comparison."""
    if not plain_password or not hashed_password or "$" not in hashed_password:
        return False
    try:
        salt_hex, hash_hex = hashed_password.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)
        candidate_hash = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return hmac.compare_digest(candidate_hash, expected_hash)
    except Exception:
        return False


def create_access_token(user_id: str, username: str, role: str = "analyst", expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token."""
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(minutes=JWT_EXPIRATION_MINUTES)
    exp = now + expires_delta

    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    
    # Use pyjwt if installed
    try:
        import jwt
        token = jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)
        return token
    except Exception:
        # Fallback pure-python signed token
        import base64
        header = {"alg": "HS256", "typ": "JWT"}
        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
        
        h_str = b64url(json.dumps(header).encode("utf-8"))
        p_str = b64url(json.dumps(payload).encode("utf-8"))
        to_sign = f"{h_str}.{p_str}".encode("utf-8")
        sig = hmac.new(SECRET_KEY.encode("utf-8"), to_sign, hashlib.sha256).digest()
        s_str = b64url(sig)
        return f"{h_str}.{p_str}.{s_str}"


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify a signed JWT access token. Returns payload or None if invalid/expired."""
    if not token or not token.strip():
        return None
    token = token.strip()
    try:
        import jwt
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except Exception:
        # Fallback parser
        try:
            import base64
            parts = token.split(".")
            if len(parts) != 3:
                return None
            h_str, p_str, s_str = parts
            to_sign = f"{h_str}.{p_str}".encode("utf-8")
            expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), to_sign, hashlib.sha256).digest()
            # Pad base64
            def b64url_decode(s: str) -> bytes:
                padding = 4 - (len(s) % 4)
                if padding != 4:
                    s += "=" * padding
                return base64.urlsafe_b64decode(s)
            
            sig = b64url_decode(s_str)
            if not hmac.compare_digest(sig, expected_sig):
                return None
            
            payload_bytes = b64url_decode(p_str)
            payload = json.loads(payload_bytes.decode("utf-8"))
            now_ts = int(datetime.now(timezone.utc).timestamp())
            if payload.get("exp", 0) < now_ts:
                return None
            return payload
        except Exception:
            return None


def validate_username(username: str) -> str:
    """Validate username string."""
    cleaned = (username or "").strip()
    if not re.match(r"^[a-zA-Z0-9_\-\.]{3,32}$", cleaned):
        raise ValueError("Username must be 3-32 alphanumeric characters, dashes, or underscores.")
    return cleaned


def validate_email(email: str) -> str:
    """Validate email address format."""
    cleaned = (email or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", cleaned):
        raise ValueError("Invalid email address format.")
    return cleaned
