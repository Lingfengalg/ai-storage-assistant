"""Per-machine health check for the team protocol (phase 1).

Run on each of the five machines after setting TEAM_URL / TEAM_TOKEN:

    python tools/team_doctor.py
    python tools/team_doctor.py --print-mcp-config C:\\path\\to\\repo

Checks: env vars, HTTPS reachability, token identity, task board visibility,
inbox sync, and whether the MCP SDK is importable for the local adapter.
Exit code 0 only when every hard check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):  # pragma: no cover
    pass

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def call(base: str, token: str, path: str) -> tuple[int, dict | str]:
    req = urllib.request.Request(base + path, method="GET")
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, body
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)


def main() -> int:
    parser = argparse.ArgumentParser(description="雏雁团队协议本机体检")
    parser.add_argument("--url", default=os.environ.get("TEAM_URL", ""))
    parser.add_argument("--token", default=os.environ.get("TEAM_TOKEN", ""))
    parser.add_argument("--print-mcp-config", default=None, metavar="REPO_PATH",
                        help="打印 DSH MCP 配置片段（不含 token）")
    args = parser.parse_args()

    if args.print_mcp_config:
        repo = args.print_mcp_config.rstrip("\\/")
        print(f"""- insert:
    - id: mcp-team
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: team
        transport: stdio
        command: {repo}\\.venv\\Scripts\\python.exe
        args: ['{repo}\\team-server\\mcp_server.py']
        env:
          TEAM_URL: {args.url or 'https://team.example.com'}
          TEAM_TOKEN: !!js process.env.TEAM_TOKEN
""")
        return 0

    base = args.url.rstrip("/")
    token = args.token
    results: list[tuple[str, str, str]] = []

    def check(kind: str, name: str, detail: str) -> None:
        results.append((kind, name, detail))

    if not base:
        check(FAIL, "TEAM_URL", "未设置：export TEAM_URL=https://team.example.com")
    if not token:
        check(FAIL, "TEAM_TOKEN", "未设置：向 admin 索要自己的 token")
    if not base or not token:
        for kind, name, detail in results:
            print(f"[{kind}] {name}: {detail}")
        return 1

    started = time.time()
    status, health = call(base, token, "/api/health")
    elapsed = int((time.time() - started) * 1000)
    if status == 200 and isinstance(health, dict) and health.get("ok"):
        check(PASS, "health", f"200 OK, {elapsed} ms")
    else:
        check(FAIL, "health", f"{status} {health}")

    status, who = call(base, token, "/api/whoami")
    if status == 200 and isinstance(who, dict):
        caps = ", ".join(who.get("capabilities") or [])
        kind = PASS
        detail = f"{who.get('id')}（{who.get('display_name')}）能力: {caps or '无'}"
        if not caps:
            kind, detail = WARN, "该 Agent 没有能力标签，可能认领不到任务"
        check(kind, "identity", detail)
    else:
        check(FAIL, "identity", f"HTTP {status}: {who}")

    status, tasks = call(base, token, "/api/tasks?all=1")
    if status == 200 and isinstance(tasks, list):
        counts: dict[str, int] = {}
        for task in tasks:
            counts[task["status"]] = counts.get(task["status"], 0) + 1
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "空"
        check(PASS, "tasks", f"{len(tasks)} 个（{summary}）")
    else:
        check(FAIL, "tasks", f"HTTP {status}: {tasks}")

    status, sync = call(base, token, "/api/sync?since=0")
    if status == 200 and isinstance(sync, dict):
        check(PASS, "sync", f"未读 {len(sync.get('unread_messages') or [])}，"
                            f"我的任务 {len(sync.get('my_tasks') or [])}，"
                            f"可认领 {len(sync.get('available_tasks') or [])}")
    else:
        check(FAIL, "sync", f"HTTP {status}: {sync}")

    try:
        import mcp  # noqa: F401
        check(PASS, "mcp-sdk", "已安装，可用 stdio 适配器")
    except ImportError:
        check(WARN, "mcp-sdk", "未安装：pip install -r team-server/requirements-mcp.txt，"
                               "或先用 tools/teamctl.py 兜底")

    for kind, name, detail in results:
        print(f"[{kind}] {name}: {detail}")

    hard_failures = [r for r in results if r[0] == FAIL]
    print(json.dumps({"ok": not hard_failures,
                      "url": base,
                      "checks": [{"level": k, "name": n, "detail": d} for k, n, d in results]},
                     ensure_ascii=False))
    return 0 if not hard_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
