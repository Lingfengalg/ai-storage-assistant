import pytest
from pydantic import ValidationError

from app.demo import demo_scene
from app.geometry import fits, overlaps, validate_layout
from app.models import Placement, Size
from app.planning import plan_scene


def test_demo_is_collision_free():
    scene = demo_scene()
    assert validate_layout(scene, {i.id: i.placement for i in scene.items}) == []


def test_greedy_is_complete_and_preserves_lock():
    scene = demo_scene()
    plan = plan_scene(scene)
    assert plan.status == "FEASIBLE"
    assert plan.placements["books"] == scene.items[0].placement
    assert validate_layout(scene, plan.placements) == []
    assert scene.version == 1
    assert scene.items[1].placement.x == 300  # Planning does not mutate input.


def test_oversize_is_not_silently_dropped():
    scene = demo_scene()
    scene.items[1].size.width = 2000
    scene.items[1].size.depth = 2000
    plan = plan_scene(scene)
    assert plan.status == "NO_SOLUTION_FOUND"
    assert "camera" in plan.unplaced_item_ids
    assert not plan.placements


def test_taken_out_objects_are_not_planned():
    scene = demo_scene()
    scene.items[1].status = "taken_out"
    plan = plan_scene(scene)
    assert "camera" not in plan.placements
    assert plan.status == "FEASIBLE"


def test_touch_is_allowed_but_overlap_is_not():
    a, b = demo_scene().items[:2]
    pa = Placement(shelf_id="lower", x=0, y=0)
    pb = Placement(shelf_id="lower", x=a.size.width, y=0)
    assert not overlaps(a, pa, b, pb)
    pb.x -= 1
    assert overlaps(a, pa, b, pb)
    pb.shelf_id = "upper"
    assert not overlaps(a, pa, b, pb)


def test_rotation_height_and_edges():
    scene = demo_scene()
    shelf = scene.shelves[0]
    item = scene.items[1]
    item.size = Size(width=450, depth=100, height=300)
    place = Placement(shelf_id=shelf.id, x=450, y=0)
    assert fits(item, place, shelf)
    place.x += 1
    assert not fits(item, place, shelf)
    place.x = 0
    place.rotated = True
    assert not fits(item, place, shelf)  # 450 mm depth exceeds 400 mm.
    place.rotated = False
    item.size.height = 301
    assert not fits(item, place, shelf)


def test_disallowed_rotation_and_fixed_movement():
    scene = demo_scene()
    item = scene.items[0]
    item.allow_rotation = False
    place = item.placement.model_copy(update={"rotated": True})
    assert not fits(item, place, scene.shelves[0])
    places = {i.id: i.placement.model_copy() for i in scene.items}
    places[item.id].x = 0
    assert any("锁定" in e for e in validate_layout(scene, places))


@pytest.mark.parametrize("width", [0, -1, 1.5, True])
def test_dimensions_are_positive_integer_mm(width):
    with pytest.raises(ValidationError):
        Size(width=width, depth=100, height=100)


def test_duplicate_ids_rejected():
    data = demo_scene().model_dump()
    data["items"].append(data["items"][0])
    with pytest.raises(ValidationError):
        type(demo_scene()).model_validate(data)


def test_missing_unknown_items_are_invalid():
    scene = demo_scene()
    places = {i.id: i.placement for i in scene.items}
    places["unknown"] = places.pop("camera")
    assert validate_layout(scene, places)
