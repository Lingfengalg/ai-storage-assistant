"""Independent axis-aligned geometry checks; touching faces are allowed."""

from .models import Item, Placement, Scene, Shelf


def footprint(item: Item, place: Placement) -> tuple[int, int]:
    return (
        (item.size.depth, item.size.width) if place.rotated else (item.size.width, item.size.depth)
    )


def compartment_spans(shelf: Shelf) -> list[tuple[int, int]]:
    """Return each compartment's (x_offset, width) inside the shelf.

    The usable width is divided with ``divmod``; leftover millimetres go to the
    leftmost compartments so the spans always sum to the usable width.
    """
    usable = shelf.size.width - (shelf.columns - 1) * shelf.divider
    base, remainder = divmod(usable, shelf.columns)
    spans = []
    x = 0
    for index in range(shelf.columns):
        width = base + (1 if index < remainder else 0)
        spans.append((x, width))
        x += width + shelf.divider
    return spans


def fits(item: Item, place: Placement, shelf: Shelf) -> bool:
    if place.shelf_id != shelf.id or not 0 <= place.column < shelf.columns:
        return False
    w, d = footprint(item, place)
    compartment_width = compartment_spans(shelf)[place.column][1]
    return (
        place.x >= 0
        and place.y >= 0
        and place.x + w <= compartment_width
        and place.y + d <= shelf.size.depth
        and item.size.height <= shelf.size.height
        and (not place.rotated or item.allow_rotation)
    )


def overlaps(a: Item, pa: Placement, b: Item, pb: Placement) -> bool:
    # A divider keeps different compartments apart even when their local coordinates coincide.
    if pa.shelf_id != pb.shelf_id or pa.column != pb.column:
        return False
    aw, ad = footprint(a, pa)
    bw, bd = footprint(b, pb)
    return pa.x < pb.x + bw and pb.x < pa.x + aw and pa.y < pb.y + bd and pb.y < pa.y + ad


def validate_layout(scene: Scene, places: dict[str, Placement]) -> list[str]:
    """Verify completeness, fixed items, bounds and collisions, independently of planner."""
    items = {i.id: i for i in scene.items if i.status == "stored"}
    shelves = {s.id: s for s in scene.shelves}
    errors = []
    if set(places) != set(items):
        errors.append("布局必须恰好包含全部在库物品")
    for item_id, place in places.items():
        item = items.get(item_id)
        if item is None:
            continue
        shelf = shelves.get(place.shelf_id)
        if shelf is None or not fits(item, place, shelf):
            errors.append(f"{item.name} 超出层板边界或朝向不允许")
        if not item.movable and place != item.placement:
            errors.append(f"{item.name} 已锁定，不允许移动")
    ids = [i for i in places if i in items]
    for index, a in enumerate(ids):
        for b in ids[index + 1 :]:
            if overlaps(items[a], places[a], items[b], places[b]):
                errors.append(f"{items[a].name} 与 {items[b].name} 重叠")
    return errors
