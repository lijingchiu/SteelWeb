const assert=require('node:assert/strict');
const fs=require('node:fs'), vm=require('node:vm');
require('../assets/chat-web.js'); require('../assets/chat-attachments.js');
const helper=global.SteelAttachments;
global.FileReader=class {readAsDataURL(file){this.result='data:application/pdf;base64,AAAA';queueMicrotask(()=>this.onload());}};
async function run(mobile, withFiles, failSuggestion=false) {
  const elements=new Map(), requests=[], messages=[];
  function elem(id='') {
    if(!elements.has(id)) elements.set(id,{id,value:'',hidden:false,children:[],style:{},dataset:{},scrollHeight:20,clientHeight:20,scrollTop:0,
      classList:{add(){},remove(){},toggle(){}},handlers:{},addEventListener(t,fn){this.handlers[t]=fn;},setAttribute(){},focus(){},click(){},querySelector(){return null;},querySelectorAll(){return [];},appendChild(c){this.children.push(c);messages.push(c);}});
    return elements.get(id);
  }
  const document={readyState:'complete',getElementById:elem,addEventListener(){},body:{classList:{add(){},remove(){}}},
    createElement(){const bubble={innerHTML:''};return {className:'',classList:{add(){}},set innerHTML(v){bubble.innerHTML=v;},querySelector(){return bubble;},bubble};}};
  const window={SteelChatWeb:{...global.SteelChatWeb,isMobileInput:()=>mobile},SteelAttachments:helper,navigator:{},matchMedia:()=>({matches:mobile})};
  const fetch=async(target,options={})=>{
    if(String(target).includes('data/laws/index.json'))return {ok:true,json:async()=>({laws:[]})};
    if(String(target).includes('data/latest.json'))return {ok:true,json:async()=>({date:'2026-11-04'})};
    if(String(target).includes('data/'))return {ok:false};
    const b=JSON.parse(options.body);
    if(b.instructions.includes('預測使用者可能')) return failSuggestion ? {ok:false,status:503} : {ok:true,json:async()=>({output_text:JSON.stringify({question:'這對鋼筋採購成本有何影響？'})})};
    if(b.instructions.includes('文件證據擷取器')){
      requests.push({type:'batch',body:b});
      const parts=b.input[0].content, f=parts.find(p=>p.type==='input_file');
      assert.equal(parts.filter(p=>p.type==='input_file').length,1);
      if(f.filename==='broken.pdf')return {ok:false,status:500,json:async()=>({})};
      return {ok:true,json:async()=>({status:'completed',output_text:f.filename==='a.pdf'?'a.pdf 鋼筋每噸12500元':'b.pdf 鋼筋每噸22700元'})};
    }
    if(!b.stream){requests.push({type:'scope',body:b});return {ok:true,json:async()=>({output_text:JSON.stringify({in_scope:true,laws:[],terms:[]})})};}
    requests.push({type:'answer',body:b});let done=false;
    const bytes=new TextEncoder().encode('data: '+JSON.stringify({type:'response.output_text.delta',delta:'a.pdf 每噸12500元；b.pdf 每噸22700元。'})+'\n\n');
    return {ok:true,body:{getReader:()=>({async read(){if(done)return {done:true};done=true;return {done:false,value:bytes};}})}};
  };
  const ctx={window,document,navigator:window.navigator,location:{hash:''},localStorage:{getItem:()=> 'sk-test'},fetch,console,URL,AbortController,TextDecoder,TextEncoder,Date,setTimeout,clearTimeout};
  vm.runInNewContext(fs.readFileSync(require.resolve('../assets/chat.js'),'utf8'),ctx);
  if(withFiles) elem('chat-file').handlers.change({target:{files:[{name:'a.pdf',size:26_000_000},{name:'b.pdf',size:26_000_000},{name:'broken.pdf',size:2}]}});
  elem('chat-input').value='比較文件的鋼筋價格';
  elem('chat-form').handlers.submit({submitter:elem('chat-send'),preventDefault(){}});
  for(let i=0;i<200 && (elem('chat-send').disabled!==false || !elem('chat-input').placeholder?.includes('建議'));i++)await new Promise(r=>setTimeout(r,2));
  return {elem,requests,messages};
}
(async()=>{
  const mobile=await run(true,true);
  assert.equal(mobile.requests.filter(r=>r.type==='batch').length,3);
  const scope=mobile.requests.find(r=>r.type==='scope').body;
  const scopeText=scope.input[0].content.map(p=>p.text||'').join(' ');
  assert(scopeText.includes('12500')&&scopeText.includes('22700')&&scopeText.includes('broken.pdf'));
  const answer=mobile.requests.find(r=>r.type==='answer').body;
  assert(answer.input.at(-1).content.some(p=>p.text?.includes('12500')));
  const html=mobile.messages.at(-1).bubble.innerHTML;
  assert(html.includes('未能讀取')&&html.includes('broken.pdf'));
  assert(html.includes('分批擷取的摘要'));
  assert.equal(mobile.elem('chat-next-suggestion').hidden,false);
  mobile.elem('chat-next-suggestion').handlers.click();
  assert.equal(mobile.elem('chat-input').value,'這對鋼筋採購成本有何影響？');
  assert.equal(mobile.elem('chat-next-suggestion').hidden,true);
  const desktop=await run(false,false); let prevented=false;
  assert(desktop.elem('chat-input').placeholder.includes('按 Tab'));
  assert.equal(desktop.elem('chat-next-suggestion').hidden,true);
  desktop.elem('chat-input').handlers.keydown({key:'Tab',shiftKey:false,isComposing:false,preventDefault(){prevented=true;}});
  assert(prevented); assert.equal(desktop.elem('chat-input').value,'這對鋼筋採購成本有何影響？');
  let typedPrevented=false;
  desktop.elem('chat-input').handlers.keydown({key:'Tab',shiftKey:false,isComposing:false,preventDefault(){typedPrevented=true;}});
  assert.equal(typedPrevented,false); // Tab does not overwrite a draft or trap focus.
  const fallback=await run(true,false,true);
  assert.equal(fallback.elem('chat-next-suggestion').hidden,false);
  assert(fallback.elem('chat-next-suggestion').textContent.includes('資料有哪些重點'));
  console.log('Batched evidence, partial failure reporting, mobile suggestion, fallback and desktop Tab passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
