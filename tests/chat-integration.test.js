const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
require('../assets/chat-web.js');
const url = 'https://news.example.tw/steel';
async function runScenario(readable, inScope, selections = []) {
  const sequence = [], messages = [], els = new Map(), handlers = {};
  function elem(id = '') {
    if (!els.has(id)) els.set(id, { id, value: '', hidden: false, children: [], scrollHeight: 20, scrollTop: 0, clientHeight: 20, style: {}, dataset: {}, innerHTML: '',
      classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } }, handlers: {},
      addEventListener(type, fn) { this.handlers[type] = fn; }, setAttribute() {}, focus() {},
      appendChild(child) { this.children.push(child); messages.push(child); },
      querySelector() { return null; }, querySelectorAll() { return []; },
    });
    return els.get(id);
  }
  const document = { readyState: 'complete', getElementById: elem, querySelector() { return null; }, addEventListener(type, fn) { handlers[type] = fn; }, dispatchEvent() {},
    body: { classList: { add() {}, remove() {} } },
    createElement() { const bubble = { innerHTML: '' }; return { className: '', classList: { add() {} }, set innerHTML(s) { bubble.innerHTML = s; }, querySelector() { return bubble; }, bubble }; },
  };
  const helper = { ...global.SteelChatWeb, isMobileInput: () => true,
    async readPage(u) { sequence.push('read'); return readable ? { url: u, status: 'read', title: '鋼筋行情', summary: '報導鋼筋價格變化。' } : { url: u, status: 'unavailable' }; } };
  const window = { SteelChatWeb: helper, navigator: {}, matchMedia: () => ({ matches: true }) };
  const fetch = async (target, options = {}) => {
    if (String(target).includes('data/laws/index.json')) return { ok: true, json: async () => ({ laws: [] }) };
    if (String(target).includes('data/latest.json')) return { ok: true, json: async () => ({ date: '2026-11-04' }) };
    if (String(target).includes('data/materials.json') || String(target).includes('data/accuracy.json')) return { ok: false };
    if (String(target).includes('data/report.json')) return { ok: true, json: async () => ({ date: '2026-11-03', file: 'reports/test.pptx', title: '電子報獨有標題', slides: 1, content: { date: '2026-11-03', file: 'reports/test.pptx', pages: [{page: 1, text: ['電子報獨有內容'], charts: [{name: '鋼筋', points: [{category: '26/10', value: '18500'}]}]}] } }) };
    if (String(target).includes('/v1/responses')) {
      const body = JSON.parse(options.body);
      if (body.instructions.includes('預測使用者可能')) return {ok:true,json:async()=>({output_text:JSON.stringify({question:'鋼筋成本有什麼影響？'})})};
      if (!body.stream) { sequence.push('scope'); assert(body.input.includes('報導鋼筋價格變化')); if (selections.length) for (const item of selections) { assert(body.input.includes(item.text)); if (item.question) assert(body.input.includes(item.text + '\n此引用的問題：' + item.question)); } return { ok: true, json: async () => ({ output_text: JSON.stringify({ in_scope: inScope, laws: [], terms: [] }) }) }; }
      sequence.push('answer'); assert(body.input.at(-1).content.includes('報導鋼筋價格變化'));
      assert(body.instructions.includes('電子報獨有內容'));
      assert(body.instructions.includes('圖表「鋼筋」：26/10：18500'));
      assert(body.instructions.includes('電子報日期與網站最新分析日期不同'));
      assert(body.instructions.includes('電子報第1頁'));
      let done = false; const encoded = new TextEncoder().encode('data: '+JSON.stringify({ type: 'response.output_text.delta', delta: '報導提到鋼筋價格變化。〔網頁1〕' })+'\n\n');
      return { ok: true, body: { getReader: () => ({ async read() { if (done) return { done: true }; done = true; return { done: false, value: encoded }; } }) } };
    }
    throw Error('unexpected ' + target);
  };
  const context = { window, document, navigator: window.navigator, location: { hash: '' }, localStorage: { getItem: () => 'sk-test' }, fetch, console, URL, AbortController, TextDecoder, TextEncoder, Date, setTimeout, clearTimeout, CustomEvent: class { constructor(type, opts) {this.type=type;this.detail=opts.detail;} }, requestAnimationFrame: fn => fn() };
  vm.runInNewContext(fs.readFileSync(require.resolve('../assets/chat.js'), 'utf8'), context);
  for (const selection of selections) { const detail = {...selection}; handlers['steel:ask-selection']({detail}); assert.equal(detail.accepted, true); }
  if (selections.length) {
    assert.deepEqual(sequence, [], 'staging must not call the assistant');
    assert(elem('chat-quotes-list').innerHTML.includes(selections[0].text));
    assert.equal(elem('chat-input').value, '', 'individual questions must stay with their own quote');
    elem('chat-quotes-continue').handlers.click();
    assert(elem('chat-quotes-list').innerHTML.includes(selections[1].text), 'continuing selection preserves staged content');
    const edit = {dataset:{quoteEdit:'0'},setAttribute(){}};
    const field = elem('chat-quote-question-0'); field.hidden=true;
    elem('chat-quotes-list').handlers.click({target:{closest:q => q === '[data-quote-edit]' ? edit : null}});
    assert.equal(field.hidden,false, 'edit opens the correct question');
    field.dataset.quoteQuestion='0'; field.value='修改後：鋼筋為什麼漲？';
    elem('chat-quotes-list').handlers.input({target:field}); selections[0].question=field.value;
    const other = elem('chat-quote-question-1'); other.hidden=true;
    handlers['steel:edit-selection']({detail:{id:selections[1].id}});
    assert.equal(other.hidden,false, 'page marker opens its matching quote');
  }
  elem('chat-input').value = url + ' 這篇說什麼？';
  elem('chat-form').handlers.submit({ submitter: elem('chat-send'), preventDefault() {} });
  for (let i = 0; i < 50 && elem('chat-send').disabled !== false; i++) await new Promise(r => setTimeout(r, 2));
  return { sequence, html: messages.at(-1)?.bubble.innerHTML || '' };
}
(async () => {
  const ok = await runScenario(true, true);
  assert.deepEqual(ok.sequence, ['read', 'scope', 'answer']);
  assert(ok.html.includes('href="https://news.example.tw/steel"'));
  assert(ok.html.includes('〔網頁1〕'));
  const off = await runScenario(true, false);
  assert.deepEqual(off.sequence, ['read', 'scope']);
  assert(off.html.includes('只回答'));
  const no = await runScenario(false, false);
  assert.deepEqual(no.sequence, ['read']);
  assert(no.html.includes('無法確認這個連結的文章內容'));
  const staged = await runScenario(true, true, [{id:'quote-a',text:'第一段鋼筋報價'.repeat(600) + '結尾資料', question:'鋼筋為什麼漲？'}, {id:'quote-b',text:'第二段廢鋼行情', question:'廢鋼有什麼風險？'}]);
  assert.deepEqual(staged.sequence, ['read', 'scope', 'answer']);
  console.log('Chat integration: read before scope, linked source citations, off-topic and unavailable pages passed.');
})().catch(e => { console.error(e); process.exitCode = 1; });
