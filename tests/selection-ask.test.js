const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const handlers = {}, elements = {};
function element(id) {
  return elements[id] ||= {id, hidden:true, style:{}, offsetHeight:200, value:'', textContent:'', disabled:false, handlers:{},
    addEventListener(type, fn) {this.handlers[type]=fn;}, contains(node) {return node === this;}, focus() {}};
}
const form = element('selection-ask');
let selectionText = '鋼筋價格上漲'.repeat(500), clearCount = 0, selectionRect = {left:30,right:130,top:80,bottom:100,width:100,height:20};
const selection = {isCollapsed:false, rangeCount:1, anchorNode:{nodeType:1,closest:()=>null}, focusNode:{nodeType:1,closest:()=>null},
  toString:()=>selectionText, getRangeAt:()=>({cloneRange:()=>({getBoundingClientRect:()=>selectionRect})}), removeAllRanges() {clearCount++;this.isCollapsed=true;}};
let staged, submissions=0, editId, markers=[];
const document = {activeElement:null,getElementById:element, addEventListener(type,fn){handlers[type]=fn;}, body:{appendChild(){}},
  createElement(){const button={style:{},hidden:false,handlers:{},addEventListener(t,fn){this.handlers[t]=fn;},setAttribute(){},remove(){this.removed=true;}}; markers.push(button); return button;},
  dispatchEvent(event){if(event.type==='steel:edit-selection') { editId=event.detail.id; return; } submissions++; staged=event.detail; event.detail.accepted=true;}};
const window = {innerWidth:1000,innerHeight:700,getSelection:()=>selection,addEventListener(){}};
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
  const firstId=staged.id; assert.equal(markers[0].textContent,'1'); markers[0].handlers.click(); assert.equal(editId,firstId);
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
  handlers['steel:selection-update']({detail:{ids:[staged.id]}}); assert(markers[0].removed); assert.equal(markers[1].textContent,'1');
  window.innerWidth=390; window.innerHeight=800; element('selection-ask-trigger').offsetHeight=44; element('selection-ask-trigger').offsetWidth=110;
  element('chat-fab').getBoundingClientRect = () => ({left:320,top:660,width:54,height:54});
  selectionRect={left:20,right:370,top:300,bottom:340,width:350,height:40};
  selection.isCollapsed=false; selectionText='原始選取內容';
  handlers.pointerup({target:{}}); await new Promise(r=>setTimeout(r,130));
  const trigger = element('selection-ask-trigger');
  assert.equal(parseInt(trigger.style.left,10),198,'mobile button is 12px left of the assistant');
  assert.equal(parseInt(trigger.style.top,10),665,'mobile button is vertically centered with the assistant');
  const beforeTouch=clearCount;
  handlers.pointerdown({target:{},pointerType:'touch'});
  assert.equal(clearCount,beforeTouch,'touching a selection handle must not clear the selection');
  assert.equal(selection.isCollapsed,false);
  selectionText='調整藍點之後的完整選取'; handlers['selectionchange']();
  await new Promise(r=>setTimeout(r,250));
  assert.equal(element('selection-ask-trigger').hidden,false);
  selectionRect={left:20,right:370,top:730,bottom:770,width:350,height:40};
  handlers['selectionchange'](); await new Promise(r=>setTimeout(r,250));
  assert.equal(parseInt(trigger.style.top,10),665,'mobile button stays next to the assistant as selection changes');
  selectionText='最後調整後的選取';
  element('selection-ask-trigger').handlers.pointerdown();
  element('selection-ask-trigger').handlers.click();
  await form.handlers.submit({preventDefault(){}});
  assert.equal(staged.text,'最後調整後的選取','the latest selection is staged even before the debounce completes');
  console.log('Selection: staged text and image, retained question, no automatic send passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
