/* Presentation only: all source content enters the DOM through textContent. */
(function(root){
  const R=root.SageReading;
  const n=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
  const details=(title,child)=>{const d=n('details');d.append(n('summary',title),child);return d;};
  function value(v){
    const out=n('div',undefined,'reading-value');
    if(Array.isArray(v)){
      if(v.length&&v.every(x=>x&&typeof x==='object'&&!Array.isArray(x))){
        const keys=[...new Set(v.flatMap(x=>Object.keys(x)))];
        // Endpoint/variable records are directly comparable; heterogeneous records stay in blocks.
        if(keys.length<=9){const wrap=n('div',undefined,'table-wrap'),table=n('table'),head=n('tr');keys.forEach(k=>head.append(n('th',R.names[k]||k)));table.append(head);
          for(const row of v){const tr=n('tr');for(const k of keys){const td=n('td');td.append(value(row[k]));tr.append(td);}table.append(tr);}wrap.append(table);out.append(wrap);return out;}
      }
      const ul=n('ul');v.forEach(x=>{const li=n('li');li.append(value(x));ul.append(li);});out.append(ul);return out;
    }
    if(v&&typeof v==='object'){
      const dl=n('dl',undefined,'reading-definitions');for(const [k,x]of Object.entries(v)){dl.append(n('dt',R.names[k]||k));const dd=n('dd');dd.append(value(x));dl.append(dd);}out.append(dl);return out;
    }
    if(typeof v==='string'){
      // Retain exact words. Paragraphs and numbered baseline entries become readable blocks.
      const parts=v.split(/\n\s*\n|;\s+(?=B\d+\s)|(?<=\.)\s+(?=B\d+\s)/).filter(Boolean);
      parts.forEach(p=>out.append(n('p',p)));return out;
    }
    out.append(n('p',String(v??'未提供')));return out;
  }
  function field(f,original=false){
    const box=n('div',undefined,'reading-field');box.append(n('h4',f.label));
    if(f.key==='endpoints'&&Array.isArray(f.value)){
      const primary=f.value.filter(x=>['primary','主要评价项'].includes(x.role)),other=f.value.filter(x=>!['primary','主要评价项'].includes(x.role));
      if(primary.length)box.append(value(primary));else box.append(n('p','终点表未明确标记 primary，请核对协议指定的主终点。','reading-missing'));
      if(other.length)box.append(details('次要、探索性与其他终点 · '+other.length,value(other)));
    }else if(f.key==='variables')box.append(details('查看变量定义与编码',value(f.value)));
    else if(typeof f.value==='string'&&f.value.length>650&&!['baselines','controls'].includes(f.key)){
      const first=R.lead(f.value);box.append(n('p',first,'reading-lead'));
      if(first!==f.value)box.append(details('阅读完整论述',value(f.value)));
    }else box.append(value(f.value));
    if(original)box.append(n('small','来源：'+f.path,'reading-source'));return box;
  }
  function download(view,context,includeOriginal=false){
    const a=n('a');const url=URL.createObjectURL(new Blob([R.markdown(view,context,{includeOriginal})],{type:'text/markdown;charset=utf-8'}));
    a.href=url;a.download=`proposal-${R.cleanId(view.id)}${includeOriginal?'-with-protocol':''}.md`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  let serial=0;
  function proposal(candidate,doc={},context={}){
    const view=R.proposal(candidate,doc,context.reading||{}),prefix='proposal-'+(++serial)+'-',article=n('article',undefined,'card proposal');
    const top=n('header');top.append(n('span',`${view.id||'候选'} · RESEARCH PROPOSAL`,'id'),n('span',view.status,'badge'));article.append(top,n('h2',view.title));
    const tools=n('div',undefined,'reading-toolbar');const save=n('button','下载易读版 Proposal');save.onclick=()=>download(view,context);const full=n('button','下载含原始协议的完整版本');full.onclick=()=>download(view,context,true);tools.append(save,full,n('span','研究提案 · 实验状态请见运行记录','subtle'));article.append(tools);
    const story=n('section',undefined,'proposal-story');story.append(n('h3','故事线速览'),n('p','以下摘取各部分的开头，完整设计与判据见下文。','section-note'));
    for(const [i,s] of view.story.entries()){const key=['motivation','method','experiment'][i],brief=view.sections.find(x=>x.id===key)?.editorial;const item=n('div');item.append(n('b',s.label),n('p',brief?R.lead(brief.text):s.text||'原稿未单列，待补充。'));story.append(item);}article.append(story);
    const nav=n('nav',undefined,'proposal-nav');nav.setAttribute('aria-label','Proposal 章节');
    for(const s of view.sections){const a=n('a',s.title.replace(/^\d+ · /,''));a.href='#'+prefix+s.id;nav.append(a);}article.append(nav);
    if(view.terms.length)article.append(details('协议编号与术语对照（核查时展开）',value(view.terms.map(t=>({'协议编号':t.id,'类别':t.kind,'名称':t.name,'原文定义':t.definition})))));
    for(const s of view.sections){const body=n('section',undefined,'proposal-section');body.id=prefix+s.id;body.append(n('h3',s.title));if(s.hint)body.append(n('p',s.hint,'section-note'));
      const originals=n('div');
      if(s.fields.length)s.fields.forEach(f=>originals.append(field(f,true)));else originals.append(n('p','原稿未单列，待补充。','reading-missing'));
      if(s.editorial){const brief=n('div',undefined,'reading-editorial');brief.append(n('p','中文阅读整理 · 依据现有稿件','reading-source'),value(s.editorial.text));body.append(brief);}else if(s.readableFields.length)s.readableFields.forEach(f=>body.append(field(f)));else body.append(n('p','原稿未单列，待补充。','reading-missing'));
      body.append(details('核对完整原稿与协议编号',originals));
      if(s.secondary){const d=details(s.title,body);d.className='proposal-supplement';article.append(d);}else article.append(body);
    }
    article.append(details('核对原始候选 JSON',n('pre',JSON.stringify(candidate,null,2))));return article;
  }
  const verdicts={supported:'模型建议：有支持',unsupported:'模型建议：不支持',uncertain:'模型建议：不确定',not_checked:'尚未核查'};
  function evidence(card){
    const out=n('div',undefined,'evidence-reading'),scope=n('div',undefined,'reading-scope');
    scope.append(n('b','读取范围：'+(card.source_scope||'未记录')),n('span','文献作者的主张；模型支持核查不等于独立复现。'));out.append(scope);
    for(const group of R.evidence(card)){
      const section=n('section',undefined,'evidence-category');section.append(n('h3',group.title+' · '+group.claims.length));
      if(!group.claims.length)section.append(n('p','本卡未提取此类信息。','reading-missing'));
      for(const c of group.claims){const row=n('div',undefined,'evidence-claim');row.append(n('span',verdicts[c.verdict]||'核查状态：'+c.verdict,'evidence-verdict '+(Object.hasOwn(verdicts,c.verdict)?c.verdict:'not_checked')),n('p',c.claim||'原主张未提供'));
        const sources=n('div');for(const ref of c.sources){const p=n('div');p.append(n('p',ref.id,'reading-source'));if(ref.span){p.append(n('p',ref.span.heading||''),n('blockquote',ref.span.text||'原文段落未附带'));}else p.append(n('p','此快照未附带该原文位置。','reading-missing'));sources.append(p);}
        if(c.entailment_audit?.reason)sources.append(n('p','模型核查理由：'+c.entailment_audit.reason));
        row.append(details(`原文依据与核查 · ${c.sources.length} 处`,sources));section.append(row);
      }
      out.append(section);
    }
    if(R.present(card.inferences_unverified))out.append(details('未验证推断',value(card.inferences_unverified)));
    if(R.present(card.coverage))out.append(details('阅读覆盖与遗漏',value(card.coverage)));
    out.append(details('原始证据卡 JSON',n('pre',JSON.stringify(card,null,2))));return out;
  }
  root.SageReadingUI={proposal,evidence,value};
})(globalThis);
