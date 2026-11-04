# 模块边界与数据约定

## 仓库结构

```text
backend/
  app/
    models.py       领域数据与输入校验
    demo.py         明确标记的合成场景
    geometry.py     独立几何检查器
    planning.py     可替换贪心规划基线
    store.py        SQLite、事务、版本与幂等
    main.py         FastAPI 路由与应用生命周期
  tests/           几何、API、事务与契约测试
  scripts/         OpenAPI 导出
frontend/
  src/
    api/            HTTP 客户端与生成类型
    components/     Three.js 三维视图
    geometry.ts     后端坐标到渲染坐标的唯一转换入口
    App.tsx         空间工作台与操作状态
shared/             OpenAPI 契约快照
scripts/            Windows 双服务启动
docs/               技术、启动、模块与任务说明
```

先采用模块化单体，不拆微服务、不加 Redis、不建复杂部署平台。目录按真实职责划分，不预建大量空目录。

## 几何坐标

所有尺寸使用正整数毫米。物品位置指包围盒左前下角；在某层板上使用 `x` 和 `y` 表示平面坐标。`x` 向右，`y` 向后；高度方向为 `z`，物品底部高度由层板 `elevation` 决定。

一层可以横向分成多个格子：`Shelf.columns` 是格子数，`Shelf.divider` 是竖向隔板厚度。可用宽度等于层宽减去 `(columns-1) × divider`，用 `divmod` 均分，余数优先给左侧格子（`geometry.compartment_spans`）。`Placement.column` 指明格子序号，`Placement.x` 是**该格子内**的横向偏移。因此不同格子的局部坐标可以重合而不算重叠，跨隔板摆放则必须被拒绝：`fits()` 用格子宽度约束 `x + w`，`overlaps()` 只比较同层同格的物品。单列时退化为整层宽度，行为与引入格子之前一致。

Three.js 约定 Y 轴向上，因此转换为 `(domain.x, domain.z, domain.y)`，再由左前下角转盒体中心。尺寸依然是毫米，不隐式除以 1000。90° 旋转只交换宽与深，高度不变。

目前没有自由堆叠。接触允许，严格体积相交不允许；这不意味着真实空间无需拿取余量。入口、拿取、稳定性与测量误差尚未建模。

## 规划模块

`plan_scene(scene) -> Plan` 不修改输入，也不修改库存。贪心先保留固定物品，再按底面积从大到小处理可移动物品，在现有物品右边缘/后边缘构成的候选点尝试有限朝向。独立的 `validate_layout` 再检查完整性、锁定、边界与重叠。

- `FEASIBLE`：当前简化几何模型下完整可行，**不是最优**。
- `NO_SOLUTION_FOUND`：本算法未找到完整方案，**不是已证明无解**。不返回可被误执行的部分布局。
- 结果携带输入版本；后续库存或可移动性变化会使旧方案过期。

接入 CP-SAT 时保持规划输入输出隔离，扩展状态以保留求解器真实状态和时限，不把超时改成无解。先用同一真值场景比较贪心与求解器，再引入 ALNS。

## 库存与执行

`stored` 表示在库，`taken_out` 表示已取出。取出保留原位置作为归还候选，但不保留空间占用；其他物品可能占用这个位置，因此归还必须重新做几何验证。

写操作携带 `expected_version` 与 `request_id`。SQLite `BEGIN IMMEDIATE` 将读版本、修改、几何验证、版本递增与事件保存放进同一事务。失败整体回滚。同一请求 ID 与相同内容返回首次结果，不二次更新；同一请求 ID 换内容返回 409。

客户端每次成功操作后重新读取场景，避免幂等重放的旧响应覆盖最新状态。前端不自动重试写请求；若网络结果不明，先刷新核对，不能盲目重新点击。后续可增加稳定请求 ID 的重试队列。

布局确认要求 `execution_confirmed: true`，代表用户已经实际执行。网页预览绝不等于现实位置已改变。当前实现不验证用户是否真的移动了物品。

## 主要 API

| 路径 | 方法 | 行为 |
| --- | --- | --- |
| `/api/health` | GET | 本地服务状态 |
| `/api/scene` | GET | 当前活动场景 |
| `/api/scenes` | GET | 活动场景 + 场景库摘要（名称、层数、列数、物品数、版本） |
| `/api/scenes` | POST | 由外部尺寸新建场景：推导骨架，并把活动场景的在库物品重新摆放进去 |
| `/api/scenes/activate` | POST | 切换活动场景，带 `request_id` 与 `expected_version` |
| `/api/plans` | POST | 基于指定版本生成并保存建议，不改库存 |
| `/api/plans/{id}/apply` | POST | 验证版本及执行确认，更新真实记录 |
| `/api/items/{id}/movable` | PATCH | 锁定或解锁在库物品 |
| `/api/inventory/events` | POST | 记录取出或归还 |
| `/api/inventory/events` | GET | 最近 30 次写操作记录 |
| `/api/perception/capabilities` | GET | 返回视觉能力尚未接入，不返回伪造结果 |

完整字段以自动生成的 OpenAPI 为准。

## 四个方向从哪里接入

- 感知与几何：另建观测候选模型与人工确认接口。不能让检测结果直接覆盖库存；先补尺寸来源和不确定性，再接真实图片。
- 收纳规划：替换 `planning.py` 的策略，保留独立几何检查器和基线测试。
- 三维交互：扩展 `SceneViewer` 与工作台；拖拽先写草稿，不直接落库存。
- 库存与集成：扩展 `store.py` 与路由，优先新增物品确认、归还位置调整及更正记录，再考虑多用户。

## 已知工程边界

单用户、本地开发数据库，无鉴权、无迁移工具、无云部署；场景更新目前主要通过取还/锁定/执行方案接口。开发中修改持久化模型后应使用新的测试数据库，不直接覆盖已有用户数据。前端桌面布局最低宽度 1100 px；移动端尚未适配。当前三维相机在选中物品或切换布局后重置为默认视角，后续可分离场景更新与相机生命周期。

## 场景库

SQLite 里 `scenes` 表保存全部场景，`active=1` 的行是活动场景，唯一部分索引 `scenes_single_active` 在数据库层保证最多一个活动场景。旧版本的单场景表 `scene` 只作为历史保留：`initialize()` 在 `scenes` 为空时把旧行迁入并置为活动场景，全新数据库则直接把演示场景 seed 进 `scenes`，此后不再写旧表。

`GET /api/scene`、规划、取还、锁定、执行方案全部只作用于活动场景，因此切换场景就是切换整套库存。`POST /api/scenes` 新建的场景是**非活动**的，原场景完好保留；它会把活动场景里 `status == "stored"` 的物品复制进来并按新柜体重新摆放，摆不下的丢弃并在 `skipped_item_ids` 里返回（因为新柜体没有旧柜体的物理位置，试排时忽略物品的锁定标记，但复制出的记录保留原字段）。`POST /api/scenes/activate` 走 `BEGIN IMMEDIATE` 事务，校验活动场景版本、切换 `active` 并把目标场景版本加一，`request_id` 幂等。

前端在浏览非活动场景时只允许查看：规划、取还、锁定、执行方案一律禁用，必须先显式「切换到此场景」。**规划接口不会替用户切换场景**——让一个读语义的操作隐式改动活动场景，会让"生成建议"同时改库存指向，是难以排查的状态漂移。

## 技术参考

- [FastAPI 测试文档](https://fastapi.tiangolo.com/tutorial/testing/)
- [Vite 官方入门](https://vite.dev/guide/)
- [Three.js 创建场景](https://threejs.org/manual/pages/creating-a-scene.html)
- [Three.js OrbitControls](https://threejs.org/docs/pages/OrbitControls)
