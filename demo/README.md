# VGGT 多视角重建原型

本目录从交接快照恢复，独立于仓库现有的 FastAPI + React 合成场景演示（`backend/`、`frontend/`）。
**状态：2026-11-04 已在本机连接远端 GPU 实例并端到端跑通（合成场景）。** 真实柜体照片尚未验证。

## 已验证事实

远端实例（通过 SSH 隧道访问，服务仅监听远端 `127.0.0.1:5050`）：

| 项目 | 实测结果 |
|---|---|
| GPU | NVIDIA GeForce RTX 4090 D，24082 MiB |
| PyTorch | 2.3.1+cu121，`torch.cuda.is_available() = True`，算力 8.9 |
| VGGT 权重 | 本地目录约 4.7 GB（`config.json` + `model.safetensors`） |
| 远端外网 | **不通**（GitHub / HuggingFace 均失败），必须用 `VGGT_MODEL` 指向本地权重 |
| 端到端 | 4 张图上传 → 30,000 点点云，耗时约 24 秒（含模型加载） |

几何自检：用 `demo/tools/render_synthetic_cabinet.py` 生成一个合成柜体场景（柜体框架、中间层板、
4 个彩色盒子、棋盘格地面、地面 A4 纸），从 4 个视角渲染后提交重建。把点云投影到三个正交平面，
柜体轮廓、层板位置、四个盒子的颜色与相对位置都能正确恢复（注意 VGGT 世界坐标的 y 轴朝下，
因此正视投影上下方向与照片相反）。说明上传、进程调度、CUDA 推理、点云导出这条链路是通的，
不是"页面能打开"级别的验证。

## 能力与边界

- 输入 2–6 张同一静态场景的照片，输出**未标定相对尺度**点云。
- 没有 A4 尺度标定，**不能输出柜格尺寸**；没有柜格分割、没有布局规划。
- 单图 YOLO 检测已明确禁用，`/detect` 返回 501，不要当作可用功能。
- 合成渲染图不代表真实照片效果；真实柜体的遮挡、反光、纹理稀疏都会影响重建质量。
- 真实照片只有在用户确认远端处理环境后才会使用。

## 本地运行（仅网页层）

在仓库根目录的 PowerShell 中：

```powershell
py -3.12 -m venv demo/.venv
./demo/.venv/Scripts/python.exe -m pip install -r demo/requirements-web.txt
./demo/.venv/Scripts/python.exe demo/app.py
```

访问 `http://127.0.0.1:5050`。**这不会安装或配置 VGGT**；本机没有模型依赖与权重时点击
"开始三维重建"会失败。网页依赖与 VGGT 依赖必须分开配置，不要污染仓库现有后端虚拟环境。

## 远端运行（推理）

在已确认身份的实例上，使用独立虚拟环境，例如：

```bash
export VGGT_MODEL=/path/to/VGGT-1B
export VGGT_REPO=/path/to/vggt-repo
/path/to/venv/bin/python demo/app.py     # 仅监听 127.0.0.1:5050
```

再把本机端口转发过去：

```bash
ssh -N -L 127.0.0.1:5051:127.0.0.1:5050 -p <port> <user>@<host>
```

首次连接前，必须通过目标平台控制台等可信渠道核实服务器 ED25519 指纹，并与本机
`ssh-keygen -F "[host]:port" -lf` 的输出比较；不能仅凭首次连接自动保存的指纹认定服务器身份。

## 冒烟测试

```powershell
python demo/tools/render_synthetic_cabinet.py
```

会在仓库根目录 `.work/synthetic_cabinet/` 生成 4 张合成视角图（已被 `.gitignore` 排除），
可直接通过页面或 `POST /reconstruct` 提交。该工具只用于验证链路，不是测量基准。

## 数据与运行限制

- 原始快照会把图片、点云与日志写入服务器临时目录 `nazhi-reconstruction`；没有清理、认证、
  权限隔离或持久化队列，**不可暴露公网**，也不能当多人服务用。
- 单进程实验原型，任务状态依赖进程内变量；重启或并发请求时状态可能不准确。
- 模型权重、环境目录、照片、点云、日志与凭据都不要提交 Git。
- 部署前核对 VGGT 官方代码与模型权重各自的使用许可和版本。
