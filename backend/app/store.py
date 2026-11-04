"""Small local SQLite store: scene library, transactions, optimistic versions, idempotent writes."""

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
                CREATE TABLE IF NOT EXISTS scenes (
                    id TEXT PRIMARY KEY,
                    body TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE UNIQUE INDEX IF NOT EXISTS scenes_single_active
                    ON scenes(active) WHERE active = 1;
                CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, body TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    request_id TEXT PRIMARY KEY, signature TEXT NOT NULL,
                    response TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # One-time upgrade from the legacy single-scene table. It stays read-only history.
            if db.execute("SELECT COUNT(*) FROM scenes").fetchone()[0] == 0:
                legacy = db.execute("SELECT body FROM scene WHERE id=1").fetchone()
                scene = (
                    Scene.model_validate_json(legacy["body"])
                    if legacy is not None and legacy["body"]
                    else demo_scene()
                )
                db.execute(
                    "INSERT INTO scenes(id, body, active) VALUES (?, ?, 1)",
                    (scene.id, scene.model_dump_json()),
                )

    def scene(self) -> Scene:
        with self.connect() as db:
            row = db.execute("SELECT body FROM scenes WHERE active = 1").fetchone()
        if row is None:
            raise DomainError("场景库中没有活动场景，请检查本地数据库")
        return Scene.model_validate_json(row["body"])

    def list_scenes(self) -> list[Scene]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT body FROM scenes ORDER BY active DESC, created_at ASC, rowid ASC"
            ).fetchall()
        return [Scene.model_validate_json(row["body"]) for row in rows]

    def create_scene(self, scene: Scene):
        with self.connect() as db, db:
            db.execute(
                "INSERT INTO scenes(id, body, active) VALUES (?, ?, 0)",
                (scene.id, scene.model_dump_json()),
            )

    def activate_scene(self, scene_id: str, request_id: str, expected_version: int) -> Scene:
        signature = json.dumps(
            {
                "action": "activate_scene",
                "scene_id": scene_id,
                "expected_version": expected_version,
            },
            sort_keys=True,
        )
        with self.connect() as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM events WHERE request_id=?", (request_id,)
            ).fetchone()
            if previous:
                if previous["signature"] != signature:
                    raise DomainError("同一 request_id 不能用于不同操作")
                return Scene.model_validate_json(previous["response"])
            active_row = db.execute("SELECT body FROM scenes WHERE active = 1").fetchone()
            if active_row is None:
                raise DomainError("场景库中没有活动场景，请检查本地数据库")
            active = Scene.model_validate_json(active_row["body"])
            if active.version != expected_version:
                raise DomainError("场景版本已变化，请刷新后重试")
            target_row = db.execute("SELECT body FROM scenes WHERE id=?", (scene_id,)).fetchone()
            if target_row is None:
                raise DomainError("场景不存在", 404)
            target = Scene.model_validate_json(target_row["body"])
            target.version += 1
            body = target.model_dump_json()
            db.execute("UPDATE scenes SET active=0 WHERE active=1")
            db.execute("UPDATE scenes SET active=1, body=? WHERE id=?", (body, scene_id))
            db.execute(
                "INSERT INTO events(request_id,signature,response) VALUES (?,?,?)",
                (request_id, signature, body),
            )
            return target

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
            row = db.execute("SELECT body FROM scenes WHERE active = 1").fetchone()
            if row is None:
                raise DomainError("场景库中没有活动场景，请检查本地数据库")
            scene = Scene.model_validate_json(row["body"])
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
            db.execute("UPDATE scenes SET body=? WHERE id=? AND active=1", (body, scene.id))
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
