"""Smoke-test the MCP stdio adapter with raw JSON-RPC (no DSH needed).

Run with the team-server up:
    python tests/mcp_smoke.py
It launches team-server/mcp_server.py as a child process, initializes the
protocol, lists tools, and calls team_status + team_sync.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SCRIPT = os.path.join(ROOT, "mcp_server.py")


def send(proc, payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def read_until(proc, wanted_id: int, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == wanted_id:
            return msg
    raise TimeoutError(f"no response for id={wanted_id}")


def main() -> int:
    env = dict(os.environ)
    proc = subprocess.Popen([PY, SCRIPT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env)
    try:
        versions = ["2025-11-25", "2025-06-18", "2024-11-05"]
        response = None
        for version in versions:
            send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": version, "capabilities": {},
                                   "clientInfo": {"name": "smoke", "version": "0.1"}}})
            response = read_until(proc, 1)
            if "result" in response:
                break
        print("initialize:", json.dumps(response, ensure_ascii=False)[:400])
        if "result" not in response:
            return 1

        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = read_until(proc, 2)
        names = [t["name"] for t in tools["result"]["tools"]]
        print("tools:", ", ".join(sorted(names)))
        assert "team_sync" in names and "team_claim" in names

        send(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "team_status", "arguments": {}}})
        status = read_until(proc, 3)
        text = status["result"]["content"][0]["text"]
        print("team_status:", text[:300])
        assert "agent" in text or "id" in text

        send(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "team_sync", "arguments": {"since": 0}}})
        sync = read_until(proc, 4)
        payload = json.loads(sync["result"]["content"][0]["text"])
        print("team_sync keys:", sorted(payload.keys()))
        print("MCP SMOKE: OK")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        err = proc.stderr.read()
        if err.strip():
            print("stderr:", err[-800:], file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
