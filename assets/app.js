'use strict';

// ============================================================
// Design constants
// ============================================================
const COPPER     = '#7a4a28';
const DOWN_COLOR = '#9c5050';
const MUTED      = '#6d625a';
const INK        = '#2a1f17';

const CONF_LABELS = {
  high:   '信心度：高',
  medium: '信心度：中',
  low:    '信心度：低',
};

// ============================================================
// Price item definitions
// ============================================================
const PRICE_ITEMS = [
  { key: 'crude_steel_production', id: 'production', name: '粗鋼產量', en: 'Crude Steel',   source: '台灣全國月產量', unit: '萬噸',   decimals: 1, color: MUTED,      isVolume: true },
  { key: 'north_scrap_price',      id: 'scrap',      name: '廢鋼',     en: 'Scrap Metal',  source: '北部廢鋼大盤',   unit: '元/公斤', decimals: 2, color: COPPER               },
  { key: 'billet_price',           id: 'billet',     name: '小鋼胚',   en: 'Billet',       source: '中級出廠價',     unit: '元/公噸', decimals: 0, color: '#9c7a58'            },
  { key: 'fengxing_rebar_price',   id: 'rebar',      name: '鋼筋',     en: 'Rebar',        source: '豐興鋼筋盤價',   unit: '元/公噸', decimals: 0, color: '#4a6a8a'            },
  { key: 'h_beam_price',           id: 'hbeam',      name: 'H型鋼',    en: 'H-Beam',       source: '東鋼流通價',     unit: '元/公噸', decimals: 0, color: '#5a8a5a'            },
  { key: 'csc_wire_rod_price',     id: 'wirerod',    name: '棒線',     en: 'Wire Rod',     source: '中鋼棒線盤價',   unit: '元/公噸', decimals: 0, color: '#7a5a8a'            },
];

// ============================================================
// Helpers
// ============================================================
function fmtNum(n, decimals) {
  if (typeof n !== 'number' || isNaN(n)) return '—';
  const d = decimals != null ? decimals : 0;
  return n.toFixed(d).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function fmtChangeStr(n, decimals) {
  if (typeof n !== 'number' || isNaN(n)) return '—';
  const d = decimals != null ? decimals : 0;
  const abs = Math.abs(n).toFixed(d).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  if (n > 0)  return '▲ +' + abs;
  if (n < 0)  return '▼ −' + abs;
  return '— ' + abs;
}

function changeClass(n) {
  if (typeof n !== 'number') return '';
  return n > 0 ? 'up' : n < 0 ? 'down' : '';
}

// ============================================================
// Sparkline generator (deterministic 30-day relative)
// ============================================================
function makeSpark(seed, drift) {
  let s = seed;
  const out = [];
  for (let i = 0; i < 30; i++) {
    s = (s * 9301 + 49297) % 233280;
    const noise = (s / 233280 - 0.5) * 0.06;
    const trend = drift * (i / 29);
    out.push(1 + noise + trend);
  }
  return out;
}

function sparkSVG(data, w, h, color, strokeWidth) {
  w = w || 110; h = h || 26; color = color || COPPER; strokeWidth = strokeWidth || 1.2;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const step = w / (data.length - 1);
  const d = data.map((v, i) => {
    const x = (i * step).toFixed(2);
    const y = (h - ((v - min) / range) * (h - 2) - 1).toFixed(2);
    return (i === 0 ? 'M' : 'L') + x + ',' + y;
  }).join(' ');
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">` +
    `<path class="spark-path" d="${d}" fill="none" stroke="${color}" ` +
    `stroke-width="${strokeWidth}" stroke-linejoin="round" stroke-linecap="round"/>` +
    `</svg>`;
}

function triggerSparks(container) {
  container.querySelectorAll('.spark-path').forEach(p => {
    requestAnimationFrame(() => requestAnimationFrame(() => p.classList.add('drawn')));
  });
}

// ============================================================
// Count-up animation
// ============================================================
function countUp(el, target, duration, decimals) {
  duration = duration || 1200;
  decimals = decimals != null ? decimals : 0;
  const start = performance.now();
  function tick(now) {
    const p = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - p, 3);
    const val = target * eased;
    el.textContent = val.toFixed(decimals).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    if (p < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

// ============================================================
// IntersectionObserver for fade-in + count-up + sparklines
// ============================================================
function setupObservers() {
  const io = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      const el = entry.target;
      el.classList.add('in');

      const priceEl = el.querySelector('[data-countup]');
      if (priceEl && !priceEl.dataset.done) {
        priceEl.dataset.done = '1';
        countUp(priceEl, +priceEl.dataset.countup, 1100, +(priceEl.dataset.decimals || 0));
      }

      triggerSparks(el);
      io.unobserve(el);
    });
  }, { threshold: 0.08 });

  document.querySelectorAll('[data-fade], [data-row]').forEach(el => io.observe(el));
}

// ============================================================
// Parallax grain
// ============================================================
function setupGrain() {
  const grain = document.getElementById('grain');
  if (!grain) return;
  window.addEventListener('scroll', () => {
    grain.style.transform = 'translateY(' + (-window.scrollY * 0.15) + 'px)';
  }, { passive: true });
}

// ============================================================
// Render: Featured commodity (Rebar)
// ============================================================
function renderFeatured(data) {
  const tp = data.taiwan_prices || {};
  const item = tp.fengxing_rebar_price || {};
  const price  = item.value;
  const change = item.mom_change;
  const month  = item.month || tp.data_month || '—';

  const featPriceEl = document.getElementById('feat-price');
  if (featPriceEl && typeof price === 'number') {
    countUp(featPriceEl, Math.round(price), 1600, 0);
  }

  const changeEl = document.getElementById('feat-change');
  if (changeEl && typeof change === 'number') {
    changeEl.className = 'feat-change ' + changeClass(change);
    const absStr = Math.abs(change).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    changeEl.textContent = (change > 0 ? '▲ +' : '▼ −') + absStr + ' 元/公噸';
  }

  const monthEl = document.getElementById('feat-month');
  if (monthEl) monthEl.textContent = month;

  const updatedEl = document.getElementById('feat-updated');
  if (updatedEl && data.generated_at) {
    try {
      const d = new Date(data.generated_at);
      updatedEl.textContent = '更新 ' + d.toLocaleDateString('zh-TW');
    } catch (_) {}
  }

  const sparkEl = document.getElementById('feat-spark');
  if (sparkEl && typeof change === 'number') {
    const drift = change > 0 ? 0.03 : (change < 0 ? -0.03 : 0);
    sparkEl.innerHTML = sparkSVG(makeSpark(42, drift), 360, 70, '#5c3a22', 1.4);
    triggerSparks(sparkEl);
  }
}

// ============================================================
// Render: Ticker
// ============================================================
function renderTicker(data) {
  const ticker = document.getElementById('ticker');
  if (!ticker) return;
  const tp = data.taiwan_prices || {};

  const items = PRICE_ITEMS.filter(it => !it.isVolume).map(it => {
    const d = tp[it.key] || {};
    const val    = d.value;
    const change = d.mom_change;
    const cls    = changeClass(change);
    const chgStr = typeof change === 'number'
      ? (change > 0 ? '+' : '') + fmtNum(change, it.decimals)
      : '';
    return `<span class="ticker-item">` +
      `<span class="ticker-label">${it.name}</span>` +
      `<span class="ticker-price">${typeof val === 'number' ? fmtNum(val, it.decimals) : '—'}</span>` +
      `<span class="ticker-chg ${cls}">${chgStr}</span>` +
      `<span class="ticker-sep">※</span>` +
      `</span>`;
  });

  ticker.innerHTML = items.join('') + items.join('');
}

// ============================================================
// Render: Price table
// ============================================================
function renderTable(data) {
  const tbody = document.getElementById('table-body');
  if (!tbody) return;
  const tp = data.taiwan_prices || {};

  tbody.innerHTML = PRICE_ITEMS.map((it, i) => {
    const d      = tp[it.key] || {};
    const val    = d.value;
    const change = d.mom_change;
    const cls    = changeClass(change);
    const color  = it.color;

    const drift    = typeof change === 'number' ? (change > 0 ? 0.03 : (change < 0 ? -0.03 : 0)) : 0;
    const sparkData = makeSpark(i * 47 + 11, drift);

    let priceCell;
    if (it.isVolume) {
      priceCell = `<span class="td col-price tr-production-price">` +
        `<span>${typeof val === 'number' ? fmtNum(val, it.decimals) : '—'}</span>` +
        `<span class="prod-unit-tag">${it.unit}</span>` +
        `</span>`;
    } else {
      const countupVal = typeof val === 'number' ? val : 0;
      priceCell = `<span class="td col-price" ` +
        `data-countup="${countupVal.toFixed(it.decimals)}" ` +
        `data-decimals="${it.decimals}">` +
        `${typeof val === 'number' ? fmtNum(val, it.decimals) : '—'}</span>`;
    }

    const chgStr = typeof change === 'number'
      ? fmtChangeStr(change, it.decimals) + ' ' + it.unit
      : '—';

    const rowClass = it.isVolume ? 'tr tr-production' : 'tr';

    return `<div class="${rowClass}" data-row style="transition-delay:${i * 45}ms">` +
      `<span class="td col-no">${String(i + 1).padStart(2, '0')}</span>` +
      `<span class="td col-prod">` +
        `<span class="prod-name">${it.name}</span>` +
        `<span class="prod-sub">${it.en}</span>` +
      `</span>` +
      `<span class="td col-spec">${it.source}</span>` +
      priceCell +
      `<span class="td col-chg ${cls}">${chgStr}</span>` +
      `<span class="td col-trend">${sparkSVG(sparkData, 110, 26, color, 1.2)}</span>` +
      `</div>`;
  }).join('');

  const metaEl = document.getElementById('table-meta');
  if (metaEl) {
    const month = tp.data_month || '';
    metaEl.textContent = month ? '資料月份 ' + month + '　·　每日自動更新' : '—';
  }
}

// ============================================================
// Render: Chart.js
// ============================================================
let priceChart = null;

async function buildChart(latestData) {
  const canvas = document.getElementById('price-chart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  let months = [], billetVals = [], rebarVals = [], hbeamVals = [], wirerodVals = [];

  try {
    const r = await fetch('data/chart-data.json?t=' + Date.now());
    if (r.ok) {
      const cd = await r.json();
      months      = cd.months || [];
      billetVals  = cd.billet_price || [];
      rebarVals   = cd.fengxing_rebar_price || [];
      hbeamVals   = cd.h_beam_price || [];
      wirerodVals = cd.csc_wire_rod_price || [];
    }
  } catch (_) {}

  if (months.length === 0 && latestData) {
    const tp = latestData.taiwan_prices || {};
    const m  = tp.data_month || latestData.date || '本月';
    months      = [m];
    billetVals  = [tp.billet_price?.value           ?? null];
    rebarVals   = [tp.fengxing_rebar_price?.value   ?? null];
    hbeamVals   = [tp.h_beam_price?.value           ?? null];
    wirerodVals = [tp.csc_wire_rod_price?.value      ?? null];
  }

  if (priceChart) priceChart.destroy();

  Chart.defaults.color       = MUTED;
  Chart.defaults.borderColor = 'rgba(42,31,23,0.08)';

  const datasets = [
    { label: '小鋼胚', data: billetVals,  color: '#9c7a58' },
    { label: '鋼筋',   data: rebarVals,   color: '#4a6a8a' },
    { label: 'H型鋼',  data: hbeamVals,   color: '#5a8a5a' },
    { label: '棒線',   data: wirerodVals, color: '#7a5a8a' },
  ].map(ds => ({
    label: ds.label,
    data: ds.data,
    borderColor: ds.color,
    backgroundColor: ds.color.replace(')', ', 0.06)').replace('rgb', 'rgba'),
    pointBackgroundColor: ds.color,
    pointRadius: 4,
    pointHoverRadius: 6,
    tension: 0.35,
    borderWidth: 1.5,
    fill: true,
  }));

  priceChart = new Chart(ctx, {
    type: 'line',
    data: { labels: months, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#f5efe6',
          borderColor: 'rgba(42,31,23,0.14)',
          borderWidth: 1,
          titleColor: INK,
          bodyColor: MUTED,
          callbacks: {
            label(c) { return ' ' + c.dataset.label + '：' + (c.parsed.y?.toLocaleString('zh-TW') ?? '—') + ' 元/噸'; },
          },
        },
      },
      scales: {
        x: {
          grid: { color: 'rgba(42,31,23,0.06)' },
          ticks: { maxRotation: 45, font: { size: 11 }, color: MUTED },
        },
        y: {
          grid: { color: 'rgba(42,31,23,0.06)' },
          ticks: { font: { size: 11 }, color: MUTED, callback: v => v.toLocaleString('zh-TW') },
        },
      },
    },
  });

  const legendEl = document.getElementById('chart-legend');
  if (legendEl) {
    legendEl.innerHTML = [
      ['小鋼胚', '#9c7a58'],
      ['鋼筋',   '#4a6a8a'],
      ['H型鋼',  '#5a8a5a'],
      ['棒線',   '#7a5a8a'],
    ].map(([label, color]) =>
      `<span class="legend-item">` +
      `<span class="legend-dot" style="background:${color}"></span>` +
      `<span>${label}</span></span>`
    ).join('');
  }
}

// ============================================================
// Render: AI Analysis
// ============================================================
function renderAnalysis(data) {
  const fields = {
    'spread-analysis':      data.spread_analysis,
    'weekly-trend':         data.monthly_trend || data.weekly_trend,
    'international-outlook': data.international_outlook,
    'model-name':           data.model_used,
  };
  for (const [id, text] of Object.entries(fields)) {
    const el = document.getElementById(id);
    if (el) el.textContent = text || '—';
  }
  const riskList = document.getElementById('risk-factors');
  if (riskList && Array.isArray(data.risk_factors)) {
    riskList.innerHTML = data.risk_factors.map(r => `<li>${r}</li>`).join('');
  }
}

// ============================================================
// Render: Exchange rate
// ============================================================
function renderExchange(data) {
  const ex     = data.exchange_rate || {};
  const rateEl = document.getElementById('exchange-rate');
  const impEl  = document.getElementById('exchange-impact');
  if (rateEl) rateEl.textContent = ex.usd_twd_estimate ? ex.usd_twd_estimate.toFixed(2) : '—';
  if (impEl)  impEl.textContent  = ex.impact_on_steel || '—';
}

// ============================================================
// Render: News grid (editorial style)
// ============================================================
function renderNews(data) {
  const grid = document.getElementById('news-grid');
  if (!grid) return;
  const sources = Array.isArray(data.news_sources) ? data.news_sources.filter(n => n.title) : [];
  if (sources.length === 0) {
    grid.innerHTML = '<p style="color:var(--muted);padding:24px 0">暫無新聞來源資料</p>';
    return;
  }
  const date = data.date || '';
  grid.innerHTML = sources.slice(0, 9).map((n, i) => {
    const leadClass = i === 0 ? ' lead-item' : '';
    const url       = (n.url && n.url.startsWith('http')) ? n.url : '#';
    return `<a class="news-item${leadClass}" href="${url}" target="_blank" rel="noopener">` +
      `<div class="news-meta">` +
        `<span>${date}</span>` +
        `<span class="news-tag">鋼市</span>` +
      `</div>` +
      `<h3 class="news-title">${n.title}</h3>` +
      `<span class="news-arrow">閱讀全文 →</span>` +
      `</a>`;
  }).join('');
}

// ============================================================
// Render: Masthead meta
// ============================================================
function renderMeta(data) {
  const tp = data.taiwan_prices || {};

  const dateEl = document.getElementById('meta-date');
  if (dateEl && data.date) {
    const d = new Date(data.date + 'T00:00:00');
    const y = d.getFullYear();
    const m = d.getMonth() + 1;
    const day = d.getDate();
    dateEl.textContent = y + ' 年 ' + m + ' 月 ' + day + ' 日';
  }

  const monthEl = document.getElementById('meta-data-month');
  if (monthEl) monthEl.textContent = tp.data_month ? '報價月份 ' + tp.data_month : '—';

  const confBadge = document.getElementById('conf-badge');
  if (confBadge) {
    const conf = data.confidence || 'medium';
    confBadge.textContent = CONF_LABELS[conf] || conf;
    confBadge.className   = 'conf-badge ' + conf;
  }

  const summaryEl = document.getElementById('summary-text');
  if (summaryEl && data.summary) summaryEl.textContent = data.summary;

  const modelEl = document.getElementById('model-name');
  if (modelEl && data.model_used) modelEl.textContent = data.model_used;

  const eyeEl = document.getElementById('hero-eyeline');
  if (eyeEl && data.date) {
    const epoch = new Date('2024-01-01T00:00:00');
    const now   = new Date(data.date + 'T00:00:00');
    const days  = Math.max(1, Math.floor((now - epoch) / 86400000) + 1);
    eyeEl.textContent = 'VOL. ' + days + ' · 行情誌';
  }
}

// ============================================================
// Main: load data and render everything
// ============================================================
async function loadData() {
  try {
    const res = await fetch('data/latest.json?t=' + Date.now());
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();

    renderMeta(data);
    renderFeatured(data);
    renderTicker(data);
    renderTable(data);
    renderAnalysis(data);
    renderExchange(data);
    renderNews(data);
    await buildChart(data);
    setupObservers();

  } catch (err) {
    console.error('Failed to load data:', err);
    const tableSection = document.querySelector('.section-table');
    if (tableSection) {
      tableSection.style.opacity = '1';
      tableSection.style.transform = 'none';
      tableSection.innerHTML =
        '<div style="padding:80px 0;text-align:center;color:var(--muted)">' +
        '<p style="font-size:16px;margin-bottom:12px">資料載入失敗</p>' +
        '<p style="font-size:12px;letter-spacing:0.1em">' + err.message + '</p>' +
        '</div>';
    }
  } finally {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.classList.add('hidden');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  setupGrain();
  loadData();
});

// ============================================================
// GitHub Actions run modal
// ============================================================
const GH_OWNER = 'lijingchiu';
const GH_REPO  = 'SteelWeb';
const WORKFLOW = 'daily-analysis.yml';
const PAT_KEY  = 'steel_gh_pat';

function openRunModal() {
  const modal = document.getElementById('run-modal');
  modal.style.display = 'flex';
  const saved = localStorage.getItem(PAT_KEY);
  if (saved) {
    document.getElementById('pat-input').value = saved;
    document.getElementById('remember-pat').checked = true;
  }
  hideRunStatus();
  document.getElementById('trigger-btn').disabled = false;
  setTimeout(() => document.getElementById('pat-input').focus(), 80);
}

function closeRunModal() {
  document.getElementById('run-modal').style.display = 'none';
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeRunModal(); });

function showRunStatus(type, msg) {
  const el = document.getElementById('run-status');
  el.style.display = 'block';
  el.className = 'run-status run-status-' + type;
  el.textContent = msg;
}
function hideRunStatus() {
  const el = document.getElementById('run-status');
  if (el) el.style.display = 'none';
}

async function triggerWorkflow() {
  const pat = document.getElementById('pat-input').value.trim();
  if (!pat) { showRunStatus('error', '請輸入 GitHub PAT'); return; }
  if (!/^[\x20-\x7E]+$/.test(pat)) {
    showRunStatus('error', '❌ Token 包含無效字元，請重新複製貼上 GitHub PAT');
    return;
  }
  if (document.getElementById('remember-pat').checked) {
    localStorage.setItem(PAT_KEY, pat);
  } else {
    localStorage.removeItem(PAT_KEY);
  }
  const btn = document.getElementById('trigger-btn');
  btn.disabled = true;
  const ghHeaders = {
    'Authorization':        'Bearer ' + pat,
    'Accept':               'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'Content-Type':         'application/json',
  };
  try {
    showRunStatus('loading', '⏳ 驗證 Token 並查詢 workflow...');
    const [listRes, repoRes] = await Promise.all([
      fetch('https://api.github.com/repos/' + GH_OWNER + '/' + GH_REPO + '/actions/workflows', { headers: ghHeaders }),
      fetch('https://api.github.com/repos/' + GH_OWNER + '/' + GH_REPO, { headers: ghHeaders }),
    ]);
    if (listRes.status === 401 || repoRes.status === 401) {
      showRunStatus('error', '❌ PAT 無效或已過期，請重新確認'); btn.disabled = false; return;
    }
    if (listRes.status === 403 || repoRes.status === 403) {
      showRunStatus('error', '❌ 權限不足，請確認 PAT 已勾選 workflow 權限'); btn.disabled = false; return;
    }
    if (!listRes.ok) {
      const b = await listRes.json().catch(() => ({}));
      showRunStatus('error', '❌ API 錯誤 ' + listRes.status + '：' + (b.message || '')); btn.disabled = false; return;
    }
    const [listData, repoData] = await Promise.all([listRes.json(), repoRes.json()]);
    const defaultBranch = repoData.default_branch || 'main';
    const wf = (listData.workflows || []).find(w => w.path && w.path.endsWith(WORKFLOW));
    const workflowId = wf ? wf.id : WORKFLOW;
    const dispatchRes = await fetch(
      'https://api.github.com/repos/' + GH_OWNER + '/' + GH_REPO + '/actions/workflows/' + workflowId + '/dispatches',
      { method: 'POST', headers: ghHeaders, body: JSON.stringify({ ref: defaultBranch, inputs: { force_run: 'true' } }) }
    );
    if (dispatchRes.status === 204) {
      showRunStatus('loading', '✅ 已成功觸發！分析執行中，約需 2–3 分鐘...');
      pollWorkflowStatus(pat);
    } else if (dispatchRes.status === 401) {
      showRunStatus('error', '❌ PAT 無效或已過期'); btn.disabled = false;
    } else if (dispatchRes.status === 403) {
      showRunStatus('error', '❌ 權限不足，請確認 workflow 權限'); btn.disabled = false;
    } else if (dispatchRes.status === 404) {
      showRunStatus('error', '❌ 找不到 workflow（分支：' + defaultBranch + '）'); btn.disabled = false;
    } else {
      const body = await dispatchRes.json().catch(() => ({}));
      showRunStatus('error', '❌ 錯誤 ' + dispatchRes.status + '：' + (body.message || '')); btn.disabled = false;
    }
  } catch (e) {
    showRunStatus('error', '❌ 網路錯誤：' + e.message); btn.disabled = false;
  }
}

async function pollWorkflowStatus(pat) {
  const maxAttempts = 36;
  let attempts = 0;
  const triggeredAt = Date.now();
  const poll = async () => {
    attempts++;
    try {
      const res = await fetch(
        'https://api.github.com/repos/' + GH_OWNER + '/' + GH_REPO + '/actions/runs?per_page=5',
        { headers: {
          'Authorization':        'Bearer ' + pat,
          'Accept':               'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
        }}
      );
      if (res.ok) {
        const d = await res.json();
        const run = (d.workflow_runs || []).find(r => new Date(r.created_at).getTime() >= triggeredAt - 30000);
        if (run) {
          if (run.status === 'completed') {
            if (run.conclusion === 'success') {
              showRunStatus('success', '✅ 分析完成！點此重新整理查看最新資料。');
              const statusEl = document.getElementById('run-status');
              statusEl.style.cursor = 'pointer';
              statusEl.onclick = () => location.reload();
            } else {
              showRunStatus('error', '❌ 執行失敗（' + run.conclusion + '），請至 GitHub Actions 查看');
            }
            document.getElementById('trigger-btn').disabled = false;
            return;
          }
          const elapsed = Math.round((Date.now() - triggeredAt) / 1000);
          const label = run.status === 'in_progress' ? '執行中' : '排隊中';
          showRunStatus('loading', '⏳ ' + label + '...（已等待 ' + elapsed + ' 秒）');
        }
      }
    } catch (_) {}
    if (attempts < maxAttempts) setTimeout(poll, 10000);
    else {
      showRunStatus('error', '⏱ 等待逾時，請至 GitHub Actions 頁面確認');
      document.getElementById('trigger-btn').disabled = false;
    }
  };
  setTimeout(poll, 8000);
}
