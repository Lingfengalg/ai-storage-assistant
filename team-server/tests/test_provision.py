"""Provisioning tests: the production bootstrap must be idempotent and rotate safely."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.api import create_app


def run_provision(db: str, out: str, *extra: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["TEAM_ADMIN_TOKEN"] = "prov-admin"
    env["TEAM_DB"] = db
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "provision.py", "--db", db, "--out", out, "--url", "https://team.test", *extra],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=60,
    )


def read_tokens(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_provision_creates_agents_and_is_idempotent(tmp_path):
    db = str(tmp_path / "team.db")
    out = str(tmp_path / "tokens.json")
    first = run_provision(db, out)
    assert first.returncode == 0, first.stderr + first.stdout

    data = read_tokens(out)
    assert set(data["agents"]) == {"agent-a", "agent-b", "agent-c", "agent-d", "agent-e"}
    tokens = {aid: entry["token"] for aid, entry in data["agents"].items()}
    assert all(tokens.values())

    app = create_app(db, "prov-admin", 90)
    client = TestClient(app)
    for agent_id, token in tokens.items():
        who = client.get("/api/whoami", headers={"Authorization": f"Bearer {token}"}).json()
        assert who["id"] == agent_id

    second = run_provision(db, out)
    assert second.returncode == 0, second.stderr + second.stdout
    again = read_tokens(out)
    assert all(entry["status"] == "exists" for entry in again["agents"].values())
    assert all("token" not in entry for entry in again["agents"].values())


def test_provision_rotate_invalidates_old_token(tmp_path):
    db = str(tmp_path / "team.db")
    out = str(tmp_path / "tokens.json")
    assert run_provision(db, out).returncode == 0
    old_tokens = {aid: e["token"] for aid, e in read_tokens(out)["agents"].items()}

    rotated_out = str(tmp_path / "tokens-rotated.json")
    rotated = run_provision(db, rotated_out, "--rotate")
    assert rotated.returncode == 0, rotated.stderr + rotated.stdout
    new_tokens = {aid: e["token"] for aid, e in read_tokens(rotated_out)["agents"].items()}
    assert all(new_tokens[aid] != old_tokens[aid] for aid in old_tokens)

    app = create_app(db, "prov-admin", 90)
    client = TestClient(app)
    assert client.get("/api/whoami",
                      headers={"Authorization": f"Bearer {old_tokens['agent-a']}"}).status_code == 401
    assert client.get("/api/whoami",
                      headers={"Authorization": f"Bearer {new_tokens['agent-a']}"}).status_code == 200

