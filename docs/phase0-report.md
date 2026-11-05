# 阶段 0 实施报告：五 Agent 协作协议本机验证

> 日期：2026-11-04 · 状态：**已完成，等待评审与阶段 1 部署**
> 方案依据：[agent-collaboration.md](agent-collaboration.md) · Agent 契约草案：[team-AGENTS.md](team-AGENTS.md) · 操作手册：[team-workflow.md](team-workflow.md)

## 结论

在**不改 DSH 本体、不共享工作目录**的前提下，本机把协调服务、`teamctl` CLI、MCP 适配器和看板跑通了，并用 **5 个真实本地 Agent** 完成了 6 个任务的认领 → 交付 → 送审 → 人工签收 → 完成，外加一次跨 Agent 交接。所有验收用例通过，无重复认领、无范围冲突、无遗留租约。

一句话：**"一个人开工，其他人下一轮就知道"已经可用**，剩下的是把它部署到 Debian 服务器并接上五台机器。

## 交付物

| 路径 | 内容 |
| --- | --- |
| [team-server/app/](../team-server/app/) | 协调服务：任务、租约、幂等、消息、事件流、审计、看板 |
| [team-server/mcp_server.py](../team-server/mcp_server.py) | MCP stdio 适配器，15 个 `team_*` 工具 |
| [team-server/seed.py](../team-server/seed.py) | 本地演练数据（5 agent + 5 任务 + token） |
| [team-server/Dockerfile](../team-server/Dockerfile)、[docker-compose.yml](../team-server/docker-compose.yml)、[Caddyfile](../team-server/Caddyfile) | Debian 部署件（服务 + 自动 TLS） |
| [tools/teamctl.py](../tools/teamctl.py) | 标准库 CLI，MCP 不可用时兜底 |
| [docs/team-AGENTS.md](team-AGENTS.md) | 仓库 `AGENTS.md` 草案（阶段 1 移到根目录） |
| [docs/team-workflow.md](team-workflow.md) | 日常操作、冲突处理、降级模式 |
| [team-server/tests/test_protocol.py](../team-server/tests/test_protocol.py) | 9 条协议验收测试 |
| [team-server/tests/mcp_smoke.py](../team-server/tests/mcp_smoke.py) | MCP 协议握手与工具调用冒烟 |

## 验收结果

### 自动化测试（9/9 通过）

```powershell
cd team-server
..\.venv\Scripts\python.exe -m pytest tests -q
# 9 passed
```

覆盖：并发认领唯一赢家、租约过期接管并拒绝旧 owner、交接必须先跑验收、范围冲突 423、建任务幂等（同 key 5 次 1 条）、无人工签收不能 done、全员可见性、审计时间线重放。

### MCP 冒烟

`initialize` 协商到协议 `2025-11-25`，`tools/list` 返回 15 个工具，`team_status` 与 `team_sync` 均返回正确 JSON。DSH 侧配置后工具名会是 `mcp__team__*`。

### 5 Agent 演练（真实并发）

| 任务 | 认领者 | 结果 |
| --- | --- | --- |
| T-0001 场景边界 | agent-a | done，review #3 签收 |
| T-0002 布局约束 | agent-b | done，review #5 签收 |
| T-0003 渲染检查点 | agent-c | done，review #4 签收 |
| T-0004 库存失败案例 | agent-d | done，review #2 签收 |
| T-0005 协作使用说明 | agent-e | done，review #1 签收 |
| T-0006 交接演练 | agent-a → agent-c | handoff #1 accepted，review #6 签收，done |

演练里验证到的行为：

- **防止重复劳动**：agent-b 在 T-0001 已被认领后尝试抢占，服务端返回 `409 already_claimed` 并给出 owner，agent-b 改做自己的 T-0002。
- **全员可见**：agent-e 在第二轮 `sync` 中看到其他 4 个 agent 的认领记录、T-0006 的交接链（`task_claimed → task_handoff → handoff_accepted → review_requested`）以及所有 `task_completed`。
- **交接可复现**：agent-c 先在本机跑 `cmd /c "if exist .work\rehearsal\handoff.md (exit 0) else (exit 1)"`（exit 0），才 `accept`；随后只读比对边界结论，再送审。
- **人仍是闸门**：5 个 agent 都在 `review` 停住，必须等我（admin）逐条 `decide --yes` 才能 `complete`；未签收时调用 `complete` 返回 428。

数据库终态：`tasks` 6 条全部 `done`，`claims` 0 条，`handoffs` 0 条 open，`reviews` 6 条全部 approved，事件流 32 条。

## 实现要点

- **原子认领**：SQLite WAL + `BEGIN IMMEDIATE`，同一事务内做租约过期清理、状态检查、能力检查、范围冲突检查、写 claim 与事件。并发 5 个请求恰好 1 个成功。
- **租约**：默认 90 分钟，心跳续租；`lease_until` 过期后任务回到 `pending`，原 owner 的 `renew/complete` 返回 410，事件流记录 `lease_expired`。
- **范围互斥**：`scope_paths` 前缀比较，空范围视为“影响一切”；冲突返回 423 与冲突任务列表。
- **幂等**：建任务必须带 `Idempotency-Key`，同 key 重放返回首次结果；缺失返回 428。
- **交接**：必须写 `acceptance_cmd`、摘要与未决问题；接收方 `ran=false` 时 428，接受后租约转移。
- **人工签收**：`reviews.human_approved` 是 `complete` 的硬前置；只有 admin token 能签。
- **事件流**：所有状态变化写 append-only `events`；看板用 SSE 秒级推送，Agent 在每轮 `sync` 拉取增量（DSH 轮次模型）。
- **接入面**：REST 与 MCP 走同一层服务代码；CLI 只依赖标准库，Windows/Linux 都能跑。

## 演练中发现并修复的问题

| 问题 | 处理 |
| --- | --- |
| `teamctl activity` 请求了不存在的 `/api/audit`（404） | 改为 `/api/activity`，已修复并回归 |
| `admin-reviews --all` 没有把 `open_only=0` 传给服务端 | 已修复 |
| PowerShell 下 JSON 输出被按 GBK 解码 | CLI/MCP 强制 UTF-8 stdout，并建议 `PYTHONUTF8=1` |
| 任务创建接口在 admin 下直接进 `pending`，与 seed/测试预期不符 | 统一为“admin 建即发布，Agent 建进 draft” |

## 已知限制（阶段 1 前需知晓）

1. **单进程 SQLite**：够 5 个 Agent 用；多副本/高可用再换 Postgres（见方案 §8）。
2. **"实时"是相对人而言**：看板秒级；Agent 每轮同步一次，不会有推送打断。
3. **服务端不是安全边界**：只能拦住认领，拦不住绕过协议直接改文件；最后一道闸仍是 git + CI + 人工评审。
4. **MCP 适配器要 Python**：每台机器用仓库自带 `.venv`；如果部署时希望零本地依赖，可改为服务端 `streamable-http`（方案 §7.2 备选）。
5. **未接 GitHub**：任务与 PR 仍靠人关联，阶段 2 再做 Issue/PR 双向同步与 CI 门禁。

## 阶段 1 部署清单（Debian + Docker）

完整手册见 [phase1-deployment.md](phase1-deployment.md)，配套 `team-server/provision.py`（正式 Agent 初始化）、`tools/team_doctor.py`（每台机器体检）和 `team-server/mcp.dsh.example.yml`。

1. 服务器：装 Docker → `cd team-server` → 写 `.env`（`TEAM_ADMIN_TOKEN`）→ 改 `Caddyfile` 域名 → `docker compose up -d --build`。
2. 用 admin token 建 5 个正式 Agent（`admin-create-agent`），把 token 一对一发给组员。
3. 每台机器：配 profile 的 `cordis.patch.yml`（MCP stdio，见 [team-server/README.md](../team-server/README.md)），重启 DSH，确认工具列表出现 `mcp__team__*`。
4. 把 `docs/team-AGENTS.md` 移到仓库根目录 `AGENTS.md`（DSH 会自动注入）。
5. 用一份真实任务做首轮联调：一个人认领、其他人确认能在 `sync`/看板看到，再逐个打开。

需要你提供：**服务器域名或内网地址**、**是否已有 DNS/TLS**、**token 分发方式**（我建议每人一个独立 token，不共用）。

## 复现方式

```powershell
# 起服务
$env:TEAM_ADMIN_TOKEN = 'dev-admin-token'
cd team-server
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765

# 另开终端：造数据并查看看板 http://127.0.0.1:8765/
$env:TEAM_ADMIN_TOKEN = 'dev-admin-token'
..\.venv\Scripts\python.exe seed.py --db ..\.work\team.db --out ..\.work\team-tokens.json
```

本次演练数据库在 `.work/team.db`（已 gitignore），未提交任何 token 或数据库文件。
