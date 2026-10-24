/* Live model interview state. No authored question or option bank. */
(function(root) {
'use strict';
const FREE_TOPIC='请自主选择一个值得研究、可通过文献和有限资源检验的科学问题，探索候选方向，提出有来源依据的研究假说、最小实验与证伪条件。用户未指定领域和资源，请保留未知。';
const MAX_TURNS=12;
function fresh(){return {version:2,phase:'welcome',seed:'',turns:[],current:null,summary:'',ready:false,choice:'',custom:'',finalTopic:'',mode:'guided',pending:null};}
function validQuestion(q){return q&&typeof q.title==='string'&&q.title.length<=600&&typeof q.hint==='string'&&Array.isArray(q.options)&&q.options.length<=4&&q.options.every(o=>typeof o.id==='string'&&typeof o.label==='string'&&typeof o.detail==='string');}
function accept(d,r){if(!validQuestion(r.question)||typeof r.summary!=='string')throw Error('模型返回格式无效，请重试');d.current=r.question;d.summary=r.summary;d.ready=r.ready===true;d.choice='';d.custom='';d.pending=null;d.phase='questions';}
function answer(d,skip=false){
 if(!d.current)return;
 const o=d.current.options.find(o=>o.id===d.choice);
 const value=[o?o.label+(o.detail?'：'+o.detail:''):'',d.custom.trim()].filter(Boolean).join('\n');
 if(!skip&&!value)throw Error('可以选一个选项、写下想法，或选择“暂不确定，跳过”。');
 d.turns.push({question:d.current.title,answer:skip?'':value,skipped:skip});d.current=null;d.choice='';d.custom='';d.finalTopic='';d.pending=null;
}
function back(d){
 const t=d.turns.pop();d.pending=null;d.summary='';d.ready=false;d.finalTopic='';
 if(t){d.current={title:t.question,hint:'修改后，模型会根据新的上下文重新追问。',options:[]};d.choice='';d.custom=t.answer;d.phase='questions';}
 else {d.current=null;d.phase='welcome';}
}
function compile(d){
 if(d.mode==='direct')return d.seed.trim()||FREE_TOPIC;
 const history=d.turns.map((t,i)=>(i+1)+'. '+t.question+'\n用户回答：'+(t.skipped?'暂不确定，保持开放。':t.answer)).join('\n\n');
 return (d.seed.trim()||'尚未指定方向，请探索值得研究的问题。')+'\n\n【研究前对话 · 用户原始回答】\n'+(history||'尚无回答，研究范围保持开放。')+'\n\n请以上述用户回答为研究约束。未回答的问题、未提供的资源和材料保持未知；区分用户假说与已核实证据。输出有来源依据的 idea、实现方案、对照实验与证伪条件，不声称已执行实验。';
}
function restore(raw){
 const d=fresh();try{const s=JSON.parse(raw);if(!s)return d;
 if(typeof s.seed==='string')d.seed=s.seed.slice(0,2000);
 if(typeof s.finalTopic==='string')d.finalTopic=s.finalTopic.slice(0,20000);
 if(s.version!==2){d.phase=d.finalTopic?'review':'welcome';return d;}
 d.turns=Array.isArray(s.turns)?s.turns.slice(0,MAX_TURNS).filter(t=>typeof t.question==='string'&&typeof t.answer==='string'&&typeof t.skipped==='boolean'):[];
 d.current=validQuestion(s.current)?s.current:null;
 for(const k of ['summary','choice','custom'])if(typeof s[k]==='string')d[k]=s[k];
 d.ready=s.ready===true;d.mode=s.mode==='direct'?'direct':'guided';
 d.phase=['welcome','questions','review'].includes(s.phase)?s.phase:'welcome';
 d.pending=s.pending&&typeof s.pending.request_id==='string'?s.pending:null;
 }catch(_){}return d;
}
const api={FREE_TOPIC,MAX_TURNS,fresh,validQuestion,accept,answer,back,compile,restore};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.SagePlanner=api;
})(globalThis);
