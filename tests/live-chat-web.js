// Manually run with the repository's existing API credential, never print it.
require('../assets/chat-web.js');
const api = global.SteelChatWeb;
const url = 'https://money.udn.com/money/story/5612/9852531';
const key = process.env.OPENAI_API_KEY;
if (!key) { console.error('OpenAI API credential is not configured for this workflow.'); process.exit(1); }
let trace = {};
const observe = async (target, options) => {
  const response = await fetch(target, options);
  trace.httpStatus = response.status;
  if (response.ok) {
    const data = await response.clone().json();
    const outputs = data.output || [];
    trace.actions = outputs.filter(x => x.type === 'web_search_call').map(x => x.action?.type || 'unknown');
    trace.openedTarget = outputs.some(x => x.type === 'web_search_call' && x.action?.type === 'open_page' && api.samePage(x.action.url, url));
    const contents = outputs.filter(x => x.type === 'message').flatMap(x => x.content || []);
    const citations = contents.flatMap(x => x.annotations || []).filter(x => x.type === 'url_citation');
    trace.targetCitation = citations.some(x => api.samePage(x.url, url));
    trace.citationCount = citations.length;
    try { trace.modelStatus = JSON.parse(contents.map(x => x.text || '').join('')).status; } catch (_) { trace.modelStatus = 'invalid JSON'; }
  }
  return response;
};
(async () => {
  const page = await api.readPage(url, '這篇鋼鐵報導在說什麼？', key, 'gpt-6.1-terra', undefined, observe);
  console.log(JSON.stringify({ ...trace, result: page.status, serviceStatus: page.httpStatus || null, mentionsTopic: /和發|越南/.test(page.summary || '') }));
  if (!['read', 'partial'].includes(page.status) || !/和發|越南/.test(page.summary || '')) process.exitCode = 1;
})().catch(() => { console.error('Live web reading request failed.'); process.exitCode = 1; });
