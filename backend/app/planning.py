"""Replaceable deterministic baseline, not a claim of optimal packing."""

from uuid import uuid4

from .geometry import fits, footprint, overlaps, validate_layout
from .models import Item, Placement, Plan, Scene, Shelf


def _candidate_in_compartment(
    item: Item,
    shelf: Shelf,
    column: int,
    placed: dict[str, Placement],
    items: dict[str, Item],
) -> Placement | None:
    """First free candidate inside one compartment, keeping the historical scan order."""
    # Cross-products of existing right/back edges are a small candidate set.
    xs, ys = {0}, {0}
    for other_id, pos in placed.items():
        if pos.shelf_id == shelf.id and pos.column == column:
            w, d = footprint(items[other_id], pos)
            xs.add(pos.x + w)
            ys.add(pos.y + d)
    for y in sorted(ys):
        for x in sorted(xs):
            for rotation in [False, True] if item.allow_rotation else [False]:
                pos = Placement(shelf_id=shelf.id, column=column, x=x, y=y, rotated=rotation)
                if fits(item, pos, shelf) and not any(
                    overlaps(item, pos, items[other_id], other)
                    for other_id, other in placed.items()
                ):
                    return pos
    return None


def plan_scene(scene: Scene) -> Plan:
    active = [i for i in scene.items if i.status == "stored"]
    items = {i.id: i for i in active}
    placed = {i.id: i.placement.model_copy() for i in active if not i.movable}
    unplaced = []
    for item in sorted(
        (i for i in active if i.movable), key=lambda i: (-i.size.width * i.size.depth, i.id)
    ):
        chosen = None
        for shelf in scene.shelves:
            # Shelves stay in scene order; within a shelf compartments are filled left to right.
            for column in range(shelf.columns):
                chosen = _candidate_in_compartment(item, shelf, column, placed, items)
                if chosen:
                    break
            if chosen:
                break
        if chosen:
            placed[item.id] = chosen
        else:
            unplaced.append(item.id)
    errors = validate_layout(scene, placed)
    success = not unplaced and not errors
    return Plan(
        id=str(uuid4()),
        input_version=scene.version,
        status="FEASIBLE" if success else "NO_SOLUTION_FOUND",
        placements=placed if success else {},
        unplaced_item_ids=unplaced,
        moved_count=sum(p != items[i].placement for i, p in placed.items()) if success else 0,
        notes=[
            "贪心基线，不保证最优；未验证拿取路径、入口、承重或测量误差。",
            "仅为建议，实际执行并确认后才会更新库存。",
        ]
        + errors,
    )
