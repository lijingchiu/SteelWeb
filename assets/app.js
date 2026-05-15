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
let toastTimer = null;
let tickerGroupMarkup = '';
let tickerResizeTimer = null;
let tickerFrameId = null;
let tickerLastTs = 0;
let tickerOffset = 0;
let tickerLoopWidth = 0;
let tickerContainerWidth = 0;
const TICKER_SPEED_PX_PER_SEC = 42;

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
  el.textContent = fmtChange(changeAmt, decimals);
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
  if (rate) rate.textContent = ex.usd_twd_estimate ? ex.usd_twd_estimate.toFixed(2) : '-';
  if (impact) impact.textContent = ex.impact_on_steel || '-';
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
      } catch {
        updatedEl.textContent = data.date || '-';
      }
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
  tickerGroupMarkup = items.map(buildItem).join('');
  renderTicker();
}

function renderTicker() {
  const inner = document.getElementById('ticker-inner');
  if (!inner || !tickerGroupMarkup) return;

  const containerWidth = inner.parentElement?.clientWidth || window.innerWidth || 0;
  const previousLoopWidth = tickerLoopWidth;
  const previousOffset = tickerOffset;
  let repeatedMarkup = tickerGroupMarkup;

  inner.innerHTML = `<div class="ticker-group">${repeatedMarkup}</div>`;
  let group = inner.firstElementChild;
  let guard = 0;

  while (group && group.scrollWidth < containerWidth * 1.5 && guard < 6) {
    repeatedMarkup += tickerGroupMarkup;
    group.innerHTML = repeatedMarkup;
    guard += 1;
  }

  inner.innerHTML = `
    <div class="ticker-group">${repeatedMarkup}</div>
    <div class="ticker-group" aria-hidden="true">${repeatedMarkup}</div>
  `;
  tickerContainerWidth = containerWidth;
  tickerLoopWidth = inner.firstElementChild?.scrollWidth || 0;
  if (previousLoopWidth > 0 && tickerLoopWidth > 0) {
    const progress = ((-previousOffset % previousLoopWidth) + previousLoopWidth) % previousLoopWidth;
    tickerOffset = -((progress / previousLoopWidth) * tickerLoopWidth);
  } else {
    tickerOffset = 0;
  }
  tickerLastTs = 0;
  inner.style.transform = `translate3d(${tickerOffset}px, 0, 0)`;
  startTickerAnimation();
}

function stopTickerAnimation() {
  if (tickerFrameId) {
    window.cancelAnimationFrame(tickerFrameId);
    tickerFrameId = null;
  }
}

function startTickerAnimation() {
  const inner = document.getElementById('ticker-inner');
  if (!inner || !tickerLoopWidth) return;
  stopTickerAnimation();

  const tick = ts => {
    if (!document.body.contains(inner)) {
      stopTickerAnimation();
      return;
    }
    if (document.hidden) {
      tickerLastTs = ts;
      tickerFrameId = window.requestAnimationFrame(tick);
      return;
    }

    if (!tickerLastTs) tickerLastTs = ts;
    const delta = Math.min((ts - tickerLastTs) / 1000, 0.05);
    tickerLastTs = ts;

    tickerOffset -= TICKER_SPEED_PX_PER_SEC * delta;
    if (Math.abs(tickerOffset) >= tickerLoopWidth) {
      tickerOffset += tickerLoopWidth;
    }

    inner.style.transform = `translate3d(${tickerOffset}px, 0, 0)`;
    tickerFrameId = window.requestAnimationFrame(tick);
  };

  tickerFrameId = window.requestAnimationFrame(tick);
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

function ensureToast() {
  let toast = document.getElementById('run-toast');
  if (toast) return toast;
  toast = document.createElement('div');
  toast.id = 'run-toast';
  toast.style.display = 'none';
  document.body.appendChild(toast);
  return toast;
}

function hideToast() {
  if (toastTimer) {
    clearTimeout(toastTimer);
    toastTimer = null;
  }
  const toast = document.getElementById('run-toast');
  if (!toast) return;
  toast.style.display = 'none';
  toast.innerHTML = '';
  toast.className = '';
}

function showToast(type, message, options = {}) {
  const toast = ensureToast();
  if (toastTimer) {
    clearTimeout(toastTimer);
    toastTimer = null;
  }
  toast.className = `run-toast-${type}`;
  toast.innerHTML = `
    <span>${message}</span>
    <button class="run-toast-close" type="button" aria-label="關閉通知">✕</button>
  `;
  toast.style.display = 'flex';
  const closeBtn = toast.querySelector('.run-toast-close');
  if (closeBtn) closeBtn.onclick = hideToast;
  if (options.autoHideMs) {
    toastTimer = window.setTimeout(hideToast, options.autoHideMs);
  }
}

function importPatFromHash() {
  const rawHash = window.location.hash;
  if (!rawHash || rawHash.length <= 1) return false;
  const params = new URLSearchParams(rawHash.slice(1));
  const pat = (params.get('pat') || '').trim();
  if (!pat) return false;
  localStorage.setItem(PAT_KEY, pat);
  const input = document.getElementById('pat-input');
  if (input) input.value = pat;
  history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
  showToast('success', '此裝置已完成授權設定', { autoHideMs: 4000 });
  return true;
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

const GH_OWNER = 'lijingchiu';
const GH_REPO  = 'SteelWeb';
const WORKFLOW = 'daily-analysis.yml';
const PAT_KEY  = 'steel_gh_pat';

function runInBackground() {
  openRunModal();
}

function openRunModal() {
  const modal = document.getElementById('run-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  const saved = localStorage.getItem(PAT_KEY);
  const input = document.getElementById('pat-input');
  const remember = document.getElementById('remember-pat');
  if (saved && input) {
    input.value = saved;
    if (remember) remember.checked = true;
  }
  hideRunStatus();
  const triggerBtn = document.getElementById('trigger-btn');
  if (triggerBtn) triggerBtn.disabled = false;
  if (saved) {
    showToast('loading', '已讀取此裝置授權，正在觸發分析...');
    setTimeout(() => triggerWorkflow(), 200);
  } else if (input) {
    showToast('loading', '請先完成此裝置授權設定', { autoHideMs: 2500 });
    setTimeout(() => input.focus(), 80);
  }
}

function closeRunModal() {
  const modal = document.getElementById('run-modal');
  if (modal) modal.style.display = 'none';
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeRunModal();
});

function showRunStatus(type, msg) {
  const el = document.getElementById('run-status');
  if (!el) return;
  el.style.display = 'block';
  el.className = `run-status run-status-${type}`;
  el.textContent = msg;
}

function hideRunStatus() {
  const el = document.getElementById('run-status');
  if (!el) return;
  el.style.display = 'none';
  el.textContent = '';
  el.onclick = null;
  el.style.cursor = 'default';
}

async function triggerWorkflow() {
  const input = document.getElementById('pat-input');
  const pat = input ? input.value.trim() : '';
  if (!pat) {
    showRunStatus('error', '請輸入 GitHub PAT');
    showToast('error', '找不到 GitHub PAT，請先完成授權設定', { autoHideMs: 4000 });
    return;
  }
  if (!/^[\x20-\x7E]+$/.test(pat)) {
    showRunStatus('error', '❌ Token 包含無效字元，請重新複製貼上 GitHub PAT（只能包含英數字及符號）');
    showToast('error', 'PAT 格式不正確，請重新設定', { autoHideMs: 4000 });
    return;
  }

  const remember = document.getElementById('remember-pat');
  if (remember && remember.checked) {
    localStorage.setItem(PAT_KEY, pat);
  } else {
    localStorage.removeItem(PAT_KEY);
  }

  const btn = document.getElementById('trigger-btn');
  if (btn) btn.disabled = true;

  const ghHeaders = {
    'Authorization': `Bearer ${pat}`,
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'Content-Type': 'application/json',
  };

  try {
    showRunStatus('loading', '⏳ 驗證 Token 並查詢 workflow...');
    showToast('loading', '正在驗證授權與查詢 workflow...');
    const [listRes, repoRes] = await Promise.all([
      fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/actions/workflows`, { headers: ghHeaders }),
      fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}`, { headers: ghHeaders }),
    ]);

    if (listRes.status === 401 || repoRes.status === 401) {
      showRunStatus('error', '❌ PAT 無效或已過期，請重新確認 Token');
      showToast('error', 'PAT 無效或已過期', { autoHideMs: 4500 });
      if (btn) btn.disabled = false;
      return;
    }
    if (listRes.status === 403 || repoRes.status === 403) {
      showRunStatus('error', '❌ 權限不足，請確認 PAT 已勾選 workflow 權限');
      showToast('error', 'PAT 權限不足，缺少 workflow 權限', { autoHideMs: 4500 });
      if (btn) btn.disabled = false;
      return;
    }
    if (!listRes.ok) {
      const b = await listRes.json().catch(() => ({}));
      const msg = `❌ API 錯誤 ${listRes.status}：${b.message || '無法取得 workflow 列表'}`;
      showRunStatus('error', msg);
      showToast('error', msg, { autoHideMs: 5000 });
      if (btn) btn.disabled = false;
      return;
    }

    const [listData, repoData] = await Promise.all([listRes.json(), repoRes.json()]);
    const defaultBranch = repoData.default_branch || 'main';
    const wf = (listData.workflows || []).find(w => w.path && w.path.endsWith(WORKFLOW));
    const workflowId = wf ? wf.id : WORKFLOW;

    if (!wf) {
      showRunStatus('loading', `⏳ Workflow 未在列表中，嘗試直接觸發（分支：${defaultBranch}）...`);
      showToast('loading', '找不到 workflow 列表項目，改用檔名直接觸發...');
    }

    const dispatchRes = await fetch(
      `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/actions/workflows/${workflowId}/dispatches`,
      {
        method: 'POST',
        headers: ghHeaders,
        body: JSON.stringify({ ref: defaultBranch, inputs: { force_run: 'true' } }),
      }
    );

    if (dispatchRes.status === 204) {
      showRunStatus('loading', '✅ 已成功觸發！分析執行中，約需 2-3 分鐘...');
      showToast('success', '已成功觸發 GitHub Actions，正在執行分析', { autoHideMs: 3500 });
      pollWorkflowStatus(pat);
    } else if (dispatchRes.status === 401) {
      showRunStatus('error', '❌ PAT 無效或已過期，請重新確認 Token');
      showToast('error', 'PAT 無效或已過期', { autoHideMs: 4500 });
      if (btn) btn.disabled = false;
    } else if (dispatchRes.status === 403) {
      showRunStatus('error', '❌ 權限不足，請確認 PAT 已勾選 workflow 權限');
      showToast('error', 'PAT 權限不足，無法觸發 workflow', { autoHideMs: 4500 });
      if (btn) btn.disabled = false;
    } else if (dispatchRes.status === 404) {
      const msg = `❌ GitHub 找不到 workflow（分支：${defaultBranch}），請至 Actions 頁面手動執行一次以啟用`;
      showRunStatus('error', msg);
      showToast('error', msg, { autoHideMs: 5000 });
      if (btn) btn.disabled = false;
    } else if (dispatchRes.status === 422) {
      const body = await dispatchRes.json().catch(() => ({}));
      const msg = `❌ 請求被拒絕 (422)：${body.message || ''} （ref: ${defaultBranch}）`;
      showRunStatus('error', msg);
      showToast('error', msg, { autoHideMs: 5000 });
      if (btn) btn.disabled = false;
    } else {
      const body = await dispatchRes.json().catch(() => ({}));
      const msg = `❌ 錯誤 ${dispatchRes.status}：${body.message || '未知錯誤'}`;
      showRunStatus('error', msg);
      showToast('error', msg, { autoHideMs: 5000 });
      if (btn) btn.disabled = false;
    }
  } catch (e) {
    const msg = `❌ 網路錯誤：${e.message}`;
    showRunStatus('error', msg);
    showToast('error', msg, { autoHideMs: 5000 });
    if (btn) btn.disabled = false;
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
        `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/actions/runs?per_page=5`,
        {
          headers: {
            'Authorization': `Bearer ${pat}`,
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
          },
        }
      );
      if (res.ok) {
        const data = await res.json();
        const run = (data.workflow_runs || []).find(
          r => new Date(r.created_at).getTime() >= triggeredAt - 30000
        );
        if (run) {
          if (run.status === 'completed') {
            if (run.conclusion === 'success') {
              showRunStatus('success', '✅ 分析完成！點此重新整理查看最新資料。');
              showToast('success', '分析完成，點通知或重新整理可查看最新資料', { autoHideMs: 5000 });
              const statusEl = document.getElementById('run-status');
              if (statusEl) {
                statusEl.style.cursor = 'pointer';
                statusEl.onclick = () => location.reload();
              }
            } else {
              const msg = `❌ 執行失敗（${run.conclusion}），請至 GitHub Actions 查看詳情`;
              showRunStatus('error', msg);
              showToast('error', msg, { autoHideMs: 5000 });
            }
            const btn = document.getElementById('trigger-btn');
            if (btn) btn.disabled = false;
            return;
          }
          const elapsed = Math.round((Date.now() - triggeredAt) / 1000);
          const label = run.status === 'in_progress' ? '執行中' : '排隊中';
          const msg = `⏳ ${label}...（已等待 ${elapsed} 秒）`;
          showRunStatus('loading', msg);
          showToast('loading', msg);
        }
      }
    } catch (_) {}
    if (attempts < maxAttempts) {
      setTimeout(poll, 10000);
    } else {
      const msg = '⏱ 等待逾時，請至 GitHub Actions 頁面確認執行狀況';
      showRunStatus('error', msg);
      showToast('error', msg, { autoHideMs: 5000 });
      const btn = document.getElementById('trigger-btn');
      if (btn) btn.disabled = false;
    }
  };

  setTimeout(poll, 8000);
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

window.addEventListener('resize', () => {
  if (!tickerGroupMarkup) return;
  if (tickerResizeTimer) clearTimeout(tickerResizeTimer);
  tickerResizeTimer = window.setTimeout(() => {
    const inner = document.getElementById('ticker-inner');
    if (!inner) return;
    const nextWidth = inner.parentElement?.clientWidth || window.innerWidth || 0;
    if (Math.abs(nextWidth - tickerContainerWidth) < 2) return;
    renderTicker();
  }, 120);
});

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    tickerLastTs = 0;
    return;
  }
  if (tickerGroupMarkup) startTickerAnimation();
});

window.addEventListener('load', () => {
  forceScrollTop();
  requestAnimationFrame(forceScrollTop);
  setTimeout(forceScrollTop, 100);
});

window.runInBackground = runInBackground;
window.openRunModal = openRunModal;
window.closeRunModal = closeRunModal;
window.triggerWorkflow = triggerWorkflow;
window.showToast = showToast;
window.hideToast = hideToast;
