import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .geometry import validate_layout
from .models import (
    ApplyRequest,
    InventoryRequest,
    LockRequest,
    Plan,
    Scene,
    Shelf,
    Size,
    StructureRequest,
    VersionedRequest,
)
from .planning import plan_scene
from .store import DomainError, Store


def create_app(db_path: Path | None = None) -> FastAPI:
    store = Store(db_path or Path(os.getenv("STORAGE_DB_PATH", "data/local/storage.sqlite3")))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.initialize()
        yield

    app = FastAPI(title="AI 收纳辅助系统 · 开发 API", version="0.1.0", lifespan=lifespan)
    app.state.store = store

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "local-development"}

    @app.get("/api/scene", response_model=Scene)
    def read_scene():
        return store.scene()

    @app.post("/api/scene/structure", response_model=Scene)
    def build_structure(body: StructureRequest):
        """Derive a multi-column cabinet skeleton; preview only, never written to the store."""
        inner_width = body.width - 2 * body.board
        inner_depth = body.depth - body.board
        net_height = (body.height - (body.rows + 1) * body.board) // body.rows
        if inner_width <= 0 or inner_depth <= 0:
            raise DomainError("外部尺寸不足以容纳板厚", 422)
        if net_height < 100:
            raise DomainError("每层净高不足 100 mm，请增加外高或减少层数", 422)
        if inner_width - (body.columns - 1) * body.divider <= 0:
            raise DomainError("内部宽度不足以容纳竖向隔板", 422)
        shelves = [
            Shelf(
                id=f"row-{index + 1}",
                name=f"第 {index + 1} 层",
                size=Size(width=inner_width, depth=inner_depth, height=net_height),
                elevation=body.board + index * (net_height + body.board),
                columns=body.columns,
                divider=body.divider,
            )
            for index in range(body.rows)
        ]
        return Scene(
            id=f"structure-{body.rows}x{body.columns}-{body.width}x{body.depth}x{body.height}",
            name=body.name,
            version=1,
            source="user",
            shelves=shelves,
            items=[],
        )

    @app.post("/api/plans", response_model=Plan)
    def create_plan(body: VersionedRequest):
        scene = store.scene()
        if body.expected_version != scene.version:
            raise DomainError("场景版本已变化，请刷新后重试")
        plan = plan_scene(scene)
        store.save_plan(plan)
        return plan

    def mutate(body, route: str, change):
        signature = json.dumps({"route": route, **body.model_dump()}, sort_keys=True)
        return store.mutate(body.request_id, body.expected_version, signature, change)

    @app.post("/api/inventory/events", response_model=Scene)
    def inventory_event(body: InventoryRequest):
        def change(scene):
            item = next((i for i in scene.items if i.id == body.item_id), None)
            if item is None:
                raise DomainError("物品不存在", 404)
            if body.action == "take":
                if item.status != "stored" or not item.movable:
                    raise DomainError("物品已取出或已锁定")
                item.status = "taken_out"
            else:
                if item.status != "taken_out":
                    raise DomainError("物品已在库")
                # The saved home may now be occupied. Full layout validation prevents conflicts.
                item.status = "stored"

        return mutate(body, "inventory", change)

    @app.patch("/api/items/{item_id}/movable", response_model=Scene)
    def set_movable(item_id: str, body: LockRequest):
        def change(scene):
            item = next((i for i in scene.items if i.id == item_id), None)
            if item is None:
                raise DomainError("物品不存在", 404)
            if item.status != "stored":
                raise DomainError("取出中的物品不能修改锁定状态")
            item.movable = body.movable

        return mutate(body, f"movable/{item_id}", change)

    @app.post("/api/plans/{plan_id}/apply", response_model=Scene)
    def apply_plan(plan_id: str, body: ApplyRequest):
        plan = store.plan(plan_id)

        def change(scene):
            if plan.input_version != scene.version:
                raise DomainError("方案已过期，请基于当前场景重新规划")
            if plan.status != "FEASIBLE":
                raise DomainError("不能执行未找到可行解的方案")
            # Compare against the original scene before assigning proposed placements.
            # Otherwise a modified locked placement would become its own reference.
            errors = validate_layout(scene, plan.placements)
            if errors:
                raise DomainError("；".join(errors))
            for item in scene.items:
                if item.status == "stored":
                    if item.id not in plan.placements:
                        raise DomainError("方案缺少物品")
                    item.placement = plan.placements[item.id]

        return mutate(body, f"apply/{plan_id}", change)

    @app.get("/api/inventory/events")
    def events():
        return store.events()

    @app.get("/api/perception/capabilities")
    def perception_capabilities():
        return {
            "available": False,
            "provider": None,
            "reason": "视觉模型尚未接入；当前只提供明确标记的合成场景。",
        }

    return app


app = create_app()
