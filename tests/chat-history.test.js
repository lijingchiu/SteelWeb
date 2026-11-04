const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
require('../assets/chat-web.js'); require('../assets/chat-attachments.js');
const saved = new Map([['steel_openai_key','sk-test']]);
const storage = {getItem:k=>saved.get(k)||null, setItem:(k,v)=>saved.set(k,v), removeItem:k=>saved.delete(k)};
const submissions=[];
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
  const win={SteelChatWeb:{...global.SteelChatWeb,isMobileInput:()=>true},SteelAttachments:global.SteelAttachments,navigator:{},matchMedia:()=>({matches:true})};
  const fetch=async(url,opt={})=>{
    if(String(url).includes('data/latest.json')) return {ok:true,json:async()=>({date:'2026-11-04'})};
    if(String(url).includes('data/')) return {ok:false};
    const b=JSON.parse(opt.body);
    if(b.instructions.includes('預測使用者可能'))return {ok:true,json:async()=>({output_text:JSON.stringify({questions:['後續趨勢如何？','有哪些風險？']})})};
    if(!b.stream)return {ok:true,json:async()=>({output_text:JSON.stringify({in_scope:true,laws:[],terms:[]})})};
    submissions.push(b.input);let done=false;
    return {ok:true,body:{getReader:()=>({read:async()=>done?{done:true}:(done=true,{done:false,value:new TextEncoder().encode('data: '+JSON.stringify({type:'response.output_text.delta',delta:'鋼筋參考回答'})+'\n\n')})})}};
  };
  const ctx={window:win,document:doc,navigator:win.navigator,location:{hash:''},localStorage:storage,fetch,console,URL,AbortController,TextDecoder,TextEncoder,Date,Intl,Math,setTimeout,clearTimeout,confirm:()=>true};
  vm.runInNewContext(fs.readFileSync(require.resolve('../assets/chat.js'),'utf8'),ctx);
  return el;
}
async function submit(el,text){el('chat-input').value=text;el('chat-form').handlers.submit({submitter:el('chat-send'),preventDefault(){}});for(let n=0;n<100 && (el('chat-send').disabled!==false || !saved.get('steel_chat_conversations_v1'));n++)await new Promise(r=>setTimeout(r,2));}
(async()=>{
  let a=start();await submit(a,'鋼筋價格如何？');
  let data=JSON.parse(saved.get('steel_chat_conversations_v1'));
  assert.equal(data.length,1);assert.equal(data[0].messages.length,2);const id=data[0].id;
  let b=start();b('chat-history-open').handlers.click();
  assert.match(b('chat-history-list').innerHTML,/鋼筋價格如何/);
  b('chat-history-search').value='參考回答';b('chat-history-search').handlers.input();assert.match(b('chat-history-list').innerHTML,/鋼筋價格如何/);
  b('chat-history-list').handlers.click({target:{closest:s=>s==='[data-conversation]'?{dataset:{conversation:id}}:null}});
  assert.equal(b('chat-log').children.length,2);
  await submit(b,'那採購呢？');
  for(let n=0;n<100 && JSON.parse(saved.get('steel_chat_conversations_v1'))[0].messages.length<4;n++)await new Promise(r=>setTimeout(r,2));
  data=JSON.parse(saved.get('steel_chat_conversations_v1'));assert.equal(data.length,1);assert.equal(data[0].messages.length,4);
  assert(submissions[1].some(m=>m.role==='user'&&m.content==='鋼筋價格如何？'));
  b('chat-history-list').handlers.click({target:{closest:s=>s==='[data-delete-conversation]'?{dataset:{deleteConversation:id}}:null}});
  assert.equal(JSON.parse(saved.get('steel_chat_conversations_v1')).length,0);
  console.log('Conversation persistence, content search, continuation and deletion passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
