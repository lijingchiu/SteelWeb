/* Transparent one-period history baseline; never an AI or researched forecast. */
(function (root) {
  'use strict';
  function baseline(item) {
    const points = (Array.isArray(item.history) ? item.history : [])
      .filter(p => Array.isArray(p) && typeof p[0] === 'string' && Number.isFinite(p[1]));
    if (item.stale) return { available: false, reason: '來源資料已過期，暫不推估。', points: points.length };
    if (points.length < 3 || !Number.isFinite(item.value)) return { available: false, reason: '歷史資料不足，暫不推估。', points: points.length };
    const last = points[points.length - 1];
    if (last[0] !== item.period || Math.abs(last[1] - item.value) > Math.max(0.000001, Math.abs(item.value) * 0.000001))
      return { available: false, reason: '最新行情與歷史資料不一致，暫不推估。', points: points.length };
    const recent = points.slice(-4);
    const changes = recent.slice(1).map((p, i) => p[1] - recent[i][1]).sort((a, b) => a - b);
    const mid = Math.floor(changes.length / 2);
    const delta = changes.length % 2 ? changes[mid] : (changes[mid - 1] + changes[mid]) / 2;
    const estimate = item.value + delta;
    const band = Math.abs(item.value) * 0.003;
    return { available: true, estimate, delta, direction: delta > band ? 'up' : delta < -band ? 'down' : 'stable', points: points.length, changes: changes.length, short: points.length < 6 };
  }
  root.SteelMaterialForecast = { baseline };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.SteelMaterialForecast;
})(typeof window !== 'undefined' ? window : globalThis);
