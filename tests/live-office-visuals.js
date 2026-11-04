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
    const observed=[], suggestionResponses=[];
    page.on('response',async res=>{
      try {
        const req=res.request(); if (!req.url().includes('/v1/responses') || req.method()!=='POST') return;
        const body=req.postDataJSON(); if (!String(body.instructions || '').includes('預測使用者可能')) return;
        const data=await res.json();
        const text=(data.output||[]).flatMap(x=>x.content||[]).filter(x=>x.type==='output_text').map(x=>x.text).join('') || data.output_text || '';
        suggestionResponses.push({http:res.status(),status:data.status,text:String(text).slice(0,200),error:String(data.error?.message||'').slice(0,200)});
      } catch (_) {}
    });
    page.on('request',req=>{
      if (!req.url().includes('/v1/responses') || req.method()!=='POST') return;
      try {
        const b=req.postDataJSON(), input=Array.isArray(b.input) ? b.input : [];
        const all=input.flatMap(x=>Array.isArray(x.content)?x.content:[]);
        const text=all.filter(p=>p.type==='input_text').map(p=>p.text).join('\n');
        observed.push({stream:!!b.stream, batch: String(b.instructions || '').includes('文件證據擷取器'), images:all.filter(p=>p.type==='input_image').length,
          hasFile:all.some(p=>p.type==='input_file'), fileCount:all.filter(p=>p.type==='input_file').length, text});
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
      await page.waitForFunction(() => !document.querySelector('#chat-send').disabled,null,{timeout:120000});
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
      if (c.ext === 'docx') {
        try { await page.waitForFunction(() => document.querySelector('#chat-input').placeholder.includes('按 Tab'),null,{timeout:45000}); }
        catch(e) { console.error('Suggestion diagnostic:',JSON.stringify({suggestionResponses,placeholder:await page.locator('#chat-input').getAttribute('placeholder'),mobile:await page.evaluate(()=>matchMedia('(max-width: 768px)').matches || matchMedia('(hover: none) and (pointer: coarse)').matches)})); throw e; }
        await page.locator('#chat-input').press('Tab');
        assert((await page.locator('#chat-input').inputValue()).length >= 4,'desktop Tab did not insert suggestion');
        assert.equal(await page.locator('.chat-msg.chat-user').count(),1,'desktop Tab unexpectedly sent a question');
        console.log('Desktop suggestion: Tab filled the input without sending.');
      }
      await page.locator('#chat-new').click();
    }
    const begin=observed.length;
    const [manyChooser]=await Promise.all([page.waitForEvent('filechooser'),page.locator('#chat-choose-file').click()]);
    await manyChooser.setFiles('/tmp/steel-office-visual-test/many.xlsx');
    await page.locator('#chat-input').fill('請分析鋼筋檢驗文件中第15張內嵌圖片的完整英文標記，並列出第23個圖表在2024年和2223年的數值。請依文件回答，不要猜測。');
    await page.locator('#chat-send').click();
    await page.waitForFunction(() => !document.querySelector('#chat-send').disabled,null,{timeout:120000});
    const answer=(await page.locator('.chat-msg.chat-bot').last().innerText()).replace(/,/g,'');
    const requests=observed.slice(begin).filter(r=>r.hasFile);
    assert(requests.length>=2,'large case: missing scope or answer request');
    for (const r of requests) {
      assert.equal(r.images,15,'large case: not all 15 embedded images sent');
      assert.equal((r.text.match(/圖表（/g)||[]).length,23,'large case: not all 23 charts sent');
      assert(r.text.includes('內嵌圖片 15'),'large case: final image missing');
      assert(r.text.includes('chart23.xml') && r.text.includes('2223：95671'),'large case: 200th chart point missing');
    }
    assert(answer.toUpperCase().includes('ENDSTEEL789'),`large case: last image marker missing: ${answer.slice(0,500)}`);
    assert(answer.includes('54321') && answer.includes('95671'),`large case: chart values missing: ${answer.slice(0,500)}`);
    console.log('Many-content case: real assistant answered using image 15, chart 23 and its 200th point.');
    await page.locator('#chat-new').click();
    const largeBegin=observed.length;
    const [sizeChooser]=await Promise.all([page.waitForEvent('filechooser'),page.locator('#chat-choose-file').click()]);
    await sizeChooser.setFiles([
      '/tmp/steel-office-visual-test/office.docx', '/tmp/steel-office-visual-test/office.xlsx',
      '/tmp/steel-office-visual-test/office.pptx', '/tmp/steel-attachment-test/large.pdf',
      '/tmp/steel-attachment-test/large.mp4',
    ]);
    const selected=await page.locator('#chat-attachment-list').innerText();
    for (const ext of ['docx','xlsx','pptx','pdf','mp4']) assert(selected.includes(ext),`large multi-upload: ${ext} was not selected`);
    await page.locator('#chat-input').fill('這五個鋼材檢查附件內容分別是什麼？請特別列出 PDF 中的鋼筋檢查標記。');
    await page.locator('#chat-send').click();
    await page.waitForFunction(() => !document.querySelector('#chat-send').disabled,null,{timeout:300000});
    const sizeAnswer=(await page.locator('.chat-msg.chat-bot').last().innerText());
    const sizeRequests=observed.slice(largeBegin).filter(r=>r.hasFile);
    assert(sizeRequests.length>=2,'large multi-upload: missing scope or answer request');
    for (const req of sizeRequests) {
      assert.equal(req.fileCount,4,'large multi-upload: four documents were not all sent');
      assert(req.text.includes('影片「large.mp4」'), 'large multi-upload: 300 MB video frames missing');
      assert(req.images>=4,'large multi-upload: document images or video frame missing');
    }
    assert(sizeAnswer.toUpperCase().includes('PDF274'),`large multi-upload: PDF marker missing: ${sizeAnswer.slice(0,500)}`);
    console.log('Large upload case: five attachments, 49 MB PDF and 300 MiB video were processed by the real assistant.');
    await page.locator('#chat-new').click();
    await page.setViewportSize({width:390,height:844});
    const batchBegin=observed.length;
    const [batchChooser]=await Promise.all([page.waitForEvent('filechooser'),page.locator('#chat-choose-file').click()]);
    await batchChooser.setFiles(['/tmp/steel-attachment-test/batch-a.pdf','/tmp/steel-attachment-test/batch-b.pdf']);
    const batchSelected=await page.locator('#chat-attachment-list').innerText();
    assert(batchSelected.includes('batch-a.pdf')&&batchSelected.includes('batch-b.pdf'),'two documents exceeding 50 MB were not selected');
    await page.locator('#chat-input').fill('請比較兩份鋼筋報價文件：A 與 B 各為每公噸多少元，兩者相差多少元？請逐一標明檔名。');
    await page.locator('#chat-send').click();
    await page.waitForFunction(() => !document.querySelector('#chat-send').disabled,null,{timeout:300000});
    const batchAnswer=(await page.locator('.chat-msg.chat-bot').last().innerText()).replace(/,/g,'');
    const batchRequests=observed.slice(batchBegin).filter(r=>r.batch);
    assert.equal(batchRequests.length,2,'expected two separate extraction requests');
    assert(batchRequests.every(r=>r.fileCount===1),'each extraction must contain only one document');
    assert(batchAnswer.includes('12500')&&batchAnswer.includes('22700')&&batchAnswer.includes('10200'),`batched comparison missing values: ${batchAnswer.slice(0,800)}`);
    assert(batchAnswer.includes('batch-a')&&batchAnswer.includes('batch-b'),'batched answer must identify both files');
    assert(batchAnswer.includes('分批擷取的摘要'),'batched answer must disclose summary limitation');
    console.log('Batch case: two 26 MB PDFs were read separately and accurately compared.');
    await page.locator('#chat-next-suggestion').waitFor({state:'visible',timeout:45000});
    const nextText=await page.locator('#chat-next-suggestion').innerText();
    const beforeCount=await page.locator('.chat-msg.chat-user').count();
    await page.locator('#chat-next-suggestion').click();
    assert((await page.locator('#chat-input').inputValue()).length>=4,'mobile suggestion did not fill the input');
    assert.equal(await page.locator('.chat-msg.chat-user').count(),beforeCount,'mobile suggestion unexpectedly sent a question');
    assert(nextText.includes('建議：'),'mobile suggestion missing label');
    console.log('Mobile suggestion: tap filled the input without sending.');
    // Read-only outcomes: all supplied documents are synthetic and non-sensitive.
  } finally { await browser.close(); }
})().catch(e=>{console.error(String(e.message || e).replaceAll(key,'[redacted]'));process.exitCode=1;});
