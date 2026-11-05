"""teamctl — the protocol CLI every DSH agent can call when MCP is unavailable.

Standard library only, so it runs on any of the five machines without new
dependencies. Output is always JSON on stdout so an agent can read it directly.

Environment:
    TEAM_URL    base URL, default http://127.0.0.1:8765
    TEAM_TOKEN  per-agent bearer token
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = (os.environ.get("TEAM_URL") or "http://127.0.0.1:8765").rstrip("/")
TOKEN = os.environ.get("TEAM_TOKEN") or ""
TIMEOUT = float(os.environ.get("TEAM_TIMEOUT") or 20)

try:  # keep UTF-8 JSON readable when stdout is redirected (Windows defaults to cp936)
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):  # pragma: no cover
    pass


class CliError(Exception):
    def __init__(self, status: int, payload):
        self.status = status
        self.payload = payload


def call(method: str, path: str, body: dict | None = None, idempotent: bool = False):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if idempotent:
        req.add_header("Idempotency-Key", str(uuid.uuid4()))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"error": "http_error", "message": raw}
        raise CliError(exc.code, payload) from None
    except urllib.error.URLError as exc:
        raise CliError(0, {"error": "network_error", "message": str(exc.reason)}) from None


def emit(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="teamctl", description="雏雁团队协调协议 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name: str, fn):
        p = sub.add_parser(name)
        fn(p)
        return p

    def p_status(p):
        pass

    def p_tasks(p):
        p.add_argument("--status")
        p.add_argument("--mine", action="store_true")
        p.add_argument("--all", action="store_true")

    def p_task(p):
        p.add_argument("task_id")

    def p_sync(p):
        p.add_argument("--since", type=int, default=0)

    def p_claim(p):
        p.add_argument("task_id")
        p.add_argument("--branch", default=None)
        p.add_argument("--base-sha", default=None)

    def p_task_id(p):
        p.add_argument("task_id")

    def p_handoff(p):
        p.add_argument("task_id")
        p.add_argument("--to", required=True, dest="to_agent")
        p.add_argument("--acceptance", required=True)
        p.add_argument("--summary", default="")
        p.add_argument("--question", default="")
        p.add_argument("--branch", default=None)

    def p_accept(p):
        p.add_argument("handoff_id", type=int)
        p.add_argument("--output", default=None, help="验收命令输出；提供即视为 ran=true")
        p.add_argument("--ran", action="store_true")

    def p_review(p):
        p.add_argument("task_id")
        p.add_argument("--pr", default="")
        p.add_argument("--evidence", required=True)

    def p_decide(p):
        p.add_argument("review_id", type=int)
        p.add_argument("--yes", action="store_true")
        p.add_argument("--no", action="store_true")
        p.add_argument("--note", default="")

    def p_complete(p):
        p.add_argument("task_id")

    def p_send(p):
        p.add_argument("--body", required=True)
        p.add_argument("--to", default=None, dest="to_agent")
        p.add_argument("--task", default=None, dest="task_id")
        p.add_argument("--kind", default="notice")

    def p_agents(p):
        pass

    def p_activity(p):
        p.add_argument("--limit", type=int, default=30)

    def p_create_agent(p):
        p.add_argument("agent_id")
        p.add_argument("--person", default="")
        p.add_argument("--display", default="")
        p.add_argument("--capability", action="append", default=[])

    def p_publish(p):
        p.add_argument("task_id")

    def p_create_task(p):
        p.add_argument("--title", required=True)
        p.add_argument("--kind", default="code")
        p.add_argument("--goal", default="")
        p.add_argument("--acceptance", default="")
        p.add_argument("--scope", action="append", default=[])
        p.add_argument("--capability", action="append", default=[])
        p.add_argument("--priority", type=int, default=3)
        p.add_argument("--lease-minutes", type=int, default=None)

    def p_audit(p):
        p.add_argument("--task", default=None, dest="task_id")
        p.add_argument("--limit", type=int, default=100)

    def p_admin_reviews(p):
        p.add_argument("--all", action="store_true")

    def p_admin_rotate(p):
        p.add_argument("agent_id")

    add("status", p_status)
    add("tasks", p_tasks)
    add("task", p_task)
    add("sync", p_sync)
    add("claim", p_claim)
    add("renew", p_task_id)
    add("release", p_task_id)
    add("handoff", p_handoff)
    add("accept", p_accept)
    add("review", p_review)
    add("decide", p_decide)
    add("complete", p_complete)
    add("send", p_send)
    add("agents", p_agents)
    add("activity", p_activity)
    add("admin-create-agent", p_create_agent)
    add("admin-publish", p_publish)
    add("admin-create-task", p_create_task)
    add("admin-audit", p_audit)
    add("admin-reviews", p_admin_reviews)
    add("admin-rotate", p_admin_rotate)

    args = parser.parse_args(argv)

    try:
        if args.cmd == "status":
            result = call("GET", "/api/whoami")
        elif args.cmd == "tasks":
            query = []
            if args.status:
                query.append("status=" + urllib.parse.quote(args.status))
            if args.mine:
                query.append("mine=me")
            if args.all:
                query.append("all=1")
            result = call("GET", "/api/tasks" + (("?" + "&".join(query)) if query else ""))
        elif args.cmd == "task":
            result = call("GET", f"/api/tasks/{args.task_id}")
        elif args.cmd == "sync":
            result = call("GET", f"/api/sync?since={args.since}")
        elif args.cmd == "claim":
            result = call("POST", f"/api/tasks/{args.task_id}/claim",
                          {"branch": args.branch, "base_sha": args.base_sha})
        elif args.cmd == "renew":
            result = call("POST", f"/api/tasks/{args.task_id}/heartbeat", {})
        elif args.cmd == "release":
            result = call("POST", f"/api/tasks/{args.task_id}/release", {})
        elif args.cmd == "handoff":
            result = call("POST", f"/api/tasks/{args.task_id}/handoff", {
                "to_agent": args.to_agent, "acceptance_cmd": args.acceptance,
                "summary": args.summary, "open_questions": args.question,
                "branch": args.branch,
            })
        elif args.cmd == "accept":
            ran = bool(args.ran or args.output)
            result = call("POST", f"/api/handoffs/{args.handoff_id}/accept",
                          {"ran": ran, "output": args.output or ""})
        elif args.cmd == "review":
            result = call("POST", f"/api/tasks/{args.task_id}/request-review",
                          {"pr_url": args.pr, "evidence": args.evidence})
        elif args.cmd == "decide":
            approved = args.yes and not args.no
            result = call("POST", f"/api/reviews/{args.review_id}/decide",
                          {"approved": approved, "note": args.note})
        elif args.cmd == "complete":
            result = call("POST", f"/api/tasks/{args.task_id}/complete", {})
        elif args.cmd == "send":
            result = call("POST", "/api/messages", {
                "body": args.body, "to_agent": args.to_agent,
                "task_id": args.task_id, "kind": args.kind,
            })
        elif args.cmd == "agents":
            result = call("GET", "/api/agents")
        elif args.cmd == "activity":
            result = call("GET", f"/api/activity?limit={args.limit}")
        elif args.cmd == "admin-create-agent":
            result = call("POST", "/api/admin/agents", {
                "id": args.agent_id, "person": args.person,
                "display_name": args.display, "capabilities": args.capability,
            })
        elif args.cmd == "admin-publish":
            result = call("POST", f"/api/admin/tasks/{args.task_id}/publish", {})
        elif args.cmd == "admin-create-task":
            result = call("POST", "/api/tasks", {
                "title": args.title, "kind": args.kind, "goal": args.goal,
                "acceptance": args.acceptance, "scope_paths": args.scope,
                "capabilities_required": args.capability, "priority": args.priority,
                "lease_minutes": args.lease_minutes,
            }, idempotent=True)
        elif args.cmd == "admin-audit":
            query = f"?limit={args.limit}" + (f"&task_id={urllib.parse.quote(args.task_id)}" if args.task_id else "")
            result = call("GET", "/api/admin/audit" + query)
        elif args.cmd == "admin-reviews":
            result = call("GET", "/api/admin/reviews" + ("?open_only=0" if args.all else ""))
        elif args.cmd == "admin-rotate":
            result = call("POST", f"/api/admin/agents/{args.agent_id}/rotate", {})
        else:  # pragma: no cover - argparse enforces the list
            parser.error("unknown command")
            return 2
    except CliError as exc:
        emit({"ok": False, "http_status": exc.status, "error": exc.payload})
        return 2
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
