'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ids=['north_scrap_price','billet_price','fengxing_rebar_price','h_beam_price','csc_wire_rod_price','crude_steel_production'];
const names=['北部廢鋼大盤收購價','小鋼胚中級出廠價','豐興鋼筋盤價','東鋼H型鋼流通價','中鋼棒線盤價','臺灣粗鋼產量'];
const items=ids.map((id,i)=>({id,name:names[i],group:i===5?'production':'tw_steel',value:100+i,change:i-2,change_pct:i-2,period:'2026-10',freq:'月',unit:i===5?'萬噸':'元/公噸',history:[['2026-09',102],['2026-10',100+i]],source:'資料來源',source_url:'https://example.com'}));
items.push({id:'fx_usd_twd',name:'美元兌新台幣',group:'fx',value:32.84,period:'2026-11-05',freq:'日',unit:'新台幣/美元',history:[],source:'國泰世華銀行',source_url:'https://example.com/fx'});
const materials={items,groups:[{id:'tw_steel',name:'臺灣鋼材盤價'},{id:'production',name:'粗鋼產量'},{id:'fx',name:'匯率'}]};
const latest={taiwan_prices:Object.fromEntries(items.filter(x=>x.freq==='月').map(x=>[x.id,{value:x.value,mom_change:x.change}])),exchange_rate:{source:'國泰世華銀行',fetched_at:'2026-11-05T06:13:58+08:00',spot_buy:32.74,spot_sell:32.94,usd_twd:32.84,impact_on_steel:'台幣轉弱會增加成本。'}};
const elements = new Map();
const listeners = {};
function el(id) {
  if (!elements.has(id)) elements.set(id, {id, value:'', innerHTML:'', textContent:'', dataset:{}, offsetTop:0, offsetParent:null, tagName:'SECTION',
    classList:{add(){},remove(){},toggle(){}}, setAttribute(){}, removeAttribute(){}, querySelectorAll(){return []}, closest(){return null},
    getBoundingClientRect(){return {top:0}}});
  return elements.get(id);
}
const document = {documentElement:{scrollTop:0, scrollHeight:5000}, body:{scrollTop:0, classList:{add(){},remove(){}}}, getElementById:el, querySelector(){return null}, querySelectorAll(){return []}, addEventListener(type,fn){listeners[type]=fn}};
const window = {addEventListener(){}, scrollTo(){}, innerHeight:800, pageYOffset:0, matchMedia(){return {matches:false}}, SteelMaterialForecast:{baseline(){return {available:false,reason:'資料不足',points:0}}}};
const context={window,document,history:{},location:{hash:''},console,URL,Date,Intl,Number,Math,Set,Map,materials,latest,requestAnimationFrame:fn=>fn(),setTimeout(){}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(require.resolve('../assets/app.js'),'utf8'),context);
vm.runInContext('matState.analysis = latest; matState.data = materials;',context);
for(const id of ids) {
  const it=materials.items.find(x=>x.id===id), old=latest.taiwan_prices[id];
  assert(it && old, id);
  assert.equal(it.value,old.value,id+' value');
  assert.equal(it.change,old.mom_change,id+' monthly change');
  const row=context.matRow(it,Object.fromEntries(materials.groups.map(g=>[g.id,g])),true);
  assert(row.includes(context.materialMonthlyChange(it)), id+' absolute change visible');
  assert(row.includes('歷史走勢') && row.includes('參考資料'),id+' chart and source retained');
}
const exchange=materials.items.find(x=>x.id==='fx_usd_twd');
const markup=context.materialExchangeDetails(exchange,latest);
assert(markup.includes('即期買入 32.74') && markup.includes('即期賣出 32.94'));
assert(markup.includes('國泰世華銀行') && markup.includes('台幣轉弱'));
assert(markup.includes('取得時間'));
assert.equal(context.materialExchangeDetails({id:'other'},latest),'');
assert.equal(context.materialMonthlyChange({freq:'月',change:0,unit:'元'}),'較前月 0 元');
assert.equal(context.materialMonthlyChange({freq:'月',change:null,unit:'元'}),'');
context.goToAnchor('prices');
assert.equal(vm.runInContext('matState.group',context),'tw_steel');
assert.equal(vm.runInContext('matState.freq',context),'all');
assert(el('mat-list').innerHTML.includes('北部廢鋼大盤收購價'));
context.resetMaterialFilters();
assert.equal(vm.runInContext('matState.group',context),'all');
context.initNav();
let prevented=false;
const priceLink={dataset:{sec:'prices'},getAttribute:()=> '#prices'};
listeners.click({button:0,target:{closest:()=>priceLink},preventDefault(){prevented=true}});
assert(prevented && vm.runInContext('matState.group',context)==='tw_steel','報價 link opens steel group');
const materialsLink={dataset:{sec:'materials'},getAttribute:()=> '#materials'};
listeners.click({button:0,target:{closest:()=>materialsLink},preventDefault(){}});
assert.equal(vm.runInContext('matState.group',context),'all','行情 link restores all categories');
const html=fs.readFileSync(require.resolve('../index.html'),'utf8');
assert(!html.includes('id="prices"') && html.includes('href="#prices"') && html.includes('id="materials"'));
console.log('Materials consolidation: all six monthly changes, exchange details, price navigation and filter reset passed.');
