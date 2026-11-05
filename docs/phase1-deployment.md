# 阶段 1 部署手册：Debian + Docker，五人接入

> 前置：[阶段 0 报告](phase0-report.md) 已验收；[方案 v0.2](agent-collaboration.md) 为设计依据。
> 目标：五台机器各自运行 DSH，通过服务端协调；**一个人开工，其余人下一轮就知道**。

## 0. 先定两件事

| 决策 | 选项 | 建议 |
| --- | --- | --- |
| 域名 | 有域名 A 记录 → Caddy 自动 HTTPS；无域名 → 内网 IP / Tailscale | 有域名最好；纯内网也能跑，但不要裸 HTTP 暴露公网 |
| token 分发 | 每人一个独立 token | 用 `provision.py` 生成，一对一私发，不共用 |

## 1. 服务器（一次性）

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin git
git clone <你的仓库地址> /opt/chuyan
cd /opt/chuyan/team-server
cp .env.example .env
openssl rand -base64 24          # 输出填进 .env 的 TEAM_ADMIN_TOKEN
vim .env                          # 填 TEAM_ADMIN_TOKEN 与 TEAM_DOMAIN
docker compose up -d --build
curl https://你的域名/api/health  # 期望 {"ok":true,...}
```

没有域名时，把 `Caddyfile` 换成仅内网可用的形式：

```text
:80 {
    reverse_proxy team-server:8765
}
```

并确保 80/443 只在 Tailscale 或内网开放（云安全组不要放 0.0.0.0/0）。

### 1.1 无域名：Tailscale / 内网模式（推荐）

> 无域名模式下，下文所有 `docker compose` 命令都加 `-f docker-compose.internal.yml`。

不跑 Caddy，直接把端口绑到 Tailscale 地址，Tailscale 自身用 WireGuard 加密：

```bash
# 服务器：安装并登录同一 tailnet
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4                       # 例如 100.x.y.z

cd /opt/chuyan/team-server
cp .env.example .env
echo "TEAM_ADMIN_TOKEN=$(openssl rand -base64 24)" >> .env
sed -i "s/^TEAM_BIND_IP=.*/TEAM_BIND_IP=100.x.y.z/" .env   # 填上面查到的地址
docker compose -f docker-compose.internal.yml up -d --build

# 五台机器（同样加入 tailnet 后）验证连通性
curl http://100.x.y.z:8765/api/health
```

- 防火墙只需对 `tailscale0` 放行 8765，公网端口保持关闭；
- 五台机器的 `TEAM_URL` 填 `http://100.x.y.z:8765` 或 MagicDNS 名；
- 之后若拿到域名，换回 `docker-compose.yml`（Caddy 自动 HTTPS）即可，服务端数据不变。

### 1.2 有公网 IP、没有域名：用 sslip.io + Caddy 自动 HTTPS

`sslip.io` 把 `<任意内容>.<IP>.sslip.io` 解析到该 IP，因此不买域名也能拿到受信任的证书：

```bash
# 假设服务器公网 IP 是 203.0.113.7
cd /opt/chuyan/team-server
cp .env.example .env
sed -i 's/^TEAM_ADMIN_TOKEN=.*/TEAM_ADMIN_TOKEN=<openssl rand -base64 24 的输出>/' .env
sed -i 's/^TEAM_DOMAIN=.*/TEAM_DOMAIN=203.0.113.7.sslip.io/' .env
docker compose up -d --build

curl https://203.0.113.7.sslip.io/api/health
```

要求：服务器 80/443 入站可达（Let's Encrypt HTTP-01 验证）。
风险提示：这是**公网可达**的服务，必须保证 token 不泄露；如果不想公开，仍建议改用 Tailscale 模式（§1.1）。

**服务端后台任务**建议加 cron 每日备份（无域名模式把 `-f docker-compose.internal.yml` 加上）：

```bash
0 3 * * * docker compose -f /opt/chuyan/team-server/docker-compose.yml exec -T team-server \
  sqlite3 /data/team.db ".backup '/data/team-backup.db'"
```

## 2. 建 5 个正式 Agent（一次性）

```bash
cd /opt/chuyan/team-server
docker compose exec team-server python provision.py --db /data/team.db --out /data/tokens.json
docker compose cp team-server:/data/tokens.json ./tokens.json
# 逐条把 agent-a…agent-e 的 token 私发给对应组员
rm ./tokens.json                      # 就地删除
docker compose exec team-server rm /data/tokens.json   # 容器里也删掉
```

- 重复执行是安全的：已存在的 Agent 不会改动；要换 token 加 `--rotate`。
- 注意：`TEAM_ADMIN_TOKEN` 改了之后重启容器即可轮换 admin（服务端以环境变量为准）。

## 3. 每台机器接入（五台各做一次）

以 Windows 为例，Linux 把路径换成分隔符即可。

### 3.1 环境

```powershell
git clone <你的仓库地址> C:\Users\<你>\Documents\ChatGPT\雏雁
cd C:\Users\<你>\Documents\ChatGPT\雏雁
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install -r team-server/requirements-mcp.txt

[Environment]::SetEnvironmentVariable("TEAM_URL", "https://你的域名", "User")
[Environment]::SetEnvironmentVariable("TEAM_TOKEN", "<你的 token>", "User")
# 重新打开终端后生效
```

### 3.2 体检（必须全 PASS）

```powershell
python tools\team_doctor.py
# 期望：[PASS] health / identity / tasks / sync / mcp-sdk
```

### 3.3 接入 MCP（推荐）

1. 打开当前 profile 的 patch：`%USERPROFILE%\.dsh\profiles\<profile>\cordis.patch.yml`
   （`desktop` 或 `web`，看你现在用哪个 GUI）。
2. 把 `team-server/mcp.dsh.example.yml` 的内容追加进去，把路径改成这台机器的实际路径。
3. 重启 DSH；工具列表应出现 `mcp__team__sync`、`mcp__team__claim` 等 15 个工具。
4. 在会话里让 agent 调一次 `mcp__team__sync` 验证。

MCP 起不来时先不要折腾：`python tools/teamctl.py sync` 一样能干活，CLI 和 MCP 走的是同一套协议。

### 3.4 契约生效

把 `docs/team-AGENTS.md` 移到仓库根目录 `AGENTS.md`（单独一个 PR），再让五台机器 `git pull`。
DSH 会在每个会话首轮自动注入，之后所有 agent 每轮都会先 `sync`。

## 4. 首轮联调（约 30 分钟）

1. admin 建一个真实小任务：`python tools/teamctl.py admin-create-task --title ... --scope <单文件> --acceptance "<命令>"`；
2. 指定一人认领，其余四人在看板（`https://域名/`，填 admin token）确认能看到认领与事件流；
3. 第二个人尝试抢同一任务，确认返回 `409 already_claimed`；
4. owner 干活、`review` 送审，admin `decide --yes`，owner `complete`；
5. （可选）租约演练：临时把 `TEAM_LEASE_MINUTES` 调成 2，重启服务，让另一人等在过期后接管，确认原 owner 的 `renew` 返回 410，再调回 90 并重启。

## 5. 验收清单

- [ ] `https://域名/api/health` 返回 ok，证书有效；
- [ ] 五台机器 `team_doctor.py` 全 PASS；
- [ ] 五台机器都能看到 15 个 `mcp__team__*` 工具（或 CLI 可用）；
- [ ] 看板能看到任务、负责人、租约和实时事件；
- [ ] 抢已被认领的任务得到 409；范围重叠得到 423；
- [ ] 交接后接收方能复现验收命令；
- [ ] 未签收调用 `complete` 得到 428；
- [ ] `AGENTS.md` 在仓库根，五台机器已 pull。

## 6. 运营动作

| 场景 | 操作 |
| --- | --- |
| 某人换电脑 / token 泄露 | `python tools/teamctl.py admin-rotate agent-b`（admin 执行），旧 token 立即失效 |
| admin token 泄露 | 改 `.env` 的 `TEAM_ADMIN_TOKEN`，`docker compose up -d` 重启 |
| 服务升级 | `git pull && docker compose up -d --build`（数据在 volume `team-data`） |
| 备份 | 见 §1 cron；恢复时停服务，把备份 cp 回 `/data/team.db`，再启动 |
| 服务完全挂掉 | 进入降级模式：停止认领，交付继续走分支/PR，见 [操作手册](team-workflow.md) |

## 7. 常见问题

| 现象 | 排查 |
| --- | --- |
| MCP 工具不出现 | 确认 `@deepseek-ai/dsh-mcp-client` 在当前 profile 可解析；看 DSH 日志；先用 CLI |
| 证书签发失败 | DNS 未生效、80 端口被占用、安全组未放行 |
| `team_doctor` 401 | token 复制错、被轮换、或环境变量没重启终端 |
| Windows 输出乱码 | `set PYTHONUTF8=1`；CLI 已强制 UTF-8 |
| 409/423 频繁 | 任务粒度太粗：把 scope 拆到单文件/单章节 |
| 看板打不开 | 只绑了 127.0.0.1：通过 Caddy 访问，或临时 `ssh -L 8765:localhost:8765` |
