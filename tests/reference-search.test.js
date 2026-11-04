const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
let docRequests = [];
global.fetch = async url => {
  if (url.includes('search-index.json')) {
    return { ok: true, json: async () => JSON.parse(fs.readFileSync(path.join(root, url.split('?')[0]), 'utf8')) };
  }
  docRequests.push(url);
  const name = url.split('?')[0].split('/').map(decodeURIComponent).join('/');
  const file = path.join(root, name);
  return { ok: fs.existsSync(file), text: async () => fs.readFileSync(file, 'utf8') };
};
require('../assets/reference-search.js');
(async () => {
  const api = global.SteelReferenceSearch;
  const map = await api.search('臺北市使用分區圖', ['臺北市', '使用分區圖']);
  assert(map.length && map[0].name.includes('臺北市'));
  assert(map.some(x => x.name.includes('主計')) && map.some(x => x.name.includes('細計')));
  assert(map.every(x => x.href.startsWith('data/laws/reference-archive/') || x.href.startsWith('https://')));
  const linked = await api.search('11920-01-01-2 臺中市都市計畫地區面積及人口', ['11920', '臺中市', '都市計畫', '人口']);
  assert(linked.some(x => x.href.startsWith('https://') && x.note.includes('只有來源連結') && x.excerpt === ''));
  const rules = await api.search('建築物耐震設計規範', ['耐震', '設計規範']);
  assert(rules.some(x => x.name.includes('100年7月')));
  assert(rules.every(x => x.note.includes('來源') || x.note.includes('查閱')));
  const county = await api.search('非都市土地使用分區彰化縣', ['非都市', '使用分區', '彰化縣']);
  assert(county[0].name.includes('彰化縣'));
  assert.deepEqual(await api.search('zz9q8x7y6w', ['zz9q8x7y6w']), []);
  const index = JSON.parse(fs.readFileSync(path.join(root, 'data/laws/reference-archive/search-index.json')));
  const huge = index.docs.find(d => d.bytes > 30000000);
  const fake = { docs: [huge], terms: { '獨特': [0] } };
  assert.equal(api.rank(fake, '獨特', ['獨特']).length, 0); // ubiquitous terms do not cause broad retrieval
  for (const request of docRequests) assert(!request.includes('..'));
  console.log('Reference search: ranking, links, missing results and source labels passed.');
})().catch(e => { console.error(e); process.exitCode = 1; });
