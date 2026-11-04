"""Plane-consistency check across a cloud.

Real back panels of one cabinet are a single flat board, so every large plane
that shares its orientation must also share its offset. Angular and offset
spread across those planes is a ground-truth-free accuracy proxy.

Usage: python plane_consistency.py cloud1.json [cloud2.json ...]
"""
import json
import sys
from pathlib import Path

import numpy as np


def load(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    return np.asarray(data['points'], float), data.get('preprocess', 'crop')


def fit_plane(p):
    c = p.mean(axis=0)
    _, _, vt = np.linalg.svd(p - c, full_matrices=False)
    n = vt[-1]
    return n, -n @ c, float(((p - c) @ n).std())


def ransac(points, thresh, iters=500, rng=None):
    rng = rng or np.random.default_rng(7)
    best = None
    for _ in range(iters):
        p = points[rng.choice(len(points), 3, replace=False)]
        n = np.cross(p[1] - p[0], p[2] - p[0])
        norm = np.linalg.norm(n)
        if norm < 1e-12:
            continue
        n /= norm
        d = -n @ p[0]
        m = np.abs(points @ n + d) < thresh
        c = int(m.sum())
        if best is None or c > best[0]:
            best = (c, n, d, m)
    return best


def analyse(path, thresh_ratio=0.01, max_planes=10, min_frac=0.02):
    pts, mode = load(path)
    scale = np.ptp(pts, axis=0).max()
    thresh = thresh_ratio * scale
    remaining = pts.copy()
    planes = []
    for _ in range(max_planes):
        if len(remaining) < 0.03 * len(pts):
            break
        r = ransac(remaining, thresh)
        if r is None or r[0] < min_frac * len(pts):
            break
        cnt, n, d, m = r
        n, d, resid = fit_plane(remaining[m])
        planes.append({'n': n / np.linalg.norm(n), 'd': d, 'frac': cnt / len(pts), 'resid': resid})
        remaining = remaining[~m]

    # cluster planes by orientation
    clusters = []
    for p in planes:
        for c in clusters:
            if abs(p['n'] @ c['ref']) > 0.99:
                c['members'].append(p)
                break
        else:
            clusters.append({'ref': p['n'], 'members': [p]})

    out = {'path': Path(path).name, 'mode': mode, 'scale': scale, 'planes': len(planes), 'clusters': []}
    for c in clusters:
        members = c['members']
        ref = members[0]['n']
        angles = [float(np.degrees(np.arccos(np.clip(abs(m['n'] @ ref), -1, 1)))) for m in members]
        offsets = [m['d'] if m['n'] @ ref > 0 else -m['d'] for m in members]
        out['clusters'].append({
            'planes': len(members),
            'coverage': sum(m['frac'] for m in members),
            'max_angle_deg': max(angles),
            'offset_spread_ratio': (max(offsets) - min(offsets)) / scale,
            'max_resid_ratio': max(m['resid'] for m in members) / scale,
        })
    return out


def main():
    for path in sys.argv[1:]:
        r = analyse(path)
        print(f"== {r['path']} (mode={r['mode']}, scale={r['scale']:.4f}, planes={r['planes']})")
        for i, c in enumerate(r['clusters']):
            print(f"   cluster{i}: planes={c['planes']} coverage={c['coverage']:.1%} "
                  f"max_angle_spread={c['max_angle_deg']:.2f}deg "
                  f"offset_spread={c['offset_spread_ratio']:.3%} of scale "
                  f"max_plane_resid={c['max_resid_ratio']:.3%} of scale")


if __name__ == '__main__':
    main()
