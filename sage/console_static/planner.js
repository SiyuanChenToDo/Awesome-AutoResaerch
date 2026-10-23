/* Optional, local research interview. No model calls and no automatic launch.
 * Interaction principles inspired by RobMitt/grill-me-skill; original questions
 * and implementation for SAGE. See docs/research-console.md for provenance. */
(function(root) {
  'use strict';
  const FREE_TOPIC = '请自主选择一个值得研究、可通过文献和有限资源检验的科学问题，探索候选方向，并提出有来源依据的研究假说、最小实验方案与证伪条件。用户没有指定领域、数据或已有结论；这些保持开放，不应假定已获得任何数据、资源或实验结果。';
  const KEYS = ['goal', 'focus', 'data', 'resources', 'validation', 'boundary'];
  const option = (id, label, detail) => ({id, label, detail});
  function question(key, answers = {}) {
    const goal = answers.goal?.choice;
    const common = {
      goal: {title: '这次研究，你最希望弄清楚什么？', hint: '先确定贡献类型，后面的问题会随你的选择调整。', options: [
        option('mechanism', '解释一个现象为什么发生', '形成机制假说，区分因果解释与相关性。'),
        option('method', '改进一个现有方法', '明确瓶颈，并与公平预算下的强基线比较。'),
        option('evaluation', '判断一种能力或结论是否成立', '设计评测、复现、边界条件或反例。'),
        option('explore', '先发现值得研究的问题', '通过文献寻找缺口，暂不预设方法。')]},
      data: {title: '哪些材料必须成为研究的起点？', hint: '可在补充框写论文链接、数据版本或服务器上可读的路径。写下路径不代表材料已被读取。', options: [
        option('provided', '我有指定论文、数据或案例', '请补充名称、链接或路径；未提供时先列为待补充。'),
        option('public', '优先使用公开、可复核的材料', '先核实可用性、使用范围和数据版本。'),
        option('existing', '从现有方法或结果出发', '请补充基线、观察到的现象及其来源。'),
        option('search', '还没有材料，先检索确定', '由研究者寻找来源，并明确证据缺口。')]},
      resources: {title: '未来验证方案需要适应什么资源？', hint: '这里描述后续实验的资源；本次 idea 生成的调用和时间预算在最后单独设置。', options: [
        option('small', '先做小规模、低成本验证', '优先最小实验、公开小数据与轻量基线；不假定有 GPU。'),
        option('open', '可以操作开放权重模型', '可考虑激活分析或干预；具体模型、显存与预算待确认。'),
        option('api', '只能调用模型 API', '以可观测行为设计检验，不假定能读取内部激活。'),
        option('unknown', '资源还没确定', '给出最低配置和替代方案，再决定是否实施。')]},
      boundary: {title: '还有哪些边界或取舍要提前说清楚？', hint: '也可以直接写你不想做什么、希望保留什么，或当前最担心的问题。', options: [
        option('narrow', '先把一个小问题验证清楚', '控制范围，优先可复现和可解释。'),
        option('novel', '优先探索有新意的方向', '容忍更高的不确定性，但仍要核查已有工作。'),
        option('practical', '优先实际可用、便于实施', '明确应用条件、成本及与已有方法的差异。'),
        option('open', '暂不限制，保留多种路线', '让研究者比较取舍，不把未决项当作已确认。')]}
    };
    if (common[key]) return {key, ...common[key]};
    const branches = {
      mechanism: [
        {title: '关于这个现象，哪类解释最值得被检验？', hint: '可以先选一个假说方向；它还不是已知结论。', options: [
          option('representation', '内部表示或计算过程发生了变化', '设计可干预的机制假说，并注明观察能力的限制。'),
          option('search', '搜索、反馈或推理策略起了作用', '区分策略收益与额外计算预算。'),
          option('data', '训练数据或已有知识可以解释', '考虑记忆、重组与泛化之间的替代解释。'),
          option('competing', '先比较多个竞争解释', '让研究者提出能区分解释的最小检验。')]},
        {title: '什么证据会让你放弃这个机制解释？', hint: '提前考虑反证，避免只收集支持它的例子。', options: [
          option('intervention', '改变假定机制后，目标行为没有变化', '需要可行的干预及匹配对照；否则说明无法识别因果。'),
          option('alternative', '更简单的替代解释同样解释现象', '比较数据、预算、提示等竞争因素。'),
          option('transfer', '换任务或分布后预测不成立', '预先规定外推范围，报告失败条件。'),
          option('design', '请先设计能区分解释的检验', '暂不编造效应阈值或已完成的结果。')]}
      ],
      method: [
        {title: '现有方法最需要解决哪个瓶颈？', hint: '如果已有方法名称或测量结果，请直接补充。', options: [
          option('quality', '正确率、质量或任务完成率', '明确任务和强基线，避免泛泛声称更好。'),
          option('cost', '时间、算力或 API 成本', '比较相同质量或相同预算下的表现。'),
          option('robustness', '稳定性、泛化或失败恢复', '定义失败分布与边界案例。'),
          option('diagnose', '先诊断瓶颈，再决定改法', '不预先锁定算法或模型。')]},
        {title: '什么结果会说明这个改进不值得继续？', hint: '这是研究判断标准，不是要求必须得到正结果。', options: [
          option('baseline', '公平预算下不优于强基线', '把实现差异和额外资源排除在贡献之外。'),
          option('ablation', '移除新组件后表现基本不变', '检查改进是否来自所声称的组件。'),
          option('cost', '收益不足以抵消额外成本', '在方案中明确成本口径和实际价值。'),
          option('design', '先让研究者提出判断标准', '阈值和测量方式保持待定，实验前再冻结。')]}
      ],
      evaluation: [
        {title: '你更想检查哪一类结论？', hint: '补充具体能力、论文主张或已观察到的失败案例。', options: [
          option('reproduce', '已有结果能否被独立复现', '区分复现偏差与原结论错误。'),
          option('generalize', '能力能否迁移到新任务或分布', '考虑数据污染和难度匹配。'),
          option('counterexample', '结论在什么条件下失效', '寻找反例、负结果与适用边界。'),
          option('metric', '现有指标是否测到了目标能力', '检查指标与真实能力之间的关系。')]},
        {title: '怎样防止评测只印证预期结论？', hint: '选择一个最重要的对照，也可写自己的评价标准。', options: [
          option('heldout', '使用独立划分与污染检查', '将开发选择和确认性评价分开。'),
          option('controls', '加入强基线、负对照与反例', '让“没有该能力”的系统也参与比较。'),
          option('replicate', '跨条件重复并报告不确定性', '避免单个例子或幸运种子主导结论。'),
          option('design', '先提出合适的评价协议', '明确什么结果支持或反对原主张。')]}
      ],
      explore: [
        {title: '发现新问题时，你倾向从哪里切入？', hint: '不需要先有一个成熟 idea；也可以跳过。', options: [
          option('gap', '已有工作中尚未解释的现象', '寻找有证据支持的研究缺口。'),
          option('failure', '系统反复出现的失败或反例', '从具体问题提炼可检验假说。'),
          option('connection', '两个方向之间可能的联系', '核查联系是否已被研究，并限制外推。'),
          option('free', '让研究者自由比较多个方向', '按价值、证据和可行性说明取舍。')]},
        {title: '筛选方向时，什么能帮助你做决定？', hint: '尚无答案的部分会保留为开放问题。', options: [
          option('test', '有清楚的最小检验与失败条件', '能通过有限资源区分不同假说。'),
          option('evidence', '能找到可靠来源和可用材料', '来源不足时保留未知。'),
          option('value', '解决的问题有明确科学或实践价值', '避免只追逐指标变化。'),
          option('compare', '先给出比较与理由，再选择', '同时呈现新意、不确定性和实施成本。')]}
      ]
    };
    return {key, ...(branches[goal] || branches.explore)[key === 'focus' ? 0 : 1]};
  }
  function fresh() {return {version: 1, phase: 'welcome', seed: '', index: 0, answers: {}, finalTopic: '', mode: 'guided'};}
  function answer(draft, key, choice, text = '') {
    if (!KEYS.includes(key)) throw Error('Unknown planning question');
    const q = question(key, draft.answers);
    if (choice && !q.options.some(o => o.id === choice)) throw Error('Unknown option');
    const previous = draft.answers[key]?.choice;
    draft.answers[key] = {choice: choice || '', text: String(text).trim().slice(0, 1500)};
    if (key === 'goal' && previous !== choice) {
      delete draft.answers.focus;
      delete draft.answers.validation;
    }
    draft.finalTopic = '';
  }
  function decision(draft, key) {
    const a = draft.answers[key], q = question(key, draft.answers);
    const chosen = q.options.find(o => o.id === a?.choice);
    return [chosen ? `${chosen.label}。${chosen.detail}` : '', a?.text ? `用户补充：${a.text}` : ''].filter(Boolean).join('\n') || '尚未确定；由研究者提出备选并说明取舍。';
  }
  function compile(draft) {
    if (draft.mode === 'direct') return draft.seed.trim() || FREE_TOPIC;
    const seed = draft.seed.trim() || '尚未指定方向，请先检索并提出值得研究的问题。';
    return `${seed}\n\n【研究前规划 · 用户偏好与开放问题】\n` + KEYS.map(key => `${question(key, draft.answers).title}\n${decision(draft, key)}`).join('\n\n') +
      '\n\n请依据上述规划开展文献调研和 idea 生成；将用户假说与已核实证据分开。未确定的材料、资源与判断标准应列出备选及限制，不应补写成已确认事实。输出可追溯的研究假说、最小验证方案、替代解释与证伪条件。本轮交付为 idea 和实验协议，实际实验另行确认。';
  }
  function restore(raw) {
    const d = fresh();
    try {
      const saved = JSON.parse(raw);
      if (saved?.version !== 1) return d;
      d.seed = typeof saved.seed === 'string' ? saved.seed.slice(0, 2000) : '';
      d.mode = saved.mode === 'direct' ? 'direct' : 'guided';
      for (const key of KEYS) {
        const a = saved.answers?.[key];
        if (!a || typeof a.text !== 'string') continue;
        const choice = question(key, d.answers).options.some(o => o.id === a.choice) ? a.choice : '';
        answer(d, key, choice, a.text);
      }
      d.phase = ['welcome', 'questions', 'review'].includes(saved.phase) ? saved.phase : 'welcome';
      d.index = Number.isInteger(saved.index) ? Math.max(0, Math.min(KEYS.length-1, saved.index)) : 0;
      d.finalTopic = typeof saved.finalTopic === 'string' ? saved.finalTopic.slice(0, 20000) : '';
    } catch (_) { /* A corrupt/disabled browser draft must not block research. */ }
    return d;
  }
  const api = {KEYS, FREE_TOPIC, fresh, question, answer, decision, compile, restore};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SagePlanner = api;
})(globalThis);
