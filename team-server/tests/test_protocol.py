"""Phase-0 protocol acceptance tests.

These mirror docs/agent-collaboration.md §10. They drive the same HTTP surface
the five real agents will use; no test calls internal functions directly.
"""

from __future__ import annotations

import os
import sys
import threading
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api import create_app
from app.db import connect
from app.service import Store

ADMIN_TOKEN = "test-admin-token"
LEASE_MINUTES = 90


def hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def env(tmp_path):
    db = str(tmp_path / "team.db")
    store = Store(db, ADMIN_TOKEN, LEASE_MINUTES)
    admin = {"id": "admin", "is_admin": True, "capabilities": ["*"]}
    tokens = {}
    for agent_id, caps in [
        ("agent-a", ["perception", "geometry"]),
        ("agent-b", ["planning"]),
        ("agent-c", ["frontend"]),
        ("agent-d", ["inventory", "backend"]),
        ("agent-e", ["docs"]),
    ]:
        tokens[agent_id] = store.create_agent(admin, agent_id, agent_id, agent_id, caps)["token"]
    app = create_app(db, ADMIN_TOKEN, LEASE_MINUTES)
    client = TestClient(app)
    return {"db": db, "store": store, "client": client, "tokens": tokens,
            "admin": hdr(ADMIN_TOKEN), "h": {k: hdr(v) for k, v in tokens.items()}}


def make_task(env, *, title="任务", scope=("backend/app",), caps=(), kind="code",
              acceptance="pytest -q", publish=True):
    client = env["client"]
    resp = client.post("/api/tasks", headers={**env["admin"], "Idempotency-Key": str(uuid.uuid4())},
                       json={"title": title, "kind": kind, "scope_paths": list(scope),
                             "capabilities_required": list(caps), "acceptance": acceptance,
                             "goal": "测试"})
    assert resp.status_code == 200, resp.text
    task = resp.json()
    if publish and task["status"] == "draft":
        resp = client.post(f"/api/admin/tasks/{task['id']}/publish", headers=env["admin"])
        assert resp.status_code == 200, resp.text
        task = resp.json()
    return task


def test_health_and_identity(env):
    client = env["client"]
    assert client.get("/api/health").status_code == 200
    me = client.get("/api/whoami", headers=env["h"]["agent-a"]).json()
    assert me["id"] == "agent-a"
    assert me["capabilities"] == ["perception", "geometry"]
    assert client.get("/api/whoami", headers=hdr("wrong")).status_code == 401


def test_concurrent_claim_has_exactly_one_winner(env):
    task = make_task(env)
    results: list[int] = []
    lock = threading.Lock()

    def try_claim(agent_id: str) -> None:
        client = TestClient(env["client"].app)
        resp = client.post(f"/api/tasks/{task['id']}/claim", headers=env["h"][agent_id],
                           json={"branch": f"codex/{task['id']}-{agent_id}"})
        with lock:
            results.append(resp.status_code)

    threads = [threading.Thread(target=try_claim, args=(a,)) for a in env["tokens"]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(200) == 1, results
    assert results.count(409) == 4, results

    detail = env["client"].get(f"/api/tasks/{task['id']}", headers=env["admin"]).json()
    assert detail["status"] == "claimed"
    assert detail["claim"] is not None

    claimed = env["client"].get("/api/events?since=0", headers=env["admin"]).json()
    assert sum(1 for e in claimed if e["type"] == "task_claimed") == 1


def test_lease_expiry_allows_takeover_and_blocks_old_owner(env):
    task = make_task(env, scope=("backend/app/planning.py",), caps=())
    client = env["client"]
    assert client.post(f"/api/tasks/{task['id']}/claim", headers=env["h"]["agent-b"],
                       json={"branch": "codex/x"}).status_code == 200

    with connect(env["db"]) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE claims SET lease_until='2000-01-01T00:00:00Z' WHERE task_id=?",
                     (task["id"],))
        conn.execute("COMMIT")

    assert client.post(f"/api/tasks/{task['id']}/claim", headers=env["h"]["agent-a"],
                       json={"branch": "codex/y"}).status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/heartbeat", headers=env["h"]["agent-b"]).status_code == 410

    detail = client.get(f"/api/tasks/{task['id']}", headers=env["admin"]).json()
    assert detail["owner_agent_id"] == "agent-a"
    events = client.get("/api/events?since=0", headers=env["admin"]).json()
    assert any(e["type"] == "lease_expired" and e["agent_id"] == "agent-b" for e in events)


def test_handoff_requires_verification_then_transfers_lease(env):
    task = make_task(env, scope=("backend/app/geometry.py",), caps=("geometry",))
    client = env["client"]
    assert client.post(f"/api/tasks/{task['id']}/claim", headers=env["h"]["agent-a"],
                       json={"branch": "codex/handoff"}).status_code == 200

    resp = client.post(f"/api/tasks/{task['id']}/handoff", headers=env["h"]["agent-a"],
                       json={"to_agent": "agent-b", "acceptance_cmd": "pytest -q",
                             "summary": "几何检查已改", "open_questions": "边界待确认"})
    assert resp.status_code == 200, resp.text
    handoff_id = resp.json()["handoff_id"]

    # The receiver cannot accept before running the acceptance command.
    assert client.post(f"/api/handoffs/{handoff_id}/accept", headers=env["h"]["agent-b"],
                       json={"ran": False}).status_code == 428
    assert client.post(f"/api/tasks/{task['id']}/heartbeat", headers=env["h"]["agent-a"]).status_code == 200

    resp = client.post(f"/api/handoffs/{handoff_id}/accept", headers=env["h"]["agent-b"],
                       json={"ran": True, "output": "passed"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner_agent_id"] == "agent-b"
    assert client.post(f"/api/tasks/{task['id']}/heartbeat", headers=env["h"]["agent-a"]).status_code == 410
    assert client.post(f"/api/tasks/{task['id']}/heartbeat", headers=env["h"]["agent-b"]).status_code == 200

    # The receiver sees the handoff in its inbox through sync.
    inbox = client.get("/api/sync?since=0", headers=env["h"]["agent-b"]).json()
    assert any(m["kind"] == "handoff_request" for m in inbox["unread_messages"])


def test_overlapping_scope_is_rejected_with_423(env):
    first = make_task(env, title="宽范围", scope=("backend/app",), caps=("geometry",))
    second = make_task(env, title="窄范围", scope=("backend/app/planning.py",), caps=("planning",))
    client = env["client"]
    assert client.post(f"/api/tasks/{first['id']}/claim", headers=env["h"]["agent-a"],
                       json={"branch": "codex/a"}).status_code == 200
    resp = client.post(f"/api/tasks/{second['id']}/claim", headers=env["h"]["agent-b"],
                       json={"branch": "codex/b"})
    assert resp.status_code == 423, resp.text
    assert resp.json()["error"] == "scope_conflict"
    assert resp.json()["conflicts"][0]["task_id"] == first["id"]

    assert client.post(f"/api/tasks/{first['id']}/release", headers=env["h"]["agent-a"]).status_code == 200
    assert client.post(f"/api/tasks/{second['id']}/claim", headers=env["h"]["agent-b"],
                       json={"branch": "codex/b"}).status_code == 200


def test_create_task_idempotency(env):
    client = env["client"]
    key = str(uuid.uuid4())
    ids = []
    for _ in range(5):
        resp = client.post("/api/tasks", headers={**env["admin"], "Idempotency-Key": key},
                           json={"title": "幂等测试", "scope_paths": ["backend/app/x.py"]})
        assert resp.status_code == 200, resp.text
        ids.append(resp.json()["id"])
    assert len(set(ids)) == 1

    with connect(env["db"]) as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM tasks WHERE title='幂等测试'").fetchone()["c"]
    assert count == 1

    # Missing key is a protocol error, not a silent duplicate.
    assert client.post("/api/tasks", headers=env["admin"],
                       json={"title": "没有 key"}).status_code == 428


def test_review_requires_human_approval_before_done(env):
    task = make_task(env, scope=("backend/app/inventory.py",), caps=("inventory",))
    client = env["client"]
    assert client.post(f"/api/tasks/{task['id']}/claim", headers=env["h"]["agent-d"],
                       json={"branch": "codex/inv"}).status_code == 200
    resp = client.post(f"/api/tasks/{task['id']}/request-review", headers=env["h"]["agent-d"],
                       json={"evidence": "pytest backend/tests -q: 42 passed", "pr_url": "https://example/pr/7"})
    assert resp.status_code == 200, resp.text
    review_id = resp.json()["review_id"]

    # An agent cannot self-approve and cannot close without human sign-off.
    assert client.post(f"/api/reviews/{review_id}/decide", headers=env["h"]["agent-d"],
                       json={"approved": True}).status_code == 403
    assert client.post(f"/api/tasks/{task['id']}/complete", headers=env["h"]["agent-d"]).status_code == 428

    resp = client.post(f"/api/reviews/{review_id}/decide", headers=env["admin"],
                       json={"approved": True, "note": "验收通过"})
    assert resp.status_code == 200, resp.text
    resp = client.post(f"/api/tasks/{task['id']}/complete", headers=env["h"]["agent-d"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "done"


def test_visibility_other_agents_see_activity(env):
    task = make_task(env, scope=("docs/team-workflow.md",), caps=("docs",), kind="doc")
    client = env["client"]
    assert client.post(f"/api/tasks/{task['id']}/claim", headers=env["h"]["agent-e"],
                       json={"branch": "codex/doc"}).status_code == 200

    # agent-a has done nothing; its sync must still reveal agent-e's claim.
    synced = client.get("/api/sync?since=0", headers=env["h"]["agent-a"]).json()
    assert any(e["type"] == "task_claimed" and e["agent_id"] == "agent-e" for e in synced["events"])
    assert synced["available_tasks"] == []
    mine = client.get("/api/tasks?mine=me", headers=env["h"]["agent-a"]).json()
    assert mine == []


def test_audit_replays_task_timeline(env):
    task = make_task(env, scope=("backend/app/other.py",), caps=("geometry",))
    client = env["client"]
    client.post(f"/api/tasks/{task['id']}/claim", headers=env["h"]["agent-a"], json={"branch": "b"})
    client.post(f"/api/tasks/{task['id']}/heartbeat", headers=env["h"]["agent-a"])
    client.post(f"/api/tasks/{task['id']}/request-review", headers=env["h"]["agent-a"],
                json={"evidence": "ok"})
    events = client.get(f"/api/admin/audit?task_id={task['id']}", headers=env["admin"]).json()
    types = [e["type"] for e in events]
    assert "task_created" in types and "task_claimed" in types and "review_requested" in types


def test_admin_can_rotate_agent_token(env):
    client = env["client"]
    rotated = client.post("/api/admin/agents/agent-a/rotate", headers=env["admin"])
    assert rotated.status_code == 200, rotated.text
    new_token = rotated.json()["token"]

    assert client.get("/api/whoami", headers=env["h"]["agent-a"]).status_code == 401
    assert client.get("/api/whoami", headers=hdr(new_token)).json()["id"] == "agent-a"

    # Agents cannot rotate peers, and admin is rotated through the environment, not the API.
    assert client.post("/api/admin/agents/agent-b/rotate",
                       headers=env["h"]["agent-b"]).status_code == 403
    assert client.post("/api/admin/agents/admin/rotate", headers=env["admin"]).status_code == 400


def test_admin_token_follows_environment(tmp_path):
    db = str(tmp_path / "rotate.db")
    Store(db, "first-admin")
    app = create_app(db, "second-admin")
    client = TestClient(app)
    assert client.get("/api/whoami", headers=hdr("first-admin")).status_code == 401
    who = client.get("/api/whoami", headers=hdr("second-admin")).json()
    assert who["id"] == "admin" and who["is_admin"] is True
