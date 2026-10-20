"""
Authentication and User Management Routes for Sherlock AI.
Provides registration, login, JWT issuance, current user profile, and audit logs.
"""

from datetime import datetime, timezone
import uuid
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status

from src.core.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    validate_username,
    validate_email,
    UserRecord,
)
from src.api.auth_schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    UserResponse,
    TokenResponse,
    AuditLogResponse,
)

auth_router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def get_sqlite_store(request: Request):
    """Retrieve SQLite store from FastAPI app state."""
    store = getattr(request.app.state, "sqlite_store", None)
    return store


def get_orchestrator(request: Request):
    """Retrieve Orchestrator from FastAPI app state."""
    return getattr(request.app.state, "orchestrator", None)


async def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Optional[UserRecord]:
    """
    Extract and verify current authenticated user from Bearer token.
    Returns UserRecord if valid token provided, or None if anonymous/unauthenticated.
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    elif "access_token" in request.cookies:
        token = request.cookies.get("access_token")

    if not token:
        return None

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None

    user_id = payload["sub"]
    store = get_sqlite_store(request)
    if store:
        user_dict = store.get_user_by_id(user_id)
        if user_dict:
            return UserRecord(
                id=user_dict["id"],
                username=user_dict["username"],
                email=user_dict["email"],
                hashed_password=user_dict["hashed_password"],
                full_name=user_dict.get("full_name"),
                role=user_dict.get("role", "analyst"),
                created_at=user_dict.get("created_at", datetime.now(timezone.utc).isoformat()),
                is_active=bool(user_dict.get("is_active", 1)),
            )

    # In-memory fallback if user was generated in-session
    return UserRecord(
        id=user_id,
        username=payload.get("username", "analyst"),
        email=f"{payload.get('username', 'analyst')}@sherlock.ai",
        hashed_password="",
        role=payload.get("role", "analyst"),
        created_at=datetime.now(timezone.utc).isoformat(),
        is_active=True,
    )


async def require_authenticated_user(
    current_user: Optional[UserRecord] = Depends(get_current_user),
) -> UserRecord:
    """Dependency requiring that a valid authenticated user is present."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in to access this private resource.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


def enforce_investigation_access(
    orchestrator: Any,
    investigation_id: str,
    current_user: Optional[UserRecord],
    store: Optional[Any] = None,
    client_ip: Optional[str] = None,
) -> Any:
    """
    Forensic Authorization Guard:
    Checks if an investigation exists and verifies that the current user is authorized to access it.
    If the case is owned by User A and User B attempts access, raises 403 Forbidden
    and logs an unauthorized access attempt to the audit trail.
    """
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator unavailable.")

    session = orchestrator.get_investigation(investigation_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation case '{investigation_id}' not found.",
        )

    owner_id = getattr(session, "owner_id", None)
    if not owner_id and store:
        owner_id = store.get_investigation_owner(investigation_id)

    # If the case is assigned to an owner and an authenticated user exists:
    if owner_id:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="This investigation case is private. Authentication is required to view or modify it.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if current_user.id != owner_id and current_user.role != "admin":
            if store:
                store.record_audit_log(
                    user_id=current_user.id,
                    username=current_user.username,
                    action="UNAUTHORIZED_ACCESS_ATTEMPT",
                    target_type="investigation",
                    target_id=investigation_id,
                    details={
                        "owner_id": owner_id,
                        "attempted_by": current_user.id,
                        "reason": "Cross-user isolation violation",
                    },
                    ip_address=client_ip,
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: You do not have authorization to access private investigation case '{investigation_id}'.",
            )

    return session


@auth_router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    body: UserRegisterRequest,
    request: Request,
    store: Any = Depends(get_sqlite_store),
):
    """Register a new user account and return an access token."""
    try:
        clean_username = validate_username(body.username)
        clean_email = validate_email(body.email)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    if not store:
        raise HTTPException(status_code=500, detail="Database store unavailable.")

    # Check for existing username or email
    if store.get_user_by_username(clean_username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{clean_username}' is already registered.",
        )
    if store.get_user_by_email(clean_email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{clean_email}' is already registered.",
        )

    user_id = f"usr_{uuid.uuid4().hex[:12]}"
    hashed_pw = hash_password(body.password)

    user_dict = store.create_user(
        user_id=user_id,
        username=clean_username,
        email=clean_email,
        hashed_password=hashed_pw,
        full_name=body.full_name,
        role=body.role or "analyst",
    )

    client_ip = request.client.host if request.client else None
    store.record_audit_log(
        user_id=user_id,
        username=clean_username,
        action="USER_REGISTER",
        target_type="user",
        target_id=user_id,
        details={"email": clean_email, "role": body.role or "analyst"},
        ip_address=client_ip,
    )

    access_token = create_access_token(user_id=user_id, username=clean_username, role=body.role or "analyst")

    user_resp = UserResponse(
        id=user_id,
        username=clean_username,
        email=clean_email,
        full_name=body.full_name,
        role=body.role or "analyst",
        created_at=user_dict["created_at"],
        is_active=True,
    )
    return TokenResponse(access_token=access_token, token_type="Bearer", user=user_resp)


@auth_router.post("/login", response_model=TokenResponse)
async def login_user(
    body: UserLoginRequest,
    request: Request,
    store: Any = Depends(get_sqlite_store),
):
    """Authenticate with username or email and password."""
    if not store:
        raise HTTPException(status_code=500, detail="Database store unavailable.")

    identifier = body.username.strip()
    user_dict = store.get_user_by_username(identifier)
    if not user_dict and "@" in identifier:
        user_dict = store.get_user_by_email(identifier)

    client_ip = request.client.host if request.client else None

    if not user_dict or not verify_password(body.password, user_dict["hashed_password"]):
        if store and user_dict:
            store.record_audit_log(
                user_id=user_dict["id"],
                username=user_dict["username"],
                action="LOGIN_FAILED",
                target_type="user",
                target_id=user_dict["id"],
                details={"reason": "Invalid credentials"},
                ip_address=client_ip,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = user_dict["id"]
    username = user_dict["username"]
    role = user_dict.get("role", "analyst")

    store.record_audit_log(
        user_id=user_id,
        username=username,
        action="USER_LOGIN",
        target_type="user",
        target_id=user_id,
        details={"login_time": datetime.now(timezone.utc).isoformat()},
        ip_address=client_ip,
    )

    access_token = create_access_token(user_id=user_id, username=username, role=role)

    user_resp = UserResponse(
        id=user_id,
        username=username,
        email=user_dict["email"],
        full_name=user_dict.get("full_name"),
        role=role,
        created_at=user_dict["created_at"],
        is_active=bool(user_dict.get("is_active", 1)),
    )
    return TokenResponse(access_token=access_token, token_type="Bearer", user=user_resp)


@auth_router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: UserRecord = Depends(require_authenticated_user),
):
    """Get profile information for the authenticated user."""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        created_at=current_user.created_at,
        is_active=current_user.is_active,
    )


@auth_router.get("/audit-logs", response_model=List[AuditLogResponse])
async def list_audit_logs(
    limit: int = 50,
    action: Optional[str] = None,
    target_id: Optional[str] = None,
    current_user: Optional[UserRecord] = Depends(get_current_user),
    store: Any = Depends(get_sqlite_store),
):
    """Retrieve security audit logs."""
    if not store:
        return []
    user_filter = None
    if current_user and current_user.role != "admin" and not target_id:
        user_filter = current_user.id

    logs = store.get_audit_logs(
        user_id=user_filter,
        target_id=target_id,
        limit=min(limit, 200),
    )
    if action:
        logs = [l for l in logs if l.get("action") == action]

    return [
        AuditLogResponse(
            id=l["id"],
            user_id=l.get("user_id"),
            username=l.get("username"),
            action=l["action"],
            target_type=l.get("target_type"),
            target_id=l.get("target_id"),
            details=l.get("details", {}),
            ip_address=l.get("ip_address"),
            timestamp=l["timestamp"],
        )
        for l in logs
    ]
