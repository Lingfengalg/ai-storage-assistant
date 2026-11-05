# 五个 Agent 的协作机制（方案 v0.2）

> 状态：**阶段 0 已在本机验证通过**（协调服务 + CLI + MCP + 5 agent 演练）。实现与验收见 [phase0-report.md](phase0-report.md)，下一步是阶段 1 部署到 Debian 服务器。
> 决策已确认，见 [附录 C](#附录-c决策记录2026-11-04)；原始待确认项见 [§13](#13-需要你确认的决策点)。

## 0. 一句话结论

五个人各自的 DSH 会话之间没有任何共享事实，所以"协作"不会自然发生。做法是把**共享状态外置到一台自建协调服务**（任务板 + 租约 + 消息 + 事件流），仓库里放一份所有 Agent 必读的 `AGENTS.md` 作为契约，DSH 侧通过 MCP 工具（首选）或 `teamctl` CLI（兜底）接入。

不共享工作目录，不共用同一个 Agent 上下文，不拿 git 当消息总线。

预计成本：协调服务约 800–1200 行 Python、部署半天；协议联调一到两天。

## 1. 现状与真正的缺口

### 已经有

| 已有 | 说明 |
| --- | --- |
| 同一仓库 | `Lingfengalg/ai-storage-assistant`，5 人本地 clone 后 push |
| 协作规范 | `CONTRIBUTING.md`：Issue、分支、PR、人工核查清单 |
| 任务清单 | `docs/initial-tasks.md`：四个方向可并行 |
| CI | `.github/workflows/ci.yml`：ruff、pytest、前端类型与构建 |
| 模板 | Issue 模板、PR 模板、启动脚本 |

### 缺的（也是 Agent 协作真正卡的）

1. **机器可读的"谁在做什么"**：现在只存在人的脑子里和聊天记录里。
2. **原子认领**：两个人同时决定做同一件事，没有任何机制能阻止，只能事后发现。
3. **租约与接管**：某人做到一半合上电脑，Agent 不知道这份工作卡住了、能不能接。
4. **交接记录**：分支、验收命令、未决问题散落在对话里，接收方要重新考古。
5. **Agent 身份**：服务端无法区分"五个人各自那个 Agent"，消息和审计没有主体。
6. **事件与通知**：别人的任务完成、契约文件变更，其余 Agent 下一轮不会知道。

### 看起来能做、实际不行的方案

| 方案 | 为什么不行 |
| --- | --- |
| 把五个 Agent 放进一个会话 | DSH 的 Agent Teams 只在**单个会话/单台机器**内有效；五个人的 DSH 是五个独立进程，跨机器不存在共享上下文 |
| 共享网盘上放一个 SQLite/共享工作目录 | SMB/NFS 上的 SQLite 锁语义不可靠，半写与锁碎裂会直接损坏状态；git 工作目录同时被两个 Agent 写也会互相踩踏 |
| 用 GitHub Issue 当任务板 | 没有原子认领、没有租约、没有事件订阅；Issue 是给人看的，不是给协议用的。但它是很好的**审计/评审层**，方案里保留 |
| 用飞书群当消息总线 | 人能沟通，机器无法可靠解析；只适合做通知出口（可选） |
| 现成看板（Plane / Kanban / Focalboard） | 可读性够，但认领的原子性、租约、幂等和 Agent 工具化都要二次封装，成本不低于自建一个轻服务 |
| **自建轻量协调服务（本方案）** | 规模只有 5 个 Agent、每分钟个位数写请求，一套 FastAPI + SQLite 就够；语义完全按协议需要设计 |

### 关键约束（来自 DSH 本身，方案必须绕开）

- **Agent 按轮次推进**：外部事件不能打断进行中的一轮。所谓"实时"，对人是实时的（面板/SSE），对 Agent 是**每轮开始同步一次**，靠租约和幂等保证正确性，不靠推送。
- **`schedule_create` 的提醒属于单个会话**：适合"每 15 分钟提醒检查收件箱"，但不能当跨机器通知通道。
- **`AGENTS.md` 是现成的注入点**：DSH 会在首个请求注入 `$DSH_HOME/AGENTS.md`，再按项目根到工作目录的链加载项目级 `AGENTS.md`；文件被读写或会话恢复后会回落更新。把团队协议放仓库根目录，五个人 clone 后自动生效，不需要改 DSH。
- **MCP 是现成的工具注入点**：`@deepseek-ai/dsh-mcp-client` 支持 `stdio` 与 `streamable-http`，工具名形如 `mcp__team__claim`；服务端 instructions 会作为系统提示的一部分注入。

## 2. 目标与非目标

### 目标（每条都可验收，见 §10）

1. **互斥**：同一任务同一时刻只有一个 owner；范围相交的任务不能同时认领。
2. **可见**：任何人/任何 Agent 一眼看到全部任务、负责人、租约剩余、阻塞点。
3. **可接管**：owner 失联超过租约，任务可被别人认领，且原 owner 后续操作被明确拒绝。
4. **可交接**：交接带分支、验收命令、未决问题；接收方能在干净环境复现。
5. **可审计**：所有状态变化有 append-only 事件，能重放"谁在何时改了什么"。
6. **不破坏现有规范**：仍然一任务一分支、一 PR、CI 必绿、人评审合并。

### 非目标

- 不做实时协同编辑（同一文件同一行两人同时写）；收益低、冲突成本高。
- 不替代人工评审与验收；`CONTRIBUTING.md` 的"AI 不能自己证明自己"继续有效。
- 不允许 Agent 自动合并 `main`。
- 不同步工作目录，不让 Server 保存物品照片、库存数据或模型权重。
- 不追求跨机器毫秒级同步；正确性优先于延迟。

## 3. 总体架构

```text
        ┌──────────── 五台电脑，各自的 DSH 会话 ────────────┐
        │ agent:A                agent:B                agent:C …│
        │  MCP 工具调用 / teamctl CLI                       │
        └───────────────────────┬───────────────────────────┘
                                │ HTTPS + Bearer Token
                    ┌───────────▼────────────┐
                    │  协调服务（自建服务器）  │
                    │  FastAPI + SQLite(WAL) │
                    │  任务板 / 租约 / 消息   │
                    │  事件流 SSE / 审计      │
                    └───────┬────────┬───────┘
                            │        │
              ┌─────────────▼──┐  ┌──▼─────────────────┐
              │ GitHub 仓库      │  │ 人：Web 看板 / CLI  │
              │ 分支 / PR / CI   │  │ 飞书 webhook（可选）│
              └─────────────────┘  └────────────────────┘
```

三层职责：

| 层 | 内容 | 谁维护 |
| --- | --- | --- |
| 事实层（Server） | 任务、认领与租约、交接、消息、事件、审计 | 服务器，唯一事实源 |
| 契约层（仓库） | `AGENTS.md`（必读协议）、`docs/` 工作流说明、PR/Issue 模板 | 进 git，随仓库版本化 |
| 接入层（DSH） | MCP 工具、`teamctl` 兜底 CLI、可选技能包、定时提醒 | 每台机器一次性配置 |

**git 仍然是代码与文档的唯一交付通道**。协调服务只回答"谁做什么、做到哪、交接给谁"，不存交付物本身。这样即使服务挂了，交付物和评审记录仍在 GitHub，可以降级运行。

## 4. 核心机制

### 4.1 身份

- 一个 Agent = 一个人 + 一个会话。每人发一个 `TEAM_TOKEN`，在服务端映射到 `agent_id` 与能力标签（`perception` / `planning` / `frontend` / `inventory` / `docs`）。
- Token 只放环境变量，不进仓库、不进日志；支持撤销与轮换。
- Agent 不能冒充别人的身份签收（见 4.5 的人工签收字段）。

### 4.2 任务、认领与租约

任务状态机：

```text
pending ──claim──▶ claimed ──first commit──▶ in_progress
   ▲                  │                          │
   │            release/expire              handoff / request-review
   │                  ▼                          ▼
   └──────────────── pending ◀────────── handoff ──▶ review ──human approve──▶ done
```

- **原子认领**：`POST /tasks/{id}/claim` 在一个事务里检查任务未被认领、范围不自相冲突、Agent 能力满足，写入 `claim` 行。并发请求只有一个返回 200，其余 409。
- **租约**：认领即获得默认 90 分钟的独占权；心跳每 15 分钟续一次。`lease_until` 过期后任务重新可认领。
- **接管**：他人认领过期任务时，服务端把原 owner 标记为 `superseded`，并给原 owner 的后续 `renew` / `complete` 返回 410——**不允许"过期后还提交"**，避免两个分支都声称自己是当前实现。
- **主动释放**：`release` 可随时归还，不扣信誉；只是留一条审计。

### 4.3 范围互斥

每个任务声明 `scope_paths`（文件或目录前缀）与 `capabilities_required`。

- 认领时检查：**活跃任务之间的 `scope_paths` 是否相交**。相交则拒绝（423），提示改用独立文件或把任务拆小。
- `shared/`、`docs/architecture.md`、`CONTRIBUTING.md`、`.github/` 是**共享契约区**：改它们必须在任务里显式声明，且同一时刻只允许一个任务持有。
- 这不是文件锁，不阻止 Agent 直接改文件；它的作用是**在认领阶段就把冲突暴露出来**，而不是等 merge 时互相打架。真正的最后一道闸是 git 与人工评审。

### 4.4 交接协议

交接不是"我把分支推上去了你自己看"，而是结构化记录：

| 字段 | 要求 |
| --- | --- |
| branch / base_sha | 分支名与基线提交，接收方可复现 |
| acceptance | 一条能直接运行的验收命令（本机通过过） |
| summary | 改了什么、为什么、没做什么 |
| open_questions | 未决问题与风险 |
| evidence | 验收输出、截图或 PR 链接 |

接收方先在本机跑 `acceptance`，通过才 `accept`；不通过退回 `reopen`，原 owner 的租约已释放，状态可再被认领。

### 4.5 完成、评审与人工签收

- `request-review`：Agent 不能自己把任务标成 `done`。
- `review` 记录两个字段：`agent_review`（另一位 Agent 的检查结论）与 `human_approved`（人的签收）。`done` 需要两者齐全。
- 证据必须可复现：CI 链接、验收命令输出、PR 号。**"我觉得做完了"不是证据**，与 `CONTRIBUTING.md` 第 19 条一致。

### 4.6 "实时"的真实含义

| 对象 | 机制 | 延迟 |
| --- | --- | --- |
| 人（看板/SSE） | 事件流实时推送 | 亚秒级 |
| Agent（轮次边界） | 每轮开头 `team_sync` 拉取未读消息、我的任务、可认领任务、冲突告警 | 一个轮次（秒级到分钟级） |
| 定时巡检 | `schedule_create` 每 15 分钟提醒"检查收件箱"（仅本会话） | 15 分钟 |
| 人不在电脑 | 服务端 → 飞书 webhook（可选） | 秒级 |

不要在方案里承诺"Agent 会被实时打断"——DSH 不支持，也不需要：租约已经保证不会两个 Agent 同时写同一任务。

### 4.7 降级模式

服务不可用时（断网、重启、维护）：

1. 停止新任务认领，已认领任务继续做，但不接管、不交接。
2. 交付仍走 git 分支 + PR；PR 描述里写明"协调服务不可用，人工确认无重复工作"。
3. 人在群里广播一次冻结的目录/模块范围。
4. 服务恢复后补记录（`/admin/backfill` 或人工补事件）。

## 5. 数据模型

| 表 | 关键字段 |
| --- | --- |
| `agents` | id, person, display_name, capabilities[], token_hash, last_seen_at, revoked_at |
| `tasks` | id, title, kind(code/doc/review), goal, acceptance, scope_paths[], capabilities_required[], priority, status, owner_agent_id, branch, base_sha, pr_url, revision, created_at, updated_at |
| `claims` | task_id（同一任务仅一条活跃行）, agent_id, lease_until, heartbeat_at, branch |
| `handoffs` | id, task_id, from_agent, to_agent, branch, acceptance_cmd, summary_md, open_questions, created_at, accepted_at |
| `reviews` | id, task_id, reviewer_agent, human_approved, verdict, evidence, created_at |
| `messages` | id, thread_id, task_id, from_agent, to_agent(可空=广播), kind, body_md, created_at, read_by[] |
| `events` | seq, type, payload_json, created_at（append-only，SSE 与审计共用） |

约定：服务端时间一律 UTC 存储、展示时换算；Agent 不用本地时钟判断租约。

## 6. API 与 MCP 工具

### REST（人、CLI、MCP 服务端共用同一套）

| 方法 | 路径 | 语义 | 失败码 |
| --- | --- | --- | --- |
| GET | `/tasks` | 列出任务，支持 `status`、`capability`、`owner` 过滤 | — |
| POST | `/tasks` | 建任务（需 Idempotency-Key） | 409 重复键 |
| POST | `/tasks/{id}/claim` | 原子认领，body 带分支与基线 | 409 已被认领 / 423 范围冲突 |
| POST | `/tasks/{id}/heartbeat` | 续租 | 410 租约已失 |
| POST | `/tasks/{id}/release` | 主动释放 | 410 |
| POST | `/tasks/{id}/handoff` | 生成交接记录 | 409 状态不符 |
| POST | `/handoffs/{id}/accept` | 接收方确认 | 409 验收未跑 |
| POST | `/tasks/{id}/request-review` | 请求评审 | 409 |
| POST | `/reviews/{id}/decide` | 人签收 / Agent 复审 | 403 越权 |
| POST | `/tasks/{id}/complete` | 结束任务（需 review 齐全） | 428 缺前置 |
| GET | `/inbox` | 未读消息 + 与我相关的变更 | — |
| POST | `/messages` | 发消息 / 提问 | — |
| GET | `/events?since=` | 事件流（SSE，Agent 用 NDJSON 拉取） | — |
| GET | `/agents` | 在线状态、负载 | — |

所有写操作：`Authorization: Bearer <token>`、`Idempotency-Key`、乐观并发 `If-Match: <revision>`；错误码语义固定，Agent 不猜。

### MCP 工具（`serverName: team`）

`mcp__team__sync`（组合：收件箱 + 我的任务 + 可认领 + 冲突）、`list_tasks`、`claim`、`renew`、`release`、`handoff`、`accept`、`request_review`、`complete`、`send`、`inbox`、`status`。

`sync` 是协议的第一入口，服务端 instructions 里写清"每轮先 sync"。

## 7. DSH 侧接入（每台机器一次性配置）

### 7.1 仓库根新增 `AGENTS.md`（草案全文）

```markdown
# 团队协作协议（五 Agent，必读）

你是「雏雁 · AI 收纳辅助系统」团队的一员。五个人各自运行 DSH，
共享本仓库和一台协调服务。开始任何工作前先完成本页流程。

## 每轮必做
1. 先调用 team_sync（或 `python tools/teamctl.py sync --json`），不要跳过。
2. 有未读消息就在本轮处理；租约剩余不足 20 分钟先续租。
3. 没有在办任务时，从可认领列表挑一个；不要两个人做同一件事。

## 认领与分支
- 动手前必须 claim；任务已被认领就换任务，或发消息问。
- 分支名 `codex/<task-id>-<简短英文描述>`，从最新 `origin/main` 拉。
- 只改任务 scope_paths 内的文件；改 `shared/`、`CONTRIBUTING.md`、
  `docs/architecture.md` 前必须在任务里声明，且确认没有他人持有。

## 完成
- 任务记录里的 acceptance 命令必须在本机通过，贴出输出。
- 提交 PR 并关联任务；CI 必须绿；合并由人确认，不自动合并 main。
- 交接写清分支、验收命令、未决问题；对方能复现才算交接完成。

## 禁止
- 不推 main，不 force push 共享分支，不改他人任务的租约。
- 不提交私照、密钥、库存数据库、模型权重。
- 不用"我觉得"当验收证据；AI 写的测试不构成独立证明。
```

### 7.2 MCP 接入（推荐）

在**当前 profile** 的 `cordis.patch.yml`（`%USERPROFILE%\.dsh\profiles\<profile>\cordis.patch.yml`）追加一个 insert 条目：

```yaml
- insert:
    - id: mcp-team
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: team
        transport: streamable-http
        url: https://team.example.com/mcp
        headers:
          Authorization: !!js '`Bearer ${process.env.TEAM_TOKEN}`'
        toolCallTimeoutMs: 15000
        failOnStartupError: false
```

生效后工具会以 `mcp__team__*` 出现在工具列表里。注意三点：

- 该 plugin 需在当前 profile 可解析（桌面 bundle 自带；web profile 若缺，用 `dsh plugin add` 或从桌面 profile 的 `node_modules` 补齐）。
- Token 走环境变量，**不要**写进 YAML 原文。
- 先在一台机器上验证 `mcp__team__status` 能调通，再复制到另外四台。

### 7.3 兜底 CLI：`tools/teamctl.py`

给 MCP 暂不可用（版本差异、启动失败）的人用同一套协议，输出单行 JSON 方便模型读取：

```powershell
python tools/teamctl.py sync --json
python tools/teamctl.py claim T-0142 --branch codex/T-0142-inventory-idempotency
python tools/teamctl.py renew T-0142
python tools/teamctl.py handoff T-0142 --to agent-b --acceptance "pytest backend/tests -q"
python tools/teamctl.py inbox
```

实现只用标准库 `urllib`，避免给五台机器再加依赖；Python 3.12 与仓库现有环境一致。

### 7.4 每轮工作流（建议写进 `docs/team-workflow.md`）

```text
sync → 处理未读 → 续租 → 认领新任务 → 拉分支 → 实现 → 跑 acceptance
→ push + PR → handoff → 等 review → 人签收 → complete
```

### 7.5 可选：技能包与提醒

- 把上面流程固化成一个 DSH 技能（`team-collab`），路由描述写"任务认领 / 交接 / 收件箱"；这样 Agent 不必每次翻文档。
- `schedule_create` 每 15 分钟提醒检查收件箱，作为轮次之外的低频巡检；它不是跨机器通知，仅作习惯兜底。

## 8. 服务器与部署

推荐最小栈：**FastAPI + SQLite(WAL) + Caddy（自动 TLS）**，全部 Docker Compose。

```yaml
services:
  team:
    build: ./team-server
    environment:
      TEAM_DB: /data/team.db
      TEAM_ADMIN_TOKEN_FILE: /run/secrets/admin_token
    volumes: [team-data:/data]
    restart: unless-stopped
  caddy:
    image: caddy:2
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
```

```text
team.example.com {
    reverse_proxy team:8765
}
```

要点：

- **只暴露 443**，服务端口绑 `127.0.0.1`；没有域名时用 Tailscale/内网 IP + 自签证书，但别裸奔 HTTP。
- **备份**：每日 `sqlite3 .backup` 到另一块盘，保留 7 天；服务端不存照片，备份体积可忽略。
- **日志**：结构化 JSON，含 `agent_id`、`task_id`、`idempotency_key`；不打印 token。
- **监控**：`/health` + 简单探活；5 个 Agent 的负载用不到 Redis，单进程 SSE 足够。
- **审计**：`events` 表只追加；提供 `/admin/audit?task_id=` 给人事后复盘。
- **隐私**：协调服务只存任务元数据与消息，**不存**室内照片、物品数据库、模型输出。

## 9. 落地路线

| 阶段 | 内容 | 产出 | 工期 |
| --- | --- | --- | --- |
| 0 本机验证 | 起本地服务 + `teamctl` + 6 条 fixture 测试；我在这台机器上生成 5 个 teammate 走一遍协议 | 协议测试报告 + 修正后的 OpenAPI | 4–6 小时 |
| 1 服务器上线 | 部署、TLS、5 人各自配 MCP、`AGENTS.md` 进仓库、一次演练 | 5 个 Agent 能认领/交接/评审 | 2–3 天 |
| 2 与 GitHub 打通 | Issue↔任务双向同步、PR 关联校验、合并队列、审计报表、写作任务模式 | 无人值守也能查 | 约 1 周 |

阶段 0 在**一台机器**上做，不需要五个人到场；阶段 1 才是真正的跨机器联调。

## 10. 验收用例（按顺序跑）

1. **并发认领**：5 个并发 `claim` 同一任务 → 恰好 1 个 200、4 个 409；库里只有一条活跃 claim。
2. **租约接管**：owner 停止心跳超过 TTL → 另一 Agent 认领成功；原 owner `renew` 返回 410；事件流出现 `lease_expired` 与 `superseded`。
3. **交接可复现**：`handoff` 的 acceptance 命令在干净 clone 上通过，接收方 `accept` 后 owner 变更。
4. **范围互斥**：两个任务 `scope_paths` 相交 → 第二个 claim 返回 423；释放后重试成功。
5. **幂等**：同一 `Idempotency-Key` 重放 5 次建任务 → 只产生 1 条，返回同一 id。
6. **断网恢复**：请求超时后同 key 重试不产生双写；心跳丢失恢复后归属正确。
7. **审计完整**：任意任务的状态时间线可由 `events` 完整重放。
8. **写作任务模式**（若启用）：同一章节文件的两个任务冲突被拒，提示按章节拆范围。

## 11. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 五台机器 DSH 版本不一致 | MCP 配置不生效、`AGENTS.md` 行为不同 | 接入前统一版本；保留 `teamctl` 兜底（不依赖 MCP） |
| Agent 不遵守协议、直接改文件 | 范围互斥失效 | 这是协作规范不是安全边界：靠 AGENTS.md 置顶 + PR 检查 + 人工评审；服务端只能在认领阶段拦截 |
| 服务器单点/断网 | 无法认领与交接 | 降级模式（§4.7），交付物仍走 git |
| Token 泄露 | 冒用身份 | 每人独立 token、可撤销轮换、审计定位；不进仓库与日志 |
| 消息洪水 | Agent 收件箱噪音 | 按任务线程聚合；`sync` 默认只返回未读与高优先级；广播限管理员 |
| 租约过短/过长 | 频繁接管或长期占坑 | 默认 90 分钟，可按任务类型配置；接管留审计 |
| 写作类任务粒度太粗 | 范围冲突频繁 | 按章节/文档单元拆任务；一条任务一个文件或一个章节 |

## 12. 与 `CONTRIBUTING.md` 的衔接

本方案是**执行层**，不替换现有规范：

- Issue / PR / 分支 / CI / 人工核查清单全部保留。
- 新增的只有"谁在做、做到哪、交给谁"的机器可读记录。
- `CONTRIBUTING.md` 第 19 条"AI 写的测试不构成独立证明"继续有效：`review` 里 `human_approved` 是硬字段。
- 不改 `.github/workflows/` 的既有检查；阶段 2 才增加"PR 必须关联任务"的可选校验。

## 13. 需要你确认的决策点

1. **服务器条件**：什么系统？能否装 Docker？有没有域名和 TLS（还是先用内网 IP / Tailscale）？
2. **接入方式**：五个人是否都允许改 DSH profile 配 MCP；如果有人的版本旧，是否接受先只用 `teamctl` CLI 兜底？
3. **任务范围**：先只接代码任务，还是把计划书/技术文档这类**写作任务**一起纳入（按章节拆 scope）？
4. **权限**：谁持有 admin（建任务、改状态、人工签收、合并 main）？Agent 能否自动建任务（我建议：能建，但状态最多到 `pending`，需人确认才进可认领池）。
5. **是否同意阶段 0 先在这台机器上起服务、用 5 个本地 Agent 演练**（会新增 `AGENTS.md`、`tools/teamctl.py`、`team-server/`，不改现有业务代码）。

## 附录 A：评审通过后才会动的文件

| 文件 | 变更 |
| --- | --- |
| `AGENTS.md` | 新增（§7.1 草案） |
| `docs/agent-collaboration.md` | 本文，评审后定稿 |
| `docs/team-workflow.md` | 新增每轮工作流与故障处理 |
| `tools/teamctl.py` | 新增兜底 CLI（标准库实现） |
| `team-server/` | 新增协调服务（FastAPI + SQLite + SSE + MCP 适配） |
| `CONTRIBUTING.md` | 加一段指向本协议，不删改原有条款 |
| `.github/workflows/` | 阶段 2 才加 PR 关联校验 |

## 附录 B：与"共同写作"的关系

如果后续要让五个 Agent 共同产出一份计划书/申报材料，不需要另起一套系统：把书写拆成 `kind=doc` 的任务，`scope_paths` 指向章节文件，合并由章节 owner 执行；交接时附上片段与引用来源。**同一章节同一时刻只有一个 owner**，这是唯一能避免"五份文风互相覆盖"的约束。

## 附录 C：决策记录（2026-11-04）

| 事项 | 已确认 |
| --- | --- |
| 服务器 | Debian + Docker，自建协调服务 |
| DSH 版本 | 五人全部最新版；MCP 为主接入，`teamctl` CLI 兜底 |
| 任务范围 | 代码与写作任务全部纳入；写作按章节/文件拆 `scope_paths`，同一章节单一 owner |
| 权限 | 团队负责人本人持有 admin（建任务、人工签收、合并 main） |
| 阶段 0 | 已在本机用 5 个 agent 跑通认领、重复认领拒绝、交接、评审、签收与全员可见，见 [phase0-report.md](phase0-report.md) |
