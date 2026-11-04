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
  assert.deepEqual(api.parseTable('名稱,數值\n"一,二",3\n'), [['名稱', '數值'], ['一,二', '3']]);
  assert.deepEqual(api.parseTable('地區,地區代碼,面積\n臺北市,123,100'), [['地區', '面積'], ['臺北市', '100']]);
  assert.deepEqual(api.parseTable('[{"地區":"臺中市","數值":3,"機關代碼":"123"}]'), [['地區', '數值'], ['臺中市', '3']]);
  assert.equal(api.parseTable('<html>not data</html>'), null);
  const savedFetch = global.fetch;
  const csvDoc = { name: '臺中市人口', path: 'test', tableSource: 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=test' };
  global.fetch = async () => ({ ok: true, headers: { get: () => null }, text: async () => '地區,年度,人口\n臺中市,2025,10\n臺北市,2025,20\n' });
  const table = await api.liveTable(csvDoc, '臺中市114年人口多少');
  assert.deepEqual(table.rows, [['臺中市', '2025', '10']]);
  assert.equal(await api.liveTable({ ...csvDoc, tableSource: 'https://example.com/data.csv' }, '人口多少'), null);
  global.fetch = async () => { throw new Error('offline'); };
  assert.equal(await api.liveTable(csvDoc, '臺中市人口多少'), null);
  global.fetch = savedFetch;
  const snapshots = JSON.parse(fs.readFileSync(path.join(root, 'data/laws/reference-archive/source-snapshots.json'), 'utf8'));
  global.fetch = async url => String(url).includes('source-snapshots.json') ? { ok: true, json: async () => snapshots } : savedFetch(url);
  const snapshotPath = Object.keys(snapshots).find(p => p.includes('臺北市都市計畫區域內現有已開闢道路長度及面積'));
  assert(snapshotPath && snapshots[snapshotPath].retrieved);
  const snapshot = await api.liveTable({ name: '臺北市道路', path: `data/laws/reference-archive/${snapshotPath}`, hasSnapshot: true }, '臺北市道路面積');
  assert(snapshot && snapshot.retrieved && snapshot.headers.some(h => h.includes('面積')));
  assert(!snapshot.headers.some(h => h.includes('代碼')));
  global.fetch = savedFetch;
  const map = await api.search('臺北市使用分區圖', ['臺北市', '使用分區圖']);
  assert(map.length && map[0].name === '臺北市土地使用分區圖（官方地圖查詢）');
  assert.equal(map[0].href, 'https://zonemap.udd.gov.taipei/');
  assert.equal(map.filter(x => x.href === map[0].href).length, 1);
  assert(map[0].note.includes('門牌地址或地段地號'));
  assert.equal(map[0].excerpt, '');
  assert(map.every(x => x.href.startsWith('data/laws/reference-archive/') || x.href.startsWith('https://')));
  const linked = await api.search('11920-01-01-2 臺中市都市計畫地區面積及人口', ['11920', '臺中市', '都市計畫', '人口']);
  assert(linked.some(x => x.href.startsWith('https://') && x.note.includes('只有來源連結') && x.excerpt === ''));
  const hsinchu = await api.search('新竹縣107-108年度都市計畫地區面積及人口', ['新竹縣', '107', '108', '面積', '人口']);
  assert(hsinchu.some(x => x.href === 'https://www.hsinchu.gov.tw/OpenDataDetail.aspx?n=902&s=1026' && !x.excerpt));
  const taichung = await api.search('臺中市潭子都市計畫區一千分之一地形圖', ['臺中市', '潭子', '地形圖']);
  assert(taichung.some(x => x.href.startsWith('https://opendata.taichung.gov.tw/search?q=') && !x.excerpt));
  const rules = await api.search('建築物耐震設計規範', ['耐震', '設計規範']);
  assert(rules.some(x => x.name.includes('100年7月')));
  assert(rules.every(x => x.note.includes('來源') || x.note.includes('查閱')));
  for (const [question, expected] of [
    ['山坡地水土保持計畫', 'swc-'],
    ['大地工程土壤液化如何評估', 'geo-'],
    ['鋼結構銲接螺栓施工檢驗', 'steel-'],
    ['建築物耐震設計規範', 'civil-seismic'],
  ]) {
    const results = await api.search(question, [question]);
    const item = results.find(x => x.knowledge && x.knowledge.id.startsWith(expected));
    assert(item && item.href.startsWith('https://') && item.excerpt && item.note.includes('來源'));
  }
  const soil = await api.search('營建剩餘土石方處理方案', ['營建剩餘土石方', '處理方案']);
  assert(soil.some(x => x.href === 'https://www.nlma.gov.tw/ch/legislation/regsearch/9'));
  const local = await api.search('屏東縣建築管理自治法規查詢', ['屏東縣','建築管理']);
  assert(local.some(x => x.href === 'https://ptlaw.pthg.gov.tw/'));
  assert(!local.some(x => /宜蘭縣|雲林縣|桃園市|臺中市/.test(x.name)));
  const bridge = await api.search('公路橋梁耐震評估與補強設計規範', ['公路橋梁','耐震評估','補強']);
  assert(bridge.some(x => x.href.includes('serno=428')));
  const county = await api.search('非都市土地使用分區彰化縣', ['非都市', '使用分區', '彰化縣']);
  assert(county[0].name.includes('彰化縣'));
  assert.deepEqual(await api.search('zz9q8x7y6w', ['zz9q8x7y6w']), []);
  const index = JSON.parse(fs.readFileSync(path.join(root, 'data/laws/reference-archive/search-index.json')));
  const huge = { name: '大型資料', path: 'data/large.txt', bytes: 36000000 };
  const fake = { docs: [huge], terms: { '獨特': [0] } };
  assert.equal(api.rank(fake, '獨特', ['獨特']).length, 0); // ubiquitous terms do not cause broad retrieval
  for (const request of docRequests) assert(!request.includes('..'));
  console.log('Reference search: ranking, links, missing results and source labels passed.');
})().catch(e => { console.error(e); process.exitCode = 1; });
