import type { Item, Placement, Scene } from "./api/client";

type Shelf = Scene["shelves"][number];

/** Splits one shelf into vertical compartments; mirrors backend geometry.compartment_spans. */
export function compartmentSpans(shelf: Shelf): [number, number][] {
  const usable = shelf.size.width - (shelf.columns - 1) * shelf.divider;
  const base = Math.floor(usable / shelf.columns);
  const remainder = usable - base * shelf.columns;
  const spans: [number, number][] = [];
  let x = 0;
  for (let index = 0; index < shelf.columns; index += 1) {
    const width = base + (index < remainder ? 1 : 0);
    spans.push([x, width]);
    x += width + shelf.divider;
  }
  return spans;
}

export function compartmentOffset(shelf: Shelf, column: number): number {
  const span = compartmentSpans(shelf)[column];
  return span ? span[0] : 0;
}

/** Domain x=right,y=back,z=up -> Three.js x=right,y=up,z=back. No scaling of mm. */
export function boxTransform(item: Item, placement: Placement, scene: Scene) {
  const shelf = scene.shelves.find((s) => s.id === placement.shelf_id);
  if (!shelf) throw new Error(`未知层板：${placement.shelf_id}`);
  const w = placement.rotated ? item.size.depth : item.size.width;
  const d = placement.rotated ? item.size.width : item.size.depth;
  const offset = compartmentOffset(shelf, placement.column);
  return {
    size: [w, item.size.height, d] as [number, number, number],
    center: [
      offset + placement.x + w / 2,
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
