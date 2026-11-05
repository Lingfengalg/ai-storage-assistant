# 阶段 1 部署状态（2026-11-05）

> 本文只记录可公开的部署事实，不含任何 token、密码或密钥。

## 已完成

| 项 | 状态 |
| --- | --- |
| 服务器 | Debian 12 (bookworm)，4C/3.7G，40G 盘，`VM-0-15-debian` |
| 容器运行时 | Docker 29.9.3 + Compose v5.7（`get.docker.com --mirror Aliyun`） |
| 镜像加速 | `/etc/docker/daemon.json` 使用腾讯云内网 registry mirror |
| 代码位置 | `/opt/chuyan/team-server`（SFTP 上传，Dockerfile 构建） |
| 服务模式 | `docker-compose.internal.yml`，绑定 `127.0.0.1:8765`，healthy 运行 |
| 数据 | 容器卷 `team-server_team-data`，`/data/team.db` |
| Agent | `provision.py` 已创建 agent-a…agent-e；token 仅存在于管理员本机 `.work/prod-tokens.json`（不入库、不回显） |
| 验证 | 容器内 `curl /api/health` 正常；用 agent-a token 调 `/api/whoami` 成功；任务板为空（生产库，无演练数据） |

## 未完成 / 阻塞

| 项 | 原因 | 需要的动作 |
| --- | --- | --- |
| 五人跨机访问 | 公网 80 曾可达，但 ACME HTTP-01 被腾讯云"未备案域名"拦截页阻断；443 被安全组封禁 | 二选一：① 授权 Tailscale；② 腾讯云安全组放行 TCP 443 后重试 TLS-ALPN |
| Tailscale 通道 | 已安装 1.104.5，节点 `chuyan-team` 处于 `NeedsLogin` | 管理员打开服务端 `tailscale up` 输出的授权链接 |
| AGENTS.md 生效 | 契约文件在分支 `feat/team-coordination` 根部，未进 main | 评审合并后五人 `git pull` |
| 五人 MCP 配置 | 等待服务可达后再填 URL | 可达后按 [phase1-deployment.md](phase1-deployment.md) §3 配置 |

## 当前对外暴露面

- 安全的：22/tcp（SSH，root 密码登录，建议尽快换成密钥并改密）；
- 未开：80、443、8765（服务只在回环）；
- 数据面：看板与 API 都不可从公网访问，因此暂无泄露风险，但也还无法供团队使用。

## 回滚与重起

```bash
cd /opt/chuyan/team-server
docker compose -f docker-compose.internal.yml ps          # 查看
docker compose -f docker-compose.internal.yml restart     # 重启
docker compose -f docker-compose.internal.yml down        # 停止（数据卷保留）
```
