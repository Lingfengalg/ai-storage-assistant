"""Entry point: `uvicorn app.main:app --host 127.0.0.1 --port 8765` from team-server/."""

from __future__ import annotations

import os
import secrets
import sys

from .api import create_app

DB_PATH = os.environ.get("TEAM_DB", os.path.join(os.path.dirname(__file__), "..", "team.db"))
ADMIN_TOKEN = os.environ.get("TEAM_ADMIN_TOKEN") or ""
if not ADMIN_TOKEN:
    ADMIN_TOKEN = secrets.token_urlsafe(18)
    print(f"[team-server] 未设置 TEAM_ADMIN_TOKEN，临时生成：{ADMIN_TOKEN}", file=sys.stderr)
LEASE_MINUTES = int(os.environ.get("TEAM_LEASE_MINUTES", "90"))

app = create_app(DB_PATH, ADMIN_TOKEN, LEASE_MINUTES)
