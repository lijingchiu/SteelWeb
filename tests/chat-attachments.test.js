const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
require('../assets/chat-web.js');
require('../assets/chat-attachments.js');
const attachments = global.SteelAttachments;
const file = (name, size = 10) => ({ name, size });
assert.equal(attachments.kind(file('材料照片.JPG')), 'image');
assert.equal(attachments.kind(file('施工影片.mov')), 'video');
for (const ext of ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'csv', 'txt']) assert.equal(attachments.kind(file('資料.' + ext)), 'document');
assert.match(attachments.validate([file('資料.exe')]), /不支援/);
assert.equal(attachments.validate([file('照片.png', 49_999_999)]), '');
assert.match(attachments.validate([file('照片.png', 50_000_000)]), /限制/);
assert.equal(attachments.validate([file('影片.mp4', 300 * 1024 * 1024)]), '');
assert.match(attachments.validate([file('影片.mp4', 300 * 1024 * 1024 + 1)]), /限制/);
assert.equal(attachments.validate(Array(12).fill(file('照片.png'))), '');
assert.equal(attachments.validate([file('a.pdf', 25_000_000), file('b.docx', 24_999_999)]), '');
assert.match(attachments.validate([file('a.pdf', 25_000_000), file('b.docx', 25_000_000)]), /合計/);
assert.equal(attachments.validate([file('工程.pdf'), file('施工.mp4')]), '');

async function scenario(inScope) {
  const els = new Map(), sent = [];
  function elem(id = '') {
    if (!els.has(id)) els.set(id, { id, value: '', hidden: false, children: [], scrollHeight: 20, scrollTop: 0, clientHeight: 20, style: {}, dataset: {}, innerHTML: '',
      classList: { add() {}, remove() {}, toggle() {} }, handlers: {},
      addEventListener(t, fn) { this.handlers[t] = fn; }, setAttribute(k,v) { this[k]=v; }, focus() {}, click() {},
      appendChild(child) { this.children.push(child); }, querySelector() { return null; },
    });
    return els.get(id);
  }
  const document = { readyState: 'complete', getElementById: elem, addEventListener() {}, body: { classList: { add() {}, remove() {} } },
    createElement() { const bubble = { innerHTML: '' }; return { className: '', classList: { add() {} }, set innerHTML(s) { bubble.innerHTML = s; }, querySelector() { return bubble; }, bubble }; } };
  const prepared = [{type: 'input_text', text: '文件「工程.pdf」'}, {type: 'input_file', filename: '工程.pdf', file_data: 'data:application/pdf;base64,AAAA'}];
  const window = { SteelChatWeb: {...global.SteelChatWeb, isMobileInput: () => true}, SteelAttachments: { ...attachments, prepare: async () => prepared }, navigator: {}, matchMedia: () => ({ matches: true }) };
  const fetch = async (target, options = {}) => {
    if (String(target).includes('data/laws/index.json')) return {ok:true,json:async()=>({laws:[]})};
    if (String(target).includes('data/latest.json')) return {ok:true,json:async()=>({date:'2026-11-04'})};
    if (String(target).includes('data/')) return {ok:false};
    if (String(target).includes('/v1/responses')) {
      const body = JSON.parse(options.body); sent.push(body);
      if (!body.stream) return {ok:true,json:async()=>({output_text:JSON.stringify({in_scope:inScope,laws:[],terms:[]})})};
      let done = false; const bytes = new TextEncoder().encode('data: '+JSON.stringify({type:'response.output_text.delta',delta:'這份工程文件說明鋼材。'})+'\n\n');
      return {ok:true,body:{getReader:()=>({async read(){if(done)return {done:true};done=true;return {done:false,value:bytes};}})}};
    }
    throw new Error('unexpected request');
  };
  vm.runInNewContext(fs.readFileSync(require.resolve('../assets/chat.js'),'utf8'), {window,document,navigator:window.navigator,location:{hash:''},localStorage:{getItem:()=> 'sk-test'},fetch,console,URL,AbortController,TextDecoder,TextEncoder,Date,setTimeout,clearTimeout});
  elem('chat-attach-menu').hidden = true;
  elem('chat-attach').handlers.click();
  assert.equal(elem('chat-attach')['aria-expanded'], 'true');
  assert.equal(elem('chat-attach-menu').hidden, false);
  elem('chat-attach').handlers.click();
  assert.equal(elem('chat-attach')['aria-expanded'], 'false');
  assert.equal(elem('chat-attach-menu').hidden, true);
  elem('chat-file').handlers.change({target:{files:[file('工程.pdf')]}});
  assert.equal(elem('chat-attachments').hidden,false);
  elem('chat-input').value = '這份文件在說什麼？';
  elem('chat-form').handlers.submit({submitter:elem('chat-send'),preventDefault(){}});
  for (let i=0;i<100 && elem('chat-send').disabled !== false;i++) await new Promise(r=>setTimeout(r,2));
  assert.equal(sent.length,inScope ? 2 : 1);
  const scopeParts=sent[0].input[0].content;
  assert(scopeParts.some(p=>p.type==='input_file' && p.filename==='工程.pdf'));
  if(inScope) assert(sent[1].input.at(-1).content.some(p=>p.type==='input_file' && p.filename==='工程.pdf'));
}
(async()=>{await scenario(true);await scenario(false);console.log('Attachment selection, limits, subject check and answer payload passed.');})().catch(e=>{console.error(e);process.exitCode=1;});

(async () => {
  const code = fs.readFileSync(require.resolve('../assets/chat-attachments.js'), 'utf8');
  let revoked = false;
  class FakeVideo {
    constructor() { this.handlers = {}; this.duration = 24; this.videoWidth = 1920; this.videoHeight = 1080; }
    addEventListener(type, fn) { this.handlers[type] = fn; }
    removeEventListener(type) { delete this.handlers[type]; }
    set src(value) { queueMicrotask(() => this.handlers.loadedmetadata?.()); }
    set currentTime(value) { this.time = value; queueMicrotask(() => this.handlers.seeked?.()); }
    removeAttribute() {} load() {}
  }
  const URL = {createObjectURL:()=> 'blob:video',revokeObjectURL:()=>{revoked = true;}};
  const document = {createElement: type => type === 'video' ? new FakeVideo() : {width:0,height:0,getContext:()=>({drawImage(){}}),toDataURL:()=> 'data:image/jpeg;base64,AAAA'}};
  const window = {};
  vm.runInNewContext(code, {window,document,URL,setTimeout,clearTimeout,queueMicrotask,Math,Number,Error,String});
  const parts = await window.SteelAttachments.prepare([file('施工影片.mp4')]);
  assert.equal(parts.filter(p => p.type === 'input_image').length, 8);
  assert.match(parts[0].text, /未讀取聲音/);
  assert(parts.some(p => p.type === 'input_text' && p.text.includes('第 1.5 秒')));
  assert.equal(revoked, true);
  console.log('Video frame extraction, timestamps and cleanup passed.');
})().catch(e => {console.error(e);process.exitCode=1;});
