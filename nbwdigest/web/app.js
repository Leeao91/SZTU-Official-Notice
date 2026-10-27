/* 公文通 · 手机版前端（无框架，纯原生 JS） */
'use strict';

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const state = { days: [], date: null, data: null, cat: '全部', q: '', onlyDue: false };
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* 隐私模式 */ } },
};

/* ---------- 取数据：先网络，失败回落到 Service Worker 缓存 ---------- */
const EMBED = window.__NBW_DATA__ || null;   // 离线导出版把数据直接内联进来

function embedded(url) {
  if (!EMBED) return undefined;
  if (url === '/api/days') return { days: EMBED.days };
  const m = url.match(/^\/api\/day\/(.+)$/);
  if (m && EMBED.reports && EMBED.reports[m[1]]) return EMBED.reports[m[1]];
  return undefined;
}

async function getJSON(url) {
  const local = embedded(url);
  if (local) return local;
  try {
    const r = await fetch(url, { cache: 'no-cache' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.json();
  } catch (e) {
    if ('caches' in window) {
      const hit = await caches.match(url);
      if (hit) return await hit.json();
    }
    throw e;
  }
}

/* ---------- 日期条 ---------- */
function renderDays() {
  const el = $('#days');
  el.innerHTML = state.days.map((d) => {
    const on = d.date === state.date ? ' on' : '';
    const md = d.date.slice(5).replace('-', '/');
    return `<button class="day${on}" data-date="${d.date}">${md} <b>${d.count}</b></button>`;
  }).join('') || '<span class="day">暂无数据</span>';

  el.querySelectorAll('.day[data-date]').forEach((b) => {
    b.addEventListener('click', () => loadDay(b.dataset.date));
  });
}

/* ---------- 分类筛选 ---------- */
function renderCats() {
  const counts = state.data?.by_category || {};
  const keys = ['全部', ...Object.keys(counts).sort((a, b) => counts[b] - counts[a])];
  $('#cats').innerHTML = keys.map((k) => {
    const n = k === '全部' ? (state.data?.count ?? 0) : counts[k];
    return `<button class="chip${k === state.cat ? ' on' : ''}" data-cat="${esc(k)}">${esc(k)} ${n}</button>`;
  }).join('');
  $('#cats').querySelectorAll('.chip').forEach((b) => {
    b.addEventListener('click', () => { state.cat = b.dataset.cat; renderCats(); renderList(); });
  });
}

/* ---------- 卡片 ---------- */
function cardHTML(it) {
  const due = !!it.deadline;
  const tags = (it.tags || []).map((t) => `<span class="badge">${esc(t)}</span>`).join('');
  const cls = due ? 'card due' : 'card';
  const meta = [
    esc(it.dept || '—'),
    it.publish_time ? esc(it.publish_time) : esc(it.list_date || ''),
    it.has_attach ? '📎 附件' : '',
  ].filter(Boolean).join(' · ');

  const kps = (it.key_points || []).slice(0, 3)
    .filter((k) => k && k !== it.abstract)
    .map((k) => `<li>${esc(k)}</li>`).join('');

  const atts = (it.attachments || []).slice(0, 6)
    .map((a) => `<a href="${esc(a.url)}" target="_blank" rel="noreferrer">📄 ${esc(a.name)}</a>`)
    .join('<br>');

  return `<article class="${cls}">
    <h2>${esc(it.title)}</h2>
    <div class="meta">
      ${tags}
      ${due ? `<span class="badge due">⏰ ${esc(it.deadline)}</span>` : ''}
      <span>${meta}</span>
    </div>
    ${it.abstract ? `<p class="abs">${esc(it.abstract)}</p>` : ''}
    ${kps ? `<ul class="kp">${kps}</ul>` : ''}
    ${atts ? `<div class="att">${atts}</div>` : ''}
    <div class="acts">
      <a class="btn solid" href="${esc(it.url)}" target="_blank" rel="noreferrer">查看原文 →</a>
      <button class="btn ghost" data-copy="${esc(it.title)}">复制标题</button>
    </div>
  </article>`;
}

function renderList() {
  if (!state.data) return;
  const q = state.q.trim().toLowerCase();
  let items = state.data.items.slice();

  if (state.cat !== '全部') items = items.filter((i) => i.category === state.cat);
  if (state.onlyDue) items = items.filter((i) => i.deadline);
  if (q) {
    items = items.filter((i) => [i.title, i.dept, i.abstract, (i.tags || []).join('')]
      .join(' ').toLowerCase().includes(q));
  }
  if (state.onlyDue) items.sort((a, b) => a.deadline.localeCompare(b.deadline));

  const list = $('#list');
  const empty = $('#empty');

  if (!items.length) {
    list.innerHTML = '';
    empty.hidden = false;
    const reason = !state.data.items.length
      ? (state.data.baseline ? '这是首次运行的基线记录' : '这一天没有新增公文')
      : '没有匹配的公文，试试换个关键词或取消筛选';
    empty.innerHTML = `<span class="big">🗂️</span>${esc(reason)}`;
    return;
  }

  empty.hidden = true;
  list.innerHTML = items.map(cardHTML).join('');
  list.querySelectorAll('[data-copy]').forEach((b) => {
    b.addEventListener('click', async () => {
      const t = b.dataset.copy;
      try {
        await navigator.clipboard.writeText(t);
        const old = b.textContent;
        b.textContent = '已复制 ✓';
        setTimeout(() => { b.textContent = old; }, 1200);
      } catch { b.textContent = '复制失败'; }
    });
  });
}

/* ---------- 加载某一天 ---------- */
async function loadDay(date) {
  state.date = date;
  store.set('nbw.lastDate', date);
  renderDays();
  $('#list').innerHTML = '<div class="skel"></div><div class="skel"></div><div class="skel"></div>';
  $('#empty').hidden = true;
  try {
    state.data = await getJSON('/api/day/' + date);
    state.cat = '全部';
    state.q = '';
    $('#search').value = '';
    $('#clear-search').style.display = 'none';
    renderCats();
    renderList();
    const d = state.data;
    $('#sub').textContent = `${d.date} · 新增 ${d.count} 条` + (d.baseline ? ' · 基线' : '');
    $('#foot-info').textContent = '生成于 ' + (d.generated_at || '—');
  } catch (e) {
    $('#list').innerHTML = '';
    $('#empty').hidden = false;
    $('#empty').innerHTML = '<span class="big">📡</span>没取到这一天数据<br><small>' +
      esc(e.message) + '</small>';
  }
}

/* ---------- 刷新 ---------- */
async function refresh(keepDate = true) {
  const btn = $('#refresh');
  btn.textContent = '…';
  try {
    const res = await getJSON('/api/days');
    state.days = res.days || [];
    if (!state.days.length) {
      $('#empty').hidden = false;
      $('#empty').innerHTML = '<span class="big">📭</span>还没有日报<br><small>先在电脑上跑一次 nbw_digest.py</small>';
      return;
    }
    const target = (keepDate && state.date && state.days.some((d) => d.date === state.date))
      ? state.date
      : (store.get('nbw.lastDate') && state.days.some((d) => d.date === store.get('nbw.lastDate'))
        ? store.get('nbw.lastDate') : state.days[0].date);
    await loadDay(target);
  } catch (e) {
    $('#empty').hidden = false;
    $('#empty').innerHTML = '<span class="big">📡</span>连接不上服务<br><small>' + esc(e.message) + '</small>';
  } finally {
    btn.textContent = '↻';
  }
}

/* ---------- 事件 ---------- */
$('#refresh').addEventListener('click', () => refresh(false));
$('#search').addEventListener('input', (e) => {
  state.q = e.target.value;
  $('#clear-search').style.display = state.q ? 'block' : 'none';
  renderList();
});
$('#clear-search').addEventListener('click', () => {
  state.q = ''; $('#search').value = ''; $('#clear-search').style.display = 'none'; renderList();
});
$('#only-due').addEventListener('change', (e) => { state.onlyDue = e.target.checked; renderList(); });

/* ---------- 启动 ---------- */
refresh(true);

if ('serviceWorker' in navigator && !EMBED) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* 忽略 */ });
  });
}
