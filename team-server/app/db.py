"""SQLite storage helpers for the team coordination service.

Design rules (aligned with docs/agent-collaboration.md and CONTRIBUTING.md):
- SQLite WAL, one connection per request, explicit BEGIN IMMEDIATE for writes.
- All timestamps are UTC ISO-8601 (seconds), so text comparison is safe.
- The database holds task metadata and messages only, never photos, item data
  or model artifacts.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id            TEXT PRIMARY KEY,
    person        TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    capabilities  TEXT NOT NULL DEFAULT '[]',
    token_hash    TEXT NOT NULL UNIQUE,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    last_seen_at  TEXT,
    created_at    TEXT NOT NULL,
    revoked_at    TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id                     TEXT PRIMARY KEY,
    seq                    INTEGER NOT NULL UNIQUE,
    title                  TEXT NOT NULL,
    kind                   TEXT NOT NULL DEFAULT 'code',
    goal                   TEXT,
    acceptance             TEXT,
    scope_paths            TEXT NOT NULL DEFAULT '[]',
    capabilities_required  TEXT NOT NULL DEFAULT '[]',
    priority               INTEGER NOT NULL DEFAULT 3,
    status                 TEXT NOT NULL DEFAULT 'draft',
    owner_agent_id         TEXT,
    branch                 TEXT,
    base_sha               TEXT,
    pr_url                 TEXT,
    lease_minutes          INTEGER,
    created_by             TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    revision               INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS claims (
    task_id       TEXT PRIMARY KEY REFERENCES tasks(id),
    agent_id      TEXT NOT NULL,
    lease_until   TEXT NOT NULL,
    heartbeat_at  TEXT NOT NULL,
    branch        TEXT,
    base_sha      TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS handoffs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id          TEXT NOT NULL,
    from_agent       TEXT NOT NULL,
    to_agent         TEXT NOT NULL,
    branch           TEXT,
    acceptance_cmd   TEXT,
    summary          TEXT,
    open_questions   TEXT,
    status           TEXT NOT NULL DEFAULT 'open',
    created_at       TEXT NOT NULL,
    accepted_at      TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id          TEXT NOT NULL,
    requester        TEXT NOT NULL,
    reviewer_agent   TEXT,
    pr_url           TEXT,
    evidence         TEXT,
    verdict          TEXT,
    human_approved   INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    decided_at       TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id    TEXT,
    task_id      TEXT,
    from_agent   TEXT NOT NULL,
    to_agent     TEXT,
    kind         TEXT NOT NULL DEFAULT 'notice',
    body         TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message_reads (
    message_id  INTEGER NOT NULL,
    agent_id    TEXT NOT NULL,
    read_at     TEXT NOT NULL,
    PRIMARY KEY (message_id, agent_id)
);

CREATE TABLE IF NOT EXISTS events (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,
    agent_id    TEXT,
    task_id     TEXT,
    payload     TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency (
    key         TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    status      INTEGER NOT NULL,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_to ON messages(to_agent);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""


def now_dt() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime | None = None) -> str:
    return (dt or now_dt()).strftime("%Y-%m-%dT%H:%M:%SZ")


def lease_until(minutes: int) -> str:
    return iso(now_dt() + timedelta(minutes=minutes))


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


@contextmanager
def immediate(conn: sqlite3.Connection):
    """Write transaction: BEGIN IMMEDIATE serialises writers, so claims are atomic."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
