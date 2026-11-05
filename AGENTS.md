# 团队协作协议（五 Agent 必读 · 阶段 0 草案）

> 评审通过后这份内容会移到仓库根目录的 `AGENTS.md`，届时 DSH 会在每个会话的首轮自动注入。
> 阶段 0 演练时由 Lead 直接把本文件路径写进每个 agent 的任务说明。

你是「雏雁 · AI 收纳辅助系统」团队的一员。五个人各自运行 DSH，共享本仓库和一台协调服务。你的记忆不会跨会话保留，所以**共享状态只认协调服务**，不认上下文。

## 环境

```powershell
$env:TEAM_URL  = "http://127.0.0.1:8765"   # 部署后换成 https://team.example.com
$env:TEAM_TOKEN = "<你的 token>"
python tools/teamctl.py status
```

也可以用 MCP 工具（`mcp__team__sync`、`mcp__team__claim`……），语义与 CLI 完全一致。

## 每轮开始（强制）

1. `python tools/teamctl.py sync --since 0`，读 `events`、`unread_messages`、`my_tasks`、`available_tasks`。
2. 有未读消息就在本轮处理；有人把任务交接给你，先跑验收命令再 `accept`。
3. 租约剩余不足 20 分钟时先 `renew`。
4. 没有在办任务 → 从 `available_tasks` 挑一个与你的能力匹配的。

## 认领与开工

- 动手前必须 `claim`。返回 409 表示已被别人认领——换一个任务，不要并行重复做。
- 返回 423 表示范围冲突：先看 `conflicts` 里的任务和 `scope_paths`，改范围或等对方释放。
- 分支名 `codex/<task-id>-<简短英文描述>`，从最新 `origin/main` 拉。
- **只改任务 `scope_paths` 内的文件**。要改 `shared/`、`CONTRIBUTING.md`、`docs/architecture.md`，必须在任务里声明且确认没人持有。
- 不推 `main`，不 force push 共享分支，不改别人的租约。

## 交付

1. 本机运行任务记录里的 `acceptance` 命令，确认通过。
2. 提交、推送、开 PR，关联任务 ID。
3. `request-review --evidence "..."`：证据写验收命令输出、CI 链接或截图说明。没有证据不要送审。
4. 送审后不要继续改同一分支；评审期间任务已释放租约。
5. 只有 admin 人工签收后 `complete` 才会成功。**不要把"我觉得做完了"当证据。**

## 交接

交接必须结构化，接收方要能独立复现：

```powershell
python tools/teamctl.py handoff T-0001 --to agent-b `
  --acceptance "pytest backend/tests -q" `
  --summary "改了什么、为什么、没做什么" `
  --question "未决问题"
```

接收方：先跑 `acceptance`，通过后 `accept <handoff_id> --output "42 passed"`。不通过就退回并说明。

## 禁止

- 不提交凭据、真实室内照片、个人物品数据库、模型权重。
- 不伪造验收输出，不替人签收。
- 不绕过任务板直接开工；重复劳动和范围冲突必须在认领阶段暴露。
- 不把服务当文件存储；交付物只走 git。

## 出错时

| 返回 | 含义 | 处理 |
| --- | --- | --- |
| 409 | 任务已被认领 | 换任务，发消息问对方进度 |
| 410 | 租约丢失 | 立即停止推送，重新 sync 看任务归属 |
| 423 | 范围冲突 | 调整 scope 或等待，不要强行改文件 |
| 428 | 缺前置（没人工签收/没跑验收） | 补齐证据或等 admin |
| 401 | token 无效 | 检查环境变量，不要重试到封禁 |
