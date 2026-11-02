'use strict';

if ('scrollRestoration' in history) history.scrollRestoration = 'manual';

// Scroll resets only apply until the visitor touches the page, so a late
// load event can never pull them away from where they navigated.
let _userInteracted = false;
['pointerdown', 'touchstart', 'wheel', 'keydown'].forEach(ev =>
  window.addEventListener(ev, () => { _userInteracted = true; }, { capture: true, passive: true, once: true }));

function forceScrollTop() {
  if (_userInteracted) return;
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

// Model-written text sometimes carries citation markup like "([site](https://...))";
// links belong in the source lists, so drop them from prose.
function plain(s) {
  return String(s ?? '')
    .replace(/\(\s*\[[^\]]*\]\([^)]*\)\s*\)/g, '')
    .replace(/\[([^\]]*)\]\((?:https?:)?[^)]*\)/g, '$1')
    .replace(/https?:\/\/\S+/g, '')
    .replace(/\(?\s*\[[^\]]*\]\(\s*\)?\s*\)?/g, '')
    .replace(/[ \t]{2,}/g, ' ')
    .trim();
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function safeUrl(u) {
  return typeof u === 'string' && /^https?:\/\//.test(u) ? esc(u) : '#';
}

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
  // Toggle classes instead of replacing className: the table cells carry
  // layout classes (td col-chg) that must survive.
  el.classList.add('price-change');
  el.classList.remove('up', 'down', 'stable');
  if (typeof changeAmt !== 'number') { el.textContent = '-'; el.classList.add('stable'); return; }
  const cls = changeAmt > 0 ? 'up' : changeAmt < 0 ? 'down' : 'stable';
  el.textContent = fmtChange(changeAmt, decimals) + ' ' + (unit || '元');
  el.classList.add(cls);
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

function populateHeadline(data) {
  const el = document.getElementById('hero-headline');
  if (!el) return;
  el.textContent = data.headline || '';
  el.hidden = !data.headline;
  const hasStories = Array.isArray(data.top_stories) && data.top_stories.length > 0;
  el.classList.toggle('clickable', hasStories);
  if (hasStories) {
    el.title = '查看今日鋼市頭條';
    el.setAttribute('role', 'button');
    el.tabIndex = 0;
    el.onclick = () => openBriefing(data);
    el.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openBriefing(data); } };
  }
}

// ── Today's top-stories briefing (opened from a push notification) ──

function closeBriefing() {
  const el = document.getElementById('briefing');
  if (el) el.remove();
  document.body.classList.remove('brief-open');
}

function scrollToEl(el, flash = true) {
  const header = document.querySelector('.masthead');
  const sticky = header && ['sticky', 'fixed'].includes(getComputedStyle(header).position);
  const offset = (sticky ? header.offsetHeight : 0) + 12;
  // offsetTop ignores the fade-in transform, so a section that is still sliding
  // into place lands where it will end up rather than where it is mid-animation.
  let top = 0;
  for (let n = el; n; n = n.offsetParent) top += n.offsetTop;
  const y = Math.max(0, top - offset);
  try { window.scrollTo({ top: y, behavior: 'smooth' }); } catch (_) { window.scrollTo(0, y); }
  if (!flash) return;
  el.classList.remove('brief-flash');
  void el.offsetWidth;
  el.classList.add('brief-flash');
  setTimeout(() => el.classList.remove('brief-flash'), 2400);
}

function goToAnchor(anchor, search) {
  _userInteracted = true;
  if (anchor === 'materials' && search) {
    const input = document.getElementById('mat-search');
    if (input) {
      input.value = search;
      matState.q = search;
      renderMaterials();
    }
  }
  const target = document.getElementById(anchor) || document.getElementById('news');
  if (!target) return;
  const section = target.closest('.section');
  if (section) section.classList.add('in');
  target.classList.add('in');
  // Wait for the modal to leave the layout before measuring.
  requestAnimationFrame(() => requestAnimationFrame(() => scrollToEl(target)));
}

function goToStory(i) {
  closeBriefing();
  goToAnchor(document.getElementById(`story-${i}`) ? `story-${i}` : 'news');
}

const ANCHOR_LABELS = {
  prices: '看鋼材報價', materials: '看營建材料行情', chart: '看價格走勢', forecast: '看盤價預測',
  analysis: '看市場深度分析', news: '',
};

function populateTopStories(data) {
  const el = document.getElementById('top-stories');
  if (!el) return;
  const stories = Array.isArray(data.top_stories) ? data.top_stories : [];
  if (!stories.length) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="ts-head">今日頭條 · 依報導媒體家數排序</div>` + stories.map((st, i) => {
    const articles = Array.isArray(st.articles) && st.articles.length
      ? st.articles
      : (/^https?:\/\//.test(st.url || '') ? [{ title: st.headline, url: st.url, source: st.source, date: st.date }] : []);
    const label = st.anchor && st.anchor.startsWith('fc-') ? '看相關盤價預測' : ANCHOR_LABELS[st.anchor] || '';
    return `<article class="ts-item" id="story-${i}">
        <div class="ts-top">
          <span class="ts-num">${String(i + 1).padStart(2, '0')}</span>
          <div class="ts-body">
            <h3 class="ts-headline">${esc(st.headline)}</h3>
            ${st.subheadline ? `<p class="ts-sub">${esc(st.subheadline)}</p>` : ''}
            <div class="ts-meta">${st.coverage > 1 ? `${st.coverage} 家媒體報導` : '1 家媒體報導'}${st.date ? ` · ${esc(st.date)}` : ''}</div>
          </div>
        </div>
        ${articles.length ? `<ul class="ts-articles">${articles.map(a => `<li><a href="${safeUrl(a.url)}" target="_blank" rel="noopener">
            <span class="ts-a-title">${esc(a.title)}</span><span class="ts-a-src">${esc([a.source, a.date].filter(Boolean).join(' · '))} ↗</span></a></li>`).join('')}</ul>` : ''}
        ${label ? `<button type="button" class="ts-go" data-anchor="${esc(st.anchor)}" data-search="${esc(st.search || '')}">${label} →</button>` : ''}
      </article>`;
  }).join('');
  el.onclick = e => {
    const b = e.target.closest('.ts-go');
    if (b) goToAnchor(b.dataset.anchor, b.dataset.search);
  };
}

function openBriefing(data) {
  const stories = Array.isArray(data.top_stories) ? data.top_stories : [];
  if (!stories.length) return;
  closeBriefing();
  const date = (data.date || '').slice(5).replace('-', '/');
  const wrap = document.createElement('div');
  wrap.id = 'briefing';
  wrap.className = 'brief-overlay';
  wrap.innerHTML = `<div class="brief-box" role="dialog" aria-modal="true" aria-labelledby="brief-title" tabindex="-1">
      <div class="brief-head">
        <div>
          <div class="kicker">TODAY'S HEADLINES · ${esc(date)}</div>
          <h3 class="brief-title" id="brief-title">今日鋼市頭條</h3>
        </div>
        <button type="button" class="brief-close" aria-label="關閉">✕</button>
      </div>
      <ol class="brief-list">
        ${stories.map((st, i) => `<li class="brief-item" role="button" tabindex="0" data-i="${i}">
            <span class="brief-num">${String(i + 1).padStart(2, '0')}</span>
            <div class="brief-text">
              <div class="brief-headline">${esc(st.headline)}</div>
              ${st.subheadline ? `<div class="brief-sub">${esc(st.subheadline)}</div>` : ''}
            </div>
            ${/^https?:\/\//.test(st.url || '') ? `<a class="brief-go" href="${safeUrl(st.url)}" target="_blank" rel="noopener"
                 aria-label="開啟新聞原文：${esc(st.source || '新聞網站')}" title="開啟新聞原文${st.source ? '（' + esc(st.source) + '）' : ''}">↗</a>` : ''}
          </li>`).join('')}
      </ol>
      <div class="brief-foot">
        <span>點標題看網站內的相關報導，點 ↗ 開啟新聞原文</span>
        <button type="button" class="btn btn-solid brief-continue">繼續瀏覽</button>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  document.body.classList.add('brief-open');

  wrap.addEventListener('click', e => {
    if (e.target === wrap || e.target.closest('.brief-close') || e.target.closest('.brief-continue')) { closeBriefing(); return; }
    if (e.target.closest('.brief-go')) return;
    const item = e.target.closest('.brief-item');
    if (item) goToStory(Number(item.dataset.i));
  });
  wrap.addEventListener('keydown', e => {
    const item = e.target.closest && e.target.closest('.brief-item');
    if (item && e.target === item && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      goToStory(Number(item.dataset.i));
    }
  });
  wrap.querySelector('.brief-box').focus({ preventScroll: true });
}

function maybeOpenBriefingFromPush(data) {
  const params = new URLSearchParams(location.search);
  if (params.get('from') !== 'push') return;
  params.delete('from');
  const qs = params.toString();
  history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
  openBriefing(data);
}

function populateAnalysis(data) {
  const fields = {
    'summary-text': data.summary,
    'spread-analysis': data.spread_analysis,
    'weekly-trend': data.monthly_trend || data.weekly_trend,
    'international-outlook': data.international_outlook,
    'materials-outlook': data.materials_outlook,
    'model-name': data.model_used,
  };
  for (const [id, text] of Object.entries(fields)) {
    const el = document.getElementById(id);
    if (el) el.textContent = text || '-';
  }
  const riskList = document.getElementById('risk-factors');
  if (riskList && Array.isArray(data.risk_factors)) {
    riskList.innerHTML = data.risk_factors.map(r => `<li>⚠ ${esc(r)}</li>`).join('');
  }
}

function populateNews(data) {
  const list = document.getElementById('news-list');
  if (!list) return;
  const sources = (Array.isArray(data.news_sources) ? data.news_sources : []).filter(n => n.title);
  if (sources.length === 0) {
    list.innerHTML = '<p class="no-news">暫無新聞來源資料</p>';
    return;
  }
  list.innerHTML = sources.map((n, i) => {
    const meta = [n.date, n.source].filter(Boolean).map(esc).join(' · ');
    return `<a class="news-item" href="${safeUrl(n.url)}" target="_blank" rel="noopener">
        <span class="news-item-num">${String(i + 1).padStart(2, '0')}</span>
        <span class="news-item-title">${esc(n.title)}${meta ? `<span class="news-item-meta">${meta}</span>` : ''}</span>
        <span class="news-arrow">閱讀全文 →</span>
      </a>`;
  }).join('');
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

let chartSeries = null;

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Transparent fill for a chart line, from a hex colour token.
function tint(hex, alpha) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  return m ? `rgba(${parseInt(m[1], 16)}, ${parseInt(m[2], 16)}, ${parseInt(m[3], 16)}, ${alpha})` : hex;
}

async function buildChart(latestData) {
  const canvas = document.getElementById('price-chart');
  if (!canvas || typeof Chart === 'undefined') return;

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

  chartSeries = { months, billetVals, rebarVals, hbeamVals, wirerodVals };
  drawChart();
}

function drawChart() {
  const canvas = document.getElementById('price-chart');
  if (!canvas || !chartSeries || typeof Chart === 'undefined') return;
  const ctx = canvas.getContext('2d');
  const { months, billetVals, rebarVals, hbeamVals, wirerodVals } = chartSeries;
  const c = [1, 2, 3, 4].map(i => cssVar(`--chart-${i}`));
  const muted = cssVar('--muted');
  const grid = cssVar('--chart-grid');
  const line = (label, data, color) => ({
    label, data, borderColor: color, backgroundColor: tint(color, 0.07), pointBackgroundColor: color,
    pointRadius: 3, pointHoverRadius: 5, tension: 0.35, borderWidth: 1.5, fill: true,
  });

  if (priceChart) priceChart.destroy();
  Chart.defaults.color = muted;
  Chart.defaults.borderColor = grid;
  priceChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: months,
      datasets: [
        line('小鋼胚', billetVals, c[0]),
        line('鋼筋', rebarVals, c[1]),
        line('H型鋼', hbeamVals, c[2]),
        line('棒線', wirerodVals, c[3]),
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: cssVar('--tooltip-bg'), borderColor: cssVar('--line'), borderWidth: 1,
          titleColor: cssVar('--ink'), bodyColor: muted,
          callbacks: { label(item) { return ` ${item.dataset.label}：${item.parsed.y?.toLocaleString('zh-TW') ?? '-'} 元/噸`; } },
        },
      },
      scales: {
        x: { grid: { color: grid }, ticks: { maxRotation: 45, font: { size: 11 }, color: muted } },
        y: { grid: { color: grid }, ticks: { font: { size: 11 }, color: muted, callback: v => v.toLocaleString('zh-TW') } },
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

const FC_ITEMS = [
  { key: 'north_scrap_price',    name: '北部廢鋼大盤收購價', sub: 'N. Taiwan Scrap' },
  { key: 'billet_price',         name: '小鋼胚中級出廠價',   sub: 'Billet Ex-Factory' },
  { key: 'fengxing_rebar_price', name: '豐興鋼筋盤價',       sub: 'Fengxing Rebar' },
  { key: 'h_beam_price',         name: '東鋼H型鋼流通價',    sub: 'H-Beam Circulation' },
  { key: 'csc_wire_rod_price',   name: '中鋼棒線盤價',       sub: 'CSC Wire Rod' },
];
const DIR_LABELS = { up: '看漲', down: '看跌', stable: '持平' };

const DIR_ARROWS = { up: '▲', down: '▼', stable: '◆' };

function fcDir(f) {
  return ['up', 'down', 'stable'].includes(f?.direction) ? f.direction : null;
}

function fcBadge(f) {
  const dir = fcDir(f);
  return `<span class="trend-badge fc-badge ${dir || 'stable'}">${dir ? `${DIR_ARROWS[dir]} ${DIR_LABELS[dir]}` : '-'}</span>`;
}

// On phones the long reasoning is collapsed behind a toggle; desktop shows it open.
function fcWide() {
  return window.matchMedia('(min-width: 769px)').matches;
}

const SCEN_LABELS = { up: '漲', stable: '持平', down: '跌' };

// Probability bar for the three possible outcomes of the next monthly average.
function fcScenarios(f, ens) {
  const sc = f?.scenarios;
  if (!sc) return '';
  const probs = ['up', 'stable', 'down'].map(d => [d, Number(sc[d]?.prob) || 0]);
  if (!probs.some(([, p]) => p > 0)) return '';
  const bar = probs.map(([d, p]) => p > 0 ? `<span class="fc-scen-${d}" style="width:${p}%"></span>` : '').join('');
  const legend = probs.map(([d, p]) => `<span class="fc-scen-key fc-scen-key-${d}">${SCEN_LABELS[d]} ${p}%</span>`).join('');
  const agree = ens && ens.runs > 1 ? `<div class="fc-scen-note">${ens.runs} 次獨立分析中，${ens.month_agree} 次判斷方向相同</div>` : '';
  return `<div class="fc-scen" title="各種結果的機率">
      <div class="fc-scen-bar">${bar}</div>
      <div class="fc-scen-legend">${legend}</div>${agree}
    </div>`;
}

function fcBlock(label, f, extra = '') {
  const open = fcWide() ? ' open' : '';
  return `<div class="fc-block">
      <div class="fc-block-head">
        <span class="fc-block-label">${esc(label)}</span>
        ${fcBadge(f)}
      </div>
      <div class="fc-est">${esc(f?.change_estimate || '-')}</div>
      ${extra}
      <details class="fc-why"${open}>
        <summary>看推論</summary>
        <p class="fc-reason">${esc(plain(f?.reason) || '預測資料將於下次分析執行後產生')}</p>
      </details>
    </div>`;
}

function fcSummary(pf, weekLabel) {
  const monthHead = (Object.values(pf.targets || {})[0] || {}).target_month;
  const weekHead = `${weekLabel}行情`;
  const monthLabel = monthHead ? `${monthHead} 月均價` : '下一期月均價';
  const rows = FC_ITEMS.map(({ key, name }) => {
    const f = pf.items[key] || {};
    const cell = (g, cls, label) => `<div class="fc-sum-cell ${cls}" data-label="${esc(label)}">${fcBadge(g)}<span class="fc-sum-est">${esc(g?.change_estimate || '-')}</span></div>`;
    return `<a class="fc-sum-row" href="#fc-${key}">
        <span class="fc-sum-name">${esc(name)}</span>
        ${cell(f.week, 'fc-sum-week', weekHead)}${cell(f.next_month, 'fc-sum-month', monthLabel)}
      </a>`;
  }).join('');
  return `<div class="fc-summary">
      <div class="fc-sum-row fc-sum-head">
        <span class="fc-sum-name">品項</span>
        <span class="fc-sum-cell">${esc(weekHead)}</span>
        <span class="fc-sum-cell">${esc(monthLabel)}</span>
      </div>
      ${rows}
    </div>`;
}

// Two independent columns (cards 1,3,5 | 2,4) so opening or closing a card only moves
// the cards below it in the same column. On phones the columns dissolve and the
// inline order restores 1-5.
function fcColumns(cards) {
  const left = cards.filter((_, i) => i % 2 === 0).join('');
  const right = cards.filter((_, i) => i % 2 === 1).join('');
  return `<div class="fc-col">${left}</div><div class="fc-col">${right}</div>`;
}

function populateForecast(data) {
  const grid = document.getElementById('fc-grid');
  const dateEl = document.getElementById('forecast-date');
  const summary = document.getElementById('fc-summary');
  const pf = data.price_forecast;
  const legacy = data.tomorrow_forecast;
  if (!grid) return;

  if (pf && pf.items) {
    const weekLabel = pf.week_label || '本週';
    if (dateEl) dateEl.textContent = `${weekLabel} ${pf.week_range || ''} · 發布於 ${data.date || '-'}`;
    if (summary) summary.innerHTML = fcSummary(pf, weekLabel);
    const factsById = Object.fromEntries(((data.research || {}).facts || []).map(x => [x.id, x]));
    grid.innerHTML = fcColumns(FC_ITEMS.map(({ key, name, sub }, i) => {
      const f = pf.items[key] || {};
      const tgt = (pf.targets || {})[key];
      const monthLabel = tgt ? `下一期月均價 ${tgt.target_month}` : '下一期月均價';
      const note = f.revision_note
        ? `<details class="fc-why fc-note-wrap"${fcWide() ? ' open' : ''}><summary>與前次預測比較</summary><div class="fc-note">${esc(plain(f.revision_note))}</div></details>`
        : '';
      return `<div class="fc-card" id="fc-${key}" style="order:${i}">
          <div class="fc-head"><div><div class="fc-name">${name}</div><div class="fc-sub">${sub}</div></div></div>
          ${fcBlock(`${weekLabel}行情 ${pf.week_range || ''}`, f.week)}
          ${fcBlock(monthLabel, f.next_month, fcScenarios(f.next_month, f.ensemble))}
          ${fcRisk(f, factsById)}
          ${note}
        </div>`;
    }));
  } else if (legacy) {
    if (dateEl) dateEl.textContent = `發布於 ${data.date || '-'}`;
    grid.innerHTML = fcColumns(FC_ITEMS.map(({ key, name, sub }, i) => `<div class="fc-card" style="order:${i}">
        <div class="fc-head"><div><div class="fc-name">${name}</div><div class="fc-sub">${sub}</div></div></div>
        ${fcBlock('短期行情', legacy[key])}
      </div>`));
  }

  const overall = document.getElementById('fc-overall-basis');
  if (overall) overall.textContent = plain((pf || legacy || {}).overall_basis) || '預測資料將於下次分析執行後產生';
  const research = document.getElementById('fc-research');
  if (research) research.innerHTML = researchHtml(data.research);

  const cites = document.getElementById('fc-cites');
  if (cites) {
    const list = Array.isArray(data.web_citations) ? data.web_citations : [];
    cites.innerHTML = list.length
      ? `<details class="fc-why"${fcWide() ? ' open' : ''}><summary>AI 搜尋引用來源（${list.length}）</summary><div class="fc-cites-list">` +
        list.map(c => `<a href="${safeUrl(c.url)}" target="_blank" rel="noopener">${esc(c.title)}</a>`).join('') + '</div></details>'
      : '';
  }
}

function factLine(fx) {
  const n = fx.source_count || (fx.sources || []).length;
  const links = (fx.sources || []).map(s => `<a href="${safeUrl(s.url)}" target="_blank" rel="noopener">${esc(s.title || '來源')}</a>`).join('、');
  return `<li class="rs-fact">
      <span class="rs-type rs-type-${esc(fx.type)}">${esc(fx.type)}</span>
      <span class="rs-text">${esc(plain(fx.fact))}</span>
      <span class="rs-meta">${fx.date ? esc(fx.date) + ' · ' : ''}${n >= 2 ? `${n} 個網站互相印證` : '只有 1 個來源'}${links ? ' · ' + links : ''}</span>
    </li>`;
}

function fcRisk(f, factsById) {
  const facts = (f.evidence || []).map(id => factsById[id]).filter(Boolean);
  if (!f.counterpoint && !f.watch && !facts.length) return '';
  const rows = [];
  if (facts.length) rows.push(`<div class="fc-risk-k">主要根據的消息</div><ul class="rs-list">${facts.map(factLine).join('')}</ul>`);
  if (f.counterpoint) rows.push(`<div class="fc-risk-k">可能看錯的地方</div><p class="fc-reason">${esc(plain(f.counterpoint))}</p>`);
  if (f.watch) rows.push(`<div class="fc-risk-k">接下來要留意</div><p class="fc-reason">${esc(plain(f.watch))}</p>`);
  return `<details class="fc-why fc-risk"${fcWide() ? ' open' : ''}><summary>根據與風險</summary>${rows.join('')}</details>`;
}

const CHAIN_STATUS = { '正在發生': 'on', '沒有發生': 'off', '尚待觀察': 'wait' };

function researchHtml(r) {
  if (!r || !(r.facts || []).length) return '';
  const facts = [...r.facts].sort((a, b) => (b.source_count || 0) - (a.source_count || 0));
  const checked = facts.filter(x => (x.source_count || 0) >= 2).length;
  const parts = [`<div class="rs-sec"><div class="fc-risk-k">查證過的消息（${facts.length} 則，其中 ${checked} 則有兩個以上網站互相印證）</div><ul class="rs-list">${facts.map(factLine).join('')}</ul></div>`];
  const links = (r.links || []).filter(x => x.strength !== '弱或不成立');
  const chains = r.chains || [];
  if (links.length || chains.length) {
    const hist = links.map(x => `<li><b>${esc(x.cause_name)} → ${esc(x.effect_name)}</b>：過去${x.lag ? '前者先動、後者下個月才跟' : '同一個月一起漲跌'}，關聯${esc(x.strength)}</li>`).join('');
    const now = chains.map(c => `<li><span class="rs-chain rs-chain-${CHAIN_STATUS[c.status] || 'wait'}">${esc(c.status)}</span> <b>${esc(c.chain)}</b>${c.note ? '：' + esc(plain(c.note)) : ''}</li>`).join('');
    parts.push(`<div class="rs-sec"><div class="fc-risk-k">原物料連動核對</div>
        ${hist ? `<p class="rs-sub">歷史上確實會一起動的組合：</p><ul class="rs-plain">${hist}</ul>` : ''}
        ${now ? `<p class="rs-sub">這個月的狀況：</p><ul class="rs-plain">${now}</ul>` : ''}</div>`);
  }
  if ((r.conflicts || []).length) {
    parts.push(`<div class="rs-sec"><div class="fc-risk-k">各家報導說法不一的地方</div><ul class="rs-plain">${r.conflicts.map(c =>
      `<li><b>${esc(plain(c.topic))}</b>：${esc(plain(c.versions))}<br><span class="rs-judge">採用：${esc(plain(c.judgment))}</span></li>`).join('')}</ul></div>`);
  }
  if ((r.gaps || []).length) {
    parts.push(`<div class="rs-sec"><div class="fc-risk-k">查不到、尚未確認的</div><ul class="rs-plain">${r.gaps.map(g => `<li>${esc(plain(g))}</li>`).join('')}</ul></div>`);
  }
  return `<details class="fc-why"><summary>研究底稿：查了哪些消息、怎麼判斷</summary>${parts.join('')}</details>`;
}

function populateAccuracy(acc) {
  const el = document.getElementById('fc-accuracy');
  if (!el || !acc) return;
  const o = acc.overall || {};
  const pct = o.total ? Math.round(o.hits / o.total * 100) : null;
  const items = Object.values(acc.per_item || {}).filter(v => v.total)
    .map(v => `<span class="fc-acc-item">${esc(v.name)} ${v.hits}/${v.total}</span>`).join('');
  el.innerHTML = `<div class="fc-acc-main">
      <span class="fc-acc-label">月均價方向命中率</span>
      <span class="fc-acc-value">${pct === null ? '累積中' : pct + '%'}</span>
      <span class="fc-acc-detail">${o.total ? `${o.hits}/${o.total} 次預測已驗證` : `${acc.pending || 0} 筆預測等待官方月均價公布`}</span>
    </div>
    ${items ? `<div class="fc-acc-items">${items}</div>` : ''}
    <div class="fc-acc-method">${esc(acc.method || '')}</div>`;
}

// ── Construction materials ────────────────────────────────

const matState = { q: '', group: 'all', freq: 'all', data: null, expanded: new Set() };
const MAT_PREVIEW = 6;
const MAT_QUIET_REGIONS = new Set(['全國', '國際', '臺灣']);

function fmtValue(v) {
  if (typeof v !== 'number') return '-';
  const abs = Math.abs(v);
  const d = abs >= 1000 ? 0 : abs >= 100 ? 1 : 2;
  return v.toLocaleString('zh-TW', { minimumFractionDigits: 0, maximumFractionDigits: d });
}

function sparkline(history) {
  const vals = (history || []).map(h => h[1]).filter(v => typeof v === 'number').slice(-24);
  if (vals.length < 2) return '';
  const w = 84, h = 24, min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * w).toFixed(1)},${(h - 2 - (v - min) / span * (h - 4)).toFixed(1)}`).join(' ');
  const cls = vals[vals.length - 1] > vals[0] ? 'up' : vals[vals.length - 1] < vals[0] ? 'down' : 'stable';
  return `<svg class="spark ${cls}" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><polyline points="${pts}"/></svg>`;
}

function matMatches(it, tokens) {
  if (matState.group !== 'all' && it.group !== matState.group) return false;
  if (matState.freq !== 'all' && it.freq !== matState.freq) return false;
  if (!tokens.length) return true;
  const hay = [it.name, it.region, it.source, it.unit, it.note].join(' ').toLowerCase();
  return tokens.every(t => hay.includes(t));
}

function renderMaterials() {
  const m = matState.data;
  const list = document.getElementById('mat-list');
  if (!m || !list) return;
  const groupsById = Object.fromEntries((m.groups || []).map(g => [g.id, g]));
  const tokens = matState.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const items = (m.items || []).filter(it => matMatches(it, tokens));

  const count = document.getElementById('mat-count');
  if (count) count.textContent = `顯示 ${items.length} / ${(m.items || []).length} 項`;

  if (!items.length) {
    list.innerHTML = '<p class="mat-empty">找不到符合的品項，試試其他關鍵字。</p>';
    return;
  }
  const browsing = !tokens.length && matState.group === 'all';
  const perGroup = {};
  items.forEach(it => { perGroup[it.group] = (perGroup[it.group] || 0) + 1; });
  const shown = {};
  let lastGroup = null;
  const rows = [];
  items.forEach(it => {
    const n = (shown[it.group] = (shown[it.group] || 0) + 1);
    const collapsed = browsing && !matState.expanded.has(it.group);
    if (collapsed && n > MAT_PREVIEW) {
      if (n === MAT_PREVIEW + 1) {
        rows.push(`<button type="button" class="mat-more" data-g="${esc(it.group)}">展開全部 ${perGroup[it.group]} 項 ↓</button>`);
      }
      return;
    }
    rows.push(matRow(it, groupsById, it.group !== lastGroup));
    lastGroup = it.group;
  });
  list.innerHTML = rows.join('');
  list.onclick = e => {
    const b = e.target.closest('.mat-more');
    if (!b) return;
    matState.expanded.add(b.dataset.g);
    renderMaterials();
  };
}

function matRow(it, groupsById, withHeader) {
  {
    const header = withHeader
      ? `<div class="mat-group-head"><span>${esc(groupsById[it.group]?.name || it.group)}</span><span class="mat-group-desc">${esc(groupsById[it.group]?.desc || '')}</span></div>`
      : '';
    const pct = typeof it.change_pct === 'number' ? it.change_pct : null;
    const cls = pct === null ? 'stable' : pct > 0 ? 'up' : pct < 0 ? 'down' : 'stable';
    const arrow = pct === null ? '' : pct > 0 ? '▲' : pct < 0 ? '▼' : '—';
    const chg = pct === null ? '-' : `${arrow} ${Math.abs(pct).toFixed(2)}%`;
    const region = it.region && !MAT_QUIET_REGIONS.has(it.region) && !it.name.includes(it.region) ? `<span class="mat-tag">${esc(it.region)}</span>` : '';
    const stale = it.stale ? '<span class="mat-tag mat-stale">過期</span>' : '';
    return `${header}<div class="mat-row">
        <div class="mat-name">${esc(it.name)}${region}${stale}</div>
        <div class="mat-spark">${sparkline(it.history)}</div>
        <div class="mat-value">${fmtValue(it.value)}<span class="mat-unit">${esc(it.unit)}</span></div>
        <div class="mat-chg price-change ${cls}">${chg}</div>
        <div class="mat-meta"><span class="mat-freq">${esc(it.freq)}</span>${esc(it.period)}
          <a href="${safeUrl(it.source_url)}" target="_blank" rel="noopener">${esc(it.source)}</a></div>
      </div>`;
  }
}

function chipRow(el, options, key) {
  if (!el) return;
  el.innerHTML = options.map(o =>
    `<button type="button" class="mat-chip${matState[key] === o.id ? ' active' : ''}" data-v="${esc(o.id)}">${esc(o.name)}</button>`).join('');
  el.onclick = e => {
    const b = e.target.closest('.mat-chip');
    if (!b) return;
    matState[key] = b.dataset.v;
    el.querySelectorAll('.mat-chip').forEach(c => c.classList.toggle('active', c === b));
    renderMaterials();
  };
}

function populateMaterials(m) {
  if (!m || !Array.isArray(m.items)) {
    const upd = document.getElementById('mat-updated');
    if (upd) upd.textContent = '行情資料將於下次排程更新後產生';
    return;
  }
  matState.data = m;
  const present = new Set(m.items.map(it => it.group));
  chipRow(document.getElementById('mat-groups'),
    [{ id: 'all', name: '全部' }, ...(m.groups || []).filter(g => present.has(g.id))], 'group');
  const freqs = ['日', '週', '月'].filter(f => m.items.some(it => it.freq === f));
  chipRow(document.getElementById('mat-freq'),
    [{ id: 'all', name: '全部頻率' }, ...freqs.map(f => ({ id: f, name: `每${f}更新` }))], 'freq');

  const search = document.getElementById('mat-search');
  if (search) search.oninput = () => { matState.q = search.value; renderMaterials(); };

  const upd = document.getElementById('mat-updated');
  if (upd) {
    const failed = (m.sources_status || []).filter(s => !s.ok).map(s => s.source);
    let when = '';
    try { when = new Date(m.updated_at).toLocaleString('zh-TW', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }); } catch (_) {}
    upd.textContent = `更新於 ${when} · ${m.items.length} 項` + (failed.length ? ` · 暫時無法連線：${failed.join('、')}` : '');
  }
  renderMaterials();
}

async function fetchJson(path) {
  try {
    const r = await fetch(`${path}?t=${Date.now()}`);
    return r.ok ? await r.json() : null;
  } catch (_) { return null; }
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
    populateHeadline(data);
    populatePrices(data);
    populateFeatured(data);
    populateTicker(data);
    populateExchange(data);
    populateAnalysis(data);
    populateForecast(data);
    populateNews(data);
    populateTopStories(data);
    const [materials, accuracy] = await Promise.all([fetchJson('data/materials.json'), fetchJson('data/accuracy.json')]);
    populateMaterials(materials);
    populateAccuracy(accuracy);
    maybeOpenBriefingFromPush(data);
    try { await buildChart(data); } catch (e) { console.error('Chart failed:', e); }
  } catch (err) {
    console.error('Failed to load data:', err);
    const area = document.getElementById('content-area');
    if (area) area.innerHTML = `<div class="error-state"><h3>資料載入失敗</h3><p>請確認 GitHub Actions 已成功執行每日分析，或稍後再試。</p><p style="font-size:12px;margin-top:10px;color:var(--sand);">${esc(err.message)}</p></div>`;
  } finally {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.classList.add('hidden');
    forceScrollTop();
    requestAnimationFrame(forceScrollTop);
  }
}

// ── Section navigation: smooth in-page jumps and the current-section highlight ──

const NAV_SECTIONS = ['prices', 'materials', 'chart', 'forecast', 'analysis', 'news', 'subscribe'];

function setActiveSection(id) {
  document.querySelectorAll('.tab[data-sec], .nav-link[data-sec]').forEach(a => {
    const on = a.dataset.sec === id;
    a.classList.toggle('active', on);
    if (on) a.setAttribute('aria-current', 'location');
    else a.removeAttribute('aria-current');
  });
}

// The current section is the last one whose top has passed a line 35% down the
// screen; at the very bottom of the page the last section wins.
function currentSection() {
  const line = window.innerHeight * 0.35;
  let current = null;
  for (const id of NAV_SECTIONS) {
    const el = document.getElementById(id);
    if (el && el.getBoundingClientRect().top <= line) current = id;
  }
  const atBottom = window.innerHeight + window.pageYOffset >= document.documentElement.scrollHeight - 4;
  return atBottom ? NAV_SECTIONS[NAV_SECTIONS.length - 1] : current;
}

function initNav() {
  document.addEventListener('click', e => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target.closest('a[href^="#"]');
    if (!a) return;
    const id = decodeURIComponent(a.getAttribute('href').slice(1));
    const target = id && document.getElementById(id);
    if (!target) return;
    e.preventDefault();
    _userInteracted = true;
    const section = target.closest('.section');
    if (section) section.classList.add('in');
    target.classList.add('in');
    // Section links just move; links to a single card also flash it so the eye finds it.
    const isSection = NAV_SECTIONS.includes(id);
    scrollToEl(target, !isSection);
    if (isSection) setActiveSection(id);
  });

  let ticking = false;
  const update = () => { ticking = false; setActiveSection(currentSection()); };
  window.addEventListener('scroll', () => {
    if (!ticking) { ticking = true; requestAnimationFrame(update); }
  }, { passive: true });
  window.addEventListener('resize', update, { passive: true });
  update();

  // The on-screen keyboard pushes a fixed bottom bar up over the field being typed in.
  document.addEventListener('focusin', e => {
    if (e.target.matches('input, textarea, select')) document.body.classList.add('typing');
  });
  document.addEventListener('focusout', () => document.body.classList.remove('typing'));
}

document.addEventListener('DOMContentLoaded', () => {
  forceScrollTop();
  requestAnimationFrame(forceScrollTop);
  setTimeout(forceScrollTop, 100);
  setTimeout(forceScrollTop, 300);
  initTheme();
  initNav();
  importPatFromHash();
  loadData();
  initSubscriptions();
  initAnimations();
});

window.addEventListener('load', () => {
  forceScrollTop();
  requestAnimationFrame(forceScrollTop);
  setTimeout(forceScrollTop, 100);
});

// ── Theme: light, dark, or follow the device ─────────────

const THEME_KEY = 'steel_theme';
const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');

function themeChoice() {
  try {
    const t = localStorage.getItem(THEME_KEY);
    return t === 'light' || t === 'dark' ? t : 'system';
  } catch (_) { return 'system'; }
}

function applyTheme(choice) {
  const root = document.documentElement;
  if (choice === 'light' || choice === 'dark') root.setAttribute('data-theme', choice);
  else root.removeAttribute('data-theme');
  document.querySelectorAll('.theme-btn').forEach(b =>
    b.setAttribute('aria-checked', String(b.dataset.themeChoice === choice)));
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', cssVar('--cream') || '#e3e3e8');
  drawChart();
}

function initTheme() {
  applyTheme(themeChoice());
  document.querySelectorAll('.theme-btn').forEach(b => b.addEventListener('click', () => {
    const choice = b.dataset.themeChoice;
    try {
      if (choice === 'system') localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, choice);
    } catch (_) {}
    applyTheme(choice);
  }));
  // While following the device, repaint when the device switches between light and dark.
  darkQuery.addEventListener('change', () => { if (themeChoice() === 'system') applyTheme('system'); });
}

// ── Subscriptions: e-mail (Buttondown) and web push (OneSignal) ──

const ONESIGNAL_SDK = 'https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js';

function setSubStatus(id, text, kind) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className = `sub-status${kind ? ' ' + kind : ''}`;
}

function isIOS() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

function isStandalone() {
  return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
}

function initEmailSubscribe(cfg) {
  const form = document.getElementById('sub-email-form');
  const input = document.getElementById('sub-email');
  const btn = document.getElementById('sub-email-btn');
  if (!form) return;
  if (!cfg.buttondown_username) {
    input.disabled = btn.disabled = true;
    setSubStatus('sub-email-status', 'Email 訂閱即將開放。');
    return;
  }
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const email = input.value.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setSubStatus('sub-email-status', '請輸入正確的 Email 地址。', 'error');
      return;
    }
    btn.disabled = true;
    setSubStatus('sub-email-status', '送出中…');
    try {
      const body = new FormData();
      body.append('email', email);
      body.append('embed', '1');
      await fetch(`https://buttondown.com/api/emails/embed-subscribe/${encodeURIComponent(cfg.buttondown_username)}`,
        { method: 'POST', body, mode: 'no-cors' });
      setSubStatus('sub-email-status', `已送出！請到 ${email} 收信並點擊確認連結，完成後每天早上就會收到快報（沒看到請檢查垃圾郵件）。`, 'ok');
      input.value = '';
    } catch (err) {
      setSubStatus('sub-email-status', `送出失敗：${err.message}，請稍後再試。`, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

function initPushSubscribe(cfg) {
  const btn = document.getElementById('sub-push-btn');
  if (!btn) return;
  const status = (t, k) => setSubStatus('sub-push-status', t, k);
  if (!cfg.onesignal_app_id) { status('通知功能即將開放。'); return; }
  if (isIOS() && !isStandalone()) {
    status('iPhone／iPad：請先點 Safari 下方的「分享」→「加入主畫面」，再從主畫面的「鋼市快報」圖示開啟網站，回到這裡按「開啟每日通知」（需 iOS 16.4 以上）。');
    return;
  }
  if (!('Notification' in window) || !('serviceWorker' in navigator)) {
    status('這個瀏覽器不支援通知（LINE、Facebook 等 App 內建瀏覽器常見）。請改用 Chrome、Safari 或 Edge 開啟本網站。', 'error');
    return;
  }

  const base = location.pathname.replace(/[^/]*$/, '');
  window.OneSignalDeferred = window.OneSignalDeferred || [];
  const script = document.createElement('script');
  script.src = ONESIGNAL_SDK;
  script.defer = true;
  script.onerror = () => status('通知服務載入失敗，請稍後重新整理。', 'error');
  document.head.appendChild(script);

  window.OneSignalDeferred.push(async OneSignal => {
    await OneSignal.init({
      appId: cfg.onesignal_app_id,
      serviceWorkerPath: `${base}push/onesignal/OneSignalSDKWorker.js`,
      serviceWorkerParam: { scope: `${base}push/onesignal/` },
      notifyButton: { enable: false },
      autoResubscribe: true,
    });
    const sub = OneSignal.User.PushSubscription;
    const refresh = () => {
      const denied = Notification.permission === 'denied';
      btn.disabled = denied;
      if (denied) {
        btn.textContent = '開啟每日通知';
        status('瀏覽器已封鎖本網站的通知。請到瀏覽器的網站設定，把「通知」改成允許後重新整理。', 'error');
      } else if (sub.optedIn) {
        btn.textContent = '關閉每日通知';
        status(`已開啟，每天 ${cfg.delivery_time || '08:00'} 左右會收到當日頭條通知。`, 'ok');
      } else {
        btn.textContent = '開啟每日通知';
        status('');
      }
    };
    sub.addEventListener('change', refresh);
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        if (sub.optedIn) {
          await sub.optOut();
        } else if (Notification.permission !== 'granted') {
          await OneSignal.Notifications.requestPermission();
          if (Notification.permission === 'granted' && !sub.optedIn) await sub.optIn();
        } else {
          await sub.optIn();
        }
      } catch (err) {
        status(`設定失敗：${err.message}`, 'error');
      } finally {
        refresh();
      }
    };
    refresh();
  });
}

async function initSubscriptions() {
  const cfg = (await fetchJson('notify-config.json')) || {};
  const t = document.getElementById('sub-time');
  if (t) t.textContent = `每天 ${cfg.delivery_time || '08:00'}（台灣時間）送達`;
  initEmailSubscribe(cfg);
  initPushSubscribe(cfg);
}

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

document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeRunModal(); closeBriefing(); } });

// ── Expose all functions to window for inline onclick ─────

window.openRunModal    = openRunModal;
window.closeRunModal   = closeRunModal;
window.triggerWorkflow = triggerWorkflow;
window.runInBackground = runInBackground;
window.hideToast       = hideToast;
