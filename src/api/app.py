"""
FastAPI Application Factory for Sherlock AI (Milestone 13).

Provides:
- FastAPI application setup with OpenAPI docs.
- Strict CORS configuration (dev origins only; no wildcard credentials).
- Centralized exception handlers preventing stack trace leakage.
- Static file serving for the dark-graphite UI workspace at `/`.
- Dependency injection for SQLite store and InvestigationOrchestrator.
"""

import os
from typing import Optional
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.core.investigation_service import InvestigationOrchestrator
from src.core.investigation_sqlite import SQLiteInvestigationStore
from src.api.routes import router as api_v1_router, set_orchestrator, get_orchestrator
from src.api.security import ALLOWED_CORS_ORIGINS, validate_api_token


def create_app(
    db_path: Optional[str] = "data/sherlock_investigations.db",
    backend_mode: str = "rule",
    api_token: Optional[str] = None,
    enforce_auth: bool = False,
    disable_auth: bool = False,
) -> FastAPI:
    """
    Construct and configure the Sherlock AI FastAPI application.
    Supports secure remote binding with token authentication.
    """
    app = FastAPI(
        title="Sherlock AI Investigation API",
        version="1.0.0",
        description="Audit-grade investigation engine API with epistemic provenance and human-in-the-loop review.",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # 1. Authentication Middleware for Remote / Protected Deployments
    effective_token = None if disable_auth else (api_token or os.getenv("SHERLOCK_API_TOKEN"))
    should_enforce_auth = False if disable_auth else (enforce_auth or bool(effective_token))

    if should_enforce_auth and effective_token:
        @app.middleware("http")
        async def remote_auth_middleware(request: Request, call_next):
            path = request.url.path
            # Keep the UI shell reachable so the operator can enter their API token.
            public_ui_asset = request.method == "GET" and (path == "/" or path.startswith("/static/"))
            if public_ui_asset or path in {"/docs", "/redoc", "/openapi.json", "/api/v1/health", "/api/v1/ready"}:
                return await call_next(request)

            auth_header = request.headers.get("Authorization", "")
            api_key_header = request.headers.get("X-API-Key", "")

            provided_token = None
            if auth_header.startswith("Bearer "):
                provided_token = auth_header[7:].strip()
            elif api_key_header:
                provided_token = api_key_header.strip()

            if not validate_api_token(provided_token, effective_token):
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Unauthorized: Missing or invalid API authentication token."},
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Store verified principal on request state
            principal = request.headers.get("X-Principal-User", "authenticated_operator").strip()
            request.state.authenticated_principal = principal

            return await call_next(request)

    # 2. CORS Middleware configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # 3. Store & Orchestrator Initialization
    sqlite_store = None
    if db_path is not None:
        sqlite_store = SQLiteInvestigationStore(db_path=db_path)

    orchestrator = InvestigationOrchestrator(
        default_backend_mode=backend_mode,
        sqlite_store=sqlite_store,
    )
    set_orchestrator(orchestrator)
    app.state.orchestrator = orchestrator
    app.state.sqlite_store = sqlite_store

    from src.api.auth_routes import auth_router
    app.include_router(auth_router)
    app.include_router(api_v1_router)

    # 4. Safe Generic Exception Handler (Never leak secrets or stack traces)
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        # Allow HTTPException subclasses to pass through with their status code
        from fastapi import HTTPException
        if isinstance(exc, HTTPException):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )
        # For unexpected exceptions, log internally and return sanitized response
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal server error occurred while processing the request."},
        )

    # 5. Mount UI Static Assets & Root HTML View
    ui_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ui"))
    if os.path.exists(ui_dir):
        app.mount("/static", StaticFiles(directory=ui_dir), name="static")

        @app.get("/", include_in_schema=False)
        async def serve_index():
            index_path = os.path.join(ui_dir, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path, media_type="text/html")
            return JSONResponse({"status": "UI index not found"}, status_code=404)

    return app


# Default app instance for ASGI servers
app = create_app(db_path=os.getenv("SHERLOCK_DB_PATH", "data/sherlock_investigations.db"))
