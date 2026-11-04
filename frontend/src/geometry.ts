import type { Item, Placement, Scene } from "./api/client";

/** Domain x=right,y=back,z=up -> Three.js x=right,y=up,z=back. No scaling of mm. */
export function boxTransform(item: Item, placement: Placement, scene: Scene) {
  const shelf = scene.shelves.find((s) => s.id === placement.shelf_id);
  if (!shelf) throw new Error(`未知层板：${placement.shelf_id}`);
  const w = placement.rotated ? item.size.depth : item.size.width;
  const d = placement.rotated ? item.size.width : item.size.depth;
  return {
    size: [w, item.size.height, d] as [number, number, number],
    center: [
      placement.x + w / 2,
      shelf.elevation + item.size.height / 2,
      placement.y + d / 2,
    ] as [number, number, number],
  };
}

export const categoryColors: Record<string, string> = {
  学习: "#699d89",
  数码: "#7f9bb9",
  生活: "#c6a76f",
};
