import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  api,
  type InventoryEvent,
  type Plan,
  type Scene,
  type SceneLibrary,
  type SceneSummary,
} from "./api/client";
import SceneViewer from "./components/SceneViewer";
import { categoryColors } from "./geometry";

const initialStructure = {
  rows: 2,
  columns: 2,
  width: 900,
  depth: 400,
  height: 800,
  board: 18,
  divider: 18,
};
type StructureField = keyof typeof initialStructure;

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
  const [structure, setStructure] = useState(initialStructure);
  const [library, setLibrary] = useState<SceneLibrary | null>(null);
  const select = useCallback((id: string) => setSelectedId(id), []);
  async function refresh() {
    const [next, history] = await Promise.all([api.library(), api.events()]);
    setLibrary(next);
    setScene(next.active);
    setEvents(history);
    setPlan(null);
    setPreview(false);
    setConfirmApply(false);
  }
  useEffect(() => {
    let active = true;
    Promise.all([api.library(), api.events()])
      .then(([next, history]) => {
        if (active) {
          setLibrary(next);
          setScene(next.active);
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
  function updateStructure(field: StructureField, raw: string) {
    const parsed = raw === "" ? 0 : Math.trunc(Number(raw));
    setStructure((current) => ({
      ...current,
      [field]: Number.isFinite(parsed) ? parsed : 0,
    }));
  }
  async function buildStructure(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await run(async () => {
      const created = await api.createScene({
        name: `结构柜 · ${structure.rows} 层 × ${structure.columns} 列`,
        ...structure,
      });
      const next = await api.library();
      setLibrary(next);
      setScene(created.scene);
      setPlan(null);
      setPreview(false);
      setConfirmApply(false);
      setSelectedId(created.scene.items[0]?.id ?? "");
      const skipped = created.skipped_item_ids.length
        ? `；${created.skipped_item_ids.length} 件物品放不下未迁入（${created.skipped_item_ids.join("、")}）`
        : "";
      setMessage(
        `已创建场景「${created.scene.name}」并加入场景库：${created.scene.shelves.length} 层 × ${created.scene.shelves[0].columns} 列，${created.scene.items.length} 件物品已重新摆放${skipped}。`,
      );
    });
  }
  async function activateScene(summary: SceneSummary) {
    await run(async () => {
      if (!library) return;
      await api.activate(summary.id, library.active.version);
      await refresh();
      setMessage(`已切换到「${summary.name}」，可以基于该场景生成收纳建议。`);
    });
  }
  async function generatePlan() {
    await run(async () => {
      if (!scene) return;
      // POST /api/plans always plans the active scene. Switching scenes is an explicit
      // user action, so a preview never silently activates itself here.
      if (library && scene.id !== library.active.id) {
        setMessage("当前显示的是场景预览，请先在场景库中切换到此场景，再生成建议。");
        return;
      }
      const result = await api.plan(scene.version);
      setPlan(result);
      setPreview(result.status === "FEASIBLE");
      setConfirmApply(false);
    });
  }
  function exitPreview() {
    if (!library) return;
    setScene(library.active);
    setPlan(null);
    setPreview(false);
    setConfirmApply(false);
    setSelectedId("");
  }
  const selected = scene?.items.find((i) => i.id === selectedId);
  const isPreview = Boolean(
    scene && library && scene.id !== library.active.id,
  );
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
          {isPreview ? (
            <>
              <span>场景预览</span>预览中的场景尚未切换，当前库存场景仍是「
              {library?.active.name}」；此状态下不会写入库存。
            </>
          ) : scene?.source === "user" ? (
            <>
              <span>结构场景</span>
              当前场景由结构建模生成，物品位置为重新摆放的副本；其他场景仍保留在场景库。
            </>
          ) : (
            <>
              <span>合成演示数据</span>非照片识别结果 · 当前使用 6
              件虚拟物品验证接口 · 视觉模型尚未接入
            </>
          )}
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
            {library && (
              <section className="library panel" aria-label="场景库">
                <div className="panel-heading">
                  <h2>场景库</h2>
                  <span>
                    {library.library.length} 个场景 · 切换不会覆盖原场景库存
                  </span>
                </div>
                <div className="library-list">
                  {library.library.map((record) => {
                    const current = record.id === library.active.id;
                    const previewing = !current && record.id === scene.id;
                    return (
                      <article
                        key={record.id}
                        className={`scene-card${current ? " current" : ""}${
                          previewing ? " previewing" : ""
                        }`}
                      >
                        <div className="scene-card-copy">
                          <strong>{record.name}</strong>
                          <small>
                            {record.shelves} 层 × {record.columns} 列 ·{" "}
                            {record.items} 件物品 · v{record.version}
                          </small>
                        </div>
                        {current ? (
                          isPreview ? (
                            <button disabled={busy} onClick={exitPreview}>
                              返回当前场景
                            </button>
                          ) : (
                            <span className="scene-badge">当前场景</span>
                          )
                        ) : (
                          <button
                            disabled={busy}
                            onClick={() => void activateScene(record)}
                          >
                            切换到此场景
                          </button>
                        )}
                      </article>
                    );
                  })}
                </div>
              </section>
            )}
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
                    {scene.shelves.length} 层 · {scene.shelves[0].columns} 列 ·{" "}
                    {Math.max(...scene.shelves.map((s) => s.size.width))} ×{" "}
                    {Math.max(...scene.shelves.map((s) => s.size.depth))} mm /
                    层
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
                      disabled={busy || isPreview || selected.status !== "stored"}
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
                        isPreview ||
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
            <section className="structure panel" aria-label="结构建模">
              <div className="structure-copy">
                <div className="eyebrow">CABINET BUILDER</div>
                <h2>结构建模</h2>
                <p>
                  输入柜体外部尺寸与层列数，生成带竖向隔板的新场景并加入场景库。当前场景不会被覆盖；在库物品会从当前活动场景复制并重新摆放，放不下的会跳过。
                </p>
              </div>
              <form
                className="structure-form"
                onSubmit={(event) => void buildStructure(event)}
              >
                <label>
                  行数
                  <input
                    type="number"
                    min={1}
                    max={10}
                    step={1}
                    value={structure.rows}
                    onChange={(e) => updateStructure("rows", e.target.value)}
                  />
                </label>
                <label>
                  列数
                  <input
                    type="number"
                    min={1}
                    max={4}
                    step={1}
                    value={structure.columns}
                    onChange={(e) =>
                      updateStructure("columns", e.target.value)
                    }
                  />
                </label>
                <label>
                  外宽 mm
                  <input
                    type="number"
                    min={1}
                    max={10000}
                    step={1}
                    value={structure.width}
                    onChange={(e) => updateStructure("width", e.target.value)}
                  />
                </label>
                <label>
                  外深 mm
                  <input
                    type="number"
                    min={1}
                    max={10000}
                    step={1}
                    value={structure.depth}
                    onChange={(e) => updateStructure("depth", e.target.value)}
                  />
                </label>
                <label>
                  外高 mm
                  <input
                    type="number"
                    min={1}
                    max={10000}
                    step={1}
                    value={structure.height}
                    onChange={(e) => updateStructure("height", e.target.value)}
                  />
                </label>
                <label>
                  板厚 mm
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={1}
                    value={structure.board}
                    onChange={(e) => updateStructure("board", e.target.value)}
                  />
                </label>
                <label>
                  隔板厚 mm
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={1}
                    value={structure.divider}
                    onChange={(e) => updateStructure("divider", e.target.value)}
                  />
                </label>
                <button className="primary" type="submit" disabled={busy}>
                  生成结构场景
                </button>
              </form>
            </section>
            <div className="bottom-grid">
              <section className="planning panel">
                <div>
                  <div className="eyebrow">LAYOUT BASELINE</div>
                  <h2>生成一个可检查的布局</h2>
                  <p>先验证边界、碰撞和固定物品。不把贪心结果称为“最优解”。</p>
                </div>
                <button
                  className="primary"
                  disabled={busy || isPreview}
                  onClick={() => void generatePlan()}
                >
                  {busy ? "处理中…" : "生成收纳建议"}
                </button>
                {isPreview && (
                  <p className="plan-hint">
                    预览场景：先在场景库中切换到此场景，才能基于它生成建议。
                  </p>
                )}
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
                          disabled={busy || isPreview || !confirmApply}
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
                          {event.operation.action === "activate_scene"
                            ? `切换场景 · ${
                                library?.library.find(
                                  (record) =>
                                    record.id === event.operation.scene_id,
                                )?.name ?? event.operation.scene_id
                              }`
                            : event.operation.route === "inventory"
                              ? `${event.operation.action === "take" ? "取出" : "归还"} · ${scene.items.find((i) => i.id === event.operation.item_id)?.name ?? event.operation.item_id}`
                              : event.operation.route?.startsWith("apply/")
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
