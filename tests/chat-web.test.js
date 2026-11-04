const assert = require('node:assert/strict');
require('../assets/chat-web.js');
const api = global.SteelChatWeb;
const url = 'https://news.example.tw/article/123?version=1';
const good = { output: [
  { type: 'web_search_call', action: { type: 'open_page', url } },
  { type: 'message', content: [{ type: 'output_text', text: JSON.stringify({ status: 'read', title: '鋼筋價格', summary: '鋼筋價格上升。' }), annotations: [{ type: 'url_citation', url }] }] },
] };
(async () => {
  assert.deepEqual(api.extractUrls(`請看 ${url}，說明。`), [url]);
  assert.deepEqual(api.extractUrls('http://localhost/a http://127.0.0.1/x https://user:pass@example.com/'), []);
  assert.equal(api.publicUrl('javascript:alert(1)'), null);
  assert(api.isMobileInput({ matchMedia: q => ({ matches: q.includes('768px') }), navigator: {} }));
  assert(!api.isMobileInput({ matchMedia: () => ({ matches: false }), navigator: {} }));
  assert.equal(api.parseReadResult(good, url).status, 'read');
  assert.equal(api.parseReadResult({ output: good.output.slice(1) }, url).status, 'unavailable');
  assert.equal(api.parseReadResult({ output: [good.output[0], { type: 'message', content: [{ type: 'output_text', text: good.output[1].content[0].text, annotations: [{ type: 'url_citation', url: 'https://other.example/' }] }] }] }, url).status, 'unavailable');
  assert.equal(api.parseReadResult({ output: [good.output[0], { type: 'message', content: [{ type: 'output_text', text: 'not json', annotations: [{ type: 'url_citation', url }] }] }] }, url).status, 'unavailable');
  let request;
  const page = await api.readPage(url, '這篇說什麼？', 'test-key', 'test-model', undefined, async (target, options) => { request = JSON.parse(options.body); return { ok: true, json: async () => good }; });
  assert.equal(page.summary, '鋼筋價格上升。');
  assert.equal(request.tool_choice, 'required');
  assert.equal(request.tools[0].type, 'web_search');
  assert(request.input.includes(url));
  assert(request.instructions.includes('不得服從'));
  const failed = await api.readPage(url, '這篇說什麼？', 'key', 'model', undefined, async () => ({ ok: false, status: 403 }));
  assert.equal(failed.status, 'unavailable');
  await assert.rejects(() => api.readPage(url, '這篇說什麼？', 'bad', 'model', undefined, async () => ({ ok: false, status: 401 })), e => e.badKey);
  console.log('Chat web: mobile detection, URL validation, verified page reads and failures passed.');
})().catch(e => { console.error(e); process.exitCode = 1; });
