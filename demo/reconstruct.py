"""Run VGGT in a separate process; output a small, unscaled point cloud."""
import json, os, sys
from pathlib import Path
import numpy as np
import torch

root = Path(os.environ.get('VGGT_REPO', str(Path.home() / '.cache/nazhi-vggt')))
sys.path.insert(0, str(root))
from vggt.models.vggt import VGGT
from vggt.utils.load_fn import load_and_preprocess_images

job = Path(sys.argv[1])
def status(s, message):
    p = job / 'status.tmp'
    p.write_text(json.dumps({'state': s, 'message': message}, ensure_ascii=False), encoding='utf-8')
    p.replace(job / 'status.json')

try:
    names = sorted(str(p) for p in (job / 'images').glob('*.jpg'))
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    status('running', f'正在加载 VGGT 模型（{device}）；首次使用需要下载约 5 GB 权重。')
    model = VGGT.from_pretrained(os.environ.get('VGGT_MODEL', 'facebook/VGGT-1B')).to(device).eval()
    status('running', f'正在执行三维重建（{device}），CPU 可能耗时较长。')
    images = load_and_preprocess_images(names).to(device)
    with torch.inference_mode():
        if device == 'cuda':
            with torch.autocast('cuda', dtype=torch.float16):
                pred = model(images)
        else:
            pred = model(images)
    pts = pred['world_points'][0].float().cpu().numpy().reshape(-1, 3)
    conf = pred['world_points_conf'][0].float().cpu().numpy().reshape(-1)
    colors = images.permute(0, 2, 3, 1).cpu().numpy().reshape(-1, 3)
    good = np.isfinite(pts).all(axis=1) & np.isfinite(conf)
    if not good.any(): raise RuntimeError('模型没有输出有效点云。')
    good &= conf >= np.quantile(conf[good], 0.4)
    idx = np.flatnonzero(good)
    if len(idx) > 30000: idx = idx[np.linspace(0, len(idx)-1, 30000, dtype=int)]
    xyz = pts[idx]
    rgb = np.clip(colors[idx] * 255, 0, 255).astype(int)
    data = {'points': np.round(xyz, 4).tolist(), 'colors': rgb.tolist(), 'units': 'relative', 'count': len(idx)}
    (job / 'cloud.json').write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
    status('done', '重建完成：当前为未标定相对尺度点云，尚不能输出可靠的柜格尺寸。')
except Exception as e:
    status('error', f'重建失败：{type(e).__name__}: {e}')
    raise
