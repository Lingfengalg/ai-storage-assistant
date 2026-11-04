"""Evaluate a reconstruction cloud: extents, plane structure, orthographic projections.

Usage: python eval_cloud.py cloud.json [out_prefix]
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def load(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    pts = np.asarray(data['points'], dtype=np.float64)
    cols = np.asarray(data['colors'], dtype=np.uint8)
    return pts, cols, data.get('units', '?')


def ransac_planes(pts, n_planes=6, iters=300, thresh_ratio=0.02, rng=None):
    """Greedy RANSAC: repeatedly find the dominant plane, remove inliers."""
    rng = rng or np.random.default_rng(0)
    remaining = pts.copy()
    scale = np.ptp(pts, axis=0).max()
    thresh = thresh_ratio * scale
    found = []
    for _ in range(n_planes):
        if len(remaining) < 200:
            break
        best = None
        for _ in range(iters):
            idx = rng.choice(len(remaining), 3, replace=False)
            p = remaining[idx]
            n = np.cross(p[1] - p[0], p[2] - p[0])
            norm = np.linalg.norm(n)
            if norm < 1e-12:
                continue
            n = n / norm
            d = -n @ p[0]
            dist = np.abs(remaining @ n + d)
            inliers = int((dist < thresh).sum())
            if best is None or inliers > best[0]:
                best = (inliers, n, d, dist < thresh)
        if best is None or best[0] < 0.05 * len(remaining):
            break
        inliers, n, d, mask = best
        sub = remaining[mask]
        # extent of the plane patch
        extent = np.ptp(sub, axis=0)
        found.append({
            'points': inliers,
            'fraction': inliers / len(pts),
            'normal': n,
            'offset': d,
            'patch_extent': extent,
        })
        remaining = remaining[~mask]
    return found, thresh


def project(pts, cols, axes, size=760, pad=20, flip_y=True):
    """Orthographic projection onto two axes, painter-sorted by depth."""
    a, b, depth = axes
    img = np.full((size, size, 3), 22, dtype=np.uint8)
    x = pts[:, a].copy()
    y = pts[:, b].copy()
    if flip_y:
        y = -y
    x0, x1 = x.min(), x.max()
    y0, y1 = y.min(), y.max()
    sx = (size - 2 * pad) / max(x1 - x0, 1e-9)
    sy = (size - 2 * pad) / max(y1 - y0, 1e-9)
    s = min(sx, sy)
    px = ((x - x0) * s + pad + (size - 2 * pad - (x1 - x0) * s) / 2).astype(int)
    py = ((y - y0) * s + pad + (size - 2 * pad - (y1 - y0) * s) / 2).astype(int)
    order = np.argsort(pts[:, depth])
    for i in order:
        cx, cy = px[i], py[i]
        if 0 <= cx < size and 0 <= cy < size:
            img[cy, cx] = cols[i]
    return Image.fromarray(img), s


def main():
    path = sys.argv[1]
    prefix = sys.argv[2] if len(sys.argv) > 2 else str(Path(path).with_suffix(''))
    pts, cols, units = load(path)
    print(f'units={units} points={len(pts)}')

    lo, hi = pts.min(axis=0), pts.max(axis=0)
    ext = hi - lo
    print(f'bbox_min={np.round(lo, 4).tolist()}')
    print(f'bbox_max={np.round(hi, 4).tolist()}')
    print(f'extents={np.round(ext, 4).tolist()}  ratio={np.round(ext / ext.max(), 4).tolist()}')

    # how much of the volume is actually occupied: a failed reconstruction
    # tends to be a thin/smeared sheet rather than a filled volume
    sampling = np.abs(pts - pts.mean(axis=0)).max(axis=0) - np.abs(pts - pts.mean(axis=0)).min(axis=0)
    print(f'per_axis_spread_ratio={np.round(sampling / sampling.max(), 3).tolist()}')

    planes, thresh = ransac_planes(pts)
    print(f'plane_threshold={thresh:.5f} planes_found={len(planes)}')
    for i, p in enumerate(planes):
        n = np.round(p['normal'], 3).tolist()
        ang = np.round(np.degrees(np.arccos(np.clip(np.abs(p['normal']), -1, 1))), 1).tolist()
        print(f"  plane{i}: frac={p['fraction']:.3f} n={n} |n|angle_to_axes_deg={ang} patch_extent={np.round(p['patch_extent'], 3).tolist()}")

    views = {
        'front_x_y': (0, 1, 2),
        'side_z_y': (2, 1, 0),
        'top_x_z': (0, 2, 1),
    }
    for name, axes in views.items():
        img, s = project(pts, cols, axes)
        out = f'{prefix}_{name}.png'
        img.save(out)
        print(f'wrote {out} scale={s:.1f}px/unit')


if __name__ == '__main__':
    main()
