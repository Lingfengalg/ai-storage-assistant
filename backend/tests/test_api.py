from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app


def event(version=1, action="take", item="camera"):
    return {
        "request_id": str(uuid4()),
        "expected_version": version,
        "item_id": item,
        "action": action,
    }


def test_health_and_explicit_perception_stub(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/perception/capabilities").json()["available"] is False
    assert client.get("/api/scene").json()["source"] == "synthetic"


def test_take_return_and_audit(client):
    result = client.post("/api/inventory/events", json=event()).json()
    assert result["version"] == 2
    assert result["items"][1]["status"] == "taken_out"
    result = client.post("/api/inventory/events", json=event(2, "return")).json()
    assert result["version"] == 3
    assert result["items"][1]["status"] == "stored"
    assert len(client.get("/api/inventory/events").json()) == 2


def test_duplicate_request_is_idempotent(client):
    body = event()
    a = client.post("/api/inventory/events", json=body)
    b = client.post("/api/inventory/events", json=body)
    assert a.json() == b.json()
    assert client.get("/api/scene").json()["version"] == 2
    assert len(client.get("/api/inventory/events").json()) == 1
    body["action"] = "return"
    assert client.post("/api/inventory/events", json=body).status_code == 409


def test_versions_lock_and_missing_item(client):
    assert client.post("/api/inventory/events", json=event(item="books")).status_code == 409
    assert client.post("/api/inventory/events", json=event(item="missing")).status_code == 404
    assert client.post("/api/inventory/events", json=event(99)).status_code == 409
    assert client.get("/api/scene").json()["version"] == 1
    assert client.get("/api/inventory/events").json() == []


def test_lock_changes_and_invalidates_plan(client):
    plan = client.post("/api/plans", json={"expected_version": 1}).json()
    response = client.patch(
        "/api/items/camera/movable",
        json={"request_id": str(uuid4()), "expected_version": 1, "movable": False},
    )
    assert response.status_code == 200
    apply = {"request_id": str(uuid4()), "expected_version": 2, "execution_confirmed": True}
    assert client.post(f"/api/plans/{plan['id']}/apply", json=apply).status_code == 409


def test_plan_preview_no_mutation_then_confirm(client):
    before = client.get("/api/scene").json()
    plan = client.post("/api/plans", json={"expected_version": 1}).json()
    assert plan["status"] == "FEASIBLE"
    assert client.get("/api/scene").json() == before
    assert client.get("/api/inventory/events").json() == []
    apply = {"request_id": str(uuid4()), "expected_version": 1, "execution_confirmed": False}
    assert client.post(f"/api/plans/{plan['id']}/apply", json=apply).status_code == 422
    apply["execution_confirmed"] = True
    response = client.post(f"/api/plans/{plan['id']}/apply", json=apply)
    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert client.post(f"/api/plans/{plan['id']}/apply", json=apply).json() == response.json()


def test_invalid_requests(client):
    body = event()
    body["action"] = "delete"
    assert client.post("/api/inventory/events", json=body).status_code == 422
    assert client.post("/api/plans", json={"expected_version": 99}).status_code == 409
    assert client.post("/api/plans", json={"expected_version": 1, "secret": 1}).status_code == 422


def test_failed_return_rolls_back(client):
    client.post("/api/inventory/events", json=event())
    # Simulate a later confirmed layout occupying the absent object's original home.
    store = client.app.state.store

    def occupy(scene):
        scene.items[2].placement = scene.items[1].placement.model_copy()

    store.mutate(str(uuid4()), 2, '{"route":"test-occupy"}', occupy)
    before = client.get("/api/scene").json()
    assert client.post("/api/inventory/events", json=event(3, "return")).status_code == 409
    assert client.get("/api/scene").json() == before
    assert len(client.get("/api/inventory/events").json()) == 2


def test_database_survives_restart(tmp_path):
    path = tmp_path / "persist.sqlite3"
    with TestClient(create_app(path)) as a:
        a.post("/api/inventory/events", json=event())
    with TestClient(create_app(path)) as b:
        assert b.get("/api/scene").json()["version"] == 2
        assert b.get("/api/scene").json()["items"][1]["status"] == "taken_out"


def test_concurrent_version_writes_only_one_succeeds(client):
    bodies = [event(item="camera"), event(item="cables")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda body: client.post("/api/inventory/events", json=body), bodies)
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    assert client.get("/api/scene").json()["version"] == 2


def test_apply_rechecks_fixed_items_against_original_scene(client):
    from app.planning import plan_scene

    store = client.app.state.store
    plan = plan_scene(store.scene())
    plan.placements["books"].x = 0
    store.save_plan(plan)
    body = {"request_id": str(uuid4()), "expected_version": 1, "execution_confirmed": True}
    result = client.post(f"/api/plans/{plan.id}/apply", json=body)
    assert result.status_code == 409
    assert "锁定" in result.json()["detail"]
    assert client.get("/api/scene").json()["version"] == 1
