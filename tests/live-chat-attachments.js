// Run manually in Actions with the repository's existing secret; never print it.
const fs = require('node:fs');
const root = '/tmp/steel-attachment-test/';
const key = process.env.OPENAI_API_KEY;
if (!key) { console.error('OpenAI API credential is not configured.'); process.exit(1); }
const files = [
  ['sample.docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document','DOC271'],
  ['sample.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','XLS272'],
  ['sample.pptx','application/vnd.openxmlformats-officedocument.presentationml.presentation','PPT273'],
  ['sample.pdf','application/pdf','PDF274'],
  ['sample.png','image/png','IMG275'],
];
(async () => {
  for (const group of [files.slice(0,3), files.slice(3)]) {
    const content = [{type:'input_text',text:'這些附件都是鋼筋檢查資料。逐一讀取附件，原樣列出每個附件中的英文標記。'}];
    for (const [name,mime] of group) {
      const data = `data:${mime};base64,${fs.readFileSync(root+name).toString('base64')}`;
      content.push(name.endsWith('.png') ? {type:'input_image',image_url:data,detail:'high'} : {type:'input_file',filename:name,file_data:data});
    }
    const res = await fetch('https://api.openai.com/v1/responses', {method:'POST',headers:{Authorization:`Bearer ${key}`,'Content-Type':'application/json'},body:JSON.stringify({model:'gpt-6.1-terra',input:[{role:'user',content}],reasoning:{effort:'low'},max_output_tokens:1000,store:false})});
    if (!res.ok) { const error = (await res.json()).error || {}; throw new Error(`API ${res.status}: ${String(error.message || '').replaceAll(key,'[redacted]').slice(0,300)}`); }
    const obj = await res.json();
    const text = (obj.output || []).flatMap(item => item.content || []).filter(c => c.type === 'output_text').map(c => c.text).join(' ');
    for (const [name,,marker] of group) {
      const ok = text.toUpperCase().includes(marker);
      console.log(`${name}: ${ok ? 'passed' : 'marker not found'}`);
      if (!ok) process.exitCode=1;
    }
  }
})().catch(e => {console.error(e.message);process.exitCode=1;});
