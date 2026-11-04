// Search the separately maintained reference archive without treating its
// historical, extracted or OCR text as verified current legislation.
(function (global) {
  const INDEX = 'data/laws/reference-archive/search-index.json?v=20261104c';
  const MAX_DOCUMENT_BYTES = 3000000;
  let indexPromise;
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

  function rank(index, question, terms) {
    const tokens = [...new Set([...grams((terms || []).join(' ')), ...grams(question)])];
    const hits = new Map();
    const useful = tokens.filter(t => index.terms[t] && index.terms[t].length < index.docs.length * 0.8);
    for (const token of useful) {
      const ids = index.terms[token];
      const weight = Math.log(1 + index.docs.length / ids.length);
      for (const id of ids) {
        const doc = index.docs[id];
        if (!doc || doc.name === 'README') continue;
        const item = hits.get(id) || { id, score: 0, matches: 0 };
        item.matches++;
        item.score += weight * (doc.name.toLowerCase().includes(token) ? 2.5 : 1);
        hits.set(id, item);
      }
    }
    const min = useful.length > 1 ? 2 : 1;
    return [...hits.values()].filter(x => x.matches >= min)
      .sort((a, b) => b.score - a.score || a.id - b.id).slice(0, 4)
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

  async function search(question, terms = []) {
    try {
      const index = await loadIndex();
      return await Promise.all(rank(index, question, terms).map(async doc => {
        const href = safePath(doc.path);
        if (doc.bytes > MAX_DOCUMENT_BYTES) return { ...doc, href, excerpt: '', note: '檔案較大，請開啟來源檔查閱。' };
        try {
          const response = await fetch(`${href}?v=20261104c`);
          if (!response.ok) throw new Error('not available');
          const text = await response.text();
          // Link-only records are deliberately distinguished from source text:
          // the search result points to the official site, and its title alone
          // must not be used as evidence for an answer.
          const match = text.match(/【檢視原始資料】\s*(https?:\/\/[^\s]+)/);
          if (match) {
            const source = new URL(match[1]);
            if (source.protocol === 'https:' || source.protocol === 'http:') {
              return { ...doc, href: source.href, excerpt: '', note: '此項只有來源連結，未提供正文；請前往來源查閱。' };
            }
          }
          return { ...doc, href, excerpt: snippet(text, terms, question), note: '文字可能為歷史版本或 OCR 擷取，請核對原始來源。' };
        } catch (_) { return { ...doc, href, excerpt: '', note: '無法載入內容，請開啟來源檔查閱。' }; }
      }));
    } catch (_) { return []; }
  }
  global.SteelReferenceSearch = { search, rank, grams, snippet };
})(typeof window === 'undefined' ? globalThis : window);
