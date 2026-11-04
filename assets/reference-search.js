// Search the separately maintained reference archive without treating its
// historical, extracted or OCR text as verified current legislation.
(function (global) {
  const INDEX = 'data/laws/reference-archive/search-index.json?v=20261104h';
  const MAX_DOCUMENT_BYTES = 3000000;
  let indexPromise;
  let snapshotsPromise;
  const ignored = new Set(['什麼','哪些','如何','可以','請問','規定','相關','資料','查詢','建築','營建','文件','法規','台灣','臺灣','規範','設計','標準']);

  function grams(value) {
    const t = String(value || '').toLowerCase();
    const out = new Set();
    for (const run of t.match(/[\u3400-\u9fff]+/g) || []) {
      for (let i = 0; i + 1 < run.length; i++) {
        const g = run.slice(i, i + 2);
        if (!ignored.has(g)) out.add(g);
      }
    }
    for (const token of t.match(/[a-z0-9]{2,}/g) || []) out.add(token);
    return [...out].slice(0, 100);
  }

  async function loadIndex() {
    if (!indexPromise) indexPromise = fetch(INDEX).then(r => {
      if (!r.ok) throw new Error('參考資料索引無法載入');
      return r.json();
    }).catch(e => { indexPromise = null; throw e; });
    return indexPromise;
  }

  function rank(index, question, terms, group = 'all') {
    const tokens = [...new Set([...grams((terms || []).join(' ')), ...grams(question)])];
    const hits = new Map();
    const useful = tokens.filter(t => index.terms[t] && index.terms[t].length < index.docs.length * 0.8);
    for (const token of useful) {
      const ids = index.terms[token];
      const weight = Math.log(1 + index.docs.length / ids.length);
      for (const id of ids) {
        const doc = index.docs[id];
        if (!doc || doc.name === 'README' || (group === 'knowledge' && !doc.knowledge) || (group === 'archive' && doc.knowledge)) continue;
        const item = hits.get(id) || { id, score: 0, matches: 0 };
        item.matches++;
        item.score += weight * (doc.name.toLowerCase().includes(token) ? 2.5 : 1);
        hits.set(id, item);
      }
    }
    const min = useful.length > 1 ? 2 : 1;
    return [...hits.values()].filter(x => x.matches >= min)
      .sort((a, b) => b.score - a.score ||
        (index.docs[b.id].name.match(/20\d{2}[-_]\d{2}/)?.[0] || '').localeCompare(index.docs[a.id].name.match(/20\d{2}[-_]\d{2}/)?.[0] || '') || a.id - b.id).slice(0, 4)
      .map(x => ({ ...index.docs[x.id], tokens: useful }));
  }

  const safePath = path => String(path).split('/').map(encodeURIComponent).join('/');
  function snippet(text, terms, question) {
    const lines = String(text).split(/\n+/).map(s => s.trim()).filter(Boolean);
    const needles = [...(terms || []), ...grams(question)].map(s => String(s).toLowerCase()).filter(s => s.length >= 2);
    const scored = lines.map((line, order) => {
      const l = line.toLowerCase();
      return { line, order, score: needles.reduce((n, x) => n + (l.includes(x) ? x.length : 0), 0) };
    }).filter(x => x.score >= 4).sort((a, b) => b.score - a.score || a.order - b.order).slice(0, 3);
    return scored.map(x => x.line.slice(0, 500)).join('\n').slice(0, 1400);
  }

  // Read only indexed, verified government CSV sources. If unavailable or not
  // a simple rectangular table, keep the source-page link instead.
  function parseCsv(text) {
    if (text.length > 250000 || /[\u0000-\u0008]/.test(text)) return null;
    const rows = []; let row = [], cell = '', quoted = false;
    text = text.replace(/^\ufeff/, '');
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (quoted && c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') quoted = !quoted;
      else if (!quoted && (c === ',' || c === '\n')) {
        row.push(cell.replace(/\r$/, '').trim()); cell = '';
        if (c === '\n') { if (row.some(Boolean)) rows.push(row); row = []; }
      } else cell += c;
    }
    if (quoted) return null;
    if (cell || row.length) { row.push(cell.replace(/\r$/, '').trim()); rows.push(row); }
    if (rows.length < 2 || rows[0].length < 2 || rows[0].length > 80 ||
        rows[0].some(x => !x || x.length > 80) || rows.some(r => r.length !== rows[0].length || r.some(x => x.length > 200))) return null;
    const columns = rows[0].map((name, i) => /代碼|郵遞區號|電子郵件|電話|市話|經度|緯度|坐標/.test(name) ? -1 : i).filter(i => i >= 0);
    if (columns.length < 2) return null;
    return rows.map(r => columns.map(i => r[i]));
  }

  function parseTable(text) {
    if (text.length > 250000) return null;
    if (!/^\s*\[/.test(text)) return parseCsv(text);
    try {
      const data = JSON.parse(text);
      if (!Array.isArray(data) || !data.length || data.length > 5000 ||
          data.some(x => !x || Array.isArray(x) || typeof x !== 'object')) return null;
      const headers = Object.keys(data[0]).filter(k => !/代碼|郵遞區號|電子郵件|電話|市話|序號|經度|緯度|坐標|坐標系/.test(k));
      if (headers.length < 2 || headers.length > 80 || headers.some(h => h.length > 80)) return null;
      const rows = data.map(item => headers.map(k => {
        const value = item[k];
        if (value === undefined || value === null) return '';
        if (typeof value !== 'string' && typeof value !== 'number') throw new Error('nested');
        const s = String(value);
        if (s.length > 200) throw new Error('long');
        return s;
      }));
      return [headers, ...rows];
    } catch (_) { return null; }
  }

  async function liveTable(doc, question) {
    if (!doc.tableSource && !doc.hasSnapshot) return null;
    try {
      let text = '', source = '', retrieved = '';
      if (doc.tableSource) {
        try {
          const u = new URL(doc.tableSource);
          if (u.protocol !== 'https:' || u.hostname !== 'newdatacenter.taichung.gov.tw' || u.pathname !== '/api/v1/no-auth/resource.download') return null;
          const res = await fetch(u.href, { signal: AbortSignal.timeout(4000), credentials: 'omit' });
          if (res.ok && Number(res.headers.get('content-length') || 0) <= 250000) { text = await res.text(); source = u.href; }
        } catch (_) { /* Try a stored snapshot when the live source is unavailable. */ }
      }
      if (!text && doc.hasSnapshot) {
        if (!snapshotsPromise) snapshotsPromise = fetch('data/laws/reference-archive/source-snapshots.json?v=20261104g').then(r => {
          if (!r.ok) throw new Error('Snapshots unavailable');
          return r.json();
        }).catch(e => { snapshotsPromise = null; throw e; });
        const snapshots = await snapshotsPromise;
        const item = snapshots[doc.path.replace(/^data\/laws\/reference-archive\//, '')];
        if (item) { text = item.text; source = item.source; retrieved = item.retrieved; }
      }
      const rows = parseTable(text);
      if (!rows) return null;
      const year = question.match(/(?:民國)?(\d{3,4})年/);
      let body = rows.slice(1);
      if (year && !doc.name.includes(year[1]) && !doc.path.includes(year[1])) {
        const y = Number(year[1]);
        const years = [String(y), String(y < 1911 ? y + 1911 : y - 1911)];
        body = body.filter(row => row.some(cell => years.some(value => cell.includes(value))));
        if (!body.length) return null;
      }
      const region = question.match(/(?:臺|台|新北|桃園|新竹|苗栗|彰化|南投|雲林|嘉義|屏東|宜蘭|花蓮|臺東|台東|澎湖|金門|連江)[\u3400-\u9fff]{0,2}[市縣區]/);
      if (region) {
        const needle = region[0].replace('台', '臺');
        const matched = body.filter(row => row.some(cell => cell.replace('台', '臺').includes(needle)));
        if (matched.length) body = matched;
        else if (!doc.name.replace('台', '臺').includes(needle) && !doc.path.replace('台', '臺').includes(needle)) return null;
      }
      // If a question names an exact table value, show those rows first.
      const matches = [...new Set(body.flat().filter(cell => cell.length >= 3 && cell.length <= 30 &&
        /[\u3400-\u9fff]/.test(cell) && question.includes(cell)))].sort((a, b) => b.length - a.length);
      if (matches.length) body = body.filter(row => row.includes(matches[0]));
      return { headers: rows[0], rows: body.slice(0, 10), total: body.length, source, retrieved };
    } catch (_) { return null; }
  }

  async function search(question, terms = []) {
    try {
      const index = await loadIndex();
      const candidates = [...rank(index, question, terms, 'archive'), ...rank(index, question, terms, 'knowledge').slice(0, 2)];
      const results = await Promise.all(candidates.map(async doc => {
        if (doc.knowledge) {
          const k = doc.knowledge;
          try {
            const u = new URL(k.url);
            if (u.protocol !== 'https:') return null;
            return { ...doc, href: u.href, excerpt: [k.summary, '實務查核方向：' + (k.checkpoints || []).join('；'), ...(k.related || []).slice(0, 2)].join('\n'),
              note: `專業知識來源：${k.organization}（${k.kind}），整理日期 ${k.reviewed}；摘要為查詢線索，請查核原文與適用版本。` };
          } catch (_) { return null; }
        }
        const href = safePath(doc.path);
        if (doc.bytes > MAX_DOCUMENT_BYTES) return { ...doc, href, excerpt: '', note: '檔案較大，請開啟來源檔查閱。' };
        try {
          const response = await fetch(`${href}?v=20261104h`);
          if (!response.ok) throw new Error('not available');
          const text = await response.text();
          // Link-only records are deliberately distinguished from source text:
          // the search result points to the official site, and its title alone
          // must not be used as evidence for an answer.
          const match = text.match(/【檢視原始資料】\s*(https?:\/\/[^\s]+)/);
          if (match) {
            const source = new URL(match[1]);
            if (source.protocol === 'https:' || source.protocol === 'http:') {
              const title = text.match(/【顯示名稱】\s*([^\n]+)/);
              const how = text.match(/【查詢方式】\s*([^\n]+)/);
              const table = await liveTable(doc, question);
              return { ...doc, name: title ? title[1].trim() : doc.name, href: source.href, table,
                excerpt: table ? [table.headers, ...table.rows].map(row => row.join(' | ')).join('\n') : '',
                note: table ? `以下是${table.retrieved ? `擷取於 ${table.retrieved} 的來源資料副本` : '即時讀取的來源資料'}，符合篩選共 ${table.total} 筆，顯示前 ${table.rows.length} 筆；注意表內年度及單位。` : `此項只有來源連結，未提供正文；${how ? how[1].trim() : '請前往來源查閱。'}` };
            }
          }
          return { ...doc, href, excerpt: snippet(text, terms, question), note: '文字可能為歷史版本或 OCR 擷取，請核對原始來源。' };
        } catch (_) { return { ...doc, href, excerpt: '', note: '無法載入內容，請開啟來源檔查閱。' }; }
      }));
      // Several entries may describe the same official map. Show it only once.
      const seen = new Set();
      return results.filter(r => { if (!r || seen.has(r.href)) return false; seen.add(r.href); return true; });
    } catch (_) { return []; }
  }
  global.SteelReferenceSearch = { search, rank, grams, snippet, parseCsv, parseTable, liveTable };
})(typeof window === 'undefined' ? globalThis : window);
