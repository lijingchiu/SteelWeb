const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const handlers = {}, elements = {};
function element(id) {
  return elements[id] ||= {id, hidden:true, style:{}, offsetHeight:200, value:'', textContent:'', disabled:false, handlers:{},
    addEventListener(type, fn) {this.handlers[type]=fn;}, contains(node) {return node === this;}, focus() {}};
}
const form = element('selection-ask');
const selection = {isCollapsed:false, rangeCount:1, anchorNode:{nodeType:1,closest:()=>null}, focusNode:{nodeType:1,closest:()=>null},
  toString:()=> '鋼筋價格上漲'.repeat(500), getRangeAt:()=>({getBoundingClientRect:()=>({left:30,bottom:100})}), removeAllRanges() {this.isCollapsed=true;}};
let staged, submissions=0;
const document = {activeElement:null,getElementById:element, addEventListener(type,fn){handlers[type]=fn;},
  dispatchEvent(event){submissions++; staged=event.detail; event.detail.accepted=true;}};
const window = {innerWidth:1000,innerHeight:700,getSelection:()=>selection};
class CustomEvent {constructor(type, options){this.type=type;this.detail=options.detail;}}
class File {constructor(parts,name,options){this.name=name;this.type=options.type;this.size=parts[0].size;}}
const context={document,window,location:{href:'https://example.com/'},CustomEvent,File,URL,Date,setTimeout,clearTimeout,
  fetch:async()=>({ok:true,blob:async()=>({type:'image/png',size:100})})};
vm.runInNewContext(fs.readFileSync(require.resolve('../assets/selection-ask.js'),'utf8'),context);
(async()=>{
  handlers.pointerup({target:{}}); await new Promise(r=>setTimeout(r,130));
  assert.equal(form.hidden,true); assert.equal(element('selection-ask-trigger').hidden,false);
  assert(element('selection-ask-quote').textContent.length < 110);
  element('selection-ask-trigger').handlers.click();
  assert.equal(form.hidden,false);
  element('selection-ask-input').value='為什麼？';
  await form.handlers.submit({preventDefault(){}});
  assert.equal(staged.text,'鋼筋價格上漲'.repeat(500)); assert.equal(staged.question,'為什麼？'); assert.equal(submissions,1); assert(form.hidden);
  selection.isCollapsed=false; handlers.pointerup({target:{}}); await new Promise(r=>setTimeout(r,130));
  element('selection-ask-trigger').handlers.click();
  handlers.pointerup({target:element('selection-ask-close')}); element('selection-ask-close').handlers.click();
  await new Promise(r=>setTimeout(r,130)); assert(form.hidden); assert(element('selection-ask-trigger').hidden); assert(selection.isCollapsed);
  selection.isCollapsed=false; handlers.pointerup({target:{}}); await new Promise(r=>setTimeout(r,130));
  handlers.pointerdown({target:{},pointerType:'mouse'}); handlers.pointerup({target:{}}); await new Promise(r=>setTimeout(r,130));
  assert(form.hidden); assert(element('selection-ask-trigger').hidden); assert(selection.isCollapsed);
  const img = {nodeType:1,tagName:'IMG',src:'https://example.com/figure.png',closest:()=>null,getAttribute:()=> '價格走勢圖',getBoundingClientRect:()=>({left:10,bottom:100,width:200,height:100})};
  handlers.contextmenu({target:{closest:()=>img},preventDefault(){}});
  assert.equal(form.hidden,true); assert.equal(element('selection-ask-trigger').hidden,false); element('selection-ask-trigger').handlers.click(); await form.handlers.submit({preventDefault(){}});
  assert.equal(staged.file.type,'image/png'); assert.equal(staged.label,'價格走勢圖'); assert.equal(submissions,2);
  console.log('Selection: staged text and image, retained question, no automatic send passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
