"""
Sherlock AI Investigation API & UI Server Entry Point (Milestone 13).

Usage:
    python -m src.api.server [--host 127.0.0.1] [--port 8000] [--db data/sherlock_investigations.db]
"""

import argparse
import os
import uvicorn
from src.api.app import create_app

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def main():
    default_host = os.getenv("HOST", "127.0.0.1")
    default_port = int(os.getenv("PORT", "8000"))
    default_allow_remote = os.getenv("SHERLOCK_ALLOW_REMOTE", "").lower() in ("1", "true", "yes")

    parser = argparse.ArgumentParser(description="Sherlock AI Investigation Server")
    parser.add_argument("--host", default=default_host, help=f"Host interface to bind (default: {default_host})")
    parser.add_argument("--port", type=int, default=default_port, help=f"Port to listen on (default: {default_port})")
    parser.add_argument("--db", default=os.getenv("SHERLOCK_DB_PATH", "data/sherlock_investigations.db"), help="SQLite database path")
    parser.add_argument("--backend", default=os.getenv("SHERLOCK_BACKEND_MODE", "rule"), choices=["rule", "ml", "hybrid", "mock_ml"], help="Extraction backend mode")
    parser.add_argument("--allow-remote", action="store_true", default=default_allow_remote, help="Explicitly enable exposure beyond loopback interface")
    parser.add_argument("--api-token", default=os.getenv("SHERLOCK_API_TOKEN"), help="API authentication token (required for remote exposure)")
    parser.add_argument("--reload", action="store_true", help="Enable live code reload")

    args = parser.parse_args()

    # Enforce loopback binding unless remote is explicitly allowed and secured
    is_loopback = args.host in LOOPBACK_HOSTS
    if not is_loopback:
        if not args.allow_remote:
            raise SystemExit(
                f"Security Refusal: Binding to non-loopback host '{args.host}' is prohibited by default. "
                "To expose Sherlock AI remotely, pass --allow-remote and configure --api-token "
                "(or set SHERLOCK_API_TOKEN environment variable)."
            )
        if not args.api_token or len(args.api_token.strip()) < 16:
            raise SystemExit(
                "Security Refusal: Remote exposure via --allow-remote requires an API token "
                "with at least 16 characters for secure authentication."
            )

    enforce_auth = not is_loopback or bool(args.api_token)
    app = create_app(
        db_path=args.db,
        backend_mode=args.backend,
        api_token=args.api_token,
        enforce_auth=enforce_auth,
    )

    print(f"================================================================")
    print(f"  Sherlock AI Investigation Platform (Milestone 14 Hardened)")
    print(f"  Binding: {args.host}:{args.port} ({'Local Loopback' if is_loopback else 'Remote (Authenticated)'})")
    print(f"  Authentication: {'Enforced (Bearer Token)' if enforce_auth else 'Disabled (Local Loopback Single-Tenant)'}")
    print(f"  Persistence: SQLite ({args.db})")
    print(f"  Extraction Backend: {args.backend}")
    print(f"  Web Interface: http://{args.host}:{args.port}/")
    print(f"  API Documentation: http://{args.host}:{args.port}/docs")
    print(f"================================================================")

    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
