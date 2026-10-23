/* Browser-only optional interview; the existing launch form is the sole start. */
(function() {
  'use strict';
  const P = window.SagePlanner, $ = id => document.getElementById(id);
  const STORAGE = 'sage-research-plan-v1';
  let draft = P.fresh(), loaded = false;
  const el = (tag, text, cls) => {const n = document.createElement(tag); if(text !== undefined)n.textContent=text; if(cls)n.className=cls; return n;};
  function save() {try {sessionStorage.setItem(STORAGE, JSON.stringify(draft));} catch (_) {}}
  function button(text, action, cls) {const b=el('button',text,cls); b.type='button'; b.onclick=action; return b;}
  function focusTitle() {$('planner-title').focus();}
  function review() {
    draft.phase='review';
    if (!draft.finalTopic) draft.finalTopic=P.compile(draft);
    save(); $('planner').hidden=true; $('launch-form').hidden=false;
    $('topic').value=draft.finalTopic;
    $('live-consent').checked=false;
    $('topic').focus();
    $('plan-summary').textContent=draft.mode==='direct' ? '直接开始：可以修改 Topic，然后确认本轮预算。' :
      `已整理 ${P.KEYS.filter(k => draft.answers[k]?.choice || draft.answers[k]?.text).length} 项回答；未回答的部分保留开放。下方内容可以直接修改。`;
  }
  function render() {
    if (draft.phase==='review') return review();
    $('planner').hidden=false; $('launch-form').hidden=true;
    const root=$('planner-body'); root.replaceChildren();
    $('planner-progress').textContent=draft.phase==='welcome'?'可选 · 研究前规划':`问题 ${draft.index+1} / ${P.KEYS.length} · 可随时结束`;
    if (draft.phase==='welcome') {
      $('planner-title').textContent='先聊一聊，你想研究什么？';
      root.append(el('p','有一个模糊方向也可以。接下来逐个梳理目标、材料和验证方式；没有想法，也可以直接自由探索。','subtle'));
      const label=el('label','大致方向 / 已有想法（可留空）'); label.htmlFor='plan-seed';
      const input=el('textarea'); input.id='plan-seed'; input.rows=3; input.maxLength=2000; input.value=draft.seed;
      input.placeholder='例如：为什么 LLM 能产生数学创造力？我想从公开数学案例开始。';
      input.oninput=()=>{draft.seed=input.value; draft.finalTopic=''; save();};
      root.append(label,input);
      const actions=el('div',undefined,'planner-actions');
      actions.append(button('帮我想清楚 →',()=>{draft.mode='guided';draft.phase='questions';save();render();focusTitle();},'primary'),
        button('跳过规划，直接写 Topic',()=>{draft.mode='direct';draft.finalTopic=draft.seed;review();}),
        button('没有想法，自由探索',()=>{draft.mode='direct';draft.finalTopic=P.FREE_TOPIC;review();}));
      root.append(actions,el('p','这一步按你的选择分支提问，不调用模型 API。草稿仅保存在当前浏览器标签页；确认启动后 Topic 才会提交给研究团队。','section-note'));
      return;
    }
    const key=P.KEYS[draft.index], q=P.question(key,draft.answers), a=draft.answers[key]||{};
    $('planner-title').textContent=q.title;
    const context=draft.seed ? `围绕：${draft.seed}` : '方向尚未确定，先梳理你关心的问题。';
    root.append(el('p',context,'planner-context'),el('p',q.hint,'subtle'));
    if (draft.index>0) {
      const previous=P.KEYS[draft.index-1];
      root.append(el('p','上一项：'+P.decision(draft,previous),'planner-recap'));
    }
    const choices=el('div',undefined,'planner-options'); choices.setAttribute('role','group'); choices.setAttribute('aria-label','选择一个方向，也可以只填写自己的想法');
    let selected=a.choice||'';
    const optionButtons=[];
    const custom=el('textarea'); custom.id='plan-custom';custom.rows=3;custom.maxLength=1500;custom.value=a.text||'';
    function persist() {P.answer(draft,key,selected,custom.value);save();}
    for(const o of q.options) {
      const b=button('',()=>{selected=selected===o.id?'':o.id;for(const v of optionButtons)v.setAttribute('aria-pressed',String(v.dataset.choice===selected));persist();},'planner-option');
      b.dataset.choice=o.id;b.setAttribute('aria-pressed',String(o.id===selected));
      b.append(el('strong',o.label),el('span',o.detail));optionButtons.push(b);choices.append(b);
    }
    const label=el('label','写下自己的想法，或补充所选项（可不选上面的选项）');label.htmlFor='plan-custom';
    custom.placeholder='你的观察、疑问、具体材料，或者任何还没想清楚的地方…';custom.oninput=persist;
    root.append(choices,label,custom);
    const error=el('p','','planner-error');error.setAttribute('role','alert');
    const actions=el('div',undefined,'planner-actions');
    function next() {persist();if(draft.index===P.KEYS.length-1)return review();draft.index++;save();render();focusTitle();}
    actions.append(button(draft.index===0?'← 返回方向':'← 上一问',()=>{persist();if(draft.index===0)draft.phase='welcome';else draft.index--;save();render();focusTitle();}),
      button('暂不确定，跳过',()=>{selected='';custom.value='';next();}),
      button(draft.index===P.KEYS.length-1?'整理 Topic →':'下一问 →',()=>{if(!selected&&!custom.value.trim()){error.textContent='可以选一个选项、写下想法，或选择“暂不确定，跳过”。';return;}next();},'primary'),
      button('用已有回答整理 Topic',()=>{persist();review();},'planner-finish'));
    root.append(error,actions);
  }
  $('topic').addEventListener('input',()=>{draft.finalTopic=$('topic').value;save();});
  $('planner-reopen').onclick=()=>{draft.phase='welcome';save();render();focusTitle();};
  $('planner-download').onclick=()=>{
    const data={...draft,finalTopic:$('topic').value,kind:'research_planning_draft',research_started:false};
    const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    const a=el('a');a.href=url;a.download='research-plan.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  window.SagePlannerUI={open(){if(!loaded){try{draft=P.restore(sessionStorage.getItem(STORAGE));}catch(_){}loaded=true;}render();},
    reset(){draft=P.fresh();try{sessionStorage.removeItem(STORAGE);}catch(_){}$('live-consent').checked=false;}};
})();
