"""A single-file live board: tasks, owners, leases, and the event feed.

No build step, no external assets. Open http://<host>:8765/ and paste an admin
token. Read-only for humans; mutations stay in the CLI/MCP path.
"""

DASHBOARD_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>雏雁 · 团队任务板</title>
<style>
  :root { --bg:#0f1115; --panel:#171a21; --line:#262b36; --text:#e6e9ef; --dim:#8b93a3;
          --ok:#3fb950; --warn:#d29922; --bad:#f85149; --accent:#58a6ff; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
         background:var(--bg); color:var(--text); }
  header { display:flex; gap:12px; align-items:center; padding:14px 20px; border-bottom:1px solid var(--line); }
  header h1 { font-size:15px; margin:0; font-weight:600; letter-spacing:.02em; }
  header .sp { flex:1; }
  input, button { background:var(--panel); color:var(--text); border:1px solid var(--line);
                  border-radius:6px; padding:6px 10px; font:inherit; }
  button { cursor:pointer; }
  button:hover { border-color:var(--accent); }
  main { display:grid; grid-template-columns: 1.6fr 1fr; gap:16px; padding:16px 20px; }
  section { background:var(--panel); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  section h2 { margin:0; padding:10px 14px; font-size:13px; color:var(--dim);
               border-bottom:1px solid var(--line); font-weight:500; }
  table { width:100%; border-collapse:collapse; }
  th, td { text-align:left; padding:8px 12px; border-bottom:1px solid var(--line); vertical-align:top; }
  th { color:var(--dim); font-weight:500; font-size:12px; }
  .chip { display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px;
          border:1px solid var(--line); color:var(--dim); }
  .pending { color:var(--dim); } .draft { color:#6e7681; }
  .claimed,.in_progress { color:var(--warn); } .handoff { color:var(--accent); }
  .review { color:#bc8cff; } .done { color:var(--ok); }
  .owner { font-family:ui-monospace, SFMono-Regular, Consolas, monospace; font-size:12px; }
  .lease { color:var(--dim); font-size:12px; }
  #feed { max-height:70vh; overflow:auto; padding:6px 0; }
  .ev { padding:6px 14px; border-bottom:1px dashed var(--line); font-size:12.5px; }
  .ev time { color:var(--dim); font-family:ui-monospace, Consolas, monospace; margin-right:8px; }
  .ev b { color:var(--accent); font-weight:500; }
  .muted { color:var(--dim); }
  .err { color:var(--bad); }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <h1>雏雁 · 五 Agent 任务板</h1>
  <span class="sp"></span>
  <input id="token" type="password" size="28" placeholder="admin token">
  <button onclick="saveToken()">连接</button>
  <span id="state" class="muted">未连接</span>
</header>
<main>
  <section>
    <h2>任务（按状态）</h2>
    <table>
      <thead><tr><th>任务</th><th>标题 / 范围</th><th>状态</th><th>负责人</th><th>租约</th></tr></thead>
      <tbody id="tasks"><tr><td colspan="5" class="muted">等待数据…</td></tr></tbody>
    </table>
  </section>
  <section>
    <h2>实时动态（谁在做什么）</h2>
    <div id="feed"><div class="ev muted">等待事件流…</div></div>
  </section>
</main>
<script>
const $ = s => document.querySelector(s);
const stateEl = $('#state');
let token = localStorage.getItem('teamToken') || '';
$('#token').value = token;

function saveToken() {
  token = $('#token').value.trim();
  localStorage.setItem('teamToken', token);
  connect();
}

async function api(path) {
  const r = await fetch(path, { headers: { 'Authorization': 'Bearer ' + token } });
  if (!r.ok) throw new Error((await r.json()).message || r.status);
  return r.json();
}

const STATUS_ORDER = ['pending','claimed','in_progress','handoff','review','done','draft','cancelled'];
function esc(v) { return String(v == null ? '' : v).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function leaseText(t) {
  if (!t.claim) return '';
  const ms = new Date(t.claim.lease_until).getTime() - Date.now();
  if (ms <= 0) return '<span class="err">已过期</span>';
  const m = Math.floor(ms / 60000);
  return (m >= 60 ? (m/60).toFixed(1) + ' 小时' : m + ' 分钟');
}

async function refresh() {
  if (!token) return;
  try {
    const tasks = await api('/api/tasks?all=1');
    tasks.sort((a,b) => (STATUS_ORDER.indexOf(a.status)-STATUS_ORDER.indexOf(b.status)) || a.seq - b.seq);
    if (!tasks.length) { $('#tasks').innerHTML = '<tr><td colspan="5" class="muted">还没有任务</td></tr>'; return; }
    $('#tasks').innerHTML = tasks.map(t => `
      <tr>
        <td class="owner">${esc(t.id)}</td>
        <td><div>${esc(t.title)}</div>
            <div class="muted">${esc(t.kind)} · ${esc(t.scope_paths.join(', ') || '—')}</div></td>
        <td><span class="chip ${esc(t.status)}">${esc(t.status)}</span></td>
        <td class="owner">${esc(t.owner_agent_id || '—')}</td>
        <td class="lease">${leaseText(t)}</td>
      </tr>`).join('');
  } catch (e) { stateEl.textContent = '连接失败: ' + e.message; stateEl.className = 'err'; }
}

const EVENT_LABELS = {
  task_created:'创建任务', task_published:'发布任务', task_claimed:'认领', task_released:'释放',
  lease_expired:'租约过期', task_handoff:'交接', handoff_accepted:'接受交接',
  review_requested:'送审', review_decided:'评审结论', task_completed:'完成',
  message_sent:'消息', agent_registered:'新 Agent 注册'
};
let es = null;
function feedLine(e) {
  const d = new Date(e.created_at);
  const label = EVENT_LABELS[e.type] || e.type;
  const who = e.agent_id ? '<b>' + esc(e.agent_id) + '</b> ' : '';
  const what = e.task_id ? esc(e.task_id) : '';
  const extra = e.type === 'task_handoff' && e.payload ? (' → ' + esc(e.payload.to_agent || '')) :
                e.type === 'lease_expired' && e.payload ? ('（原 ' + esc(e.payload.previous_owner || '') + '）') :
                e.type === 'review_decided' && e.payload ? (e.payload.approved ? ' 通过' : ' 未通过') : '';
  const div = document.createElement('div');
  div.className = 'ev';
  div.innerHTML = `<time>${d.toLocaleTimeString('zh-CN', {hour12:false})}</time>${who}${esc(label)} ${what}${esc(extra)}`;
  return div;
}
function connect() {
  if (es) { es.close(); es = null; }
  if (!token) { stateEl.textContent = '请先填 token'; return; }
  refresh();
  const since = 0;
  es = new EventSource('/api/events/stream?since=' + since + '&token=' + encodeURIComponent(token));
  es.onopen = () => { stateEl.textContent = '实时连接中'; stateEl.className = 'muted'; };
  es.onerror = () => { stateEl.textContent = '连接中断，重试中'; stateEl.className = 'err'; };
  const feed = $('#feed');
  const handler = e => {
    const data = JSON.parse(e.data);
    feed.prepend(feedLine(data));
    while (feed.children.length > 300) feed.lastChild.remove();
    refresh();
  };
  Object.keys(EVENT_LABELS).forEach(name => es.addEventListener(name, handler));
  es.addEventListener('message_sent', handler);
}
if (token) connect();
</script>
</body>
</html>
"""
