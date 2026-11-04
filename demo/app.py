import base64
import io
import os
import json
import subprocess
import sys
import uuid
import tempfile
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from PIL import Image, ImageOps, UnidentifiedImageError

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 80 * 1024 * 1024
JOBS = Path(tempfile.gettempdir()) / 'nazhi-reconstruction'
JOBS.mkdir(mode=0o700, exist_ok=True)
active_process = None
model = None
LABELS = {'book':'书', 'cup':'杯子', 'bottle':'瓶子', 'bowl':'碗', 'scissors':'剪刀', 'cell phone':'手机', 'laptop':'笔记本电脑', 'keyboard':'键盘', 'mouse':'鼠标', 'remote':'遥控器', 'backpack':'背包', 'handbag':'手提包', 'clock':'钟表', 'vase':'花瓶', 'toothbrush':'牙刷', 'chair':'椅子', 'tv':'电视', 'potted plant':'盆栽', 'person':'人'}

@app.get('/')
def index():
    return render_template('index.html')

@app.post('/detect')
def detect():
    return jsonify(error='单图检测未部署；本原型当前只用于 VGGT 多视角重建。'), 501

@app.post('/reconstruct')
def reconstruct():
    global active_process
    if active_process is not None and active_process.poll() is None:
        return jsonify(error='已有重建任务正在运行，请等待完成。'), 409
    files = request.files.getlist('photos')
    if not 2 <= len(files) <= 6:
        return jsonify(error='请选择 2 至 6 张不同视角的 JPEG 或 PNG 照片。'), 400
    job_id = uuid.uuid4().hex
    job = JOBS / job_id
    images = job / 'images'
    images.mkdir(parents=True, mode=0o700)
    try:
        for i, f in enumerate(files):
            with Image.open(f.stream) as source:
                if source.width * source.height > 40_000_000:
                    raise ValueError('单张图片像素过大')
                img = ImageOps.exif_transpose(source).convert('RGB')
                img.thumbnail((1600, 1600))
                img.save(images / f'{i:03}.jpg', quality=90)
        (job / 'status.json').write_text(json.dumps({'state':'running', 'message':'正在启动重建任务。'}, ensure_ascii=False), encoding='utf-8')
        log = open(job / 'worker.log', 'w', encoding='utf-8')
        active_process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('reconstruct.py')), str(job)], stdout=log, stderr=subprocess.STDOUT)
        log.close()
        return jsonify(job=job_id)
    except (ValueError, UnidentifiedImageError, OSError) as e:
        return jsonify(error=f'无法读取照片：{e}'), 400

@app.get('/reconstruct/<job_id>')
def reconstruct_status(job_id):
    if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        return jsonify(error='无效任务'), 404
    job = JOBS / job_id
    try:
        data = json.loads((job / 'status.json').read_text(encoding='utf-8'))
        if data['state'] == 'running' and active_process is not None and active_process.poll() is not None:
            data = {'state':'error', 'message':f'重建进程意外退出（{active_process.returncode}），请检查内存、依赖和网络。'}
        if data['state'] == 'done': data['cloud'] = json.loads((job / 'cloud.json').read_text(encoding='utf-8'))
        return jsonify(data)
    except (OSError, ValueError):
        return jsonify(error='任务不存在或数据损坏'), 404

@app.errorhandler(413)
def too_large(_):
    return jsonify(error='图片总大小超过 80 MB，请压缩后重试。'), 413

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5050, debug=False)
