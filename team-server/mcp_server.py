"""MCP stdio adapter: makes the team protocol native tools for DSH agents.

Each machine runs this process with its own TEAM_TOKEN:

    TEAM_URL=https://team.example.com TEAM_TOKEN=<token> python team-server/mcp_server.py

DSH config (profile cordis.patch.yml):

    - insert:
        - id: mcp-team
          name: '@deepseek-ai/dsh-mcp-client'
          config:
            serverName: team
            transport: stdio
            command: C:/path/to/repo/.venv/Scripts/python.exe
            args: ['C:/path/to/repo/team-server/mcp_server.py']
            env:
              TEAM_URL: https://team.example.com
              TEAM_TOKEN: !!js process.env.TEAM_TOKEN

Tools then appear as mcp__team__sync, mcp__team__claim, ... and every call
goes through the same HTTP API telemetry and audit as the CLI.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from mcp.server.mcpserver import MCPServer

BASE = (os.environ.get("TEAM_URL") or "http://127.0.0.1:8765").rstrip("/")
TOKEN = os.environ.get("TEAM_TOKEN") or ""
TIMEOUT = float(os.environ.get("TEAM_TIMEOUT") or 20)

INSTRUCTIONS = (
    "雏雁团队协调服务。每轮开始必须先调用 team_sync 获取未读消息、我的任务与可认领任务；"
    "动手前先 team_claim；交付时 team_request_review 并等 admin 人工签收；"
    "不要绕过协议直接改文件，不要推 main。"
)

server = MCPServer(name="team", instructions=INSTRUCTIONS)


def _http(method: str, path: str, body: dict | None = None, idempotent: bool = False) -> str:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + _token())
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if idempotent:
        import uuid
        req.add_header("Idempotency-Key", str(uuid.uuid4()))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            return raw or "{}"
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        return json.dumps({"ok": False, "http_status": exc.code,
                           "error": json.loads(payload) if payload else {}}, ensure_ascii=False)
    except urllib.error.URLError as exc:
        return json.dumps({"ok": False, "http_status": 0,
                           "error": {"error": "network_error", "message": str(exc.reason)}},
                          ensure_ascii=False)


def _token() -> str:
    return TOKEN


def _q(**params) -> str:
    items = {k: v for k, v in params.items() if v is not None and v != ""}
    return ("?" + urllib.parse.urlencode(items)) if items else ""


@server.tool()
def team_sync(since: int = 0) -> str:
    """获取自 since 以来的事件、未读消息、我的任务、可认领任务和待接收的交接。"""
    return _http("GET", "/api/sync" + _q(since=since))


@server.tool()
def team_list_tasks(status: str = "", mine: bool = False) -> str:
    """列出任务。status 可填 pending/claimed/in_progress/handoff/review/done；mine=true 只看自己的。"""
    query = _q(status=status, mine="me" if mine else None)
    return _http("GET", "/api/tasks" + query)


@server.tool()
def team_get_task(task_id: str) -> str:
    """查看单个任务详情，包括租约与验收命令。"""
    return _http("GET", f"/api/tasks/{task_id}")


@server.tool()
def team_claim(task_id: str, branch: str = "", base_sha: str = "") -> str:
    """认领任务。branch 建议 codex/<task-id>-<slug>；已被认领返回 409，范围冲突返回 423。"""
    return _http("POST", f"/api/tasks/{task_id}/claim",
                 {"branch": branch or None, "base_sha": base_sha or None})


@server.tool()
def team_renew(task_id: str) -> str:
    """续租。租约丢失返回 410，此时必须停止推送并重新同步任务状态。"""
    return _http("POST", f"/api/tasks/{task_id}/heartbeat", {})


@server.tool()
def team_release(task_id: str) -> str:
    """主动释放任务，把它还给待认领池。"""
    return _http("POST", f"/api/tasks/{task_id}/release", {})


@server.tool()
def team_handoff(task_id: str, to_agent: str, acceptance_cmd: str,
                 summary: str = "", open_questions: str = "", branch: str = "") -> str:
    """把任务交接给另一位 Agent。acceptance_cmd 必填，接收方必须跑通才能接受。"""
    return _http("POST", f"/api/tasks/{task_id}/handoff",
                 {"to_agent": to_agent, "acceptance_cmd": acceptance_cmd,
                  "summary": summary, "open_questions": open_questions,
                  "branch": branch or None})


@server.tool()
def team_accept(handoff_id: int, ran: bool = True, output: str = "") -> str:
    """接受交接。ran=true 表示已在本机运行过 acceptance 命令。"""
    return _http("POST", f"/api/handoffs/{handoff_id}/accept",
                 {"ran": ran, "output": output})


@server.tool()
def team_request_review(task_id: str, evidence: str, pr_url: str = "") -> str:
    """送审。evidence 必填：验收命令输出、CI 链接或截图说明。"""
    return _http("POST", f"/api/tasks/{task_id}/request-review",
                 {"evidence": evidence, "pr_url": pr_url})


@server.tool()
def team_complete(task_id: str) -> str:
    """标记完成。只有 admin 人工签收后才会成功，否则返回 428。"""
    return _http("POST", f"/api/tasks/{task_id}/complete", {})


@server.tool()
def team_send(body: str, to_agent: str = "", task_id: str = "", kind: str = "notice") -> str:
    """发消息。to_agent 留空是广播；kind 可用 question/handoff_request/review_request/notice。"""
    return _http("POST", "/api/messages",
                 {"body": body, "to_agent": to_agent or None,
                  "task_id": task_id or None, "kind": kind})


@server.tool()
def team_status() -> str:
    """我是谁：身份、能力标签和最近上线时间。"""
    return _http("GET", "/api/whoami")


@server.tool()
def team_agents() -> str:
    """团队在线状态与各自当前任务。"""
    return _http("GET", "/api/agents")


@server.tool()
def team_activity(limit: int = 20) -> str:
    """最近事件流，用于知道别人在做什么。"""
    return _http("GET", "/api/audit" + _q(limit=limit))


@server.tool()
def team_create_task(title: str, kind: str = "code", scope_paths: str = "",
                     capabilities_required: str = "", acceptance: str = "",
                     goal: str = "", priority: int = 3) -> str:
    """新建任务（Agent 建的会先进入 draft，等 admin 发布）。scope_paths 用逗号分隔。"""
    return _http("POST", "/api/tasks", {
        "title": title, "kind": kind,
        "scope_paths": [p.strip() for p in scope_paths.split(",") if p.strip()],
        "capabilities_required": [c.strip() for c in capabilities_required.split(",") if c.strip()],
        "acceptance": acceptance, "goal": goal, "priority": priority,
    }, idempotent=True)


if __name__ == "__main__":
    if not TOKEN:
        print("[team-mcp] 警告：TEAM_TOKEN 为空，所有调用会返回 401", file=sys.stderr)
    try:  # MCP framing is JSON lines on stdout; keep UTF-8 regardless of Windows locale
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # pragma: no cover
        pass
    server.run("stdio")
