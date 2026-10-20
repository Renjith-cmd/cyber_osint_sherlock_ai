"""Vercel serverless entry point for the Sherlock investigation SPA and API."""

import os

os.environ.setdefault("SHERLOCK_DB_PATH", "/tmp/sherlock_investigations.db")

from src.api.app import create_app


app = create_app(
    db_path=os.getenv("SHERLOCK_DB_PATH", "/tmp/sherlock_investigations.db"),
    backend_mode=os.getenv("SHERLOCK_BACKEND_MODE", "rule"),
    disable_auth=True,
)
