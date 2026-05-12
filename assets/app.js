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

function setTrend(badgeId, barId, trend) {
  const badge = document.getElementById(badgeId);
  const bar = document.getElementById(barId);
  if (!badge || !bar) return;
  badge.textContent = TREND_LABELS[trend] || trend;
  badge.className = `trend-badge ${trend}`;
  bar.className = `trend-bar-fill ${trend}`;
  bar.style.width = trend === 'up' ? '75%' : trend === 'down' ? '25%' : '50%';
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
    setTrend(`${prefix}-trend-badge`, `${prefix}-trend-bar`, p.trend || 'stable');
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
    } catch { updatedEl.textContent = data.date || '-'; }
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
  let dates = [], scrapVals = [], rebarVals = [], structVals = [];
  try {
    const chartRes = await fetch('data/chart-data.json?t=' + Date.now());
    if (chartRes.ok) {
      const cd = await chartRes.json();
      dates = cd.dates || []; scrapVals = cd.scrap_steel || [];
      rebarVals = cd.rebar || []; structVals = cd.structural_steel || [];
    }
  } catch (_) {}
  if (dates.length === 0 && latestData) {
    const p = latestData.prices || {};
    dates = [latestData.date || '今日'];
    scrapVals = [p.scrap_steel?.current_estimate ?? null];
    rebarVals = [p.rebar?.current_estimate ?? null];
    structVals = [p.structural_steel?.current_estimate ?? null];
  }
  if (priceChart) priceChart.destroy();
  Chart.defaults.color = '#8b949e';
  Chart.defaults.borderColor = '#30363d';
  priceChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: dates,
      datasets: [
        { label: '廢鋼', data: scrapVals, borderColor: '#f0a500', backgroundColor: 'rgba(240,165,0,0.08)', pointBackgroundColor: '#f0a500', pointRadius: 4, pointHoverRadius: 6, tension: 0.3, borderWidth: 2, fill: true },
        { label: '鋼筋', data: rebarVals, borderColor: '#388bfd', backgroundColor: 'rgba(56,139,253,0.08)', pointBackgroundColor: '#388bfd', pointRadius: 4, pointHoverRadius: 6, tension: 0.3, borderWidth: 2, fill: true },
        { label: '型鋼', data: structVals, borderColor: '#3fb950', backgroundColor: 'rgba(63,185,80,0.08)', pointBackgroundColor: '#3fb950', pointRadius: 4, pointHoverRadius: 6, tension: 0.3, borderWidth: 2, fill: true },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#21262d', borderColor: '#30363d', borderWidth: 1,
          titleColor: '#e6edf3', bodyColor: '#8b949e',
          callbacks: { label(c) { return ` ${c.dataset.label}：${c.parsed.y?.toLocaleString('zh-TW') ?? '-'} 元/噸`; } },
        },
      },
      scales: {
        x: { grid: { color: 'rgba(48,54,61,0.5)' }, ticks: { maxRotation: 45, font: { size: 11 } } },
        y: { grid: { color: 'rgba(48,54,61,0.5)' }, ticks: { font: { size: 11 }, callback: v => v.toLocaleString('zh-TW') } },
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
    if (main) main.innerHTML = `<div class="error-state"><h3>資料載入失敗</h3><p>請確認 GitHub Actions 已成功執行每日分析，或稍後再試。</p><p style="font-size:12px;margin-top:8px;color:#656d76;">${err.message}</p></div>`;
  } finally {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.classList.add('hidden');
  }
}

document.addEventListener('DOMContentLoaded', loadData);

// ── Run Modal ────────────────────────────────────────────

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
  el.className = `run-status run-status-${type}`;
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
    showRunStatus('error', '❌ Token 包含無效字元，請重新複製貼上 GitHub PAT（只能包含英數字及符號）');
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
    'Authorization': `Bearer ${pat}`,
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'Content-Type': 'application/json',
  };

  try {
    // Step 1: verify PAT, get default branch, and find numeric workflow ID
    showRunStatus('loading', '⏳ 驗證 Token 並查詢 workflow...');
    const [listRes, repoRes] = await Promise.all([
      fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/actions/workflows`, { headers: ghHeaders }),
      fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}`, { headers: ghHeaders }),
    ]);

    if (listRes.status === 401 || repoRes.status === 401) { showRunStatus('error', '❌ PAT 無效或已過期，請重新確認 Token'); btn.disabled = false; return; }
    if (listRes.status === 403 || repoRes.status === 403) { showRunStatus('error', '❌ 權限不足，請確認 PAT 已勾選 workflow 權限'); btn.disabled = false; return; }
    if (!listRes.ok) {
      const b = await listRes.json().catch(() => ({}));
      showRunStatus('error', `❌ API 錯誤 ${listRes.status}：${b.message || '無法取得 workflow 列表'}`);
      btn.disabled = false; return;
    }

    const [listData, repoData] = await Promise.all([listRes.json(), repoRes.json()]);
    const defaultBranch = repoData.default_branch || 'main';
    const wf = (listData.workflows || []).find(w => w.path && w.path.endsWith(WORKFLOW));
    const workflowId = wf ? wf.id : WORKFLOW;

    if (!wf) {
      showRunStatus('loading', `⏳ Workflow 未在列表中，嘗試直接觸發（分支：${defaultBranch}）...`);
    }

    // Step 2: dispatch to default branch (required by GitHub for workflow_dispatch)
    const dispatchRes = await fetch(
      `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/actions/workflows/${workflowId}/dispatches`,
      {
        method: 'POST',
        headers: ghHeaders,
        body: JSON.stringify({ ref: defaultBranch }),
      }
    );

    if (dispatchRes.status === 204) {
      showRunStatus('loading', '✅ 已成功觸發！分析執行中，約需 2-3 分鐘...');
      pollWorkflowStatus(pat);
    } else if (dispatchRes.status === 401) {
      showRunStatus('error', '❌ PAT 無效或已過期，請重新確認 Token');
      btn.disabled = false;
    } else if (dispatchRes.status === 403) {
      showRunStatus('error', '❌ 權限不足，請確認 PAT 已勾選 workflow 權限');
      btn.disabled = false;
    } else if (dispatchRes.status === 404) {
      showRunStatus('error', `❌ GitHub 找不到 workflow（分支：${defaultBranch}），請至 Actions 頁面手動執行一次以啟用`);
      btn.disabled = false;
    } else if (dispatchRes.status === 422) {
      const body = await dispatchRes.json().catch(() => ({}));
      showRunStatus('error', `❌ 請求被拒絕 (422)：${body.message || ''} （ref: ${defaultBranch}）`);
      btn.disabled = false;
    } else {
      const body = await dispatchRes.json().catch(() => ({}));
      showRunStatus('error', `❌ 錯誤 ${dispatchRes.status}：${body.message || '未知錯誤'}`);
      btn.disabled = false;
    }
  } catch (e) {
    showRunStatus('error', `❌ 網路錯誤：${e.message}`);
    btn.disabled = false;
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
              const statusEl = document.getElementById('run-status');
              statusEl.style.cursor = 'pointer';
              statusEl.onclick = () => location.reload();
            } else {
              showRunStatus('error', `❌ 執行失敗（${run.conclusion}），請至 GitHub Actions 查看詳情`);
            }
            document.getElementById('trigger-btn').disabled = false;
            return;
          }
          const elapsed = Math.round((Date.now() - triggeredAt) / 1000);
          const label = run.status === 'in_progress' ? '執行中' : '排隊中';
          showRunStatus('loading', `⏳ ${label}...（已等待 ${elapsed} 秒）`);
        }
      }
    } catch (_) {}
    if (attempts < maxAttempts) {
      setTimeout(poll, 10000);
    } else {
      showRunStatus('error', '⏱ 等待逾時，請至 GitHub Actions 頁面確認執行狀況');
      document.getElementById('trigger-btn').disabled = false;
    }
  };

  setTimeout(poll, 8000);
}
