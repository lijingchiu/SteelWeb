// This exercises the actual chat UI, scope check, streamed answer and real API.
// Only generated test documents are uploaded; never log credentials or payloads.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const key = process.env.OPENAI_API_KEY;
if (!key) throw new Error('Missing test API credential');
const cases = [
  {ext:'docx',mark:'WORDPHOTO793',values:['22917','65142'],place:'Word 文件內文'},
  {ext:'xlsx',mark:'EXCELPHOTO684',values:['31247','58763'],place:'Rebar costs'},
  {ext:'pptx',mark:'PPTPHOTO562',values:['41638','79251'],place:'第 1 張投影片'},
];
(async () => {
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || undefined,args:['--no-sandbox']});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    await page.addInitScript(k => localStorage.setItem('steel_openai_key',k), key);
    const observed=[];
    page.on('request',req=>{
      if (!req.url().includes('/v1/responses') || req.method()!=='POST') return;
      try {
        const b=req.postDataJSON(), input=Array.isArray(b.input) ? b.input : [];
        const all=input.flatMap(x=>Array.isArray(x.content)?x.content:[]);
        const text=all.filter(p=>p.type==='input_text').map(p=>p.text).join('\n');
        observed.push({stream:!!b.stream, images:all.filter(p=>p.type==='input_image').length,
          hasFile:all.some(p=>p.type==='input_file'), text});
      } catch (_) { /* requests without this structure are irrelevant */ }
    });
    await page.goto('http://127.0.0.1:8765/',{waitUntil:'domcontentloaded'});
    await page.locator('#chat-fab').click(); await page.locator('#chat-input').waitFor({state:'visible'});
    await page.locator('#chat-attach').click();
    for (const c of cases) {
      const begin=observed.length;
      const [chooser]=await Promise.all([page.waitForEvent('filechooser'),page.locator('#chat-choose-file').click()]);
      await chooser.setFiles(`/tmp/steel-office-visual-test/office.${c.ext}`);
      await page.locator('#chat-input').fill('請分析這份鋼筋檢查文件：先寫出內嵌圖片中完整的英文標記，再列出圖表 2024 與 2025 各自的數值。請忠於附件內容，不要猜測。');
      await page.locator('#chat-send').click();
      await page.waitForFunction(() => !document.querySelector('#chat-send').disabled,{timeout:120000});
      const answer=(await page.locator('.chat-msg.chat-bot').last().innerText()).replace(/,/g,'');
      const requests=observed.slice(begin).filter(r=>r.hasFile);
      assert(requests.length>=2,`${c.ext}: scope and answer requests missing`);
      for (const req of requests) {
        assert(req.images>=1,`${c.ext}: embedded image missing from ${req.stream ? 'answer' : 'scope'} request`);
        assert(req.text.includes(c.place),`${c.ext}: location metadata missing`);
        for (const v of c.values) assert(req.text.includes(v),`${c.ext}: chart data ${v} missing`);
      }
      assert(answer.toUpperCase().includes(c.mark),`${c.ext}: image marker missing from answer: ${answer.slice(0,500)}`);
      for (const v of c.values) assert(answer.includes(v),`${c.ext}: chart value ${v} missing from answer: ${answer.slice(0,500)}`);
      console.log(`${c.ext}: real assistant read image ${c.mark} and chart values ${c.values.join(', ')}.`);
      await page.locator('#chat-new').click();
    }
    // Read-only outcomes: all supplied documents are synthetic and non-sensitive.
  } finally { await browser.close(); }
})().catch(e=>{console.error(String(e.message || e).replaceAll(key,'[redacted]'));process.exitCode=1;});
