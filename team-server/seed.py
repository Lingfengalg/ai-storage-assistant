"""Seed the coordination database for phase-0 rehearsal (local only).

Creates the admin agent, five team agents with random tokens, and one task per
rehearsal scope under .work/rehearsal/. Prints a JSON token map that the Lead
captures and hands to the five rehearsal agents.

Usage (from team-server/):
    python seed.py --out ..\\.work\\team-tokens.json
Then pipe the value of TEAM_ADMIN_TOKEN from that file to the server process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db import iso
from app.service import Store

PEOPLE = [
    ("agent-a", "组员A", "感知与几何", ["perception", "geometry"]),
    ("agent-b", "组员B", "规划", ["planning", "constraint"]),
    ("agent-c", "组员C", "三维交互", ["frontend", "three"]),
    ("agent-d", "组员D", "库存与集成", ["inventory", "backend"]),
    ("agent-e", "组员E", "文档与写作", ["docs", "writing"]),
]

TASKS = [
    ("T-BOOT-1", "记录当前场景的边界条件", "code",
     ".work/rehearsal/boundary.md", ["geometry"],
     "python -c \"import pathlib,sys; sys.exit(0 if pathlib.Path('.work/rehearsal/boundary.md').exists() else 1)\""),
    ("T-BOOT-2", "编写布局约束清单", "doc",
     ".work/rehearsal/constraints.md", ["planning"],
     "python -c \"import pathlib,sys; sys.exit(0 if pathlib.Path('.work/rehearsal/constraints.md').exists() else 1)\""),
    ("T-BOOT-3", "整理三维渲染检查点", "code",
     ".work/rehearsal/render-check.md", ["frontend"],
     "python -c \"import pathlib,sys; sys.exit(0 if pathlib.Path('.work/rehearsal/render-check.md').exists() else 1)\""),
    ("T-BOOT-4", "库存事务失败案例清单", "doc",
     ".work/rehearsal/inventory-cases.md", ["inventory"],
     "python -c \"import pathlib,sys; sys.exit(0 if pathlib.Path('.work/rehearsal/inventory-cases.md').exists() else 1)\""),
    ("T-BOOT-5", "协作机制使用说明草稿", "doc",
     ".work/rehearsal/team-usage.md", ["docs"],
     "python -c \"import pathlib,sys; sys.exit(0 if pathlib.Path('.work/rehearsal/team-usage.md').exists() else 1)\""),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.environ.get("TEAM_DB", "team.db"))
    parser.add_argument("--out", default=None, help="write token map JSON here")
    parser.add_argument("--no-tasks", action="store_true")
    args = parser.parse_args()

    admin_token = os.environ.get("TEAM_ADMIN_TOKEN") or secrets.token_urlsafe(18)
    store = Store(args.db, admin_token)
    admin = {"id": "admin", "is_admin": True, "capabilities": ["*"]}

    tokens: dict[str, str] = {}
    with store._conn() as conn:
        for agent_id, person, display, caps in PEOPLE:
            row = conn.execute("SELECT id FROM agents WHERE id=?", (agent_id,)).fetchone()
            if row is not None:
                print(f"[seed] {agent_id} 已存在，跳过", file=sys.stderr)
                continue
            token = secrets.token_urlsafe(18)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO agents(id, person, display_name, capabilities, token_hash,"
                " is_admin, created_at) VALUES (?,?,?,?,?,0,?)",
                (agent_id, person, display, json.dumps(caps), hashlib.sha256(token.encode()).hexdigest(),
                 iso()),
            )
            conn.execute("COMMIT")
            tokens[agent_id] = token

    created_tasks = []
    if not args.no_tasks:
        for task_id, title, kind, scope, caps, acceptance in TASKS:
            with store._conn() as conn:
                row = conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row:
                continue
            task = store.create_task(admin, {
                "title": title, "kind": kind, "scope_paths": [scope],
                "capabilities_required": caps, "acceptance": acceptance,
                "goal": f"phase-0 演练任务：{title}",
            }, idempotency_key=f"seed:{task_id}")
            if task["status"] == "draft":
                store.publish_task(admin, task["id"])
            created_tasks.append(task["id"])

    result = {
        "url": os.environ.get("TEAM_URL", "http://127.0.0.1:8765"),
        "admin_token": admin_token,
        "agents": tokens,
        "created_tasks": created_tasks,
        "db": os.path.abspath(args.db),
    }
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
