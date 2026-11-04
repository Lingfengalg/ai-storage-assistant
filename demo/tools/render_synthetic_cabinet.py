"""Render a synthetic multi-view cabinet scene for a pipeline smoke test.

The scene is a placeholder: a shelf cabinet, a few boxes and an A4 sheet.
It exists only to verify that the reconstruction worker (upload -> VGGT ->
point cloud) actually runs end to end on the GPU host. It is NOT a
measurement reference and says nothing about real cabinet accuracy.
"""
import math
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parents[2] / '.work' / 'synthetic_cabinet'
WIDTH, HEIGHT = 640, 480
SUPERSAMPLE = 2
FOV_DEG = 50.0


def make_box(x_range, y_range, z_range, color, texture='solid'):
    return {
        'lo': np.array([x_range[0], y_range[0], z_range[0]], dtype=np.float64),
        'hi': np.array([x_range[1], y_range[1], z_range[1]], dtype=np.float64),
        'color': np.array(color, dtype=np.float64),
        'texture': texture,
    }


def build_scene():
    wood = (0.56, 0.41, 0.29)
    boxes = [
        make_box((-1.6, 1.6), (-0.03, 0.0), (-0.5, 1.7), (1.0, 1.0, 1.0), 'floor'),
        # cabinet shell
        make_box((-0.46, -0.44), (0.00, 0.75), (0.00, 0.34), wood),
        make_box((0.44, 0.46), (0.00, 0.75), (0.00, 0.34), wood),
        make_box((-0.46, 0.46), (0.00, 0.02), (0.00, 0.34), wood),
        make_box((-0.46, 0.46), (0.34, 0.36), (0.00, 0.34), wood),
        make_box((-0.46, 0.46), (0.73, 0.75), (0.00, 0.34), wood),
        make_box((-0.46, 0.46), (0.00, 0.75), (0.00, 0.02), (0.48, 0.35, 0.25)),
        # items on the bottom level
        make_box((-0.36, -0.12), (0.02, 0.30), (0.06, 0.30), (0.20, 0.35, 0.78)),
        make_box((0.06, 0.32), (0.02, 0.22), (0.06, 0.30), (0.86, 0.46, 0.16)),
        # items on the middle shelf
        make_box((-0.34, -0.04), (0.36, 0.58), (0.08, 0.28), (0.24, 0.62, 0.30)),
        make_box((0.08, 0.30), (0.36, 0.50), (0.08, 0.28), (0.88, 0.76, 0.20)),
        # A4 sheet lying on the floor in front of the cabinet (210 x 297 mm)
        make_box((-0.105, 0.105), (0.0, 0.004), (0.50, 0.797), (1.0, 1.0, 1.0), 'paper'),
    ]
    return boxes


def camera_rays(eye, target, width, height):
    forward = np.asarray(target, dtype=np.float64) - np.asarray(eye, dtype=np.float64)
    forward /= np.linalg.norm(forward)
    world_up = np.array([0.0, 1.0, 0.0])
    right = np.cross(forward, world_up)
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)

    tan_half = math.tan(math.radians(FOV_DEG) / 2.0)
    aspect = width / height

    us = (np.arange(width) + 0.5) / width * 2.0 - 1.0
    vs = 1.0 - (np.arange(height) + 0.5) / height * 2.0
    uu, vv = np.meshgrid(us * tan_half * aspect, vs * tan_half)
    dirs = forward[None, None, :] + uu[..., None] * right + vv[..., None] * up
    dirs /= np.linalg.norm(dirs, axis=-1, keepdims=True)
    return np.asarray(eye, dtype=np.float64), dirs.reshape(-1, 3)


def intersect(origin, dirs, box):
    lo, hi = box['lo'], box['hi']
    safe = np.where(np.abs(dirs) < 1e-12, 1e-12, dirs)
    t1 = (lo[None, :] - origin[None, :]) / safe
    t2 = (hi[None, :] - origin[None, :]) / safe
    t_near = np.minimum(t1, t2)
    t_far = np.maximum(t1, t2)
    t_enter = t_near.max(axis=1)
    t_exit = t_far.min(axis=1)
    return t_enter, t_exit


def shade(box, points):
    lo, hi = box['lo'], box['hi']
    p = points
    gaps = np.stack([np.abs(p - lo[None, :]), np.abs(p - hi[None, :])], axis=-1)
    face_index = np.argmin(gaps.reshape(-1, 6), axis=1)
    axis = face_index // 2
    is_max = (face_index % 2) == 1

    normals = np.zeros_like(p)
    for a in range(3):
        mask = axis == a
        if not mask.any():
            continue
        normals[mask, a] = np.where(is_max[mask], 1.0, -1.0)

    lambert = np.abs(normals @ np.array([0.35, 0.86, 0.36]))
    factor = 0.55 + 0.45 * lambert

    colors = np.tile(box['color'], (p.shape[0], 1)) * factor[:, None]

    if box['texture'] == 'floor':
        cell = np.floor(p[:, 0] / 0.1) + np.floor(p[:, 2] / 0.1)
        dark = (cell.astype(np.int64) % 2) == 0
        base = np.where(dark[:, None], 0.42, 0.82)
        colors = base * factor[:, None]
    elif box['texture'] == 'paper':
        border = (
            (np.minimum(p[:, 0] - lo[0], hi[0] - p[:, 0]) < 0.010)
            | (np.minimum(p[:, 2] - lo[2], hi[2] - p[:, 2]) < 0.010)
        )
        colors = np.where(border[:, None], 0.25, 0.96) * factor[:, None]

    return np.clip(colors, 0.0, 1.0)


def render(boxes, eye, target, width, height):
    origin, dirs = camera_rays(eye, target, width, height)
    best_t = np.full(dirs.shape[0], np.inf)
    image = np.full((dirs.shape[0], 3), 0.05)

    for box in boxes:
        t_enter, t_exit = intersect(origin, dirs, box)
        hit = (t_exit >= np.maximum(t_enter, 1e-6)) & (t_enter > 1e-6)
        better = hit & (t_enter < best_t)
        if not better.any():
            continue
        points = origin[None, :] + dirs[better] * t_enter[better, None]
        image[better] = shade(box, points)
        best_t[better] = t_enter[better]

    image = image.reshape(height, width, 3)
    image = (image * 255.0).astype(np.uint8)
    return Image.fromarray(image).resize((width, height), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    boxes = build_scene()
    target = (0.0, 0.32, 0.30)
    views = [
        ((0.02, 0.62, 1.85), 'view_0'),
        ((-0.62, 0.82, 1.75), 'view_1'),
        ((0.66, 0.50, 1.78), 'view_2'),
        ((-0.26, 1.05, 1.62), 'view_3'),
    ]
    for eye, name in views:
        img = render(boxes, eye, target, WIDTH * SUPERSAMPLE, HEIGHT * SUPERSAMPLE)
        path = OUT / f'{name}.jpg'
        img.save(path, quality=92)
        print('wrote', path)


if __name__ == '__main__':
    main()
