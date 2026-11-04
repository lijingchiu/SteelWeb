const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
require('../assets/chat-web.js');
const url = 'https://news.example.tw/steel';
async function runScenario(readable, inScope, selections = [], animated = false) {
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
  const window = { SteelChatWeb: helper, navigator: {}, matchMedia: q => ({ matches: !animated || !q.includes('prefers-reduced-motion') }) };
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
  const animations = [];
  if (animated) elem('chat-quote-detail').animate = () => { const a={cancel(){this.cancelled=true}, onfinish:null}; animations.push(a); return a; };
  for (const selection of selections) { const detail = {...selection}; handlers['steel:ask-selection']({detail}); assert.equal(detail.accepted, true); }
  if (selections.length) {
    assert.deepEqual(sequence, [], 'staging must not call the assistant');
    assert(elem('chat-quotes-list').innerHTML.includes(selections[0].text));
    assert.equal(elem('chat-input').value, '', 'individual questions must stay with their own quote');
    elem('chat-quotes-continue').handlers.click();
    assert(elem('chat-quotes-list').innerHTML.includes(selections[1].text), 'continuing selection preserves staged content');
    assert.equal(elem('chat-quote-detail').hidden, true, 'quotes begin as compact cards');
    const card = {dataset:{quoteSelect:'0'}};
    const field = elem('chat-quote-question-0');
    elem('chat-quotes-list').handlers.click({target:{closest:q => q === '[data-quote-select]' ? card : null}});
    assert.equal(elem('chat-quote-detail').hidden,false, 'selecting a card opens its details');
    if (animated) animations.at(-1).onfinish();
    assert(elem('chat-quote-detail').innerHTML.includes(selections[0].question));
    field.dataset.quoteQuestion='0'; field.value='修改後：鋼筋為什麼漲？';
    elem('chat-quote-detail').handlers.input({target:field}); selections[0].question=field.value;
    elem('chat-quote-detail').handlers.click({target:{closest:q => q === '[data-quote-collapse]' ? {} : null}});
    if (animated) {
      assert.equal(elem('chat-quote-detail').hidden,false, 'details stay visible during collapse animation');
      elem('chat-quotes-list').handlers.click({target:{closest:q => q === '[data-quote-select]' ? card : null}});
      assert(animations.at(-2).cancelled, 'reopening cancels a pending collapse');
      animations.at(-1).onfinish();
      elem('chat-quote-detail').handlers.click({target:{closest:q => q === '[data-quote-collapse]' ? {} : null}});
      animations.at(-1).onfinish();
    }
    assert.equal(elem('chat-quote-detail').hidden,true,'collapse hides details without removing the quote');
    assert(elem('chat-quotes-list').innerHTML.includes(field.value),'the edited question survives collapse');
    elem('chat-quotes-list').handlers.click({target:{closest:q => q === '[data-quote-select]' ? card : null}});
    assert(elem('chat-quote-detail').innerHTML.includes(field.value),'the edited question is retained after reopening');
    handlers['steel:edit-selection']({detail:{id:selections[1].id}});
    assert(elem('chat-quote-detail').innerHTML.includes(selections[1].question), 'page marker opens its matching quote');
    const extra = {id:'temporary-quote',text:'待刪除的引用',question:'暫存問題'};
    handlers['steel:ask-selection']({detail:extra}); assert(extra.accepted);
    assert(elem('chat-quotes-list').innerHTML.includes('data-quote-card-remove="2"'), 'each card has its own remove button');
    const remove = {dataset:{quoteCardRemove:'2'}};
    elem('chat-quotes-list').handlers.click({target:{closest:q=>q==='[data-quote-card-remove]'?remove:null}});
    assert(!elem('chat-quotes-list').innerHTML.includes('待刪除的引用'), 'removal works without opening the card');
    assert(elem('chat-quote-detail').innerHTML.includes(selections[1].question), 'removing another card preserves the active quote');
  }
  elem('chat-input').value = url + ' 這篇說什麼？';
  elem('chat-form').handlers.submit({ submitter: elem('chat-send'), preventDefault() {} });
  if (selections.length) assert.equal(elem('chat-quotes').hidden, true, 'all quotes hide immediately while the reply is pending');
  for (let i = 0; i < 50 && elem('chat-send').disabled !== false; i++) await new Promise(r => setTimeout(r, 2));
  return { sequence, html: messages.at(-1)?.bubble.innerHTML || '', quotesHidden:elem('chat-quotes').hidden };
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
  assert.equal(staged.quotesHidden,true, 'successful reply clears the whole tray');
  const failed = await runScenario(false, false, [{id:'quote-c',text:'第一筆鋼筋資料',question:'價格為何？'}, {id:'quote-d',text:'第二筆鋼筋資料',question:'影響為何？'}]);
  assert.equal(failed.quotesHidden,false, 'failed lookup restores all pending quotes');
  await runScenario(true, true, [{id:'quote-e',text:'鋼材行情',question:'原因？'}, {id:'quote-f',text:'廢鋼行情',question:'風險？'}], true);
  console.log('Chat integration: read before scope, linked source citations, off-topic and unavailable pages passed.');
})().catch(e => { console.error(e); process.exitCode = 1; });
