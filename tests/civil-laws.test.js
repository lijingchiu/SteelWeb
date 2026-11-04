const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const index = JSON.parse(fs.readFileSync(path.join(root,'data/laws/index.json'),'utf8'));
const names = JSON.parse(fs.readFileSync(path.join(root,'scripts/civil_laws_catalog.json'),'utf8')).names;
const unique = new Set(index.laws.map(l=>l.pcode));
assert.equal(unique.size,index.laws.length);
for (const name of names) assert(index.laws.some(l=>l.name===name),`missing ${name}`);
for (const entry of index.laws) {
  const doc=JSON.parse(fs.readFileSync(path.join(root,'data/laws',entry.pcode+'.json'),'utf8'));
  assert.equal(doc.name,entry.name); assert.equal(doc.articles.length,entry.articles);
  assert(doc.articles.every(a=>typeof a.text==='string'&&typeof a.n==='string'));
  assert(entry.url.startsWith('https://'));
}
const document={readyState:'complete',getElementById:()=>null};
const window={};
const fetch=async url=>{const file=path.join(root,String(url).split('?')[0]);return {ok:fs.existsSync(file),json:async()=>JSON.parse(fs.readFileSync(file,'utf8'))}};
vm.runInNewContext(fs.readFileSync(path.join(root,'assets/chat.js'),'utf8'),{window,document,fetch,console,URL,AbortController,Date,setTimeout,clearTimeout});
(async()=>{
  for(const [name,number] of [['水利法','1'],['地質法','1'],['環境影響評估法','1'],['市區道路及附屬工程設計標準','1']]) {
    const result=await window.__steelLaws.searchLaws([name],[],`${name}第${number}條`);
    assert(result.some(r=>r.law===name&&r.n===number),name);
  }
  for(const name of ['桃園市建築管理自治條例','嘉義縣營建剩餘土石方管理自治條例','花蓮縣建築管理自治條例','臺東縣營建剩餘土石方管理自治條例']) {
    const result=await window.__steelLaws.searchLaws([name],[],`${name}第1條`);
    assert(result.some(r=>r.law===name && r.n==='1' && r.region),name);
  }
  const local=index.laws.filter(l=>l.pcode.match(/^(KL|HC|ML|CH|NT|KM|HCC|CYI|CYC|PT|PH|HL|TT|TY)-/));
  assert.equal(local.length,28);
  for(const entry of local){const doc=JSON.parse(fs.readFileSync(path.join(root,'data/laws',entry.pcode+'.json'),'utf8'));assert(doc.articles.at(-1).text.includes('施行'));assert(!doc.articles.some(a=>/GlobalCheckForm|font-family|<script/i.test(a.text)));}
  const safety=await window.__steelLaws.searchLaws(['營造安全衛生設施標準'],[],'營造安全衛生設施標準第11-2條');
  assert(safety.some(r=>r.effective_note.includes('一百十六年七月一日')));
  console.log(`Civil law catalog, source files, lookups and effective-date notes passed: ${index.laws.length} laws.`);
})().catch(e=>{console.error(e);process.exitCode=1});
