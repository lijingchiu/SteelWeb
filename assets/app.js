'use strict';

if ('scrollRestoration' in history) history.scrollRestoration = 'manual';

function forceScrollTop() {
  try { window.scrollTo({ top: 0, behavior: 'instant' }); } catch (_) { window.scrollTo(0, 0); }
  document.documentElement.scrollTop = 0;
  document.body.scrollTop = 0;
}
forceScrollTop();

const TREND_LABELS = { up: '上漲', down: '下跌', stable: '持平' };
const CONF_LABELS = { high: '信心度：高', medium: '信心度：中', low: '信心度：低' };

let priceChart = null;
let _tickerRAF = null;
let _tickerX = 0;

function fmt(n, decimals) {
  if (typeof n !== 'number') return '-';
  if (decimals !== undefined) return n.toFixed(decimals);
  return n.toLocaleString('zh-TW');
}

function fmtChange(n, decimals) {
  if (typeof n !== 'number') return '';
  const sign = n > 0 ? '+' : '';
  if (decimals !== undefined) return `${sign}${n.toFixed(decimals)}`;
  return `${sign}${n.toLocaleString('zh-TW')}`;
}

function trendFromChange(change) {
  if (typeof change !== 'number') return 'stable';
  if (change > 0) return 'up';
  if (change < 0) return 'down';
  return 'stable';
}

function setTrend(badgeId, barId, trend) {
  const badge = document.getElementById(badgeId);
  const bar = document.getElementById(barId);
  if (!badge || !bar) return;
  badge.textContent = TREND_LABELS[trend] || trend;
  badge.className = `trend-badge ${trend}`;
  bar.className = `trend-bar-fill ${trend}`;
  bar.style.width = trend === 'up' ? '75%' : trend === 'down' ? '25%' : '50%';
}

function setChange(el, changeAmt, unit, decimals) {
  if (!el) return;
  if (typeof changeAmt !== 'number') { el.textContent = '-'; el.className = 'price-change stable'; return; }
  const cls = changeAmt > 0 ? 'up' : changeAmt < 0 ? 'down' : 'stable';
  el.textContent = fmtChange(changeAmt, decimals) + ' ' + (unit || '元');
  el.className = `price-change ${cls}`;
}

function setDataMonth(el, monthStr) {
  if (!el) return;
  el.textContent = monthStr ? `資料月份：${monthStr}` : '資料月份：-';
}

function populatePrices(data) {
  const tp = data.taiwan_prices || {};

  function fillCard(key, prefix, decimals) {
    const item = tp[key] || {};
    const cur = document.getElementById(`${prefix}-current`);
    const chg = document.getElementById(`${prefix}-change`);
    const monthEl = document.getElementById(`${prefix}-month`);
    const val = item.value;
    const mom = item.mom_change;
    const unit = item.unit || '元';
    const trend = trendFromChange(mom);

    if (cur) cur.textContent = (val !== null && val !== undefined) ? fmt(val, decimals) : '-';
    setChange(chg, mom, unit, decimals);
    setDataMonth(monthEl, item.month);
    setTrend(`${prefix}-trend-badge`, `${prefix}-trend-bar`, trend);
  }

  fillCard('crude_steel_production', 'production', 1);
  fillCard('north_scrap_price', 'scrap', 2);
  fillCard('billet_price', 'billet');
  fillCard('fengxing_rebar_price', 'rebar');
  fillCard('h_beam_price', 'hbeam');
  fillCard('csc_wire_rod_price', 'wirerod');
}

function populateExchange(data) {
  const ex = data.exchange_rate || {};
  const rate = document.getElementById('exchange-rate');
  const impact = document.getElementById('exchange-impact');
  const source = document.getElementById('exchange-source');
  const val = typeof ex.usd_twd === 'number' ? ex.usd_twd : ex.usd_twd_estimate;
  if (rate) rate.textContent = typeof val === 'number' ? val.toFixed(2) : '-';
  if (impact) impact.textContent = ex.impact_on_steel || '-';
  if (source) {
    if (ex.source) {
      const buySell = (typeof ex.spot_buy === 'number' && typeof ex.spot_sell === 'number')
        ? ` · 即期買 ${ex.spot_buy.toFixed(2)} / 賣 ${ex.spot_sell.toFixed(2)}` : '';
      source.textContent = `來源：${ex.source}${buySell}`;
    } else {
      source.textContent = '';
    }
  }
}

function populateAnalysis(data) {
  const fields = {
    'summary-text': data.summary,
    'spread-analysis': data.spread_analysis,
    'weekly-trend': data.monthly_trend || data.weekly_trend,
    'international-outlook': data.international_outlook,
    'model-name': data.model_used,
  };
  for (const [id, text] of Object.entries(fields)) {
    const el = document.getElementById(id);
    if (el) el.textContent = text || '-';
  }
  const riskList = document.getElementById('risk-factors');
  if (riskList && Array.isArray(data.risk_factors)) {
    riskList.innerHTML = data.risk_factors.map(r => `<li>⚠ ${r}</li>`).join('');
  }
}

function populateNews(data) {
  const list = document.getElementById('news-list');
  if (!list) return;
  const sources = Array.isArray(data.news_sources) ? data.news_sources : [];
  if (sources.length === 0) {
    list.innerHTML = '<p class="no-news">暫無新聞來源資料</p>';
    return;
  }
  list.innerHTML = sources
    .filter(n => n.title)
    .map((n, i) => {
      const url = n.url && n.url.startsWith('http') ? n.url : '#';
      return `<a class="news-item" href="${url}" target="_blank" rel="noopener">
        <span class="news-item-num">${String(i + 1).padStart(2, '0')}</span>
        <span class="news-item-title">${n.title}</span>
        <span class="news-arrow">閱讀全文 →</span>
      </a>`;
    })
    .join('');
}

function populateMeta(data) {
  const updatedEl = document.getElementById('last-updated-text');
  const confBadge = document.getElementById('confidence-badge');
  const tp = data.taiwan_prices || {};
  const dataMonth = tp.data_month;

  if (updatedEl) {
    if (dataMonth) {
      updatedEl.textContent = `報價月份 ${dataMonth}`;
    } else if (data.generated_at) {
      try {
        const d = new Date(data.generated_at);
        updatedEl.textContent = `更新於 ${d.toLocaleDateString('zh-TW')} ${d.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })}`;
      } catch { updatedEl.textContent = data.date || '-'; }
    }
  }
  if (confBadge) {
    const conf = data.confidence || 'medium';
    confBadge.textContent = CONF_LABELS[conf] || conf;
    confBadge.className = `badge confidence-badge ${conf}`;
  }
}

async function buildChart(latestData) {
  const canvas = document.getElementById('price-chart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  let months = [], billetVals = [], rebarVals = [], hbeamVals = [], wirerodVals = [];

  try {
    const chartRes = await fetch('data/chart-data.json?t=' + Date.now());
    if (chartRes.ok) {
      const cd = await chartRes.json();
      months = cd.months || [];
      billetVals = cd.billet_price || [];
      rebarVals = cd.fengxing_rebar_price || [];
      hbeamVals = cd.h_beam_price || [];
      wirerodVals = cd.csc_wire_rod_price || [];
    }
  } catch (_) {}

  if (months.length === 0 && latestData) {
    const tp = latestData.taiwan_prices || {};
    const m = tp.data_month || latestData.date || '本月';
    months = [m];
    billetVals = [tp.billet_price?.value ?? null];
    rebarVals = [tp.fengxing_rebar_price?.value ?? null];
    hbeamVals = [tp.h_beam_price?.value ?? null];
    wirerodVals = [tp.csc_wire_rod_price?.value ?? null];
  }

  if (priceChart) priceChart.destroy();
  Chart.defaults.color = '#6d625a';
  Chart.defaults.borderColor = 'rgba(42,31,23,0.12)';
  priceChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: months,
      datasets: [
        { label: '小鋼胚', data: billetVals,  borderColor: '#7a4a28', backgroundColor: 'rgba(122,74,40,0.07)',  pointBackgroundColor: '#7a4a28', pointRadius: 3, pointHoverRadius: 5, tension: 0.35, borderWidth: 1.5, fill: true },
        { label: '鋼筋',   data: rebarVals,   borderColor: '#9c5050', backgroundColor: 'rgba(156,80,80,0.06)',  pointBackgroundColor: '#9c5050', pointRadius: 3, pointHoverRadius: 5, tension: 0.35, borderWidth: 1.5, fill: true },
        { label: 'H型鋼',  data: hbeamVals,   borderColor: '#6d625a', backgroundColor: 'rgba(109,98,90,0.06)', pointBackgroundColor: '#6d625a', pointRadius: 3, pointHoverRadius: 5, tension: 0.35, borderWidth: 1.5, fill: true },
        { label: '棒線',   data: wirerodVals, borderColor: '#a89682', backgroundColor: 'rgba(168,150,130,0.06)', pointBackgroundColor: '#a89682', pointRadius: 3, pointHoverRadius: 5, tension: 0.35, borderWidth: 1.5, fill: true },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(247,241,229,0.96)', borderColor: 'rgba(42,31,23,0.14)', borderWidth: 1,
          titleColor: '#2a1f17', bodyColor: '#6d625a',
          callbacks: { label(c) { return ` ${c.dataset.label}：${c.parsed.y?.toLocaleString('zh-TW') ?? '-'} 元/噸`; } },
        },
      },
      scales: {
        x: { grid: { color: 'rgba(42,31,23,0.06)' }, ticks: { maxRotation: 45, font: { size: 11 }, color: '#6d625a' } },
        y: { grid: { color: 'rgba(42,31,23,0.06)' }, ticks: { font: { size: 11 }, color: '#6d625a', callback: v => v.toLocaleString('zh-TW') } },
      },
    },
  });
}

function populateFeatured(data) {
  const tp = data.taiwan_prices || {};
  const rebar = tp.fengxing_rebar_price || {};
  const cur = document.getElementById('feat-current');
  const chg = document.getElementById('feat-change');
  const mon = document.getElementById('feat-month');
  if (cur) cur.textContent = rebar.value != null ? fmt(rebar.value) : '-';
  if (chg) setChange(chg, rebar.mom_change, rebar.unit || '元', 0);
  if (mon) mon.textContent = rebar.month ? `DATA · ${rebar.month}` : '-';
}

function populateTicker(data) {
  const inner = document.getElementById('ticker-inner');
  if (!inner) return;
  const tp = data.taiwan_prices || {};
  const items = [
    { label: '臺灣粗鋼產量', key: 'crude_steel_production', decimals: 1 },
    { label: '北部廢鋼',     key: 'north_scrap_price',      decimals: 2 },
    { label: '小鋼胚',       key: 'billet_price',           decimals: 0 },
    { label: '豐興鋼筋',     key: 'fengxing_rebar_price',   decimals: 0 },
    { label: 'H型鋼',        key: 'h_beam_price',           decimals: 0 },
    { label: '棒線盤價',     key: 'csc_wire_rod_price',     decimals: 0 },
  ];
  const buildItem = item => {
    const d = tp[item.key] || {};
    const val = d.value != null ? fmt(d.value, item.decimals) : '-';
    const chg = typeof d.mom_change === 'number' ? d.mom_change : null;
    const cls = chg === null ? '' : chg > 0 ? 'up' : chg < 0 ? 'down' : '';
    const arrow = chg === null ? '' : chg > 0 ? '▲' : chg < 0 ? '▼' : '—';
    const chgText = chg !== null ? `${arrow} ${Math.abs(chg).toFixed(item.decimals)}` : '';
    return `<span class="ticker-item">
      <span class="ticker-label">${item.label}</span>
      <span class="ticker-price">${val}</span>
      ${chgText ? `<span class="ticker-chg ${cls}">${chgText}</span>` : ''}
      <span class="ticker-sep">※</span>
    </span>`;
  };
  inner.innerHTML = [...items, ...items].map(buildItem).join('');
  startTicker();
}

function startTicker() {
  const inner = document.getElementById('ticker-inner');
  if (!inner) return;
  if (_tickerRAF) { cancelAnimationFrame(_tickerRAF); _tickerRAF = null; }
  _tickerX = 0;
  inner.style.transform = 'translateX(0px)';

  requestAnimationFrame(() => {
    const half = inner.scrollWidth / 2;
    if (half <= 0) return;
    const tick = () => {
      _tickerX -= 0.4;
      if (_tickerX <= -half) _tickerX += half;
      inner.style.transform = `translateX(${_tickerX}px)`;
      _tickerRAF = requestAnimationFrame(tick);
    };
    _tickerRAF = requestAnimationFrame(tick);
  });
}

function populateForecast(data) {
  const fc = data.tomorrow_forecast || {};
  const DIR_LABELS = { up: '看漲', down: '看跌', stable: '持平' };
  const items = [
    { key: 'north_scrap_price',    prefix: 'scrap' },
    { key: 'billet_price',         prefix: 'billet' },
    { key: 'fengxing_rebar_price', prefix: 'rebar' },
    { key: 'h_beam_price',         prefix: 'hbeam' },
    { key: 'csc_wire_rod_price',   prefix: 'wirerod' },
  ];

  for (const { key, prefix } of items) {
    const f = fc[key] || {};
    const badge  = document.getElementById(`fc-${prefix}-badge`);
    const est    = document.getElementById(`fc-${prefix}-est`);
    const reason = document.getElementById(`fc-${prefix}-reason`);
    const dir = ['up', 'down', 'stable'].includes(f.direction) ? f.direction : null;

    if (badge) {
      badge.textContent = dir ? DIR_LABELS[dir] : '-';
      badge.className = `trend-badge ${dir || 'stable'}`;
    }
    if (est)    est.textContent = f.change_estimate || (dir ? '幅度：待估' : '-');
    if (reason) reason.textContent = f.reason || '預測資料將於下次分析執行後產生';
  }

  const overall = document.getElementById('fc-overall-basis');
  if (overall) overall.textContent = fc.overall_basis || '預測資料將於下次分析執行後產生';

  const dateEl = document.getElementById('forecast-date');
  if (dateEl) {
    try {
      const base = data.generated_at ? new Date(data.generated_at) : new Date();
      base.setDate(base.getDate() + 1);
      const label = base.toLocaleDateString('zh-TW', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' });
      dateEl.textContent = `預測目標日：${label}`;
    } catch (_) { dateEl.textContent = '預測目標日：明日'; }
  }
}

function initAnimations() {
  const sectionIO = new IntersectionObserver(entries => {
    entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); sectionIO.unobserve(e.target); } });
  }, { threshold: 0.05 });
  document.querySelectorAll('.section[data-fade]').forEach(el => sectionIO.observe(el));

  const rowIO = new IntersectionObserver(entries => {
    entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); rowIO.unobserve(e.target); } });
  }, { threshold: 0.08 });
  document.querySelectorAll('.tr[data-row]').forEach(el => rowIO.observe(el));

  const grain = document.getElementById('grain');
  if (grain) {
    window.addEventListener('scroll', () => {
      grain.style.transform = `translateY(${-window.scrollY * 0.14}px)`;
    }, { passive: true });
  }
}

async function loadData() {
  try {
    const res = await fetch('data/latest.json?t=' + Date.now());
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    populateMeta(data);
    populatePrices(data);
    populateFeatured(data);
    populateTicker(data);
    populateExchange(data);
    populateAnalysis(data);
    populateForecast(data);
    populateNews(data);
    await buildChart(data);
  } catch (err) {
    console.error('Failed to load data:', err);
    const area = document.getElementById('content-area');
    if (area) area.innerHTML = `<div class="error-state"><h3>資料載入失敗</h3><p>請確認 GitHub Actions 已成功執行每日分析，或稍後再試。</p><p style="font-size:12px;margin-top:10px;color:#a89682;">${err.message}</p></div>`;
  } finally {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.classList.add('hidden');
    forceScrollTop();
    requestAnimationFrame(forceScrollTop);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  forceScrollTop();
  requestAnimationFrame(forceScrollTop);
  setTimeout(forceScrollTop, 100);
  setTimeout(forceScrollTop, 300);
  importPatFromHash();
  loadData();
  initAnimations();
});

window.addEventListener('load', () => {
  forceScrollTop();
  requestAnimationFrame(forceScrollTop);
  setTimeout(forceScrollTop, 100);
});

// ── GitHub config ─────────────────────────────────────────

const GH_OWNER = 'lijingchiu';
const GH_REPO  = 'SteelWeb';
const WORKFLOW  = 'daily-analysis.yml';
const PAT_KEY   = 'steel_gh_pat';

// ── Toast ──────────────────────────────────────────────────

let _toastTimer = null;

function showToast(type, msg, duration) {
  let el = document.getElementById('run-toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'run-toast';
    document.body.appendChild(el);
  }
  clearTimeout(_toastTimer);
  _toastTimer = null;
  el.className = `run-toast-${type}`;
  el.style.display = 'flex';
  el.innerHTML = `<span>${msg}</span>` +
    (type !== 'loading' ? `<button class="run-toast-close" onclick="window.hideToast()">✕</button>` : '');
  // Auto-dismiss: success=5s, error=8s, loading=never
  const ms = duration !== undefined ? duration
    : type === 'success' ? 5000 : type === 'error' ? 8000 : 0;
  if (ms > 0) _toastTimer = setTimeout(hideToast, ms);
}

function hideToast() {
  clearTimeout(_toastTimer);
  _toastTimer = null;
  const el = document.getElementById('run-toast');
  if (el) el.style.display = 'none';
}

// ── URL hash one-time token import ────────────────────────
// Usage: open https://<site>/#pat=ghp_xxxxxx once to store token.
// The hash is cleared immediately; subsequent visits use localStorage.

function importPatFromHash() {
  try {
    if (!location.hash || !location.hash.includes('pat=')) return;
    const m = location.hash.match(/[#&]?pat=([^&]+)/);
    if (!m || !m[1]) return;
    const token = decodeURIComponent(m[1]).trim();
    if (!token) return;
    localStorage.setItem(PAT_KEY, token);
    history.replaceState(null, '', location.pathname + location.search);
    showToast('success', '✅ 此裝置已完成授權設定，之後按按鈕即可自動執行分析');
  } catch (e) {
    console.error('importPatFromHash:', e);
  }
}

// ── Run modal ──────────────────────────────────────────────

function openRunModal() {
  const modal = document.getElementById('run-modal');
  if (!modal) return;
  modal.style.display = 'flex';

  let saved = null;
  try { saved = localStorage.getItem(PAT_KEY); } catch (_) {}

  const input    = document.getElementById('pat-input');
  const remember = document.getElementById('remember-pat');
  const btn      = document.getElementById('trigger-btn');

  hideRunStatus();
  if (btn) btn.disabled = false;

  if (saved) {
    // Token already stored → auto-fill and auto-trigger
    if (input)    input.value = saved;
    if (remember) remember.checked = true;
    setTimeout(triggerWorkflow, 400);
  } else {
    // No token → wait for manual input
    if (input)    input.value = '';
    if (remember) remember.checked = false;
  }
}

function closeRunModal() {
  const modal = document.getElementById('run-modal');
  if (modal) modal.style.display = 'none';
}

// runInBackground is the onclick target; it opens the modal which
// handles the auto-trigger flow internally.
function runInBackground() {
  openRunModal();
}

function showRunStatus(type, msg) {
  const el = document.getElementById('run-status');
  if (!el) return;
  el.style.display = 'block';
  el.className = `run-status run-status-${type}`;
  el.textContent = msg;
}

function hideRunStatus() {
  const el = document.getElementById('run-status');
  if (el) el.style.display = 'none';
}

// ── Dispatch workflow ──────────────────────────────────────

async function triggerWorkflow() {
  const input = document.getElementById('pat-input');
  const pat = input ? input.value.trim() : '';
  if (!pat) { showRunStatus('error', '請輸入 GitHub PAT'); return; }

  try {
    const remember = document.getElementById('remember-pat');
    if (remember && remember.checked) localStorage.setItem(PAT_KEY, pat);
    else localStorage.removeItem(PAT_KEY);
  } catch (_) {}

  closeRunModal();
  document.querySelectorAll('#run-btn, .btn-ghost').forEach(b => b.disabled = true);
  const enableBtns = () => document.querySelectorAll('#run-btn, .btn-ghost').forEach(b => b.disabled = false);

  const ghHeaders = {
    'Authorization': `Bearer ${pat}`,
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'Content-Type': 'application/json',
  };

  try {
    showToast('loading', '⏳ 驗證 Token，查詢 workflow...');
    const [listRes, repoRes] = await Promise.all([
      fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/actions/workflows`, { headers: ghHeaders }),
      fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}`, { headers: ghHeaders }),
    ]);

    if (listRes.status === 401) {
      showToast('error', '❌ Token 無效或已過期，請重新設定');
      enableBtns(); return;
    }
    if (listRes.status === 403) {
      showToast('error', '❌ 權限不足，請確認 PAT 有 workflow 權限');
      enableBtns(); return;
    }
    if (!listRes.ok) {
      showToast('error', `❌ GitHub API 錯誤 ${listRes.status}`);
      enableBtns(); return;
    }

    const [listData, repoData] = await Promise.all([listRes.json(), repoRes.json()]);
    const defaultBranch = repoData.default_branch || 'main';
    const wf = (listData.workflows || []).find(w => w.path && w.path.endsWith(WORKFLOW));
    const workflowId = wf ? wf.id : WORKFLOW;

    showToast('loading', '⏳ 觸發分析 workflow...');
    const dispatchRes = await fetch(
      `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/actions/workflows/${workflowId}/dispatches`,
      { method: 'POST', headers: ghHeaders, body: JSON.stringify({ ref: defaultBranch, inputs: { force_run: 'true' } }) }
    );

    if (dispatchRes.status === 204) {
      showToast('loading', '✅ 已觸發！分析執行中，約需 2–3 分鐘...');
      pollWorkflow(pat, enableBtns);
    } else {
      const body = await dispatchRes.json().catch(() => ({}));
      showToast('error', `❌ 觸發失敗 ${dispatchRes.status}：${body.message || '未知錯誤'}`);
      enableBtns();
    }
  } catch (e) {
    showToast('error', `❌ 網路錯誤：${e.message}`);
    enableBtns();
  }
}

// ── Poll workflow completion ───────────────────────────────

async function pollWorkflow(pat, enableBtns) {
  const maxAttempts = 36;
  let attempts = 0;
  const triggeredAt = Date.now();

  const poll = async () => {
    attempts++;
    try {
      const res = await fetch(
        `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/actions/runs?per_page=5`,
        { headers: { 'Authorization': `Bearer ${pat}`, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' } }
      );
      if (res.ok) {
        const data = await res.json();
        const run = (data.workflow_runs || []).find(
          r => new Date(r.created_at).getTime() >= triggeredAt - 30000
        );
        if (run) {
          if (run.status === 'completed') {
            if (run.conclusion === 'success') {
              showToast('success', '✅ 分析完成！正在重新整理頁面...', 3000);
              setTimeout(() => location.reload(), 3000);
            } else {
              showToast('error', `❌ 執行失敗（${run.conclusion}），請至 GitHub Actions 查看`);
              enableBtns();
            }
            return;
          }
          const elapsed = Math.round((Date.now() - triggeredAt) / 1000);
          const label = run.status === 'in_progress' ? '執行中' : '排隊中';
          showToast('loading', `⏳ ${label}... 已等待 ${elapsed} 秒`);
        }
      }
    } catch (_) {}
    if (attempts < maxAttempts) setTimeout(poll, 10000);
    else { showToast('error', '⏱ 等待逾時，請至 GitHub Actions 確認執行狀況'); enableBtns(); }
  };

  setTimeout(poll, 8000);
}

// ── Keyboard: ESC closes modal ────────────────────────────

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeRunModal(); });

// ── Expose all functions to window for inline onclick ─────

window.openRunModal    = openRunModal;
window.closeRunModal   = closeRunModal;
window.triggerWorkflow = triggerWorkflow;
window.runInBackground = runInBackground;
window.hideToast       = hideToast;
