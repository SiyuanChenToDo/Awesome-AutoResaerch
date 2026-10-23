/* Offline behavioral tests: branching, open questions, draft recovery and UI handoff. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const P = require('../sage/console_static/planner.js');
let d=P.fresh();
assert.match(P.compile(d),/尚未指定方向/);
assert.match(P.compile(d),/尚未确定/);
d.mode='direct';assert.equal(P.compile(d),P.FREE_TOPIC);
d.seed='my exact topic';assert.equal(P.compile(d),'my exact topic');
d.mode='guided';P.answer(d,'goal','mechanism','why?');
assert.match(P.question('focus',d.answers).title,/解释/);
P.answer(d,'focus','representation','do not assume internal access');
P.answer(d,'validation','alternative','');P.answer(d,'resources','api','');
let topic=P.compile(d);assert.match(topic,/do not assume internal access/);assert.match(topic,/不假定能读取内部激活/);
P.answer(d,'goal','method','');
assert.equal(d.answers.focus,undefined,'Changing an upstream choice invalidates dependent answers');
assert.equal(d.answers.validation,undefined);
assert.equal(d.answers.resources.choice,'api','Independent decisions survive');
assert.match(P.question('focus',d.answers).title,/瓶颈/);
P.answer(d,'focus','','custom-only answer <script>alert(1)</script>');
assert.match(P.compile(d),/custom-only answer/);
P.answer(d,'data','provided','');assert.match(P.compile(d),/未提供时先列为待补充/);
d.phase='questions';d.index=4;
assert.deepEqual(P.restore(JSON.stringify(d)),d);
assert.deepEqual(P.restore('{broken'),P.fresh());
assert.equal(P.restore(JSON.stringify({version:1,index:999,seed:4})).index,5);
const polluted=P.restore(JSON.stringify({version:1,answers:{goal:{choice:'arbitrary',text:'custom'},focus:{choice:'representation',text:'note'}}}));
assert.equal(polluted.answers.goal.choice,'');assert.equal(polluted.answers.focus.choice,'');
for(const goal of ['mechanism','method','evaluation','explore']){
 const s=P.fresh();P.answer(s,'goal',goal,'');
 for(const key of P.KEYS){const q=P.question(key,s.answers);assert.ok(q.options.length>=2 && q.options.length<=4);assert.equal(new Set(q.options.map(o=>o.id)).size,q.options.length);}
}

// Execute actual event handlers with a tiny DOM; no fetch is available by design.
function fixture(raw){
 const elements=new Map(),storage=new Map(raw?[["sage-research-plan-v1",raw]]:[]);
 function element(tag='div'){return {tag,children:[],dataset:{},attrs:{},hidden:false,value:'',textContent:'',checked:false,
  append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items},setAttribute(k,v){this.attrs[k]=v},focus(){},addEventListener(k,f){this['on'+k]=f},click(){this.onclick?.()}};}
 const get=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id)};
 const context=vm.createContext({window:{SagePlanner:P},document:{getElementById:get,createElement:element},sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},setTimeout(){},URL,Blob});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../sage/console_static/planner-ui.js'),'utf8'),context);
 function all(n){return [n,...n.children.flatMap(all)]}
 const nodes=()=>all(get('planner-body'));
 const click=text=>{const n=nodes().find(n=>n.tag==='button'&&n.textContent===text);assert.ok(n,`Button ${text}`);n.click();};
 const input=(id,value)=>{const n=nodes().find(n=>n.id===id);assert.ok(n);n.value=value;n.oninput();};
 return {get,nodes,click,input,storage,open:()=>context.window.SagePlannerUI.open(),reset:()=>context.window.SagePlannerUI.reset()};
}
let f=fixture();f.open();assert.equal(f.get('launch-form').hidden,true);
f.input('plan-seed','LLM creativity');f.click('帮我想清楚 →');
f.click('下一问 →');assert.ok(f.nodes().some(n=>n.textContent.includes('可以选一个选项')));
f.nodes().find(n=>n.dataset.choice==='mechanism').click();f.click('下一问 →');
assert.match(f.get('planner-title').textContent,/解释/);
f.input('plan-custom','my mechanism');f.click('下一问 →');
f.click('暂不确定，跳过');
f.nodes().find(n=>n.dataset.choice==='api').click();f.click('用已有回答整理 Topic');
assert.equal(f.get('launch-form').hidden,false);assert.equal(f.get('planner').hidden,true);
assert.match(f.get('topic').value,/my mechanism/);assert.equal(f.get('live-consent').checked,false);
f.get('topic').value='edited exact final topic';f.get('topic').oninput();
const reloaded=fixture(f.storage.get('sage-research-plan-v1'));reloaded.open();
assert.equal(reloaded.get('topic').value,'edited exact final topic','Manual edits survive reload');
reloaded.reset();reloaded.open();assert.equal(reloaded.get('launch-form').hidden,true);
f=fixture();f.open();f.click('没有想法，自由探索');assert.equal(f.get('topic').value,P.FREE_TOPIC);
assert.equal(f.get('live-consent').checked,false);
f=fixture();f.open();f.input('plan-seed','exact direct input');f.click('跳过规划，直接写 Topic');assert.equal(f.get('topic').value,'exact direct input');
f=fixture();f.open();f.click('帮我想清楚 →');for(let i=0;i<6;i++)f.click('暂不确定，跳过');
assert.equal(f.get('launch-form').hidden,false);assert.match(f.get('topic').value,/尚未确定/);
console.log('Research planner: branching, custom answers, skips, free exploration, recovery and launch handoff passed');
