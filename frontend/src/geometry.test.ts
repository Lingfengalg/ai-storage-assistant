import { describe, expect, it } from "vitest";
import { boxTransform } from "./geometry";
import type { Item, Scene } from "./api/client";

const item: Item = {
  id: "test",
  name: "test",
  category: "学习",
  size: { width: 100, depth: 200, height: 300 },
  placement: { shelf_id: "lower", x: 20, y: 30, rotated: false },
  movable: true,
  allow_rotation: true,
  status: "stored",
  measurement_source: "synthetic",
};
const scene: Scene = {
  id: "test",
  name: "test",
  version: 1,
  unit: "mm",
  source: "synthetic",
  items: [item],
  shelves: [
    {
      id: "lower",
      name: "lower",
      elevation: 40,
      size: { width: 900, depth: 400, height: 350 },
    },
  ],
};
describe("domain millimetres to Three.js coordinates", () => {
  it("maps depth to z and height to y without unit loss", () => {
    expect(boxTransform(item, item.placement, scene)).toEqual({
      size: [100, 300, 200],
      center: [70, 190, 130],
    });
  });
  it("rotates footprint but not height", () => {
    expect(
      boxTransform(item, { ...item.placement, rotated: true }, scene),
    ).toEqual({
      size: [200, 300, 100],
      center: [120, 190, 80],
    });
  });
  it("rejects unknown shelf rather than drawing at origin", () => {
    expect(() =>
      boxTransform(item, { ...item.placement, shelf_id: "unknown" }, scene),
    ).toThrow();
  });
});
