/* One explicit click, one live question; research launch remains separate. */
(function(){
'use strict';
const P=window.SagePlanner,$=id=>document.getElementById(id),STORAGE='sage-research-plan-v2';
let draft=P.fresh(),loaded=false,busy=false,error='',generation=0;
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const save=()=>{try{sessionStorage.setItem(STORAGE,JSON.stringify(draft));}catch(_){}};
function button(text,fn,cls){const b=el('button',text,cls);b.type='button';b.onclick=fn;return b;}
function review(){
 if(draft.current&&(draft.choice||draft.custom.trim()))P.answer(draft);
 draft.phase='review';draft.pending=null;generation++;busy=false;
 if(!draft.finalTopic)draft.finalTopic=P.compile(draft);
 save();$('planner').hidden=true;$('launch-form').hidden=false;$('topic').value=draft.finalTopic;$('live-consent').checked=false;
 $('plan-summary').textContent=draft.mode==='direct'?'直接开始：请确认 Topic 和研究预算。':'已整理 '+draft.turns.length+' 轮原始问答；可编辑后再开始研究。追问不会自动启动研究。';
 $('topic').focus();
}
async function next(retry=false){
 if(busy)return;
 if(draft.turns.length>=P.MAX_TURNS)return review();
 draft.mode='guided';draft.phase='questions';error='';busy=true;
 if(!draft.pending||retry)draft.pending={request_id:crypto.randomUUID(),seed:draft.seed,turns:draft.turns.map(t=>({...t})),allow_live:true};
 const payload=draft.pending,epoch=++generation;save();render();
 try{
  const headers={'Content-Type':'application/json'};
  if(!window.SageTeamMode){const token=sessionStorage.getItem('sage-console-token');if(token)headers.Authorization='Bearer '+token;}
  const response=await fetch('/api/planning/next',{method:'POST',headers,body:JSON.stringify(payload)});
  const data=await response.json();if(!response.ok)throw Error(data.error||'模型追问暂时不可用');
  if(epoch!==generation)return;P.accept(draft,data);save();
 }catch(e){if(epoch!==generation)return;error=e.message||'连接中断，已有回答已保留。';}
 finally{if(epoch===generation){busy=false;render();$('planner-title').focus();}}
}
function render(){
 if(draft.phase==='review')return review();
 $('planner').hidden=false;$('launch-form').hidden=true;
 const root=$('planner-body');root.replaceChildren();
 $('planner-progress').textContent=draft.phase==='welcome'?'模型实时追问 · 可选':'已回答 '+draft.turns.length+' 轮 · 最多 '+P.MAX_TURNS+' 轮 · 可随时结束';
 if(draft.phase==='welcome'){
  $('planner-title').textContent='你想研究什么？我们一起想清楚';
  root.append(el('p','模型会结合你的 Topic 和每次回答，决定下一步问什么。问题和选项都会实时生成，也可以全程输入自己的想法。','subtle'));
  const label=el('label','大致方向 / 已有想法（可留空）');label.htmlFor='plan-seed';
  const input=el('textarea');input.id='plan-seed';input.rows=3;input.maxLength=2000;input.value=draft.seed;
  input.placeholder='例如：从模型内部机制解释 LLM 的数学创造力。';
  input.oninput=()=>{if(draft.seed!==input.value){draft=P.fresh();draft.seed=input.value;save();}};
  const actions=el('div',undefined,'planner-actions');
  actions.append(button('开始模型追问 →',()=>next(),'primary'),button('跳过追问，直接写 Topic',()=>{draft.mode='direct';draft.finalTopic='';review();}),button('没有想法，自由探索',()=>{draft=P.fresh();draft.mode='direct';review();}));
  root.append(label,input,actions,el('p','点击“开始模型追问”会将 Topic 和后续回答发送到已配置模型，产生少量 API 费用。每次追问一次调用；不会启动研究。','section-note'));return;
 }
 $('planner-title').textContent=busy?'模型正在结合你的回答思考下一问…':draft.current?.title||'继续梳理研究方向';
 root.append(el('p',draft.seed||'方向开放，由对话逐步明确。','planner-context'));
 if(draft.turns.length){const details=el('details');details.append(el('summary','查看前面 '+draft.turns.length+' 轮问答'));for(const t of draft.turns)details.append(el('p',t.question+'\n'+(t.skipped?'暂不确定':t.answer),'planner-recap'));root.append(details);}
 if(draft.summary)root.append(el('p','模型对当前方向的理解（供核对）：'+draft.summary,'planner-recap'));
 if(draft.ready)root.append(el('p','模型认为已有信息可以整理为初步 Topic。你可以结束，也可以继续深入。','subtle'));
 if(draft.current&&!busy){
  const q=draft.current;root.append(el('p',q.hint,'subtle'));
  const choices=el('div',undefined,'planner-options'),buttons=[];
  for(const o of q.options){const b=button('',()=>{draft.choice=draft.choice===o.id?'':o.id;for(const v of buttons)v.setAttribute('aria-pressed',String(v.dataset.choice===draft.choice));save();},'planner-option');b.dataset.choice=o.id;b.setAttribute('aria-pressed',String(o.id===draft.choice));b.append(el('strong',o.label),el('span',o.detail));buttons.push(b);choices.append(b);}
  const label=el('label','你的想法（可以不选上面的选项）');label.htmlFor='plan-custom';
  const custom=el('textarea');custom.id='plan-custom';custom.rows=3;custom.maxLength=1500;custom.value=draft.custom;custom.oninput=()=>{draft.custom=custom.value;save();};root.append(choices,label,custom);
 }
 const notice=el('p',error,'planner-error');notice.setAttribute('role','alert');root.append(notice);
 const actions=el('div',undefined,'planner-actions');
 if(!busy){
  actions.append(button(draft.turns.length?'← 修改上一条回答':'← 修改 Topic',()=>{P.back(draft);error='';save();render();}));
  if(draft.current)actions.append(button('暂不确定，跳过',()=>{P.answer(draft,true);next();}),button('回答并继续追问 →',()=>{try{P.answer(draft);next();}catch(e){error=e.message;render();}},'primary'));
  else actions.append(button(error?'重试模型追问':'继续模型追问',()=>next(Boolean(error)),'primary'));
 }
 actions.append(button('用已有回答整理 Topic',review,'planner-finish'));root.append(actions);
 if(busy)root.append(el('p','通常需要几秒到一分钟。也可以直接结束追问；已经发出的模型调用可能仍会计费。','section-note'));
}
$('topic').addEventListener('input',()=>{draft.finalTopic=$('topic').value;save();});
$('planner-reopen').onclick=()=>{draft.phase=draft.current||draft.turns.length?'questions':'welcome';draft.finalTopic='';error='';save();render();};
$('planner-download').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify({...draft,finalTopic:$('topic').value,research_started:false},null,2)],{type:'application/json'}));const a=el('a');a.href=url;a.download='research-plan.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
window.SagePlannerUI={open(){if(!loaded){try{draft=P.restore(sessionStorage.getItem(STORAGE)||sessionStorage.getItem('sage-research-plan-v1'));}catch(_){}loaded=true;}render();},reset(){generation++;busy=false;error='';draft=P.fresh();try{sessionStorage.removeItem(STORAGE);sessionStorage.removeItem('sage-research-plan-v1');}catch(_){}$('live-consent').checked=false;}};
})();
