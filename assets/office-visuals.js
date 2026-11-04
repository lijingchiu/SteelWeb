// Read bounded OOXML package parts locally. Files and extracted media stay in the
// browser until the user sends the question to the assistant.
(function (global) {
  const MAX_ENTRIES = 2500, MAX_PART = 50 * 1024 * 1024, MAX_TOTAL = 256 * 1024 * 1024;
  const MIME = {png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',webp:'image/webp',gif:'image/gif'};
  const local = n => n && n.localName;
  const children = (node, name) => Array.from(node?.children || []).filter(n => local(n) === name);
  const first = (node, name) => node?.getElementsByTagNameNS('*', name)[0] || null;
  const all = (node, name) => Array.from(node?.getElementsByTagNameNS('*', name) || []);
  const val = node => (node?.textContent || '').trim();
  const truncate = (s,n=500) => String(s || '').slice(0,n);
  function parse(xml) {
    if (/<!DOCTYPE|<!ENTITY/i.test(xml)) throw new Error('Office 文件包含不支援的 XML 宣告。');
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    if (doc.getElementsByTagName('parsererror').length) throw new Error('Office 文件內容損壞。');
    return doc;
  }
  function resolve(base, target) {
    const out = [];
    const joined = target.startsWith('/') ? target.slice(1) : base.split('/').slice(0,-1).join('/') + '/' + target;
    for (const p of joined.split('/')) {
      if (!p || p === '.') continue;
      if (p === '..') { if (!out.length) return ''; out.pop(); } else out.push(p);
    }
    return out.join('/');
  }
  function ownerPath(rels) {
    const m = rels.match(/^(.*\/)\_rels\/([^/]+)\.rels$/);
    return m ? m[1] + m[2] : '';
  }
  function bytesData(bytes, mime) {
    let s = '';
    for (let i=0; i<bytes.length; i+=16384) s += String.fromCharCode(...bytes.subarray(i, i+16384));
    return `data:${mime};base64,${btoa(s)}`;
  }
  async function readXml(zip, name) {
    const item = zip.file(name);
    return item ? parse(await item.async('string')) : null;
  }
  function guard(zip) {
    const files = Object.values(zip.files).filter(f => !f.dir);
    if (files.length > MAX_ENTRIES) throw new Error('Office 文件內部項目過多，無法安全擷取。');
    let total=0;
    for (const f of files) {
      const size=f._data?.uncompressedSize;
      if (!Number.isFinite(size) || size < 0 || size > MAX_PART) throw new Error('Office 文件包含過大的內部項目，無法安全擷取。');
      total += size;
      if (total > MAX_TOTAL) throw new Error('Office 文件解壓後過大，無法安全擷取。');
    }
  }
  async function relationships(zip) {
    const reverse = new Map(), byOwner = new Map();
    const paths = Object.keys(zip.files).filter(n => /\/_rels\/[^/]+\.rels$/i.test(n));
    for (const path of paths) {
      const owner=ownerPath(path); if (!owner) continue;
      const doc=await readXml(zip,path), list=[];
      for (const r of all(doc,'Relationship')) {
        if ((r.getAttribute('TargetMode') || '').toLowerCase() === 'external') continue;
        const target=resolve(owner,r.getAttribute('Target') || '');
        if (!target || !zip.file(target)) continue;
        const item={id:r.getAttribute('Id'),target,type:r.getAttribute('Type') || ''}; list.push(item);
        if (!reverse.has(target)) reverse.set(target,[]);
        reverse.get(target).push(owner);
      }
      byOwner.set(owner,list);
    }
    return {reverse,byOwner};
  }
  async function workbookInfo(zip, rels) {
    const doc=await readXml(zip,'xl/workbook.xml');
    if (!doc) return {sheets:new Map(),shared:[]};
    const byId=new Map((rels.byOwner.get('xl/workbook.xml') || []).map(x=>[x.id,x.target]));
    const sheets=new Map();
    for (const s of all(doc,'sheet')) {
      const id=s.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships','id') || s.getAttribute('r:id');
      if (byId.has(id)) sheets.set(s.getAttribute('name'),byId.get(id));
    }
    const sharedDoc=await readXml(zip,'xl/sharedStrings.xml');
    return {sheets, shared:sharedDoc ? all(sharedDoc,'si').map(s=>all(s,'t').map(val).join('')) : []};
  }
  function contexts(path, reverse, sheets) {
    const names = new Map([...sheets].map(([name,p])=>[p,name]));
    const seen=new Set([path]), queue=[path], found=new Set();
    while (queue.length && seen.size < 200) {
      const n=queue.shift();
      let m=n.match(/^ppt\/slides\/slide(\d+)\.xml$/);
      if (m) found.add(`第 ${m[1]} 張投影片`);
      if (names.has(n)) found.add(`工作表「${names.get(n)}」`);
      if (n === 'word/document.xml') found.add('Word 文件內文');
      if (/^word\/(header|footer)\d+\.xml$/.test(n)) found.add('Word 頁首或頁尾');
      for (const prev of reverse.get(n) || []) if (!seen.has(prev)) { seen.add(prev); queue.push(prev); }
    }
    return found.size ? [...found].join('、') : '無法確定在文件中的位置';
  }
  function points(node) {
    const out = new Map();
    for (const p of all(node,'pt')) {
      const idx=Number(p.getAttribute('idx'));
      const v=first(p,'v');
      if (Number.isInteger(idx) && v && val(v) !== '') out.set(idx,truncate(val(v),200));
    }
    return out;
  }
  function colNum(v) { return [...v].reduce((a,c)=>a*26+c.charCodeAt(0)-64,0); }
  async function refPoints(node, zip, book, sheetCache) {
    const cached=points(node); if (cached.size) return cached;
    const formula=val(first(node,'f'));
    const m=formula.match(/^(?:'((?:[^']|'')+)'|([^'!]+))!\$?([A-Za-z]+)\$?(\d+)(?::\$?([A-Za-z]+)\$?(\d+))?$/);
    if (!m) return cached;
    const name=(m[1] || m[2]).replace(/''/g,"'"), path=book.sheets.get(name);
    if (!path) return cached;
    if (!sheetCache.has(path)) {
      const doc=await readXml(zip,path), cells=new Map();
      for (const c of all(doc,'c')) {
        const addr=c.getAttribute('r'); if (!addr) continue;
        let value=val(first(c,'v'));
        if (c.getAttribute('t') === 's') value=book.shared[Number(value)] ?? '';
        else if (c.getAttribute('t') === 'inlineStr') value=all(c,'t').map(val).join('');
        if (value !== '') cells.set(addr.toUpperCase(),truncate(value,200));
      }
      sheetCache.set(path,cells);
    }
    const col1=colNum(m[3].toUpperCase()), row1=Number(m[4]), col2=colNum((m[5] || m[3]).toUpperCase()), row2=Number(m[6] || m[4]);
    if (row2 < row1 || col2 < col1 || (row1!==row2 && col1!==col2)) return cached;
    // Iterate stored cells, not the potentially million-row reference range.
    for (const [addr,value] of sheetCache.get(path)) {
      const cell=addr.match(/^([A-Z]+)([0-9]+)$/); if (!cell) continue;
      const col=colNum(cell[1]), row=Number(cell[2]);
      if (row>=row1 && row<=row2 && col>=col1 && col<=col2)
        cached.set(row1===row2 ? col-col1 : row-row1,value);
    }
    return new Map([...cached].sort((a,b)=>a[0]-b[0]));
  }
  async function chartData(doc, zip, book, sheetCache) {
    const title=truncate(all(first(doc,'title'),'t').map(val).filter(Boolean).join(' '),200);
    const out=[], series=all(doc,'ser'); let missing=false;
    for (const s of series) {
      const tx=children(s,'tx')[0];
      const titles=await refPoints(tx,zip,book,sheetCache);
      const name=truncate(val(first(tx,'v')) || [...titles.values()][0] || '未命名數列',150);
      const category=children(s,'cat')[0] || children(s,'xVal')[0];
      const values=children(s,'val')[0] || children(s,'yVal')[0];
      const labels=await refPoints(category,zip,book,sheetCache), vals=await refPoints(values,zip,book,sheetCache);
      if (!vals.size) {missing=true; continue;}
      const data=[...vals.entries()].map(([i,v])=>`${labels.get(i) || `資料點${i+1}`}：${v}`);
      out.push(`數列「${name}」：${data.join('；')}`);
    }
    if (!series.length) missing=true;
    return {title, lines:out, missing};
  }
  async function extract(file) {
    if (!/\.(docx|xlsx|pptx)$/i.test(file.name)) return {parts:[],warnings:[]};
    if (!global.JSZip) return {parts:[],warnings:['無法載入 Office 解析工具，內嵌圖片及圖表未擷取。']};
    const warnings=[], parts=[];
    try {
      const zip=await global.JSZip.loadAsync(await file.arrayBuffer()); guard(zip);
      const rels=await relationships(zip), book=await workbookInfo(zip,rels), sheetCache=new Map();
      const media=Object.keys(zip.files).filter(n=>/^(word|xl|ppt)\/media\/[^/]+$/i.test(n) && !zip.files[n].dir && rels.reverse.has(n)).sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
      let imageCount=0;
      for (const path of media) {
        const ext=(path.split('.').pop() || '').toLowerCase(), mime=MIME[ext];
        if (!mime) {warnings.push(`不支援的內嵌圖片格式：${truncate(path,120)}`); continue;}
        const bytes=await zip.file(path).async('uint8array');
        parts.push({type:'input_text',text:`附件「${file.name}」內嵌圖片 ${imageCount+1}（${contexts(path,rels.reverse,book.sheets)}；來源 ${path}）。`});
        parts.push({type:'input_image',image_url:bytesData(bytes,mime),detail:'high'});
        imageCount++;
      }
      const charts=Object.keys(zip.files).filter(n=>/^(word|xl|ppt)\/charts\/chart\d+\.xml$/i.test(n) && rels.reverse.has(n)).sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
      for (const path of charts) {
        const data=await chartData(await readXml(zip,path),zip,book,sheetCache);
        if (data.missing) warnings.push(`圖表 ${path} 的部分數列沒有可讀取的數值。`);
        if (data.lines.length) parts.push({type:'input_text',text:`附件「${file.name}」圖表（${contexts(path,rels.reverse,book.sheets)}；來源 ${path}）${data.title ? `，標題「${data.title}」` : ''}：\n${data.lines.join('\n')}\n圖表數值來自文件內快取或工作表，可能不是最新的外部連線資料。`});
      }
      if (!media.length && !charts.length) warnings.push('未找到受支援且有連結的內嵌圖片或圖表；圖案、外部連結或特殊物件不一定能擷取。');
    } catch (e) {
      warnings.push(`Office 內嵌內容擷取失敗：${truncate(e.message,180)}。原文件仍會送出供文字分析。`);
    }
    return {parts,warnings:[...new Set(warnings)]};
  }
  global.SteelOfficeVisuals={extract};
})(typeof window === 'undefined' ? globalThis : window);
