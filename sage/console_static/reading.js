/* Read-only projections. Source fields stay intact; no model calls or invented claims. */
(function(root){
  const names = {
    problem:'研究问题',motivation:'研究动机',research_gap:'研究缺口',contribution:'拟议贡献',contributions:'拟议贡献',
    hypothesis:'核心假设',mechanism:'方法与机制',algorithm:'算法',implementation:'实现步骤',method:'方法',
    data:'数据来源',datasets:'任务与数据集',data_requirements:'数据要求',baselines:'对比 baseline',controls:'控制与消融',
    predictions:'可检验预测',falsification:'证伪条件',analysis_plan:'统计分析',statistics:'统计方案',power_analysis:'功效分析',
    estimand:'目标效应',sample_size:'样本量',compute_budget:'计算预算',resource_requirements:'资源要求',feasibility:'可行性',
    risks:'风险',known_limitations:'已知局限',limitations:'局限',evidence_gaps:'证据缺口',assumptions:'假设条件',definitions:'概念定义',
    closest_prior_art:'最接近的已有工作',source_ids:'引用来源',novelty_queries:'查新查询',counterexamples:'反例',alternative_explanations:'替代解释',
    variables:'变量与操作化',endpoints:'实验终点',primary_endpoint_ids:'主终点 ID',decision_rule:'判定规则',analysis:'分析方案',resources:'资源与停止规则',
    definition:'定义',encoding:'操作化',unit:'单位',metric:'指标',direction:'方向',role:'实验角色',variable_ids:'关联变量',
    contrast:'比较设计',support_if:'支持条件',reject_if:'否定条件',inconclusive_if:'不确定条件',
    shared_protocol:'所有候选共用的实验协议',shared_scientific_context:'共享科学边界',common_controls:'共同控制条件',
    decision_conventions:'共同判定约定',novelty_operationalization:'新颖性操作化',computational_envelope:'计算范围',
    evidence_policy:'证据使用规则',verification_boundary:'可验证边界',calibration_plan:'评审校准说明',
    origin:'候选来源谱系',status:'原始状态',disposition:'候选处置',rejection_reason:'未选取理由',
    schema_version:'格式版本',results:'文献报告结果',metrics:'评价指标',future_work:'后续问题',reproducibility:'复现信息'
  };
  const present=v=>v!==undefined&&v!==null&&v!==''&&(!(Array.isArray(v))||v.length>0)&&(!(v&&typeof v==='object'&&!Array.isArray(v))||Object.keys(v).length>0);
  const cleanId=v=>String(v||'candidate').replace(/[^a-z0-9_-]/gi,'_');
  function lead(v){
    if(typeof v!=='string')return '';
    // A complete opening sentence, explicitly labelled as an excerpt (never a generated summary).
    return v.match(/^.*?[。！？](?:\s|$)/s)?.[0]?.trim() || v.match(/^.*?[.!?](?=\s+[A-Z]|$)/s)?.[0]?.trim() || v;
  }
  function proposal(c,doc={},reading={}){
    const sections=[],used=new Set(['id','title']);
    const add=(id,title,hint,keys,extra=[])=>{
      const fields=keys.filter(k=>present(c[k])).map(k=>{used.add(k);return {key:k,label:names[k]||k,value:c[k],path:'candidate.'+k};});
      sections.push({id,title,hint,fields:[...fields,...extra]});
    };
    add('motivation','01 · 研究动机与问题','为什么值得做？已有研究还缺少什么？',['problem','motivation','research_gap','closest_prior_art']);
    add('hypothesis','02 · 核心假设与拟议贡献','想验证什么解释？什么观察会支持它？',['hypothesis','contribution','contributions','predictions']);
    add('method','03 · 算法与实现方案','方法如何工作？需要哪些关键步骤和操作？',['algorithm','implementation','method','mechanism','definitions','assumptions']);
    add('experiment','04 · 主实验与评价','在哪些数据和任务上，比较什么，测量什么？',['data','datasets','data_requirements','estimand','sample_size']);
    const protocol=c.protocol&&typeof c.protocol==='object'&&!Array.isArray(c.protocol)?c.protocol:{};
    const extra=(key,label)=>present(protocol[key])?{key,label,value:protocol[key],path:'candidate.protocol.'+key}:null;
    const ex=sections.at(-1);
    for(const [k,l] of [['hypothesis','主实验比较'],['primary_endpoint_ids','协议指定主终点'],['endpoints','实验终点表'],['variables','变量与操作化']]){const f=extra(k,l);if(f)ex.fields.push(f);}
    add('baselines','05 · Baseline、控制与消融','排除哪些更简单的解释？如何保证公平比较？',['baselines','controls','alternative_explanations','counterexamples']);
    add('decisions','06 · 分析与成败判据','如何分析结果？什么结果会推翻假设？',['analysis_plan','statistics','power_analysis','falsification'],[extra('decision_rule','协议判定规则'),extra('analysis','协议分析方案')].filter(Boolean));
    add('feasibility','07 · 资源、风险与研究边界','实施需要什么？哪些问题仍未解决？',['compute_budget','resource_requirements','feasibility','risks','known_limitations','limitations','evidence_gaps'],[extra('resources','协议资源要求')].filter(Boolean));
    add('sources','08 · 文献依据与查新',['引用可用于定位来源；引用存在不等于主张已获证实。'].join(''),['source_ids','novelty_queries']);
    if(present(c.protocol)){
      used.add('protocol');
      const other=Object.fromEntries(Object.entries(protocol).filter(([k])=>!['hypothesis','primary_endpoint_ids','endpoints','variables','decision_rule','analysis','resources'].includes(k)));
      if(present(other)||typeof c.protocol!=='object')sections.push({id:'protocol-other',title:'协议补充',fields:[{label:'其余协议字段',path:'candidate.protocol',value:Object.keys(protocol).length?other:c.protocol}]});
    }
    const rest=Object.fromEntries(Object.entries(c).filter(([k])=>!used.has(k)));
    if(present(rest))sections.push({id:'metadata',title:'版本、处置与补充记录',secondary:true,fields:[{label:'原始附加字段',path:'candidate',value:rest}]});
    const shared=['shared_protocol','shared_scientific_context'].filter(k=>present(doc[k])).map(k=>({key:k,label:names[k],path:k,value:doc[k]}));
    if(shared.length)sections.push({id:'shared',title:'共同实验约定',hint:'下列内容适用于整份候选文档；保留原文，不自动覆盖候选自己的协议。',fields:shared,secondary:true});
    for(const s of sections){const part=reading.sections?.[s.id];if(part&&typeof part.text==='string')s.editorial=part;}
    return {id:c.id,title:c.title||c.hypothesis||'未命名候选',status:c.disposition||c.status||'未提供',sections,
      story:[['研究缺口',c.problem||c.motivation],['核心思路',c.mechanism||c.method||c.hypothesis],['验证路径',protocol.hypothesis?.contrast||c.estimand||c.falsification]].map(([label,v])=>({label,text:lead(v)})),raw:c};
  }
  const categories=[['problem','研究问题'],['motivation','研究动机'],['method','方法与算法'],['data','实验数据'],['baselines','对比方法'],['metrics','评价指标'],['results','文献报告结果'],['assumptions','成立条件'],['limitations','局限'],['reproducibility','复现信息'],['future_work','后续研究']];
  function evidence(card){
    const claims=[...(card.claims||[]).map(c=>({...c,bucket:'claims'})),...(card.unverified_claims||[]).map(c=>({...c,bucket:'unverified_claims'}))];
    const known=new Set(categories.map(c=>c[0]));
    const defs=[...categories,...[...new Set(claims.map(c=>c.category||'other'))].filter(k=>!known.has(k)).map(k=>[k,names[k]||k])];
    return defs.map(([key,title])=>({key,title,claims:claims.filter(c=>(c.category||'other')===key).map(c=>({
      ...c,verdict:c.entailment_audit?.verdict||(c.bucket==='unverified_claims'?'uncertain':'not_checked'),
      sources:(c.source_span_ids||[]).map(id=>({id,span:card.source_spans?.[id]||null}))
    }))}));
  }
  function lines(value,level=0){
    if(Array.isArray(value))return value.map(v=>typeof v==='object'?lines(v,level):'- '+String(v)).join('\n\n');
    if(value&&typeof value==='object')return Object.entries(value).map(([k,v])=>`${'#'.repeat(Math.min(level+4,6))} ${names[k]||k}\n\n${lines(v,level+1)}`).join('\n\n');
    return String(value??'未提供');
  }
  function markdown(view,context={}){
    return `# ${view.title}\n\n候选：${view.id} · 状态：${view.status}\n\n运行：${context.run||'未提供'}\n版本：${context.version||'当前所选文档'}\n\n本文件是已有科学字段的结构化阅读版，不新增科学结论。未提供的内容保留缺口；计划中的实验不代表已执行。\n\n`+
      view.sections.map(s=>`## ${s.title}\n\n${s.hint||''}\n\n`+(s.editorial?`### 中文阅读整理（非新增研究结果）\n\n${s.editorial.text}\n\n整理依据：${s.editorial.source_fields.join(', ')}\n\n`:'')+(s.fields.length?s.fields.map(f=>`### ${f.label}\n\n${lines(f.value)}\n\n来源字段：${f.path}`).join('\n\n'):'原稿未单列，待补充。')).join('\n\n');
  }
  const api={proposal,evidence,markdown,names,present,lead,cleanId};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.SageReading=api;
})(globalThis);
