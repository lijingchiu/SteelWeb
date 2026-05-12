'use strict';

const TREND_LABELS = { up: '上漲', down: '下跌', stable: '持平' };
const CONF_LABELS = { high: '信心度：高', medium: '信心度：中', low: '信心度：低' };

let priceChart = null;

function fmt(n) {
  if (typeof n !== 'number') return '-';
  return n.toLocaleString('zh-TW');
}

function fmtChange(n) {
  if (typeof n !== 'number') return '';
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toLocaleString('zh-TW')}`;
}

function setTrend(badgeId, barId, trend, changeAmt) {
  const badge = document.getElementById(badgeId);
  const bar = document.getElementById(barId);
  if (!badge || !bar) return;

  badge.textContent = TREND_LABELS[trend] || trend;
  badge.className = `trend-badge ${trend}`;
  bar.className = `trend-bar-fill ${trend}`;

  const pct = trend === 'up' ? 75 : trend === 'down' ? 25 : 50;
  bar.style.width = `${pct}%`;
}

function setChange(el, changeAmt) {
  if (!el) return;
  if (typeof changeAmt !== 'number') { el.textContent = '-'; return; }
  const cls = changeAmt > 0 ? 'up' : changeAmt < 0 ? 'down' : 'stable';
  el.textContent = fmtChange(changeAmt) + ' 元';
  el.className = `price-change ${cls}`;
}

function populatePrices(data) {
  const prices = data.prices || {};

  function fillCard(key, prefix) {
    const p = prices[key] || {};
    const cur = document.getElementById(`${prefix}-current`);
    const chg = document.getElementById(`${prefix}-change`);
    const pred = document.getElementById(`${prefix}-prediction`);
    const reason = document.getElementById(`${prefix}-reason`);

    if (cur) cur.textContent = fmt(p.current_estimate);
    setChange(chg, p.change_amount);
    if (pred) pred.textContent = fmt(p.prediction_next_week);
    if (reason) reason.textContent = p.reason || '-';
    setTrend(`${prefix}-trend-badge`, `${prefix}-trend-bar`, p.trend || 'stable', p.change_amount);
  }

  fillCard('scrap_steel', 'scrap');
  fillCard('rebar', 'rebar');
  fillCard('structural_steel', 'structural');
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
    'weekly-trend': data.weekly_trend,
    'international-outlook': data.international_outlook,
    'model-name': data.model_used,
  };
  for (const [id, text] of Object.entries(fields)) {
    const el = document.getElementById(id);
    if (el) el.textContent = text || '-';
  }

  const riskList = document.getElementById('risk-factors');
  if (riskList && Array.isArray(data.risk_factors)) {
    riskList.innerHTML = data.risk_factors
      .map(r => `<li>⚠ ${r}</li>`)
      .join('');
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
        <span>${n.title}</span>
      </a>`;
    })
    .join('');
}

function populateMeta(data) {
  const updatedEl = document.getElementById('last-updated-text');
  const confBadge = document.getElementById('confidence-badge');

  if (updatedEl && data.generated_at) {
    try {
      const d = new Date(data.generated_at);
      updatedEl.textContent = `更新於 ${d.toLocaleDateString('zh-TW')} ${d.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })}`;
    } catch {
      updatedEl.textContent = data.date || '-';
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

  let dates = [];
  let scrapVals = [];
  let rebarVals = [];
  let structVals = [];

  try {
    const chartRes = await fetch('data/chart-data.json?t=' + Date.now());
    if (chartRes.ok) {
      const cd = await chartRes.json();
      dates = cd.dates || [];
      scrapVals = cd.scrap_steel || [];
      rebarVals = cd.rebar || [];
      structVals = cd.structural_steel || [];
    }
  } catch (_) {}

  if (dates.length === 0 && latestData) {
    const p = latestData.prices || {};
    dates = [latestData.date || '今日'];
    scrapVals = [p.scrap_steel?.current_estimate ?? null];
    rebarVals = [p.rebar?.current_estimate ?? null];
    structVals = [p.structural_steel?.current_estimate ?? null];
  }

  const commonDatasetOpts = {
    pointRadius: 4,
    pointHoverRadius: 6,
    tension: 0.3,
    borderWidth: 2,
    fill: false,
  };

  if (priceChart) priceChart.destroy();

  Chart.defaults.color = '#8b949e';
  Chart.defaults.borderColor = '#30363d';

  priceChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: dates,
      datasets: [
        {
          label: '廢鋼',
          data: scrapVals,
          borderColor: '#f0a500',
          backgroundColor: 'rgba(240,165,0,0.08)',
          pointBackgroundColor: '#f0a500',
          ...commonDatasetOpts,
          fill: true,
        },
        {
          label: '鋼筋',
          data: rebarVals,
          borderColor: '#388bfd',
          backgroundColor: 'rgba(56,139,253,0.08)',
          pointBackgroundColor: '#388bfd',
          ...commonDatasetOpts,
          fill: true,
        },
        {
          label: '型鋼',
          data: structVals,
          borderColor: '#3fb950',
          backgroundColor: 'rgba(63,185,80,0.08)',
          pointBackgroundColor: '#3fb950',
          ...commonDatasetOpts,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#21262d',
          borderColor: '#30363d',
          borderWidth: 1,
          titleColor: '#e6edf3',
          bodyColor: '#8b949e',
          callbacks: {
            label(ctx) {
              return ` ${ctx.dataset.label}：${ctx.parsed.y?.toLocaleString('zh-TW') ?? '-'} 元/噸`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: { color: 'rgba(48,54,61,0.5)' },
          ticks: { maxRotation: 45, font: { size: 11 } },
        },
        y: {
          grid: { color: 'rgba(48,54,61,0.5)' },
          ticks: {
            font: { size: 11 },
            callback: v => v.toLocaleString('zh-TW'),
          },
        },
      },
    },
  });
}

async function loadData() {
  try {
    const res = await fetch('data/latest.json?t=' + Date.now());
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    populateMeta(data);
    populatePrices(data);
    populateExchange(data);
    populateAnalysis(data);
    populateNews(data);
    await buildChart(data);
  } catch (err) {
    console.error('Failed to load data:', err);
    const main = document.querySelector('main');
    if (main) {
      main.innerHTML = `<div class="error-state">
        <h3>資料載入失敗</h3>
        <p>請確認 GitHub Actions 已成功執行每日分析，或稍後再試。</p>
        <p style="font-size:12px;margin-top:8px;color:#656d76;">${err.message}</p>
      </div>`;
    }
  } finally {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.classList.add('hidden');
  }
}

document.addEventListener('DOMContentLoaded', loadData);
