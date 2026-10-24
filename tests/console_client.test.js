/* Deterministic delayed network responses; no HTTP or scientific execution. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function element(){return {children:[],textContent:'',hidden:false,append(...v){this.children.push(...v)},replaceChildren(...v){this.children=v;this.textContent=''},setAttribute(){}};}
const elements=new Map(), storage=new Map([['sage-console-run','B']]), pending=[];
const context=vm.createContext({document:{getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)},createElement:element,createTextNode:text=>({textContent:text}),hidden:false},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},location:{hash:'',pathname:'/'},history:{replaceState(){}},URLSearchParams,AbortController,setInterval(){},setTimeout,URL,console,fetch:(url,options)=>new Promise(resolve=>pending.push({url,options,resolve}))});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../sage/console_static/app.js'),'utf8'),context);
vm.runInContext("renderSummary=s=>{state.summary=s;$('run-title').textContent=s.id};renderSection=(tab,p)=>{$('content').textContent=p.marker}",context);
const tick=()=>new Promise(r=>setImmediate(r));
async function reply(request,data){request.resolve({ok:true,status:200,json:async()=>data});await tick();}
const take=url=>{const index=pending.findIndex(r=>r.url===url);assert.notEqual(index,-1,'Expected request '+url);return pending.splice(index,1)[0]};
const summary=id=>({id,status:'completed',counts:{},artifacts:[]});
(async()=>{
 await reply(take('/api/runs'),{runs:[{id:'A'},{id:'B'}],allow_live:false});
 assert.equal(vm.runInContext('state.id',context),'B','Restores selected run rather than the first row');
 await reply(take('/api/run?id=B'),summary('B'));
 await reply(take('/api/run?id=B&section=overview'),{marker:'B original'});
 vm.runInContext("selectRun('A')",context);const oldA=take('/api/run?id=A');
 assert.equal(elements.get('content').textContent,'','Clears previous content immediately');
 assert.equal(elements.get('run-title').textContent,'');
 vm.runInContext("selectRun('B')",context);const delayedB=take('/api/run?id=B');
 vm.runInContext("selectRun('A')",context);const newA=take('/api/run?id=A');
 assert.equal(oldA.options.signal.aborted,true);assert.equal(delayedB.options.signal.aborted,true);
 await reply(newA,summary('A'));const sectionA=take('/api/run?id=A&section=overview');
 await reply(oldA,{...summary('A'),id:'stale A'});await reply(delayedB,summary('B'));
 assert.equal(elements.get('run-title').textContent,'A','Even A→B→A cannot admit an earlier A response');
 await reply(sectionA,{marker:'A current'});assert.equal(elements.get('content').textContent,'A current');
 vm.runInContext("state.tab='reviews';refreshRun(true)",context);await reply(take('/api/run?id=A'),summary('A'));const reviews=take('/api/run?id=A&section=reviews');
 vm.runInContext("state.tab='events';refreshRun(true)",context);await reply(take('/api/run?id=A'),summary('A'));await reply(take('/api/run?id=A&section=events'),{marker:'events current'});
 await reply(reviews,{marker:'stale reviews'});assert.equal(elements.get('content').textContent,'events current');
 vm.runInContext('refreshRun(true)',context);const last=take('/api/run?id=A');vm.runInContext('showForm()',context);
 await reply(last,{...summary('A'),id:'stale after form'});assert.equal(elements.get('workspace').hidden,true);assert.equal(vm.runInContext('state.summary',context),null);
 assert.equal(storage.has('sage-console-run'),false);assert.equal(pending.length,0);
 vm.runInContext('refreshList(true)',context);const initialList=take('/api/runs');vm.runInContext('showForm()',context);
 await reply(initialList,{runs:[{id:'A'}],allow_live:true});
 assert.equal(elements.get('create').hidden,false,'A late initial run list cannot hide an interview');
 assert.equal(vm.runInContext('state.id',context),null);assert.equal(pending.length,0);
 vm.runInContext('refreshList(true)',context);await reply(take('/api/runs'),{runs:[{id:'A'}],allow_live:true});
 assert.equal(elements.get('create').hidden,false,'Delayed authentication must not initiate navigation after the user opened the form');
 assert.equal(pending.length,0);
 console.log('Console client: saved selection, run/tab races, and form cancellation passed');
})().catch(e=>{console.error(e);process.exitCode=1});
