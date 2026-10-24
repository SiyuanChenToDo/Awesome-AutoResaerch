/* Behavioral tests of the live interview; no real model requests. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const P=require('../sage/console_static/planner.js');
const reply=(title='针对你的数学构造任务，模型内部哪个环节最想解释？')=>({question:{title,hint:'决定可检验的机制对象',options:[{id:'0',label:'关系表示重组',detail:'在开放权重模型上观察并干预'}]},summary:'模型建议不应成为用户决定',ready:false});
let d=P.fresh();d.mode='direct';assert.equal(P.compile(d),P.FREE_TOPIC);
d.seed='exact topic';assert.equal(P.compile(d),'exact topic');d.mode='guided';P.accept(d,reply());d.custom='只做内部可干预量';P.answer(d);
assert.match(P.compile(d),/只做内部可干预量/);assert.doesNotMatch(P.compile(d),/模型建议不应成为用户决定/);
P.accept(d,reply('新问题'));P.answer(d,true);P.back(d);assert.equal(d.turns.length,1);assert.equal(d.current.title,'新问题');
assert.deepEqual(P.restore(JSON.stringify(d)),d);assert.deepEqual(P.restore('broken'),P.fresh());
assert.equal(P.restore(JSON.stringify({version:1,finalTopic:'old edited topic'})).finalTopic,'old edited topic');
function fixture(raw){
 const elements=new Map(),storage=new Map(raw?[['sage-research-plan-v2',raw]]:[]),calls=[];
 function element(tag='div'){return {tag,children:[],dataset:{},attrs:{},hidden:false,value:'',textContent:'',checked:false,
 append(...v){this.children.push(...v)},replaceChildren(...v){this.children=v},setAttribute(k,v){this.attrs[k]=v},focus(){},addEventListener(k,f){this['on'+k]=f},click(){return this.onclick?.()}};}
 const get=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id)};
 const context=vm.createContext({window:{SagePlanner:P,SageTeamMode:true},document:{getElementById:get,createElement:element},
 sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},crypto:require('node:crypto').webcrypto,URL,Blob,setTimeout(){},
 fetch:(url,options)=>new Promise(resolve=>calls.push({url,body:JSON.parse(options.body),resolve}))});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../sage/console_static/planner-ui.js'),'utf8'),context);
 const all=n=>[n,...n.children.flatMap(all)],nodes=()=>all(get('planner-body'));
 const click=text=>{const n=nodes().find(n=>n.tag==='button'&&n.textContent===text);assert.ok(n,text);return n.click()};
 const input=(id,value)=>{const n=nodes().find(n=>n.id===id);assert.ok(n,id);n.value=value;n.oninput()};
 return {get,nodes,click,input,calls,storage,open:()=>context.window.SagePlannerUI.open(),reset:()=>context.window.SagePlannerUI.reset()};
}
const flush=()=>new Promise(r=>setImmediate(r));
(async()=>{
 let f=fixture();f.open();assert.equal(f.calls.length,0);
 f.input('plan-seed','LLM 数学创造力');const first=f.click('开始模型追问 →');
 assert.equal(f.calls.length,1);assert.equal(f.calls[0].url,'/api/planning/next');assert.equal(f.calls[0].body.seed,'LLM 数学创造力');
 f.calls[0].resolve({ok:true,json:async()=>reply()});await first;
 assert.match(f.get('planner-title').textContent,/数学构造/);
 f.input('plan-custom','只有 API，无法读取激活');f.click('回答并继续追问 →');
 assert.equal(f.calls.length,2);assert.equal(f.calls[1].body.turns[0].answer,'只有 API，无法读取激活');
 f.calls[1].resolve({ok:true,json:async()=>reply('既然只有 API，是否先做行为假设并保留内部因果未知？')});await flush();
 assert.match(f.get('planner-title').textContent,/只有 API/);
 f.click('← 修改上一条回答');assert.equal(f.nodes().find(n=>n.id==='plan-custom').value,'只有 API，无法读取激活');
 f.input('plan-custom','现在可以访问开放权重模型');f.click('回答并继续追问 →');
 assert.equal(f.calls[2].body.turns.length,1);assert.match(f.calls[2].body.turns[0].answer,/开放权重/);
 f.calls[2].resolve({ok:false,json:async()=>({error:'provider unavailable'})});await flush();
 assert.ok(f.nodes().some(n=>n.textContent==='provider unavailable'));assert.equal(f.calls.length,3,'no automatic retry');
 f.click('重试模型追问');assert.notEqual(f.calls[3].body.request_id,f.calls[2].body.request_id);
 f.click('用已有回答整理 Topic');const final=f.get('topic').value;
 f.calls[3].resolve({ok:true,json:async()=>reply('late question')});await flush();
 assert.equal(f.get('launch-form').hidden,false);assert.equal(f.get('topic').value,final,'late reply cannot overwrite review');
 assert.match(final,/现在可以访问开放权重模型/);assert.doesNotMatch(final,/provider unavailable|模型建议不应/);
 assert.equal(f.get('live-consent').checked,false);
 f.get('topic').value='edited exact final topic';f.get('topic').oninput();
 const reload=fixture(f.storage.get('sage-research-plan-v2'));reload.open();assert.equal(reload.get('topic').value,'edited exact final topic');assert.equal(reload.calls.length,0);
 f=fixture();f.open();f.click('没有想法，自由探索');assert.equal(f.get('topic').value,P.FREE_TOPIC);assert.equal(f.calls.length,0);
 f=fixture();f.open();f.input('plan-seed','direct');f.click('跳过追问，直接写 Topic');assert.equal(f.get('topic').value,'direct');assert.equal(f.calls.length,0);
 f=fixture();f.open();f.click('开始模型追问 →');const saved=f.storage.get('sage-research-plan-v2');const restored=fixture(saved);restored.open();assert.equal(restored.calls.length,0);
 restored.click('继续模型追问');assert.equal(restored.calls[0].body.request_id,f.calls[0].body.request_id,'refresh reuses in-flight request ID');
 console.log('Live planner: dynamic context, edits, errors, manual retries, stale responses, refresh and free exploration passed');
})().catch(e=>{console.error(e);process.exitCode=1});
