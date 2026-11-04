const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
require('../assets/chat-web.js'); require('../assets/chat-attachments.js');
const saved = new Map([['steel_openai_key','sk-test']]);
const storage = {getItem:k=>saved.get(k)||null, setItem:(k,v)=>saved.set(k,v), removeItem:k=>saved.delete(k)};
const submissions=[]; let onlineCalls=0, failWeb=false, archiveTimedOut=false, webBeforeArchiveTimeout=false;
function start() {
  const els = new Map();
  function el(id) {
    if (!els.has(id)) els.set(id,{id,value:'',hidden:false,children:[],style:{},dataset:{},scrollHeight:20,clientHeight:20,scrollTop:0,innerHTML:'',
      classList:{add(){},remove(){},toggle(){}},handlers:{},addEventListener(t,fn){this.handlers[t]=fn},setAttribute(){},focus(){},querySelector(){return null},querySelectorAll(){return []},
      appendChild(c){this.children.push(c)},});
    return els.get(id);
  }
  const doc={readyState:'complete',getElementById:el,querySelector(){return null},addEventListener(){},body:{classList:{add(){},remove(){}}},
    createElement(){const bubble={innerHTML:''};return {className:'',classList:{add(){}},set innerHTML(v){bubble.innerHTML=v},querySelector(){return bubble}}}};
  const win={SteelReferenceSearch:{search:()=>new Promise(()=>{})},SteelChatWeb:{...global.SteelChatWeb,isMobileInput:()=>true,searchRegulations:async()=>{onlineCalls++;if (onlineCalls === 1) webBeforeArchiveTimeout = !archiveTimedOut;return failWeb?[]:[{url:'https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=M0110001',title:'水土保持法',status:'partial',origin:'law_search',summary:'水土保持法第1條規定其立法目的。'}]}},SteelAttachments:global.SteelAttachments,navigator:{},matchMedia:()=>({matches:true})};
  const fetch=async(url,opt={})=>{
    if(String(url).includes('data/latest.json')) return {ok:true,json:async()=>({date:'2026-11-04'})};
    if(String(url).includes('data/')) return {ok:false};
    const b=JSON.parse(opt.body);
    if(b.instructions.includes('預測使用者可能'))return {ok:true,json:async()=>({output_text:JSON.stringify({questions:['後續趨勢如何？','有哪些風險？']})})};
    if(!b.stream)return {ok:true,json:async()=>({output_text:JSON.stringify({in_scope:true,legal:true,target_law:'水土保持法',laws:[],terms:['水保法']})})};
    submissions.push(b.input);let done=false;
    return {ok:true,body:{getReader:()=>({read:async()=>done?{done:true}:(done=true,{done:false,value:new TextEncoder().encode('data: '+JSON.stringify({type:'response.output_text.delta',delta:'水土保持法的立法目的〔網頁1〕'})+'\n\n')})})}};
  };
  const ctx={window:win,document:doc,navigator:win.navigator,location:{hash:''},localStorage:storage,fetch,console,URL,AbortController,TextDecoder,TextEncoder,Date,Intl,Math,setTimeout:(fn,ms)=>setTimeout(ms===8000?()=>{archiveTimedOut=true;fn()}:fn,ms===8000?20:ms),clearTimeout,confirm:()=>true};
  vm.runInNewContext(fs.readFileSync(require.resolve('../assets/chat.js'),'utf8'),ctx);
  return el;
}
async function submit(el,text){el('chat-input').value=text;el('chat-form').handlers.submit({submitter:el('chat-send'),preventDefault(){}});for(let n=0;n<100 && (el('chat-send').disabled!==false || !saved.get('steel_chat_conversations_v1'));n++)await new Promise(r=>setTimeout(r,2));}
(async()=>{
  const a=start(); await submit(a,'水保法');
  assert(webBeforeArchiveTimeout, 'start web search without waiting for the stalled reference archive');
  for(let n=0;n<200 && !submissions.length;n++)await new Promise(r=>setTimeout(r,2));
  assert.equal(onlineCalls,1);assert(submissions[0].at(-1).content.includes('<online_regulations>'));
  assert(submissions[0].at(-1).content.includes('M0110001'));
  const messages=JSON.parse(saved.get('steel_chat_conversations_v1'))[0].messages;
  assert.equal(messages[1].sources.pages[0].url,'https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=M0110001');
  failWeb=true; const b=start(); b('chat-input').value='水保法';
  b('chat-form').handlers.submit({submitter:b('chat-send'),preventDefault(){}});
  for(let n=0;n<200 && b('chat-send').disabled!==false;n++)await new Promise(r=>setTimeout(r,2));
  assert.equal(onlineCalls,2);assert.equal(b('chat-send').disabled,false);
  assert(b('chat-log').children.at(-1).querySelector().innerHTML.includes('無法取得可確認'));
  console.log('Hung archive fallback, official web search and unavailable-source recovery passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
