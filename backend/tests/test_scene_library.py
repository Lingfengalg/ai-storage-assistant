import sqlite3
from uuid import uuid4

from app.demo import demo_scene
from app.models import Scene
from app.store import Store

STRUCTURE = {
    "name": "两列两层结构柜",
    "rows": 2,
    "columns": 2,
    "width": 900,
    "depth": 400,
    "height": 900,
    "board": 18,
    "divider": 18,
}


def create_scene(client, **overrides):
    response = client.post("/api/scenes", json={**STRUCTURE, **overrides})
    assert response.status_code == 200, response.text
    return response.json()


def activate(client, scene_id, expected_version=1, request_id=None):
    return client.post(
        "/api/scenes/activate",
        json={
            "scene_id": scene_id,
            "request_id": request_id or str(uuid4()),
            "expected_version": expected_version,
        },
    )


def test_create_scene_copies_items_without_overwriting_active(client):
    before = client.get("/api/scene").json()
    payload = create_scene(client)
    scene = payload["scene"]
    assert payload["skipped_item_ids"] == []
    assert scene["source"] == "user"
    assert len(scene["shelves"]) == 2
    assert {record["columns"] for record in scene["shelves"]} == {2}
    assert len(scene["items"]) == 6
    shelf_ids = {record["id"] for record in scene["shelves"]}
    assert {item["placement"]["shelf_id"] for item in scene["items"]} <= shelf_ids
    Scene.model_validate(scene)

    # The active inventory must stay byte-for-byte unchanged.
    assert client.get("/api/scene").json() == before

    library = client.get("/api/scenes").json()
    assert library["active"] == before
    records = library["library"]
    assert [record["id"] for record in records] == [before["id"], scene["id"]]
    assert records[0]["active"] is True
    assert records[1]["active"] is False
    new_summary = records[1]
    assert new_summary["shelves"] == 2
    assert new_summary["columns"] == 2
    assert new_summary["items"] == 6


def test_create_scene_copies_only_stored_items(client):
    take = client.post(
        "/api/inventory/events",
        json={
            "request_id": str(uuid4()),
            "expected_version": 1,
            "item_id": "camera",
            "action": "take",
        },
    )
    assert take.status_code == 200
    payload = create_scene(client)
    ids = {item["id"] for item in payload["scene"]["items"]}
    assert "camera" not in ids
    assert len(ids) == 5


def test_activate_scene_then_plan_on_new_scene(client):
    created = create_scene(client)["scene"]
    response = activate(client, created["id"])
    assert response.status_code == 200, response.text
    active = response.json()
    assert active["id"] == created["id"]
    assert active["version"] == 2  # Activation bumps the target scene version.
    assert client.get("/api/scene").json() == active

    plan = client.post("/api/plans", json={"expected_version": 2})
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["status"] == "FEASIBLE"
    assert body["input_version"] == 2
    assert set(body["placements"]) == {item["id"] for item in active["items"]}

    library = client.get("/api/scenes").json()
    assert library["active"]["id"] == created["id"]
    assert library["active"]["version"] == 2


def test_activate_rejects_stale_version(client):
    created = create_scene(client)["scene"]
    stale = activate(client, created["id"], expected_version=99)
    assert stale.status_code == 409
    assert "版本已变化" in stale.json()["detail"]
    assert client.get("/api/scene").json()["id"] == "demo-room"


def test_activate_is_idempotent(client):
    created = create_scene(client)["scene"]
    request_id = str(uuid4())
    first = activate(client, created["id"], request_id=request_id)
    second = activate(client, created["id"], request_id=request_id)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["version"] == 2
    events = client.get("/api/inventory/events").json()
    switched = [
        event for event in events if event["operation"].get("action") == "activate_scene"
    ]
    assert len(switched) == 1
    assert switched[0]["operation"]["scene_id"] == created["id"]

    # The same request_id cannot be replayed for a different scene.
    other = create_scene(client, name="另一个结构柜")["scene"]
    conflict = activate(client, other["id"], expected_version=2, request_id=request_id)
    assert conflict.status_code == 409
    assert "request_id" in conflict.json()["detail"]


def test_activate_missing_scene_returns_404(client):
    response = activate(client, "missing-scene")
    assert response.status_code == 404


def test_create_scene_skips_items_that_do_not_fit(client):
    before = client.get("/api/scene").json()
    payload = create_scene(client, rows=1, columns=1, width=300, depth=300, height=400)
    scene = payload["scene"]
    copied_ids = [item["id"] for item in scene["items"]]
    skipped = payload["skipped_item_ids"]
    assert 0 < len(copied_ids) < 6
    assert len(copied_ids) + len(skipped) == 6
    assert not set(copied_ids) & set(skipped)
    assert client.get("/api/scene").json() == before


def test_legacy_preview_endpoint_is_removed(client):
    assert client.post("/api/scene/structure", json=STRUCTURE).status_code == 404


def test_inventory_mutations_target_only_the_active_scene(client):
    created = create_scene(client)["scene"]
    assert activate(client, created["id"]).status_code == 200
    take = client.post(
        "/api/inventory/events",
        json={
            "request_id": str(uuid4()),
            "expected_version": 2,
            "item_id": "camera",
            "action": "take",
        },
    )
    assert take.status_code == 200
    new_active = client.get("/api/scene").json()
    assert next(item for item in new_active["items"] if item["id"] == "camera")[
        "status"
    ] == "taken_out"

    back = activate(client, "demo-room", expected_version=3)
    assert back.status_code == 200
    demo = client.get("/api/scene").json()
    assert demo["id"] == "demo-room"
    assert next(item for item in demo["items"] if item["id"] == "camera")[
        "status"
    ] == "stored"


def test_initialize_migrates_legacy_scene_table(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    legacy = demo_scene()
    legacy_body = legacy.model_dump_json()
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE scene (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT)")
        db.execute("INSERT INTO scene VALUES (1, ?)", (legacy_body,))

    store = Store(path)
    store.initialize()
    assert store.scene() == legacy
    with store.connect() as db:
        rows = db.execute("SELECT id, active FROM scenes").fetchall()
        assert [(row["id"], row["active"]) for row in rows] == [(legacy.id, 1)]
    # The legacy table is read-only history: a mutation touches only the active library row.
    store.mutate(str(uuid4()), 1, '{"route":"test-migration"}', lambda scene: None)
    with store.connect() as db:
        assert db.execute("SELECT body FROM scene WHERE id=1").fetchone()["body"] == legacy_body
        assert db.execute("SELECT active FROM scenes WHERE id=?", (legacy.id,)).fetchone()[
            "active"
        ] == 1


def test_initialize_seeds_fresh_database_into_scenes_table(tmp_path):
    store = Store(tmp_path / "fresh.sqlite3")
    store.initialize()
    store.initialize()  # Idempotent: a restart must not duplicate the seed scene.
    with store.connect() as db:
        rows = db.execute("SELECT id, active FROM scenes").fetchall()
        assert [(row["id"], row["active"]) for row in rows] == [("demo-room", 1)]
        assert db.execute("SELECT COUNT(*) FROM scene").fetchone()[0] == 0
    assert store.scene().id == "demo-room"
