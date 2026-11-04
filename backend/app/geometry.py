"""Independent axis-aligned geometry checks; touching faces are allowed."""

from .models import Item, Placement, Scene, Shelf


def footprint(item: Item, place: Placement) -> tuple[int, int]:
    return (
        (item.size.depth, item.size.width) if place.rotated else (item.size.width, item.size.depth)
    )


def fits(item: Item, place: Placement, shelf: Shelf) -> bool:
    w, d = footprint(item, place)
    return (
        place.shelf_id == shelf.id
        and place.x >= 0
        and place.y >= 0
        and place.x + w <= shelf.size.width
        and place.y + d <= shelf.size.depth
        and item.size.height <= shelf.size.height
        and (not place.rotated or item.allow_rotation)
    )


def overlaps(a: Item, pa: Placement, b: Item, pb: Placement) -> bool:
    if pa.shelf_id != pb.shelf_id:
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
