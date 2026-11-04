# 开发启动与协作入口

## 当前能运行什么

这是一条可运行的本地链路，不是完整产品：浏览器读取合成场景，显示真实尺度的简化三维盒体；后端生成贪心布局；用户可锁定物品、记录取出和归还，或确认实际执行后的布局。SQLite 保存状态和操作记录，刷新页面与重启后端不会重置。

**未实现：** 图片上传与识别、真实空间扫描、手工新增物品界面、CP-SAT、拿取路径、入口/承重校验、多用户登录、购物平台和深度硬件。按钮不会把这些未完成项伪装成已实现能力。

## 环境

- 推荐 Python 3.12、Node.js 24 LTS、Git。
- 首次依赖安装需联网；当前合成场景运行不需要模型 API 或 GPU。
- 以下命令在仓库根目录运行。不要将本地开发服务暴露到公网；当前未实现身份鉴权。

## Windows 首次安装

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e backend
npm --prefix frontend ci
```

若 `py -3.12` 不存在，使用已安装的 Python 3.12 可执行文件运行 `-m venv .venv`。不需要激活虚拟环境。

## 启动

在 PowerShell 运行：

```powershell
.\scripts\dev.ps1
```

访问 `http://127.0.0.1:5173`，API 文档为 `http://127.0.0.1:8000/docs`。终端保持打开，Ctrl+C 停止这次启动的两个子进程。日志在 `.work/dev-logs/`，本地数据库默认在 `data/local/storage.sqlite3`。

如果系统脚本策略禁止执行，不必修改全局策略，使用两个终端分别运行：

```powershell
# 终端一，仓库根目录
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
# 终端二，仓库根目录
npm --prefix frontend run dev
```

后端可通过 `STORAGE_DB_PATH` 环境变量指定新的独立数据库。测试使用临时库，不触碰开发数据库。

## macOS 或 Linux

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e backend
npm --prefix frontend ci
.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# 另一个终端执行 npm --prefix frontend run dev
```

依赖清单使用跨平台包版本；当前实际验证环境是 Windows，Linux 检查交由仓库 CI 执行，不宣称已在所有系统实测。

## 检查与构建

```powershell
.\.venv\Scripts\ruff.exe check backend
.\.venv\Scripts\python.exe -m pytest backend/tests -q
npm --prefix frontend test
npm --prefix frontend run build
```

`frontend/dist/` 是静态构建产物，不提交 Git。开发模式的 Vite 负责代理 `/api` 到后端；正式部署需要另行配置同源反向代理，不能把 `vite preview` 当作完整部署方案。

## 修改接口时

1. 修改 `backend/app/models.py` 与路由，补测试。
2. 导出 OpenAPI，并从它生成 TypeScript 类型：

```powershell
.\.venv\Scripts\python.exe backend/scripts/export_openapi.py
npm --prefix frontend run types:api
```

3. 同时提交后端改动、`shared/openapi.json` 和 `frontend/src/api/schema.d.ts`。不要手工编辑生成类型。
4. 再运行测试和构建。后端测试会检查 OpenAPI 快照，CI 会检查前端生成类型是否过期。

## 依赖说明

前端 `package-lock.json` 和后端 `requirements-dev.lock` 固定本次验证过的依赖。TypeScript 固定为 5.9.3，以匹配当前 `openapi-typescript` 的 peer dependency；`minimatch` override 使用修复审计问题的 11.x，接口生成已测试。升级时先复核兼容性与审计结果，不盲目更新全部依赖。

后端测试依赖的 Starlette 当前仍支持 HTTPX，但发出迁移至 HTTPX2 的弃用提示；测试通过，后续升级测试客户端时单独验证。Three.js 的独立压缩分块约 560 kB，构建会给出体积提示；当前优先保证三维开发入口，尚未做按需渲染器裁剪。
