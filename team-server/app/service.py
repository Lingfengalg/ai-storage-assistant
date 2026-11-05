"""Domain logic: tasks, claims with leases, handoffs, reviews, messages, events.

Everything the five agents coordinate on lives here. The REST layer and the MCP
adapter are deliberately thin wrappers so protocol tests exercise the same code
path the production clients use.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from .db import connect, immediate, init_db, iso, lease_until, now_dt

TASK_STATUSES = {"draft", "pending", "claimed", "in_progress", "handoff", "review", "done", "cancelled"}
ACTIVE_STATUSES = {"claimed", "in_progress", "handoff"}
TASK_KINDS = {"code", "doc", "review"}


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


def _err(status: int, code: str, message: str, **extra):
    raise ServiceError(status, code, message, **extra)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value, default):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def normalize_scope(path: str) -> str:
    path = (path or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    path = "/".join(part for part in path.split("/") if part)
    return path


def scopes_overlap(a: str, b: str) -> bool:
    a, b = normalize_scope(a), normalize_scope(b)
    if not a or not b:
        return True  # an empty scope means "touches everything"
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


class Store:
    def __init__(self, db_path: str, admin_token: str, lease_minutes: int = 90):
        self.db_path = db_path
        self.admin_token = admin_token
        self.lease_minutes = int(lease_minutes)
        with self._conn() as conn:
            init_db(conn)
            self._ensure_admin(conn)

    # ------------------------------------------------------------------ infra
    @contextmanager
    def _conn(self):
        conn = connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_admin(self, conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT id, token_hash FROM agents WHERE id='admin'").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO agents(id, person, display_name, capabilities, token_hash,"
                    " is_admin, created_at) VALUES ('admin','管理员','admin','[\"*\"]',?,1,?)",
                    (hash_token(self.admin_token), iso()),
                )
            elif row["token_hash"] != hash_token(self.admin_token):
                # The environment variable is the source of truth: changing it rotates admin.
                conn.execute("UPDATE agents SET token_hash=? WHERE id='admin'",
                             (hash_token(self.admin_token),))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    def _sweep(self, conn: sqlite3.Connection) -> None:
        """Return expired leases to the pool. Must run inside a write transaction."""
        now = iso()
        rows = conn.execute(
            "SELECT c.*, t.status AS task_status FROM claims c JOIN tasks t ON t.id = c.task_id"
            " WHERE c.lease_until < ?",
            (now,),
        ).fetchall()
        for row in rows:
            task_id, agent_id = row["task_id"], row["agent_id"]
            conn.execute("DELETE FROM claims WHERE task_id = ?", (task_id,))
            if row["task_status"] in ACTIVE_STATUSES:
                conn.execute(
                    "UPDATE tasks SET status='pending', owner_agent_id=NULL, updated_at=?,"
                    " revision=revision+1 WHERE id=?",
                    (now, task_id),
                )
            self.emit(conn, "lease_expired", agent_id, task_id,
                      {"previous_owner": agent_id, "branch": row["branch"]})
            self._message(conn, None, task_id, "system", agent_id, "notice",
                          f"任务 {task_id} 的认领已过期，任务已回到待认领池。")

    def emit(self, conn, event_type: str, agent_id: str | None, task_id: str | None,
             payload: dict | None = None) -> None:
        conn.execute(
            "INSERT INTO events(type, agent_id, task_id, payload, created_at) VALUES (?,?,?,?,?)",
            (event_type, agent_id, task_id, dumps(payload or {}), iso()),
        )

    def _message(self, conn, thread_id, task_id, from_agent, to_agent, kind, body):
        conn.execute(
            "INSERT INTO messages(thread_id, task_id, from_agent, to_agent, kind, body, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (thread_id, task_id, from_agent, to_agent, kind, body, iso()),
        )

    # ------------------------------------------------------------------ agents
    def resolve_token(self, token: str) -> dict:
        if not token:
            _err(401, "unauthenticated", "缺少 Bearer Token")
        digest = hash_token(token)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE token_hash=? AND revoked_at IS NULL", (digest,)
            ).fetchone()
            if row is not None:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("UPDATE agents SET last_seen_at=? WHERE id=?", (iso(), row["id"]))
                conn.execute("COMMIT")
                return self.agent_out(row)
            if token == self.admin_token:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("UPDATE agents SET last_seen_at=? WHERE id='admin'", (iso(),))
                conn.execute("COMMIT")
                row = conn.execute("SELECT * FROM agents WHERE id='admin'").fetchone()
                return self.agent_out(row)
        _err(401, "unauthenticated", "无效或已撤销的 Token")

    def create_agent(self, actor: dict, agent_id: str, person: str, display_name: str,
                     capabilities: list[str]) -> dict:
        if not actor.get("is_admin"):
            _err(403, "forbidden", "只有 admin 可以创建 Agent")
        agent_id = (agent_id or "").strip()
        if not agent_id:
            _err(422, "invalid_agent", "agent_id 不能为空")
        token = secrets.token_urlsafe(24)
        with self._conn() as conn, immediate(conn):
            if conn.execute("SELECT 1 FROM agents WHERE id=?", (agent_id,)).fetchone():
                _err(409, "already_exists", f"Agent {agent_id} 已存在")
            conn.execute(
                "INSERT INTO agents(id, person, display_name, capabilities, token_hash,"
                " is_admin, created_at) VALUES (?,?,?,?,?,0,?)",
                (agent_id, person, display_name or agent_id,
                 dumps(capabilities or []), hash_token(token), iso()),
            )
            self.emit(conn, "agent_registered", agent_id, None,
                      {"person": person, "capabilities": capabilities or []})
        return {"id": agent_id, "token": token}

    def agent_out(self, row) -> dict:
        return {
            "id": row["id"],
            "person": row["person"],
            "display_name": row["display_name"],
            "capabilities": loads(row["capabilities"], []),
            "is_admin": bool(row["is_admin"]),
            "last_seen_at": row["last_seen_at"],
        }

    def rotate_token(self, actor: dict, agent_id: str) -> dict:
        """Issue a new token for one agent and invalidate the old one."""
        if not actor.get("is_admin"):
            _err(403, "forbidden", "只有 admin 可以轮换 token")
        if agent_id == "admin":
            _err(400, "invalid_agent", "admin token 来自服务端环境变量，不走接口轮换")
        token = secrets.token_urlsafe(24)
        with self._conn() as conn:
            with immediate(conn):
                row = conn.execute("SELECT id FROM agents WHERE id=? AND revoked_at IS NULL",
                                   (agent_id,)).fetchone()
                if row is None:
                    _err(404, "not_found", f"Agent {agent_id} 不存在或已撤销")
                conn.execute("UPDATE agents SET token_hash=? WHERE id=?",
                             (hash_token(token), agent_id))
                self.emit(conn, "agent_token_rotated", actor["id"], None, {"agent_id": agent_id})
        return {"id": agent_id, "token": token}

    def list_agents(self) -> list[dict]:
        now = now_dt()
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM agents ORDER BY id").fetchall()
            result = []
            for row in rows:
                item = self.agent_out(row)
                last = row["last_seen_at"]
                item["online"] = bool(last and datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ")
                                      .replace(tzinfo=UTC) > now - timedelta(minutes=10))
                result.append(item)
            return result

    # ------------------------------------------------------------------- tasks
    def _next_task_id(self, conn) -> tuple[int, str]:
        seq = conn.execute("SELECT COALESCE(MAX(seq),0)+1 AS s FROM tasks").fetchone()["s"]
        return seq, f"T-{seq:04d}"

    def create_task(self, actor: dict, payload: dict, idempotency_key: str | None) -> dict:
        title = (payload.get("title") or "").strip()
        if not title:
            _err(422, "invalid_task", "title 不能为空")
        kind = payload.get("kind") or "code"
        if kind not in TASK_KINDS:
            _err(422, "invalid_task", f"kind 必须是 {sorted(TASK_KINDS)}")
        scope = [normalize_scope(p) for p in (payload.get("scope_paths") or []) if normalize_scope(p)]
        caps = payload.get("capabilities_required") or []
        priority = int(payload.get("priority") or 3)
        if not 1 <= priority <= 5:
            _err(422, "invalid_task", "priority 需在 1..5")
        lease_minutes = payload.get("lease_minutes") or None
        with self._conn() as conn:
            with immediate(conn):
                self._sweep(conn)
                if idempotency_key:
                    cached = conn.execute(
                        "SELECT status, body FROM idempotency WHERE key=? AND agent_id=?",
                        (idempotency_key, actor["id"]),
                    ).fetchone()
                    if cached is not None:
                        return loads(cached["body"], {})
                seq, task_id = self._next_task_id(conn)
                status = "pending" if actor.get("is_admin") else "draft"
                now = iso()
                conn.execute(
                    "INSERT INTO tasks(id, seq, title, kind, goal, acceptance, scope_paths,"
                    " capabilities_required, priority, status, created_by, lease_minutes,"
                    " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (task_id, seq, title, kind, payload.get("goal") or "",
                     payload.get("acceptance") or "", dumps(scope), dumps(caps),
                     priority, status, actor["id"], lease_minutes, now, now),
                )
                self.emit(conn, "task_created", actor["id"], task_id,
                          {"title": title, "kind": kind, "status": status, "scope_paths": scope})
                body = self._task_by_id(conn, task_id)
                if idempotency_key:
                    conn.execute(
                        "INSERT INTO idempotency(key, agent_id, status, body, created_at)"
                        " VALUES (?,?,?,?,?)",
                        (idempotency_key, actor["id"], 200, dumps(body), iso()),
                    )
        return body

    def publish_task(self, actor: dict, task_id: str) -> dict:
        if not actor.get("is_admin"):
            _err(403, "forbidden", "只有 admin 可以发布任务")
        with self._conn() as conn:
            with immediate(conn):
                row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row is None:
                    _err(404, "not_found", f"任务 {task_id} 不存在")
                if row["status"] != "draft":
                    _err(409, "invalid_state", f"任务当前状态为 {row['status']}，只有 draft 可发布")
                conn.execute("UPDATE tasks SET status='pending', updated_at=?, revision=revision+1"
                             " WHERE id=?", (iso(), task_id))
                self.emit(conn, "task_published", actor["id"], task_id, {"title": row["title"]})
                return self._task_by_id(conn, task_id)

    def _task_by_id(self, conn, task_id: str) -> dict:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            _err(404, "not_found", f"任务 {task_id} 不存在")
        return self.task_out(conn, row)

    def task_out(self, conn, row) -> dict:
        claim = conn.execute("SELECT * FROM claims WHERE task_id=?", (row["id"],)).fetchone()
        return {
            "id": row["id"],
            "seq": row["seq"],
            "title": row["title"],
            "kind": row["kind"],
            "goal": row["goal"],
            "acceptance": row["acceptance"],
            "scope_paths": loads(row["scope_paths"], []),
            "capabilities_required": loads(row["capabilities_required"], []),
            "priority": row["priority"],
            "status": row["status"],
            "owner_agent_id": row["owner_agent_id"],
            "branch": row["branch"],
            "base_sha": row["base_sha"],
            "pr_url": row["pr_url"],
            "lease_minutes": row["lease_minutes"] or self.lease_minutes,
            "claim": None if claim is None else {
                "agent_id": claim["agent_id"],
                "lease_until": claim["lease_until"],
                "heartbeat_at": claim["heartbeat_at"],
                "branch": claim["branch"],
            },
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "revision": row["revision"],
        }

    def list_tasks(self, status: str | None = None, mine: str | None = None,
                   all_tasks: bool = False) -> list[dict]:
        with self._conn() as conn:
            with immediate(conn):
                self._sweep(conn)
                sql, args = "SELECT * FROM tasks", []
                where = []
                if status:
                    where.append("status=?"); args.append(status)
                if mine:
                    where.append("owner_agent_id=?"); args.append(mine)
                if not all_tasks and not status and not mine:
                    where.append("status IN ('pending','claimed','in_progress','handoff','review')")
                if where:
                    sql += " WHERE " + " AND ".join(where)
                sql += " ORDER BY priority, seq"
                return [self.task_out(conn, row) for row in conn.execute(sql, args).fetchall()]

    def get_task(self, task_id: str) -> dict:
        with self._conn() as conn, immediate(conn):
            self._sweep(conn)
            return self._task_by_id(conn, task_id)

    def _check_scope_conflicts(self, conn, task_row) -> list[dict]:
        scope = loads(task_row["scope_paths"], [])
        conflicts = []
        rows = conn.execute(
            "SELECT t.*, c.agent_id AS c_agent FROM tasks t JOIN claims c ON c.task_id=t.id"
            " WHERE t.id != ?", (task_row["id"],),
        ).fetchall()
        for row in rows:
            other = loads(row["scope_paths"], [])
            for a in (scope or [""]):
                for b in (other or [""]):
                    if scopes_overlap(a, b):
                        conflicts.append({"task_id": row["id"], "owner_agent_id": row["c_agent"],
                                          "scope_paths": other})
                        break
                else:
                    continue
                break
        return conflicts

    def claim(self, actor: dict, task_id: str, branch: str | None = None,
              base_sha: str | None = None) -> dict:
        with self._conn() as conn:
            with immediate(conn):
                self._sweep(conn)
                row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row is None:
                    _err(404, "not_found", f"任务 {task_id} 不存在")
                if row["status"] == "draft":
                    _err(409, "not_published", "任务尚未发布，只有 admin 发布后才可认领")
                if row["status"] != "pending":
                    claim = conn.execute("SELECT * FROM claims WHERE task_id=?", (task_id,)).fetchone()
                    _err(409, "already_claimed", "任务已被认领",
                         owner=claim["agent_id"] if claim else row["owner_agent_id"],
                         task_status=row["status"])
                caps = loads(row["capabilities_required"], [])
                mine = actor.get("capabilities") or []
                if not actor.get("is_admin") and caps:
                    missing = [c for c in caps if c != "*" and c not in mine and "*" not in mine]
                    if missing:
                        _err(403, "capability_mismatch", "Agent 能力不满足任务要求",
                             missing=missing, required=caps)
                conflicts = self._check_scope_conflicts(conn, row)
                if conflicts:
                    _err(423, "scope_conflict", "与其他在办任务的修改范围重叠",
                         conflicts=conflicts)
                minutes = row["lease_minutes"] or self.lease_minutes
                now = iso()
                conn.execute("DELETE FROM claims WHERE task_id=?", (task_id,))
                conn.execute(
                    "INSERT INTO claims(task_id, agent_id, lease_until, heartbeat_at, branch,"
                    " base_sha, created_at) VALUES (?,?,?,?,?,?,?)",
                    (task_id, actor["id"], lease_until(minutes), now, branch, base_sha, now),
                )
                conn.execute(
                    "UPDATE tasks SET status='claimed', owner_agent_id=?, branch=?, base_sha=?,"
                    " updated_at=?, revision=revision+1 WHERE id=?",
                    (actor["id"], branch, base_sha, now, task_id),
                )
                self.emit(conn, "task_claimed", actor["id"], task_id,
                          {"branch": branch, "lease_minutes": minutes,
                           "lease_until": lease_until(minutes)})
                return self._task_by_id(conn, task_id)

    def _require_claim(self, conn, task_id: str, actor: dict):
        claim = conn.execute("SELECT * FROM claims WHERE task_id=?", (task_id,)).fetchone()
        if claim is None:
            _err(410, "lease_lost", "你没有该任务的有效租约")
        if claim["agent_id"] != actor["id"] and not actor.get("is_admin"):
            _err(403, "forbidden", "该任务由其他 Agent 持有")
        return claim

    def heartbeat(self, actor: dict, task_id: str) -> dict:
        with self._conn() as conn:
            with immediate(conn):
                row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row is None:
                    _err(404, "not_found", f"任务 {task_id} 不存在")
                claim = conn.execute("SELECT * FROM claims WHERE task_id=?", (task_id,)).fetchone()
                if claim is None or (claim["agent_id"] != actor["id"] and not actor.get("is_admin")):
                    # Losing the lease is 410 regardless of whether the task is now
                    # free or held by someone else: the caller's claim is gone.
                    _err(410, "lease_lost", "你没有该任务的有效租约")
                minutes = row["lease_minutes"] or self.lease_minutes
                now = iso()
                conn.execute("UPDATE claims SET lease_until=?, heartbeat_at=? WHERE task_id=?",
                             (lease_until(minutes), now, task_id))
                conn.execute("UPDATE tasks SET updated_at=?, revision=revision+1 WHERE id=?",
                             (now, task_id))
                return {"task_id": task_id, "lease_until": lease_until(minutes),
                        "heartbeat_at": now}

    def release(self, actor: dict, task_id: str) -> dict:
        with self._conn() as conn, immediate(conn):
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                _err(404, "not_found", f"任务 {task_id} 不存在")
            self._require_claim(conn, task_id, actor)
            conn.execute("DELETE FROM claims WHERE task_id=?", (task_id,))
            conn.execute(
                "UPDATE tasks SET status='pending', owner_agent_id=NULL, updated_at=?,"
                " revision=revision+1 WHERE id=?", (iso(), task_id))
            self.emit(conn, "task_released", actor["id"], task_id, {})
            return self._task_by_id(conn, task_id)

    def handoff(self, actor: dict, task_id: str, payload: dict) -> dict:
        to_agent = (payload.get("to_agent") or "").strip()
        acceptance_cmd = (payload.get("acceptance_cmd") or "").strip()
        if not to_agent or not acceptance_cmd:
            _err(422, "invalid_handoff", "to_agent 与 acceptance_cmd 必填")
        with self._conn() as conn:
            with immediate(conn):
                row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row is None:
                    _err(404, "not_found", f"任务 {task_id} 不存在")
                if row["status"] not in {"claimed", "in_progress"}:
                    _err(409, "invalid_state", "只有 claimed/in_progress 状态可以交接")
                self._require_claim(conn, task_id, actor)
                if not conn.execute("SELECT 1 FROM agents WHERE id=? AND revoked_at IS NULL",
                                    (to_agent,)).fetchone():
                    _err(404, "not_found", f"目标 Agent {to_agent} 不存在")
                if to_agent == actor["id"]:
                    _err(422, "invalid_handoff", "不能交接给自己")
                now = iso()
                cur = conn.execute(
                    "INSERT INTO handoffs(task_id, from_agent, to_agent, branch, acceptance_cmd,"
                    " summary, open_questions, status, created_at) VALUES (?,?,?,?,?,?,?,'open',?)",
                    (task_id, actor["id"], to_agent, payload.get("branch") or row["branch"],
                     acceptance_cmd, payload.get("summary") or "",
                     payload.get("open_questions") or "", now),
                )
                handoff_id = cur.lastrowid
                conn.execute("UPDATE tasks SET status='handoff', updated_at=?, revision=revision+1"
                             " WHERE id=?", (now, task_id))
                self.emit(conn, "task_handoff", actor["id"], task_id,
                          {"handoff_id": handoff_id, "to_agent": to_agent,
                           "acceptance_cmd": acceptance_cmd, "branch": payload.get("branch") or row["branch"]})
                self._message(conn, None, task_id, actor["id"], to_agent, "handoff_request",
                              f"任务 {task_id}「{row['title']}」交接给你，handoff_id={handoff_id}")
                return {"handoff_id": handoff_id, "task": self._task_by_id(conn, task_id)}

    def accept_handoff(self, actor: dict, handoff_id: int, ran: bool) -> dict:
        if not ran:
            _err(428, "verification_required", "接收方必须先运行 acceptance 命令，再 accept")
        with self._conn() as conn:
            with immediate(conn):
                h = conn.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone()
                if h is None:
                    _err(404, "not_found", f"交接 {handoff_id} 不存在")
                if h["status"] != "open":
                    _err(409, "invalid_state", "该交接已被处理")
                if actor["id"] not in (h["to_agent"], "admin") and not actor.get("is_admin"):
                    _err(403, "forbidden", "只有接收方或 admin 可以确认交接")
                task = conn.execute("SELECT * FROM tasks WHERE id=?", (h["task_id"],)).fetchone()
                if task["status"] != "handoff":
                    _err(409, "invalid_state", "任务已不在交接状态")
                minutes = task["lease_minutes"] or self.lease_minutes
                now = iso()
                receiver = actor["id"]
                conn.execute(
                    "INSERT OR REPLACE INTO claims(task_id, agent_id, lease_until, heartbeat_at,"
                    " branch, base_sha, created_at) VALUES (?,?,?,?,?,?,?)",
                    (h["task_id"], receiver, lease_until(minutes), now, h["branch"],
                     task["base_sha"], now),
                )
                conn.execute("UPDATE tasks SET status='in_progress', owner_agent_id=?,"
                             " updated_at=?, revision=revision+1 WHERE id=?",
                             (receiver, now, h["task_id"]))
                conn.execute("UPDATE handoffs SET status='accepted', accepted_at=? WHERE id=?",
                             (now, handoff_id))
                self.emit(conn, "handoff_accepted", receiver, h["task_id"],
                          {"handoff_id": handoff_id, "from_agent": h["from_agent"]})
                self._message(conn, None, h["task_id"], receiver, h["from_agent"], "handoff_accepted",
                              f"任务 {h['task_id']} 的交接已被 {receiver} 接受。")
                return self._task_by_id(conn, h["task_id"])

    def request_review(self, actor: dict, task_id: str, payload: dict) -> dict:
        pr_url = (payload.get("pr_url") or "").strip()
        evidence = (payload.get("evidence") or "").strip()
        if not evidence:
            _err(422, "invalid_review", "evidence 必填：附上验收命令输出或 CI 链接")
        with self._conn() as conn:
            with immediate(conn):
                row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row is None:
                    _err(404, "not_found", f"任务 {task_id} 不存在")
                if row["status"] not in {"claimed", "in_progress"}:
                    _err(409, "invalid_state", "只有 claimed/in_progress 状态可以送审")
                self._require_claim(conn, task_id, actor)
                now = iso()
                cur = conn.execute(
                    "INSERT INTO reviews(task_id, requester, pr_url, evidence, created_at)"
                    " VALUES (?,?,?,?,?)", (task_id, actor["id"], pr_url, evidence, now))
                review_id = cur.lastrowid
                conn.execute("DELETE FROM claims WHERE task_id=?", (task_id,))
                conn.execute("UPDATE tasks SET status='review', pr_url=?, updated_at=?,"
                             " revision=revision+1 WHERE id=?", (pr_url or row["pr_url"], now, task_id))
                self.emit(conn, "review_requested", actor["id"], task_id,
                          {"review_id": review_id, "pr_url": pr_url, "evidence": evidence})
                self._message(conn, None, task_id, actor["id"], "admin", "review_request",
                              f"任务 {task_id}「{row['title']}」送审，review_id={review_id}")
                return {"review_id": review_id, "task": self._task_by_id(conn, task_id)}

    def decide_review(self, actor: dict, review_id: int, approved: bool, note: str = "") -> dict:
        if not actor.get("is_admin"):
            _err(403, "forbidden", "人工签收只有 admin 可以操作")
        with self._conn() as conn:
            with immediate(conn):
                review = conn.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
                if review is None:
                    _err(404, "not_found", f"评审 {review_id} 不存在")
                if review["human_approved"] or review["verdict"]:
                    _err(409, "invalid_state", "该评审已有结论")
                task = conn.execute("SELECT * FROM tasks WHERE id=?", (review["task_id"],)).fetchone()
                minutes = (task["lease_minutes"] or self.lease_minutes) if task else self.lease_minutes
                now = iso()
                verdict = "approved" if approved else "blocked"
                conn.execute("UPDATE reviews SET human_approved=?, verdict=?, decided_at=?"
                             " WHERE id=?", (1 if approved else 0, verdict, now, review_id))
                conn.execute("UPDATE tasks SET status=?, updated_at=?, revision=revision+1"
                             " WHERE id=?",
                             ("review" if approved else "in_progress", now, review["task_id"]))
                # The requester keeps (or regains) the lease either way: an approved
                # task still needs its owner to close it, a blocked one needs fixing.
                conn.execute(
                    "INSERT OR REPLACE INTO claims(task_id, agent_id, lease_until,"
                    " heartbeat_at, branch, created_at) SELECT id, owner_agent_id, ?, ?,"
                    " branch, ? FROM tasks WHERE id=? AND owner_agent_id IS NOT NULL",
                    (lease_until(minutes), now, now, review["task_id"]))
                self.emit(conn, "review_decided", actor["id"], review["task_id"],
                          {"review_id": review_id, "approved": approved, "note": note})
                self._message(conn, None, review["task_id"], "admin", review["requester"],
                              "review_decided",
                              f"任务 {review['task_id']} 评审{'通过' if approved else '未通过'}：{note}")
                return {"review_id": review_id, "task": self._task_by_id(conn, review["task_id"])}

    def complete(self, actor: dict, task_id: str) -> dict:
        with self._conn() as conn:
            with immediate(conn):
                row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row is None:
                    _err(404, "not_found", f"任务 {task_id} 不存在")
                if row["status"] != "review":
                    _err(409, "invalid_state", "只有 review 状态可以完成")
                review = conn.execute(
                    "SELECT * FROM reviews WHERE task_id=? AND human_approved=1"
                    " ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
                if review is None:
                    _err(428, "human_approval_required", "缺少 admin 的人工签收，不能标记完成")
                if actor["id"] != row["owner_agent_id"] and not actor.get("is_admin"):
                    _err(403, "forbidden", "只有任务 owner 或 admin 可以完成")
                now = iso()
                conn.execute("UPDATE tasks SET status='done', updated_at=?, revision=revision+1"
                             " WHERE id=?", (now, task_id))
                conn.execute("DELETE FROM claims WHERE task_id=?", (task_id,))
                self.emit(conn, "task_completed", actor["id"], task_id,
                          {"review_id": review["id"], "pr_url": row["pr_url"]})
                return self._task_by_id(conn, task_id)

    # ------------------------------------------------------------------ messages
    def send_message(self, actor: dict, payload: dict) -> dict:
        body = (payload.get("body") or "").strip()
        if not body:
            _err(422, "invalid_message", "body 不能为空")
        to_agent = payload.get("to_agent") or None
        kind = payload.get("kind") or "notice"
        task_id = payload.get("task_id") or None
        with self._conn() as conn:
            with immediate(conn):
                if to_agent and not conn.execute(
                        "SELECT 1 FROM agents WHERE id=? AND revoked_at IS NULL", (to_agent,)).fetchone():
                    _err(404, "not_found", f"收件人 {to_agent} 不存在")
                cur = conn.execute(
                    "INSERT INTO messages(thread_id, task_id, from_agent, to_agent, kind, body,"
                    " created_at) VALUES (?,?,?,?,?,?,?)",
                    (payload.get("thread_id"), task_id, actor["id"], to_agent, kind, body, iso()))
                msg_id = cur.lastrowid
                self.emit(conn, "message_sent", actor["id"], task_id,
                          {"message_id": msg_id, "to_agent": to_agent, "kind": kind})
                return {"message_id": msg_id}

    # --------------------------------------------------------------------- sync
    def sync(self, actor: dict, since: int | None = None) -> dict:
        with self._conn() as conn:
            with immediate(conn):
                self._sweep(conn)
                cursor = conn.execute("SELECT COALESCE(MAX(seq),0) AS s FROM events").fetchone()["s"]
                since = int(since or 0)
                events = conn.execute(
                    "SELECT * FROM events WHERE seq > ? ORDER BY seq LIMIT 200", (since,)).fetchall()
                unread = conn.execute(
                    "SELECT m.* FROM messages m LEFT JOIN message_reads r"
                    " ON r.message_id=m.id AND r.agent_id=?"
                    " WHERE (m.to_agent=? OR m.to_agent IS NULL) AND m.from_agent != ?"
                    " AND r.message_id IS NULL ORDER BY m.id LIMIT 100",
                    (actor["id"], actor["id"], actor["id"])).fetchall()
                now = iso()
                for msg in unread:
                    conn.execute("INSERT OR IGNORE INTO message_reads(message_id, agent_id, read_at)"
                                 " VALUES (?,?,?)", (msg["id"], actor["id"], now))
                mine = conn.execute(
                    "SELECT * FROM tasks WHERE owner_agent_id=? AND status IN"
                    " ('claimed','in_progress','handoff','review') ORDER BY seq",
                    (actor["id"],)).fetchall()
                available = conn.execute(
                    "SELECT * FROM tasks WHERE status='pending' ORDER BY priority, seq"
                ).fetchall()
                handoffs = conn.execute(
                    "SELECT h.*, t.title FROM handoffs h JOIN tasks t ON t.id=h.task_id"
                    " WHERE h.to_agent=? AND h.status='open' ORDER BY h.id", (actor["id"],)).fetchall()
                return {
                    "cursor": cursor,
                    "agent": self.agent_out(
                        conn.execute("SELECT * FROM agents WHERE id=?", (actor["id"],)).fetchone()),
                    "since": since,
                    "events": [self.event_out(e) for e in events],
                    "unread_messages": [self.message_out(m) for m in unread],
                    "my_tasks": [self.task_out(conn, t) for t in mine],
                    "available_tasks": [self.task_out(conn, t) for t in available],
                    "incoming_handoffs": [dict(h) for h in handoffs],
                    "server_time": iso(),
                }

    def event_out(self, row) -> dict:
        return {
            "seq": row["seq"],
            "type": row["type"],
            "agent_id": row["agent_id"],
            "task_id": row["task_id"],
            "payload": loads(row["payload"], {}),
            "created_at": row["created_at"],
        }

    def message_out(self, row) -> dict:
        return {
            "id": row["id"],
            "thread_id": row["thread_id"],
            "task_id": row["task_id"],
            "from_agent": row["from_agent"],
            "to_agent": row["to_agent"],
            "kind": row["kind"],
            "body": row["body"],
            "created_at": row["created_at"],
        }

    def events_since(self, since: int, limit: int = 200) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM events WHERE seq > ? ORDER BY seq LIMIT ?",
                                (int(since), int(limit))).fetchall()
            return [self.event_out(r) for r in rows]

    def cursor(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COALESCE(MAX(seq),0) AS s FROM events").fetchone()["s"]

    def list_reviews(self, open_only: bool = True) -> list[dict]:
        with self._conn() as conn:
            sql = ("SELECT r.*, t.title, t.owner_agent_id FROM reviews r"
                   " JOIN tasks t ON t.id = r.task_id")
            if open_only:
                sql += " WHERE r.verdict IS NULL"
            sql += " ORDER BY r.id"
            return [dict(row) for row in conn.execute(sql).fetchall()]

    def audit(self, task_id: str | None = None, limit: int = 500) -> list[dict]:
        with self._conn() as conn:
            if task_id:
                rows = conn.execute("SELECT * FROM events WHERE task_id=? ORDER BY seq DESC"
                                    " LIMIT ?", (task_id, limit)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM events ORDER BY seq DESC LIMIT ?",
                                    (limit,)).fetchall()
            return [self.event_out(r) for r in rows]
