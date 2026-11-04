import pytest

from app.geometry import compartment_spans, fits, overlaps, validate_layout
from app.models import Item, Placement, Scene, Shelf, Size
from app.planning import plan_scene


def shelf(
    *,
    width: int = 900,
    depth: int = 400,
    height: int = 300,
    columns: int = 2,
    divider: int = 18,
    elevation: int = 40,
) -> Shelf:
    return Shelf(
        id="shelf",
        name="测试层",
        size=Size(width=width, depth=depth, height=height),
        elevation=elevation,
        columns=columns,
        divider=divider,
    )


def item(
    item_id: str = "a",
    *,
    width: int = 100,
    depth: int = 100,
    height: int = 100,
) -> Item:
    return Item(
        id=item_id,
        name=item_id,
        category="测试",
        size=Size(width=width, depth=depth, height=height),
        placement=Placement(shelf_id="shelf", x=0, y=0),
    )


@pytest.mark.parametrize(
    ("width", "columns", "divider", "expected"),
    [
        (900, 1, 18, [(0, 900)]),
        (900, 2, 18, [(0, 441), (459, 441)]),
        # 883 usable mm: the leftover millimetre belongs to the left compartment.
        (901, 2, 18, [(0, 442), (460, 441)]),
        # 80 usable mm: 27 + 27 + 26, remainder to the left.
        (100, 3, 10, [(0, 27), (37, 27), (74, 26)]),
    ],
)
def test_compartment_spans_cover_usable_width(width, columns, divider, expected):
    spans = compartment_spans(shelf(width=width, columns=columns, divider=divider))
    assert spans == expected
    assert sum(span_width for _, span_width in spans) == width - (columns - 1) * divider


def test_cross_divider_placement_is_rejected():
    tested_shelf = shelf()
    test_item = item()
    inside = Placement(shelf_id="shelf", column=0, x=341, y=0)
    across = Placement(shelf_id="shelf", column=0, x=342, y=0)
    out_of_range = Placement(shelf_id="shelf", column=2, x=0, y=0)
    assert fits(test_item, inside, tested_shelf)  # 341 + 100 == the 441 mm compartment.
    assert not fits(test_item, across, tested_shelf)  # Would cross the vertical divider.
    assert not fits(test_item, out_of_range, tested_shelf)  # Only columns 0 and 1 exist.


def test_same_coordinates_in_different_columns_do_not_overlap():
    a, b = item("a"), item("b")
    pa = Placement(shelf_id="shelf", column=0, x=10, y=10)
    pb = Placement(shelf_id="shelf", column=1, x=10, y=10)
    assert not overlaps(a, pa, b, pb)
    pb.column = 0
    assert overlaps(a, pa, b, pb)
    pb.column = 1
    pb.x = 10
    pa.column = 2
    assert not overlaps(a, pa, b, pb)


def test_planner_keeps_compartments_separate():
    wide = 300
    a = item("a", width=wide, depth=400)
    b = item("b", width=wide, depth=400)
    scene = Scene(
        id="two-columns",
        name="两列柜",
        version=1,
        source="user",
        shelves=[shelf(depth=400, columns=2, divider=18)],
        items=[a, b],
    )
    plan = plan_scene(scene)
    assert plan.status == "FEASIBLE"
    # Two 300 mm items cannot share one 441 mm compartment, so the second uses column 1.
    assert plan.placements["a"].column == 0
    assert plan.placements["b"].column == 1
    assert plan.placements["a"].x == 0
    assert plan.placements["b"].x == 0
    assert validate_layout(scene, plan.placements) == []


def test_structure_endpoint_derives_rows_columns_and_clearance(client):
    response = client.post(
        "/api/scene/structure",
        json={
            "name": "两列两层测试柜",
            "rows": 2,
            "columns": 2,
            "width": 900,
            "depth": 400,
            "height": 900,
            "board": 18,
            "divider": 18,
        },
    )
    assert response.status_code == 200
    scene = response.json()
    assert scene["source"] == "user"
    assert scene["items"] == []
    assert len(scene["shelves"]) == 2
    assert [s["elevation"] for s in scene["shelves"]] == [18, 459]
    for record in scene["shelves"]:
        assert record["columns"] == 2
        assert record["divider"] == 18
        # Inner width 900-36, inner depth 400-18, clear height (900-3*18)//2.
        assert record["size"] == {"width": 864, "depth": 382, "height": 423}
    # The derived scene must itself satisfy the shared contract, not just the response shape.
    Scene.model_validate(scene)


def test_structure_endpoint_rejects_impossible_cabinet(client):
    base = {
        "name": "测试柜",
        "rows": 2,
        "columns": 2,
        "width": 900,
        "depth": 400,
        "height": 900,
        "board": 18,
        "divider": 18,
    }
    low_clearance = {**base, "rows": 3, "height": 300}  # (300 - 72) // 3 == 76 mm.
    assert client.post("/api/scene/structure", json=low_clearance).status_code == 422
    too_narrow = {**base, "width": 20}  # Outer width cannot even hold two 18 mm boards.
    assert client.post("/api/scene/structure", json=too_narrow).status_code == 422
    divider_overflow = {**base, "width": 90, "columns": 4}  # Usable width 54-54 == 0.
    assert client.post("/api/scene/structure", json=divider_overflow).status_code == 422
    invalid_rows = {**base, "rows": 0}
    assert client.post("/api/scene/structure", json=invalid_rows).status_code == 422
