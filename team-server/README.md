# 雏雁团队协调服务（team-server）

五个人各自运行 DSH，agent 之间没有共享上下文。这个服务只做四件事：**谁在做什么、认领有没有冲突、交接是否可复现、别人知不知道**。交付物仍然走 git 分支 + PR，服务里只有任务元数据。

协议设计见 [../docs/agent-collaboration.md](../docs/agent-collaboration.md)。

## 本地跑起来（阶段 0 已演练）

```powershell
# 1) 起服务（首次会自动建库）
$env:TEAM_ADMIN_TOKEN = "dev-admin-token"
cd team-server
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765

# 2) 另开一个终端：造 5 个 agent 与演练任务，token 写到 .work/team-tokens.json
$env:TEAM_ADMIN_TOKEN = "dev-admin-token"
cd team-server
..\.venv\Scripts\python.exe seed.py --db ..\.work\team.db --out ..\.work\team-tokens.json

# 3) 看板（浏览器打开 127.0.0.1:8765，粘贴 admin token）
# 4) CLI（任意 agent token）
$env:TEAM_URL = "http://127.0.0.1:8765"
$env:TEAM_TOKEN = "<agent-a token>"
..\.venv\Scripts\python.exe ..\tools\teamctl.py sync
```

协议验收测试：

```powershell
cd team-server
..\.venv\Scripts\python.exe -m pytest tests -q
```

## 部署到 Debian（阶段 1）

完整步骤见 [../docs/phase1-deployment.md](../docs/phase1-deployment.md)。要点：

```bash
# 服务器上
git clone <repo> && cd <repo>/team-server
cp .env.example .env && vim .env          # TEAM_ADMIN_TOKEN 用 openssl rand -base64 24
sed -i 's/team.example.com/你的域名/' Caddyfile
docker compose up -d --build
curl https://你的域名/api/health

# 建 5 个正式 Agent（token 只显示一次）
docker compose exec team-server python provision.py --db /data/team.db --out /data/tokens.json
docker compose cp team-server:/data/tokens.json ./tokens.json
# 一对一发送后删除：rm ./tokens.json && docker compose exec team-server rm /data/tokens.json
```

每台机器接入后用 `python tools/team_doctor.py` 体检，全 PASS 才算接入成功；MCP 配置可用
`python tools/team_doctor.py --print-mcp-config <仓库路径>` 生成。

`docker-compose.yml` 已把服务端口绑在 `127.0.0.1`，对外只经 Caddy 443 暴露。**没有域名时**用
`docker-compose.internal.yml`：把 `TEAM_BIND_IP` 设为服务器 Tailscale 地址，端口绑到 tailnet 上，
不走 Caddy、无需证书。

每天备份（建议 cron）：

```bash
docker compose exec team-server sqlite3 /data/team.db ".backup '/data/team-backup.db'"
```

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `TEAM_DB` | `team-server/team.db` | SQLite 路径，容器里是 `/data/team.db` |
| `TEAM_ADMIN_TOKEN` | 无（启动时随机生成并打印） | admin 令牌，签收/发布/建 Agent 用 |
| `TEAM_LEASE_MINUTES` | `90` | 默认认领租约 |
| `TEAM_URL` / `TEAM_TOKEN` | — | CLI 与 MCP 适配器使用 |

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 探活 |
| GET | `/api/whoami` | 我是谁 |
| GET | `/api/tasks` | 任务列表（`status`、`mine=me`、`all=1`） |
| POST | `/api/tasks` | 建任务，需要 `Idempotency-Key`；Agent 建的进 draft |
| POST | `/api/admin/tasks/{id}/publish` | admin 发布 draft |
| POST | `/api/tasks/{id}/claim` | 原子认领，409 已被认领 / 423 范围冲突 |
| POST | `/api/tasks/{id}/heartbeat` | 续租，410 租约已失 |
| POST | `/api/tasks/{id}/release` | 主动释放 |
| POST | `/api/tasks/{id}/handoff` | 交接（必须带验收命令） |
| POST | `/api/handoffs/{id}/accept` | 接收方确认（必须先跑验收） |
| POST | `/api/tasks/{id}/request-review` | 送审（必须带 evidence） |
| POST | `/api/reviews/{id}/decide` | admin 人工签收 |
| POST | `/api/tasks/{id}/complete` | 完成（需人工签收，否则 428） |
| GET | `/api/sync?since=` | 每轮同步：事件 + 未读 + 我的任务 + 可认领 |
| GET | `/api/events`、`/api/events/stream` | 事件查询 / SSE 实时流 |
| POST | `/api/messages` | 发消息 |
| GET | `/api/agents` | 在线状态 |
| POST | `/api/admin/agents` | 建 Agent（返回一次性 token） |

错误码固定：401 未认证、403 越权、404 不存在、409 状态冲突、410 租约丢失、423 范围冲突、428 缺前置条件。

## DSH 接入

### 方式 A：MCP（推荐，全员最新版）

每台机器配一次 profile 的 `cordis.patch.yml`：

```yaml
- insert:
    - id: mcp-team
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: team
        transport: stdio
        command: C:/Users/<you>/Documents/ChatGPT/雏雁/.venv/Scripts/python.exe
        args: ['C:/Users/<you>/Documents/ChatGPT/雏雁/team-server/mcp_server.py']
        env:
          TEAM_URL: https://team.example.com
          TEAM_TOKEN: !!js process.env.TEAM_TOKEN
```

工具会以 `mcp__team__sync`、`mcp__team__claim`、`mcp__team__handoff` 等名字出现。适配器进程只做 HTTP 转发，token 从环境变量读，不写进 YAML。

### 方式 B：CLI 兜底

```powershell
$env:TEAM_URL = "https://team.example.com"
$env:TEAM_TOKEN = "<token>"
python tools/teamctl.py sync --since 0
python tools/teamctl.py claim T-0001 --branch codex/T-0001-xxx
python tools/teamctl.py renew T-0001
python tools/teamctl.py handoff T-0001 --to agent-b --acceptance "pytest backend/tests -q"
python tools/teamctl.py accept 1 --output "42 passed"
python tools/teamctl.py review T-0001 --evidence "pytest: 42 passed"
python tools/teamctl.py complete T-0001
```

## 边界

- 这不是安全边界：服务端只能拦住"认领"这一步，Agent 绕过协议直接改文件仍要靠 git 审计与人工评审。
- 不存照片、物品数据、模型权重；只有任务元数据与消息。
- 5 个 Agent、每分钟个位数写请求，SQLite WAL 足够；真要水平扩容再换 Postgres。
