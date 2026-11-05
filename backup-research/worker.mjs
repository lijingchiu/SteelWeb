import { sendYahoo } from './smtp.mjs';
// Independent watchdog; research and subscriber delivery stay in the GitHub workflow.
const API = 'https://api.github.com/repos/lijingchiu/SteelWeb';
const WORKFLOW = 'daily-analysis.yml';

export function targetAt(date) {
  const local = new Date(date.getTime() + 8 * 3600_000);
  const hour = local.getUTCHours(), minute = local.getUTCMinutes();
  if (hour === 23 && minute >= 50) local.setUTCDate(local.getUTCDate() + 1);
  else if (hour >= 8 || hour === 23) return null;
  const day = local.getUTCDay();
  if (day === 0 || day === 6) return null;
  return { date: local.toISOString().slice(0, 10), hour, minute };
}

async function github(path, token, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'steel-research-watchdog', Authorization: `Bearer ${token}`, 'X-GitHub-Api-Version': '2022-11-28', ...options.headers },
  });
  if (!response.ok) throw new Error(`GitHub HTTP ${response.status}`);
  if (response.status === 204) return null;
  return response.json();
}

async function file(path, token) {
  const data = await github(`/contents/${path}?ref=main`, token);
  if (data.encoding !== 'base64' || typeof data.content !== 'string') throw new Error('Unexpected GitHub content');
  return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(data.content.replace(/\s/g, '')), c => c.charCodeAt(0))));
}

export function ready(date, latest, outlooks, materials, report, notifications) {
  const research = outlooks.research_date || String(outlooks.generated_at || '').slice(0, 10);
  return latest.date === date && research === date && outlooks.failed_batches === 0 && outlooks.total_items > 0 && outlooks.covered_items > 0 && outlooks.total_items === materials.items?.length && report.date === date && !!report.file && !!report.pdf_file && ['push', 'email'].every(k => notifications[k]?.date === date);
}

async function claim(db, key, now, ttl) {
  const result = await db.prepare('INSERT INTO watchdog_locks (key, expires) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET expires = excluded.expires WHERE watchdog_locks.expires < ?')
    .bind(key, now + ttl, now).run();
  return result.meta.changes === 1;
}

async function alertOnce(env, date, reason, now) {
  if (!await claim(env.DB, `alert:${date}`, now, 2 * 86400_000)) return;
  try {
    const { connect } = await import('cloudflare:sockets');
    await sendYahoo(connect, env.YAHOO_APP_PASSWORD, env.ALERT_TO, date, reason);
  } catch (error) {
    // Delivery outcome can be ambiguous. Keep the claim to avoid duplicate emails.
    console.error('Alert delivery failed or uncertain', String(error));
  }
}

export async function check(env, now = new Date()) {
  const target = targetAt(now);
  if (!target) return 'outside-window';
  const ts = now.getTime();
  if (!await claim(env.DB, 'check', ts, 2 * 60_000)) return 'locked';
  try {
    const [latest, outlooks, materials, report, notifications, runs] = await Promise.all([
      file('data/latest.json', env.GITHUB_TOKEN), file('data/material-outlooks.json', env.GITHUB_TOKEN),
      file('data/materials.json', env.GITHUB_TOKEN), file('data/report.json', env.GITHUB_TOKEN),
      file('data/notify-state.json', env.GITHUB_TOKEN), github(`/actions/workflows/${WORKFLOW}/runs?branch=main&per_page=20`, env.GITHUB_TOKEN),
    ]);
    if (ready(target.date, latest, outlooks, materials, report, notifications)) return 'complete';
    const active = runs.workflow_runs.some(r => ['queued', 'in_progress', 'pending', 'waiting', 'requested'].includes(r.status));
    const recent = runs.workflow_runs.some(r => ts - Date.parse(r.created_at) < 10 * 60_000 && ts >= Date.parse(r.created_at));
    if (target.hour >= 6 && target.hour < 8) await alertOnce(env, target.date, '研究、電子報或通知狀態尚未全部完成', ts);
    if (active || recent) return 'running-or-recent';
    if (!await claim(env.DB, `dispatch:${target.date}`, ts, 20 * 60_000)) return 'dispatch-cooldown';
    await github(`/actions/workflows/${WORKFLOW}/dispatches`, env.GITHUB_TOKEN, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ref: 'main', inputs: { backup: true, force_run: 'false' } }) });
    return 'dispatched';
  } catch (error) {
    if (target.hour >= 6 && target.hour < 8) await alertOnce(env, target.date, '無法確認 GitHub 研究狀態，請檢查 GitHub 或服務連線', ts);
    console.error('Watchdog check failed', String(error));
    return 'error';
  } finally {
    await env.DB.prepare('DELETE FROM watchdog_locks WHERE key = ? AND expires = ?').bind('check', ts + 2 * 60_000).run();
  }
}

export default { async scheduled(controller, env, ctx) { ctx.waitUntil(check(env, new Date(controller.scheduledTime))); } };
