import { useCallback, useEffect, useState } from "react";
import { api, type InventoryEvent, type Plan, type Scene } from "./api/client";
import SceneViewer from "./components/SceneViewer";
import { categoryColors } from "./geometry";

export default function App() {
  const [scene, setScene] = useState<Scene | null>(null);
  const [events, setEvents] = useState<InventoryEvent[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [preview, setPreview] = useState(false);
  const [selectedId, setSelectedId] = useState("camera");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [confirmApply, setConfirmApply] = useState(false);
  const select = useCallback((id: string) => setSelectedId(id), []);
  async function refresh() {
    const [next, history] = await Promise.all([api.scene(), api.events()]);
    setScene(next);
    setEvents(history);
    setPlan(null);
    setPreview(false);
    setConfirmApply(false);
  }
  useEffect(() => {
    let active = true;
    Promise.all([api.scene(), api.events()])
      .then(([next, history]) => {
        if (active) {
          setScene(next);
          setEvents(history);
        }
      })
      .catch(() => {
        if (active) setError("后端尚未连接。请启动 127.0.0.1:8000 后重试。");
      });
    return () => {
      active = false;
    };
  }, []);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，请刷新后重试");
    } finally {
      setBusy(false);
    }
  }
  const selected = scene?.items.find((i) => i.id === selectedId);
  const shown =
    scene?.items.filter((i) =>
      `${i.name} ${i.category}`.includes(query.trim()),
    ) ?? [];
  const stored = scene?.items.filter((i) => i.status === "stored").length ?? 0;
  const proposed = preview && plan?.status === "FEASIBLE" ? plan : null;
  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ▦
          </span>
          <div>
            <strong>收纳工作台</strong>
            <span>AI STORAGE / 开发原型</span>
          </div>
        </div>
        <nav aria-label="当前工作区">
          <span className="active-nav">空间与物品</span>
        </nav>
        <div className="connection">
          <i className={scene ? "online" : ""} />
          {scene ? "本地服务已连接" : "等待后端连接"}
        </div>
      </header>
      <main>
        <section className="page-heading">
          <div>
            <div className="eyebrow">空间实验室 / WORKSPACE 01</div>
            <h1>{scene?.name ?? "连接你的收纳空间"}</h1>
            <p>先看清物品，再验证布局。每一次真实移动，都有记录。</p>
          </div>
          <button disabled={busy} onClick={() => void run(refresh)}>
            刷新场景
          </button>
        </section>
        <div className="sample-banner">
          <span>合成演示数据</span>非照片识别结果 · 当前使用 6
          件虚拟物品验证接口 · 视觉模型尚未接入
        </div>
        {error && (
          <div className="notice error" role="alert">
            {error}
          </div>
        )}
        {message && (
          <div className="notice" role="status">
            {message}
          </div>
        )}
        {!scene ? (
          <section className="empty">
            <h2>{error ? "暂时无法加载场景" : "正在读取场景…"}</h2>
            <p>启动后端后点击“刷新场景”。不会用假数据掩盖连接失败。</p>
          </section>
        ) : (
          <>
            <div className="workspace">
              <aside className="inventory panel">
                <div className="panel-heading">
                  <h2>物品清单</h2>
                  <span>{scene.items.length} 件</span>
                </div>
                <label className="search">
                  <span className="sr-only">搜索物品</span>
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="搜索名称或分类"
                  />
                </label>
                <div className="inventory-summary">
                  在库 {stored} <span>取出 {scene.items.length - stored}</span>
                </div>
                <div className="item-list">
                  {shown.length === 0 && (
                    <p className="no-results">没有匹配的物品</p>
                  )}
                  {shown.map((item) => (
                    <button
                      key={item.id}
                      className={`item-row ${selectedId === item.id ? "selected" : ""}`}
                      aria-pressed={selectedId === item.id}
                      onClick={() => setSelectedId(item.id)}
                    >
                      <span
                        className="item-swatch"
                        style={{
                          background:
                            categoryColors[item.category] ?? "#a5aba9",
                        }}
                      />
                      <span>
                        <strong>{item.name}</strong>
                        <small>
                          {item.category} ·{" "}
                          {item.status === "stored" ? "在库" : "已取出"}
                        </small>
                      </span>
                      {!item.movable && <span className="locked">固定</span>}
                    </button>
                  ))}
                </div>
                <div className="inventory-foot">
                  数据版本 v{scene.version}
                  <br />
                  单位 mm · 物品均为简化包围盒
                </div>
              </aside>
              <section className="scene-panel panel" aria-label="空间预览">
                <div className="scene-toolbar">
                  <div className="segmented">
                    <button
                      className={!preview ? "chosen" : ""}
                      onClick={() => setPreview(false)}
                      aria-pressed={!preview}
                    >
                      当前布局
                    </button>
                    <button
                      className={preview ? "chosen" : ""}
                      disabled={!plan || plan.status !== "FEASIBLE"}
                      onClick={() => setPreview(true)}
                      aria-pressed={preview}
                    >
                      建议布局
                    </button>
                  </div>
                  <span>3D / 毫米</span>
                </div>
                <div className="canvas-wrap">
                  <SceneViewer
                    scene={scene}
                    plan={proposed}
                    selectedId={selectedId}
                    onSelect={select}
                  />
                  <div className="view-label">
                    {preview
                      ? "方案预览 · 尚未更改库存"
                      : "当前记录 · 可点击物品"}
                  </div>
                  <div className="view-controls">
                    拖动旋转 · 滚轮缩放 · 左侧清单可键盘选择
                  </div>
                </div>
                <div className="scene-caption">
                  <span>
                    <i style={{ background: "#699d89" }} />
                    学习
                  </span>
                  <span>
                    <i style={{ background: "#7f9bb9" }} />
                    数码
                  </span>
                  <span>
                    <i style={{ background: "#c6a76f" }} />
                    生活
                  </span>
                  <span className="caption-end">
                    双层柜体 · 900 × 400 mm / 层
                  </span>
                </div>
              </section>
              <aside className="details panel">
                <div className="panel-heading">
                  <h2>物品详情</h2>
                  <span>已确认记录</span>
                </div>
                {selected ? (
                  <>
                    <div className="detail-category">{selected.category}</div>
                    <h3>{selected.name}</h3>
                    <p className="muted">来源：合成样例 / {selected.id}</p>
                    <dl>
                      <div>
                        <dt>尺寸 / 宽 × 深 × 高</dt>
                        <dd>
                          {selected.size.width} × {selected.size.depth} ×{" "}
                          {selected.size.height} mm
                        </dd>
                      </div>
                      <div>
                        <dt>
                          {selected.status === "stored"
                            ? "当前记录位置"
                            : "原归还位置（可能被占用）"}
                        </dt>
                        <dd>
                          {
                            scene.shelves.find(
                              (s) => s.id === selected.placement.shelf_id,
                            )?.name
                          }{" "}
                          · x {selected.placement.x} / y {selected.placement.y}
                        </dd>
                      </div>
                      <div>
                        <dt>状态</dt>
                        <dd>
                          {selected.status === "stored" ? "在库" : "已取出"} ·{" "}
                          {selected.movable ? "允许移动" : "固定不动"}
                        </dd>
                      </div>
                    </dl>
                    {proposed?.placements[selected.id] && (
                      <p className="proposal-position">
                        建议：
                        {
                          scene.shelves.find(
                            (s) =>
                              s.id ===
                              proposed.placements[selected.id].shelf_id,
                          )?.name
                        }{" "}
                        · x {proposed.placements[selected.id].x} / y{" "}
                        {proposed.placements[selected.id].y}
                      </p>
                    )}
                    <button
                      className="wide"
                      disabled={busy || selected.status !== "stored"}
                      onClick={() =>
                        void run(async () => {
                          await api.lock(selected, scene.version);
                          await refresh();
                          setMessage("已更新可移动性，旧方案已清除。");
                        })
                      }
                    >
                      {selected.movable ? "设为固定物品" : "允许移动此物品"}
                    </button>
                    <button
                      className="wide primary"
                      disabled={
                        busy ||
                        (!selected.movable && selected.status === "stored")
                      }
                      onClick={() =>
                        void run(async () => {
                          await api.inventory(selected, scene.version);
                          await refresh();
                          setMessage("取还记录已保存。");
                        })
                      }
                    >
                      {selected.status === "stored" ? "记录取出" : "归还原位"}
                    </button>
                    <p className="helper">
                      操作代表你已实际取还物品。归还原位若发生重叠，后端会拒绝写入。
                    </p>
                  </>
                ) : (
                  <p className="helper">从清单选择物品以查看详情。</p>
                )}
              </aside>
            </div>
            <div className="bottom-grid">
              <section className="planning panel">
                <div>
                  <div className="eyebrow">LAYOUT BASELINE</div>
                  <h2>生成一个可检查的布局</h2>
                  <p>先验证边界、碰撞和固定物品。不把贪心结果称为“最优解”。</p>
                </div>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      const result = await api.plan(scene.version);
                      setPlan(result);
                      setPreview(result.status === "FEASIBLE");
                      setConfirmApply(false);
                    })
                  }
                >
                  {busy ? "处理中…" : "生成收纳建议"}
                </button>
                {plan && (
                  <div className="plan-result" role="status">
                    <strong>
                      {plan.status === "FEASIBLE"
                        ? `找到几何可行布局 · ${plan.moved_count} 件物品改变位置`
                        : "基线未找到完整方案，不代表问题无解"}
                    </strong>
                    {plan.notes.map((n, i) => (
                      <p key={i}>{n}</p>
                    ))}
                    {plan.status === "FEASIBLE" && (
                      <>
                        <label className="confirm">
                          <input
                            type="checkbox"
                            checked={confirmApply}
                            onChange={(e) => setConfirmApply(e.target.checked)}
                          />
                          我已按建议实际摆放物品，并核对拿取与稳定性
                        </label>
                        <button
                          disabled={busy || !confirmApply}
                          onClick={() =>
                            void run(async () => {
                              await api.apply(plan, scene.version);
                              await refresh();
                              setMessage("已将执行后的布局记入库存。");
                            })
                          }
                        >
                          确认执行并更新记录
                        </button>
                      </>
                    )}
                  </div>
                )}
              </section>
              <section className="activity panel">
                <div className="panel-heading">
                  <h2>最近操作</h2>
                  <span>SQLite 持久化</span>
                </div>
                {events.length === 0 ? (
                  <p className="muted">
                    还没有操作记录。生成建议不会修改库存。
                  </p>
                ) : (
                  <ul>
                    {events.slice(0, 4).map((event) => (
                      <li key={event.request_id}>
                        <span>
                          {event.operation.route === "inventory"
                            ? `${event.operation.action === "take" ? "取出" : "归还"} · ${scene.items.find((i) => i.id === event.operation.item_id)?.name ?? event.operation.item_id}`
                            : event.operation.route.startsWith("apply/")
                              ? "确认收纳布局"
                              : "更新可移动性"}
                        </span>
                        <time>
                          {new Date(event.created_at).toLocaleTimeString(
                            "zh-CN",
                            { hour12: false },
                          )}
                        </time>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </>
        )}
        <footer>
          本地研发框架 · 未接入视觉模型、CP-SAT 或深度硬件{" "}
          <a href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">
            查看 API 文档 ↗
          </a>
        </footer>
      </main>
    </>
  );
}
