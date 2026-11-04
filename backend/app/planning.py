"""Replaceable deterministic baseline, not a claim of optimal packing."""

from uuid import uuid4

from .geometry import fits, footprint, overlaps, validate_layout
from .models import Placement, Plan, Scene


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
            # Cross-products of existing right/back edges are a small candidate set.
            xs, ys = {0}, {0}
            for oid, pos in placed.items():
                if pos.shelf_id == shelf.id:
                    w, d = footprint(items[oid], pos)
                    xs.add(pos.x + w)
                    ys.add(pos.y + d)
            for y in sorted(ys):
                for x in sorted(xs):
                    for rotation in [False, True] if item.allow_rotation else [False]:
                        pos = Placement(shelf_id=shelf.id, x=x, y=y, rotated=rotation)
                        if fits(item, pos, shelf) and not any(
                            overlaps(item, pos, items[oid], p) for oid, p in placed.items()
                        ):
                            chosen = pos
                            break
                    if chosen:
                        break
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
