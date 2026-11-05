"""FastAPI surface: REST for clients and a tiny live dashboard for humans."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .dashboard import DASHBOARD_HTML
from .schemas import (
    AcceptHandoffRequest,
    AgentCreate,
    ClaimRequest,
    DecideReviewRequest,
    HandoffRequest,
    MessageCreate,
    ReviewRequest,
    TaskCreate,
)
from .service import ServiceError, Store


def _bearer(authorization: str | None) -> str:
    if not authorization:
        return ""
    parts = authorization.split(" ", 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else authorization.strip()


def create_app(db_path: str, admin_token: str, lease_minutes: int = 90) -> FastAPI:
    app = FastAPI(title="雏雁团队协调服务", version="0.1.0")
    store = Store(db_path, admin_token, lease_minutes)
    app.state.store = store
    app.state.admin_token = admin_token

    @app.exception_handler(ServiceError)
    async def _service_error(_request: Request, exc: ServiceError):
        payload = {"error": exc.code, "message": exc.message, **exc.extra}
        return JSONResponse(status_code=exc.status, content=payload)

    def actor(request: Request, authorization: str | None = Header(default=None)) -> dict:
        token = _bearer(authorization)
        return request.app.state.store.resolve_token(token)

    # ------------------------------------------------------------------- health
    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "team-server", "time": store.cursor()}

    @app.get("/api/whoami")
    def whoami(me: dict = Depends(actor)):
        return me

    # -------------------------------------------------------------------- tasks
    @app.get("/api/tasks")
    def list_tasks(request: Request, status: str | None = None, mine: str | None = None,
                   all: bool = False, me: dict = Depends(actor)):
        if mine == "me":
            mine = me["id"]
        return request.app.state.store.list_tasks(status=status, mine=mine, all_tasks=all)

    @app.get("/api/tasks/{task_id}")
    def get_task(request: Request, task_id: str, me: dict = Depends(actor)):
        return request.app.state.store.get_task(task_id)

    @app.post("/api/tasks")
    def create_task(request: Request, payload: TaskCreate, me: dict = Depends(actor),
                    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        if not idempotency_key:
            raise ServiceError(428, "idempotency_key_required",
                               "创建任务必须带 Idempotency-Key，避免超时重试产生重复任务")
        return request.app.state.store.create_task(me, payload.model_dump(), idempotency_key)

    @app.post("/api/admin/tasks/{task_id}/publish")
    def publish_task(request: Request, task_id: str, me: dict = Depends(actor)):
        return request.app.state.store.publish_task(me, task_id)

    @app.post("/api/tasks/{task_id}/claim")
    def claim(request: Request, task_id: str, payload: ClaimRequest, me: dict = Depends(actor)):
        return request.app.state.store.claim(me, task_id, payload.branch, payload.base_sha)

    @app.post("/api/tasks/{task_id}/heartbeat")
    def heartbeat(request: Request, task_id: str, me: dict = Depends(actor)):
        return request.app.state.store.heartbeat(me, task_id)

    @app.post("/api/tasks/{task_id}/release")
    def release(request: Request, task_id: str, me: dict = Depends(actor)):
        return request.app.state.store.release(me, task_id)

    @app.post("/api/tasks/{task_id}/handoff")
    def handoff(request: Request, task_id: str, payload: HandoffRequest, me: dict = Depends(actor)):
        return request.app.state.store.handoff(me, task_id, payload.model_dump())

    @app.post("/api/handoffs/{handoff_id}/accept")
    def accept_handoff(request: Request, handoff_id: int, payload: AcceptHandoffRequest,
                       me: dict = Depends(actor)):
        return request.app.state.store.accept_handoff(me, handoff_id, payload.ran)

    @app.post("/api/tasks/{task_id}/request-review")
    def request_review(request: Request, task_id: str, payload: ReviewRequest,
                       me: dict = Depends(actor)):
        return request.app.state.store.request_review(me, task_id, payload.model_dump())

    @app.post("/api/reviews/{review_id}/decide")
    def decide_review(request: Request, review_id: int, payload: DecideReviewRequest,
                      me: dict = Depends(actor)):
        return request.app.state.store.decide_review(me, review_id, payload.approved, payload.note)

    @app.post("/api/tasks/{task_id}/complete")
    def complete(request: Request, task_id: str, me: dict = Depends(actor)):
        return request.app.state.store.complete(me, task_id)

    # ----------------------------------------------------------------- messages
    @app.post("/api/messages")
    def send_message(request: Request, payload: MessageCreate, me: dict = Depends(actor)):
        return request.app.state.store.send_message(me, payload.model_dump())

    # --------------------------------------------------------------------- sync
    @app.get("/api/sync")
    def sync(request: Request, since: int = 0, me: dict = Depends(actor)):
        return request.app.state.store.sync(me, since)

    @app.get("/api/agents")
    def agents(request: Request, me: dict = Depends(actor)):
        return request.app.state.store.list_agents()

    @app.get("/api/activity")
    def activity(request: Request, limit: int = 50, me: dict = Depends(actor)):
        return request.app.state.store.audit(None, limit)

    # -------------------------------------------------------------------- admin
    @app.post("/api/admin/agents")
    def create_agent(request: Request, payload: AgentCreate, me: dict = Depends(actor)):
        return request.app.state.store.create_agent(me, payload.id, payload.person,
                                                    payload.display_name, payload.capabilities)

    @app.post("/api/admin/agents/{agent_id}/rotate")
    def rotate_agent_token(request: Request, agent_id: str, me: dict = Depends(actor)):
        return request.app.state.store.rotate_token(me, agent_id)

    @app.get("/api/admin/reviews")
    def list_reviews(request: Request, open_only: bool = True, me: dict = Depends(actor)):
        if not me.get("is_admin"):
            raise ServiceError(403, "forbidden", "只有 admin 可以查看评审")
        return request.app.state.store.list_reviews(open_only)

    @app.get("/api/admin/audit")
    def audit(request: Request, task_id: str | None = None, limit: int = 200,
              me: dict = Depends(actor)):
        if not me.get("is_admin"):
            raise ServiceError(403, "forbidden", "只有 admin 可以查看审计")
        return request.app.state.store.audit(task_id, limit)

    # -------------------------------------------------------------------- events
    @app.get("/api/events")
    def events(request: Request, since: int = 0, limit: int = 200, me: dict = Depends(actor)):
        return request.app.state.store.events_since(since, limit)

    @app.get("/api/events/stream")
    async def events_stream(request: Request, since: int = 0,
                            token: str = Query(default=""),
                            authorization: str | None = Header(default=None)):
        bearer = _bearer(authorization) or token
        request.app.state.store.resolve_token(bearer)  # 401 before streaming starts

        async def gen() -> AsyncIterator[str]:
            last = since
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                chunk = await asyncio.to_thread(request.app.state.store.events_since, last, 100)
                for event in chunk:
                    last = event["seq"]
                    yield (f"id: {last}\nevent: {event['type']}\n"
                           f"data: {json.dumps(event, ensure_ascii=False)}\n\n")
                yield ": keepalive\n\n"
                await asyncio.sleep(1.0)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------------- board
    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        return DASHBOARD_HTML

    return app
