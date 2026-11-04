import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { Plan, Scene } from "../api/client";
import { boxTransform, categoryColors, compartmentSpans } from "../geometry";

type Props = {
  scene: Scene;
  plan: Plan | null;
  selectedId: string;
  onSelect: (id: string) => void;
};

export default function SceneViewer({
  scene,
  plan,
  selectedId,
  onSelect,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const container = host.current!;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      setError("当前环境无法启用 WebGL。物品清单和库存操作仍可使用。");
      return;
    }
    setError("");
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor("#eef2ef");
    renderer.domElement.setAttribute(
      "aria-label",
      "收纳柜三维视图；可用左侧物品按钮选择物品",
    );
    container.appendChild(renderer.domElement);
    const world = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 1, 10000);
    camera.position.set(1500, 1050, -1500);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(450, 300, 180);
    controls.minDistance = 700;
    controls.maxDistance = 3200;
    controls.maxPolarAngle = Math.PI * 0.49;
    controls.update();
    world.add(new THREE.HemisphereLight("#ffffff", "#9ba99e", 2.5));
    const light = new THREE.DirectionalLight("#ffffff", 3);
    light.position.set(500, 1500, -500);
    world.add(light);
    const disposables: { dispose(): void }[] = [];
    const targets: THREE.Mesh[] = [];
    function box(
      size: [number, number, number],
      pos: [number, number, number],
      color: string,
      selected = false,
    ) {
      const geo = new THREE.BoxGeometry(...size);
      const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.8 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(...pos);
      world.add(mesh);
      const edges = new THREE.EdgesGeometry(geo);
      const lineMat = new THREE.LineBasicMaterial({
        color: selected ? "#164f3d" : "#53645c",
        transparent: true,
        opacity: selected ? 1 : 0.26,
      });
      const wire = new THREE.LineSegments(edges, lineMat);
      mesh.add(wire);
      disposables.push(geo, mat, edges, lineMat);
      return mesh;
    }
    for (const shelf of scene.shelves) {
      box(
        [shelf.size.width + 30, 16, shelf.size.depth + 20],
        [shelf.size.width / 2, shelf.elevation - 8, shelf.size.depth / 2],
        "#c9d1cb",
      );
      if (shelf.columns > 1 && shelf.divider > 0) {
        const spans = compartmentSpans(shelf);
        for (let index = 0; index < spans.length - 1; index += 1) {
          const dividerX =
            spans[index][0] + spans[index][1] + shelf.divider / 2;
          box(
            [shelf.divider, shelf.size.height, shelf.size.depth],
            [
              dividerX,
              shelf.elevation + shelf.size.height / 2,
              shelf.size.depth / 2,
            ],
            "#aebbb2",
          );
        }
      }
    }
    const maxHeight = Math.max(
      ...scene.shelves.map((s) => s.elevation + s.size.height),
    );
    const width = Math.max(...scene.shelves.map((s) => s.size.width));
    const depth = Math.max(...scene.shelves.map((s) => s.size.depth));
    for (const x of [-12, width + 12]) {
      for (const z of [0, depth])
        box([18, maxHeight + 20, 18], [x, maxHeight / 2, z], "#7f9188");
    }
    for (const item of scene.items.filter((i) => i.status === "stored")) {
      const position = plan?.placements[item.id] ?? item.placement;
      const transform = boxTransform(item, position, scene);
      const selected = item.id === selectedId;
      const mesh = box(
        transform.size,
        transform.center,
        selected ? "#3e8068" : (categoryColors[item.category] ?? "#a5aba9"),
        selected,
      );
      mesh.userData.itemId = item.id;
      targets.push(mesh);
    }
    const grid = new THREE.GridHelper(1800, 36, "#aebcb3", "#d7dfd9");
    grid.position.set(450, 0, 180);
    world.add(grid);
    disposables.push(grid.geometry);
    const gridMaterials = Array.isArray(grid.material)
      ? grid.material
      : [grid.material];
    disposables.push(...gridMaterials);
    const raycaster = new THREE.Raycaster();
    let start = [0, 0];
    const down = (event: PointerEvent) => {
      start = [event.clientX, event.clientY];
    };
    const up = (event: PointerEvent) => {
      if (Math.hypot(event.clientX - start[0], event.clientY - start[1]) > 5)
        return;
      const rect = renderer.domElement.getBoundingClientRect();
      raycaster.setFromCamera(
        new THREE.Vector2(
          ((event.clientX - rect.left) / rect.width) * 2 - 1,
          -((event.clientY - rect.top) / rect.height) * 2 + 1,
        ),
        camera,
      );
      const hit = raycaster.intersectObjects(targets, false)[0];
      if (hit) onSelect(hit.object.userData.itemId as string);
    };
    const render = () => renderer.render(world, camera);
    const resize = new ResizeObserver(() => {
      const { width, height } = container.getBoundingClientRect();
      camera.aspect = width / Math.max(height, 1);
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
      render();
    });
    resize.observe(container);
    controls.addEventListener("change", render);
    renderer.domElement.addEventListener("pointerdown", down);
    renderer.domElement.addEventListener("pointerup", up);
    render();
    return () => {
      resize.disconnect();
      controls.dispose();
      renderer.domElement.removeEventListener("pointerdown", down);
      renderer.domElement.removeEventListener("pointerup", up);
      disposables.forEach((d) => d.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [scene, plan, selectedId, onSelect]);

  return (
    <div className="viewer" ref={host}>
      {error && (
        <div className="viewer-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
