"""Small local SQLite store: transactions, optimistic versions and idempotent writes."""

import json
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from .demo import demo_scene
from .geometry import validate_layout
from .models import Plan, Scene


class DomainError(Exception):
    def __init__(self, message: str, status: int = 409):
        self.message = message
        self.status = status


class Store:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS scene (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT);
                CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, body TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    request_id TEXT PRIMARY KEY, signature TEXT NOT NULL,
                    response TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            db.execute(
                "INSERT OR IGNORE INTO scene VALUES (1, ?)", (demo_scene().model_dump_json(),)
            )

    def scene(self) -> Scene:
        with self.connect() as db:
            return Scene.model_validate_json(db.execute("SELECT body FROM scene").fetchone()[0])

    def save_plan(self, plan: Plan):
        with self.connect() as db, db:
            db.execute("INSERT INTO plans VALUES (?, ?)", (plan.id, plan.model_dump_json()))

    def plan(self, plan_id: str) -> Plan:
        with self.connect() as db:
            row = db.execute("SELECT body FROM plans WHERE id=?", (plan_id,)).fetchone()
            if row is None:
                raise DomainError("方案不存在", 404)
            return Plan.model_validate_json(row[0])

    def mutate(
        self,
        request_id: str,
        expected_version: int,
        signature: str,
        change: Callable[[Scene], None],
    ) -> Scene:
        with self.connect() as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM events WHERE request_id=?", (request_id,)
            ).fetchone()
            if previous:
                if previous["signature"] != signature:
                    raise DomainError("同一 request_id 不能用于不同操作")
                return Scene.model_validate_json(previous["response"])
            scene = Scene.model_validate_json(db.execute("SELECT body FROM scene").fetchone()[0])
            if scene.version != expected_version:
                raise DomainError("场景版本已变化，请刷新后重试")
            change(scene)
            errors = validate_layout(
                scene, {i.id: i.placement for i in scene.items if i.status == "stored"}
            )
            if errors:
                raise DomainError("；".join(errors))
            scene.version += 1
            body = scene.model_dump_json()
            db.execute("UPDATE scene SET body=? WHERE id=1", (body,))
            db.execute(
                "INSERT INTO events(request_id,signature,response) VALUES (?,?,?)",
                (request_id, signature, body),
            )
            return scene

    def events(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT request_id,signature,created_at FROM events ORDER BY rowid DESC LIMIT 30"
            ).fetchall()
            return [
                {
                    "request_id": r["request_id"],
                    "operation": json.loads(r["signature"]),
                    "created_at": r["created_at"] + "Z",
                }
                for r in rows
            ]
