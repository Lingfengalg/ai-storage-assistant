# 团队协作操作手册

配套文件：[五 Agent 协作方案](agent-collaboration.md) · [Agent 协议草案](team-AGENTS.md)

## 一个人一条命令的日常

```powershell
# 我是谁
python tools/teamctl.py status

# 每轮第一件事：看看别人在干什么、有没有我的消息
python tools/teamctl.py sync --since 0

# 认领
python tools/teamctl.py claim T-0003 --branch codex/T-0003-render-check

# 干活中续租（默认 90 分钟，剩 20 分钟就该续）
python tools/teamctl.py renew T-0003

# 交付
python tools/teamctl.py review T-0003 --evidence "npm test: 31 passed，构建成功"

# 完成（需要 admin 先签收，否则 428）
python tools/teamctl.py complete T-0003
```

## 管理员（你）

```powershell
# 建任务；Agent 建的任务是 draft，需要你发布
python tools/teamctl.py admin-create-task --title "感知模块尺寸来源字段" `
  --kind code --scope backend/app/models.py --capability perception `
  --acceptance "pytest backend/tests -q"

# 发布 Agent 起草的任务
python tools/teamctl.py admin-publish T-0007

# 看谁等着签收
python tools/teamctl.py admin-reviews

# 签收（带一句结论，会发回给提交者）
python tools/teamctl.py decide 3 --yes --note "几何检查覆盖了反例"

# 审计某个任务的时间线
python tools/teamctl.py admin-audit --task T-0003
```

## 实时看板

浏览器打开服务地址（本地 `http://127.0.0.1:8765/`），粘贴 admin token：

- 任务表：状态、负责人、租约剩余；
- 右侧事件流：谁认领、谁交接、谁送审，**这就是"一个人工作其他人知道"**；
- 事件流来自 SSE，人看到的是秒级；Agent 在每轮 `sync` 时滞后一个轮次，这是 DSH 的轮次模型决定的，不是服务缺陷。

## 冲突处理

| 场景 | 表现 | 处理 |
| --- | --- | --- |
| 两人抢同一任务 | 后到者 409 | 后到者换任务；如确有并行必要，拆出独立 scope |
| 范围重叠 | 423 + `conflicts` | 拆任务/改 scope；不要靠"我只改一行"绕过 |
| 对方失联 | 租约到期自动回收 | 直接认领；原 owner 的 `renew` 会得到 410 |
| 交接后验收不过 | 接收方不 `accept` | 退回并说明失败输出，原 owner 修复或重新交接 |

## 降级模式（服务不可用）

1. 停止新认领；已认领的继续做，但不接管、不交接。
2. 交付仍走分支 + PR；PR 描述注明"协调服务不可用，人工确认无重复工作"。
3. 群公告冻结的目录范围。
4. 恢复后由 admin 用 `admin-audit` 补看时间线，需要时补建任务记录。

## 安全边界

- 服务端只能拦住"认领"这一步，无法阻止 Agent 绕过协议直接改文件；最后一道闸仍是 git 审计、CI 与人工评审。
- Token 每人一个，放环境变量；泄露就重建 Agent 并撤销旧 token。
- 协调服务不存照片、物品数据、模型文件。
