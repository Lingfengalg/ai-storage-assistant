"""Provision the five production agents (phase 1, server side).

Run this once on the server after the coordination service is up:

    docker compose exec team-server python provision.py --db /data/team.db --out /data/tokens.json
    docker compose cp team-server:/data/tokens.json ./tokens.json
    # 把每个 token 一对一发给对应组员，然后删除服务器与本地副本

Behaviour:
- creates missing agents; existing agents are left untouched unless --rotate;
- --rotate issues a brand-new token for an existing agent (the old one stops working);
- tokens are written to --out with owner-only permissions and never printed when
  --out is used; keep the file out of the repository.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.service import Store

AGENTS = [
    ("agent-a", "组员A", "感知与几何", ["perception", "geometry"]),
    ("agent-b", "组员B", "收纳规划", ["planning", "solver"]),
    ("agent-c", "组员C", "三维交互", ["frontend", "three"]),
    ("agent-d", "组员D", "库存与集成", ["inventory", "backend"]),
    ("agent-e", "组员E", "文档与写作", ["docs", "writing"]),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="创建/轮换雏雁五人团队的正式 Agent")
    parser.add_argument("--db", default=os.environ.get("TEAM_DB", "team.db"))
    parser.add_argument("--out", default=None, help="把 token 映射写入该文件（推荐）")
    parser.add_argument("--rotate", action="store_true", help="为已存在的 Agent 轮换 token")
    parser.add_argument("--url", default=os.environ.get("TEAM_URL", "https://team.example.com"))
    parser.add_argument("--print-tokens", action="store_true",
                        help="连同 token 一起打印到 stdout（仅在没有 --out 时生效）")
    args = parser.parse_args()

    admin_token = os.environ.get("TEAM_ADMIN_TOKEN", "")
    if not admin_token:
        print("错误：需要设置 TEAM_ADMIN_TOKEN（与服务端一致）", file=sys.stderr)
        return 2

    store = Store(args.db, admin_token)
    admin = {"id": "admin", "is_admin": True, "capabilities": ["*"]}
    result: dict = {"url": args.url, "db": os.path.abspath(args.db), "agents": {}}
    notes: list[str] = []

    for agent_id, person, display, caps in AGENTS:
        with store._conn() as conn:
            exists = conn.execute("SELECT 1 FROM agents WHERE id=?", (agent_id,)).fetchone()
        if exists and not args.rotate:
            result["agents"][agent_id] = {"status": "exists",
                                          "hint": "如需换新 token，加 --rotate"}
            notes.append(f"{agent_id} 已存在，未改动")
            continue
        if exists and args.rotate:
            token = store.rotate_token(admin, agent_id)["token"]
            result["agents"][agent_id] = {"status": "rotated", "token": token}
            notes.append(f"{agent_id} token 已轮换，旧 token 立即失效")
        else:
            token = store.create_agent(admin, agent_id, person, display, caps)["token"]
            result["agents"][agent_id] = {"status": "created", "token": token}
            notes.append(f"{agent_id} 已创建")

    result["notes"] = notes
    with_tokens = {k: v for k, v in result["agents"].items() if "token" in v}

    if args.out:
        out_dir = os.path.dirname(os.path.abspath(args.out))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        try:
            os.chmod(args.out, 0o600)
        except OSError:  # pragma: no cover - Windows
            pass
        print(json.dumps({"ok": True, "out": os.path.abspath(args.out),
                          "accounts": {k: v["status"] for k, v in result["agents"].items()},
                          "notes": notes}, ensure_ascii=False, indent=2))
        print("token 已写入文件；一对一发送后删除服务器与本地副本。", file=sys.stderr)
        return 0

    if with_tokens and not args.print_tokens:
        print("检测到新 token。请加 --out <文件> 保存，或加 --print-tokens 打印。", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
