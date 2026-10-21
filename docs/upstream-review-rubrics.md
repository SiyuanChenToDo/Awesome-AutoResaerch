# 原版评审量表、SAGE 接线与迁移边界

原项目确实有 rubric，不能把它们笼统说成“没有评分标准”。SAGE 的旧模块化流程已经移植 CoI 的配对比较和 Agent Laboratory 的成稿加权量表；早期 native autonomous 猜想评分却采用了另写的整体 0–1 提示，没有复用这些标准，也遗漏了 ARIS 七维量表及其校准依赖。CORAL 管理器和 TaskGrader 的真实接入，不等于采用了 CORAL 附带的 rubric judge 实现。

本文依据冻结版本的实际源码和调用路径，区别原版规则、选择性移植和 SAGE 新增设计。不包含私有科研候选、论文内容、API 响应或运行凭据；也不把源码检查称为新的 live 验证。

## 四个来源分别评什么

| 来源 | 原版维度 / 标准 | 原版尺度与汇总 | 使用阶段 | 早期 SAGE 接线 / 漏接 |
|---|---|---|---|---|
| CoI-Agent | Idea 的 novelty、significance、feasibility、clarity、effectiveness；代码额外读取 relevance，但原提示缺此项 | 每维左胜 / 右胜 / 平局；所有有序候选对等权累加，胜者 +1，平局各 +0.5 | 多个 idea 的相对选择 | 旧 `Review.rank` 已移植，并补 relevance 输出；native 猜想路径没有调用它 |
| Agent Laboratory | 七项 1–4 质量维度、Overall 1–10、Confidence 1–5；另有实验代码评分 | 论文归一化后按固定权重计算 0–10 上界的综合分；代码是另一条 0–1 模型评分 | 有结果的完整论文；执行后的代码与输出 | 旧报告流程保留论文维度与公式；没有把三 reviewer persona 包装移入 native 猜想评分 |
| ARIS | `research-refine` 七维及固定权重；另有查新、定性研究评阅和通用修订循环 | 七维各 1–10，加权；READY 另有约束；校准有 / 无必须明示 | 方法方案细化与研究评阅 | 原文研究技能已交付，但七维本体与 taste-calibration 没进入早期 native 正式评分服务 |
| CORAL | 由任务作者配置的静态条目，或裁判演进的动态条目；不是通用科研创新量表 | 每条 PASS=1 / FAIL=0，按权重求通过比例；动态版记录 rubric 版本 | 开放产物的任务裁判基础设施 | 原生管理器、会话、TaskGrader 已接；两个示例 rubric judge 未被实例化 |

以上分数含义不同，不能把配对票数、代码评分、提案成熟度和论文接收建议互换，也不能乘以 10 就称其为同一量表。

## 1. CoI：配对比较，不是真正的 Elo

来源：[DAMO-NLP-SG/CoI-Agent](https://github.com/DAMO-NLP-SG/CoI-Agent)，固定提交 `ac94317ff2d1997f362747edc2c9e5f0fdc9c450`。本地原始快照及逐文件校验值在 [manifest](../third_party/coi_agent/manifest.json)。

原 [idea judge 提示，第14–35行](https://github.com/DAMO-NLP-SG/CoI-Agent/blob/ac94317ff2d1997f362747edc2c9e5f0fdc9c450/prompts/juder_prompts.py#L14-L35)包含：

| 原维度 | 判断内容的中文释义 |
|---|---|
| Novelty | 问题、方法或组合是否新；与已有工作区别是否清楚 |
| Significance | 问题是否重要，别人是否会使用或继续研究 |
| Feasibility | 现有技术能否实现，逻辑和实验设计是否合理 |
| Clarity | 表述、组织是否清楚，信息是否足够 |
| Effectiveness | 相比已有基线，预期是否有效 |

每项 `0` 表示左侧胜，`1` 表示右侧胜，`2` 表示平局。原提示要求避免位置和篇幅偏见。

实际调用：[agents.py，第203–230行](https://github.com/DAMO-NLP-SG/CoI-Agent/blob/ac94317ff2d1997f362747edc2c9e5f0fdc9c450/agents.py#L203-L230)。它枚举所有有序候选对，胜者每维加 1，平局各加 0.5，最后取最大值。虽然变量叫 `elo_scores`，没有预期胜率、K 值或 Elo 评级更新，因此应称配对票数汇总。

**原版存在五维提示与六维解析不一致。** [agents.py，第28–38行](https://github.com/DAMO-NLP-SG/CoI-Agent/blob/ac94317ff2d1997f362747edc2c9e5f0fdc9c450/agents.py#L28-L38)还解析 relevance；原提示没有此标签。[utils.py，第15–25行](https://github.com/DAMO-NLP-SG/CoI-Agent/blob/ac94317ff2d1997f362747edc2c9e5f0fdc9c450/utils.py#L15-L25)默认在标签缺失时返回整段响应，通常无法转换整数，最后被当作平局。SAGE 补充了 relevance 输出说明并严格校验六维值，不应为了原样复制而恢复这个缺陷。

新颖性筛查是另一条路径：[check_novel，第467–493行](https://github.com/DAMO-NLP-SG/CoI-Agent/blob/ac94317ff2d1997f362747edc2c9e5f0fdc9c450/agents.py#L467-L493)检索近邻，再询问模型是否相似。原版空检索直接判 novel。SAGE 将空检索记为 `not_established`，这是明确的行为纠正。

原 [实验比较提示，第40–68行](https://github.com/DAMO-NLP-SG/CoI-Agent/blob/ac94317ff2d1997f362747edc2c9e5f0fdc9c450/prompts/juder_prompts.py#L40-L68)还有 feasibility / quality / clarity 三维，但保存的主流程没有调用它。实际方案改进走文字建议；有 prompt 定义不能等同于执行过该评分阶段。

**建议提示与执行要区分。** 原 `prompts/review_agent_prompts.py` 的文献建议提示要求结合相关论文提高新颖性、可行性，尽量不增加复杂度；`agents.py:81–91` 定义 `get_suggestions_from_papers`，但固定提交中没有调用该函数。原实际实验迭代调用 `review_experiment`，其提示约束只改实验、不要改变原 idea。SAGE 旧模块的 `Review.literature_suggestions` 确实由实验方案流程调用；原生入口则使用自己的 `review_prompt`，新增的建议核查与主张级反馈见[新颖性裁判](novelty-judge.md)。不能将上游存在模板当成已运行“打分后自动提升 idea”的证据。

SAGE 旧调用路径为 [orchestration](../sage/orchestration/__init__.py) → [Review.rank](../sage/review/__init__.py) → [配对提示](../sage/review/prompts.py)。它提供相对排序，不提供已校准的绝对科研质量。

## 2. Agent Laboratory：代码和成稿使用两条不同标准

来源：[SamuelSchmidgall/AgentLaboratory](https://github.com/SamuelSchmidgall/AgentLaboratory)，固定提交 `d9017d90e329112d2a80b7712f37ee9094d2cd27`。[本地 manifest](../third_party/agent_laboratory/manifest.json)明确只保存所选原始文件，不是完整可运行的上游 checkout。

### 完整论文量表

原 [agents.get_score，第58–135行](https://github.com/SamuelSchmidgall/AgentLaboratory/blob/d9017d90e329112d2a80b7712f37ee9094d2cd27/agents.py#L58-L135)输入计划与 LaTeX 论文，要求以下评分：

| 原字段 | 范围 | 判断内容 | 汇总权重 |
|---|---:|---|---:|
| Originality | 1–4 | 任务、方法、组合和相对已有工作的原创性 | 0.1 |
| Quality | 1–4 | 技术正确性、方法适当性、证据与工作完整性 | 0.1 |
| Clarity | 1–4 | 写作、组织、理解与复现所需的信息 | 0.1 |
| Significance | 1–4 | 问题与结果的重要性、可使用和扩展性 | 0.1 |
| Soundness | 1–4 | 技术主张和实验方法是否有证据支撑 | 0.1 |
| Presentation | 1–4 | 表达及相对相关工作的定位 | 0.2 |
| Contribution | 1–4 | 对领域的总体贡献 | 0.4 |
| Overall | 1–10 | 从极强拒绝到获奖级的总体接收建议 | 1.0 |
| Confidence | 1–5 | 审稿人对相关工作、数学和细节的把握 | 0.1 |

还输出摘要、优缺点、问题、局限、伦理标记和 Accept / Reject。Overall 的关键锚点为 3=Reject、4=Borderline Reject、5=Borderline Accept、6=Weak Accept、7=Accept、8=Strong Accept；完整定义见上游源码。

原 [加权计算，第151–176行](https://github.com/SamuelSchmidgall/AgentLaboratory/blob/d9017d90e329112d2a80b7712f37ee9094d2cd27/agents.py#L151-L176)：

```text
paper_score = 10 × Σ(weight[d] × rating[d] / scale_max[d]) / 2.2
```

最高为 10；因为所有维度最低均为 1，最低约为 1.795，并非从 0 开始的均匀量尺。Confidence 进入总分、Overall 与其他字段重叠，都是原算法的特点；保留来源不等于证明其已校准。Overall 的接收文字锚点也不等于加权总分的硬阈值。

SAGE 在 [review/report.py](../sage/review/report.py)保留尺度与公式，由 [writing/report.py](../sage/writing/report.py)调用，并明确标为未独立验证的模型意见。这里的正文提示是 SAGE 重写，不能称逐字复制原评审表。完整论文标准依赖已有结果和证据，不能直接给尚无实验的猜想打发表分。

### 三位 reviewer 的真实含义

原 [ReviewersAgent，第184–201行](https://github.com/SamuelSchmidgall/AgentLaboratory/blob/d9017d90e329112d2a80b7712f37ee9094d2cd27/agents.py#L184-L201)调用同一个模型三次，分别强调实验洞见、领域影响和新颖性。返回三份结果组成的字符串，没有均值、投票或共识计算。

原 [PaperSolver 编辑评分，第433–455行](https://github.com/SamuelSchmidgall/AgentLaboratory/blob/d9017d90e329112d2a80b7712f37ee9094d2cd27/papersolver.py#L433-L455)直接调用一次 `get_score`，不是每次编辑都使用三 reviewer。SAGE 旧 `review_report` 也是单次评阅；不能把多个生成者、多个视角和独立裁判混称为一项能力。

### 实验代码评分

原 [mlesolver.get_score，第141–160行](https://github.com/SamuelSchmidgall/AgentLaboratory/blob/d9017d90e329112d2a80b7712f37ee9094d2cd27/mlesolver.py#L141-L160)输入计划、代码、输出，让模型给 0–1 分，判断是否遵循计划并得到合适输出，没有上述论文分项或权重。SAGE 的 [execution](../sage/execution/)保留生成、编辑、修复思路，采用冻结合同的实际指标，而没有把 LLM 的输出判断当成实验测量。

## 3. ARIS：七维方法细化，以及必须公开的校准状态

来源：[wanshuiyin/Auto-claude-code-research-in-sleep](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep)，固定提交 `15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee`。

原 [research-refine，第362–400行](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee/skills/research-refine/SKILL.md#L362-L400)：

| 原维度 | 权重 | 检查什么 |
|---|---:|---|
| Problem Fidelity | 15% | 是否仍解决原始瓶颈，有无换成容易问题 |
| Method Specificity | 25% | 接口、表示、损失、训练和推理是否具体到可实施 |
| Contribution Quality | 25% | 是否有一个聚焦、简洁且有新意的机制贡献 |
| Frontier Leverage | 15% | 是否适当地利用当前手段，避免无意义模块堆叠 |
| Feasibility | 10% | 是否符合声明的资源和数据假设 |
| Validation Focus | 5% | 实验是否最少而足以验证核心主张 |
| Venue Readiness | 5% | 假如执行成功，贡献是否清楚、及时且适合目标场所 |

各维 **1–10**，综合分为上述权重的加权和。低于 7 分的轴必须提供具体弱点、方法层面的修复和 CRITICAL / IMPORTANT / MINOR 优先级。另报告精简机会、现代化机会、问题漂移和 READY / REVISE / RETHINK。

READY 要求总分至少 9、无明显问题漂移、一个聚焦的主贡献、无明显复杂度膨胀。**这是七维；9 是阈值，不是第九个维度。**

原 [taste-calibration，第14–65行](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee/skills/shared-references/taste-calibration.md#L14-L65)进一步要求：

1. 具名评分轴和权重，程序可按分项复算；一个整体数字不满足该协议。
2. 如有预先存在、由人整理的参考集，先评 3 个好例子和 3 个差例子；执行者不能自选、自生成锚点。
3. 好坏参考集不能分开时，先修量表。
4. 没有参考集允许继续，但必须写 `calibration: none`，不能伪造已校准。
5. 解释目标在什么轴上距离参考水平还有什么差距。

ARIS 不是只用这一个分数：[novelty-check](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee/skills/novelty-check/SKILL.md#L104-L122)另有新颖性 X/10 和 PROCEED / CAUTION / ABANDON；[auto-review-loop](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee/skills/auto-review-loop/SKILL.md#L24-L38)的正向门是 `score >= 6` 且 `ready/almost`。这不能与 research-refine 的 >=9 READY 规则混用。[research-review](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee/skills/research-review/SKILL.md#L61-L89)主要是定性、对抗式研究审查，也不是这张七维表。

早期 native 输入交付了研究技能及 pipeline，但没有强制展开 `research-refine` 和 `taste-calibration` 这两个关键依赖；正式服务又另写了整体 0–1 评分。这是具体接入遗漏，不能用“已提供 ARIS 原文”代替实际评分路径证明。

本次修复将七维及权重迁入 **proposal/conjecture 的评阅**。对诊断性、理论性猜想，方法具体性应对应测量/证明/证伪步骤，前沿手段也应按是否适合问题判断，不能强迫每项都训练新模型。多候选汇总、输入盲化、schema 校验和版本输出策略属于 SAGE 新增控制设计，必须与 ARIS 原规则分开说明；新分数不能追写成历史运行的“原始 ARIS 分数”。

## 4. CORAL：有 rubric judge，维度由任务决定

来源：[Human-Agent-Society/CORAL](https://github.com/Human-Agent-Society/CORAL)，固定提交 `0123dfb939b35228cf2c1fde224cd0561e727408`。

除 [Score / ScoreBundle 接口](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/coral/types.py#L40-L102)，CORAL 确实附带两套可复用实现，见 [rubric-judges 指南](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/plugin/skills/creating-a-coral-task/references/rubric-judges.md#L1-L75)：

| 原实现 | 条目来源 | 实际评分和版本 |
|---|---|---|
| StrictRubricJudgeGrader | 任务作者在配置中固定名称、定义和权重 | 每项 PASS/FAIL；按配置清单遍历，缺项算 FAIL；加权通过率 |
| AgentJudgeGrader | 模型初次生成，之后允许演进 | 同样逐项 PASS/FAIL；加权通过率；保存 rubric 版本与变更 |

静态 [grader.py，第183–234行](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/examples/race-japan-elderly/grader/src/race_japan_grader/grader.py#L183-L234)实际执行：

```text
score = Σ(weight[i] × pass[i]) / Σ(weight[i])
pass[i] ∈ {0, 1}
```

[静态评审提示](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/examples/race-japan-elderly/grader/src/race_japan_grader/grader.py#L316-L366)要求逐条检查、提供理由并核对来源。[动态实现，第309–424行](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/examples/apex-eggshell-skull/grader/src/apex_judge/grader.py#L309-L424)允许提升标准；全部通过却没有演进时还会把分数封顶 0.99。标准变化后不能直接比较不同版本的分数。

示例中的具体任务是市场研究和法律分析，不能把领域条目照搬为科研创新标准。静态示例 task tips 有连续 0–10 的文字，但实际 parser 和指南采用二值加权，应以执行代码为准。

SAGE 使用的是自己的 [native Grader](../sage/autonomous/grader.py)回调管理器的 [service](../sage/autonomous/service.py)，没有实例化上述示例裁判。应借鉴固定标准、逐项解释、程序汇总和版本化机制，不能宣称 CORAL 会自动提供一套科研正确性 rubric。

## 迁移验收应证明什么

- **原版存在**：提供固定提交、准确文件和执行代码，而不只看 README。
- **实际接线**：追到运行入口与调用路径；原始文件在磁盘上不等于执行了其方法。
- **软件可靠**：分项、尺度、候选和来源范围、缺项、版本、汇总等有有效校验。
- **评分可解释**：公开 rubric、逐项理由、计算方法和 `calibration`，不让 confidence 冒充成果质量。
- **科研质量独立**：同模型多会话/多 persona 的意见不能等同于跨模型验收；模型分数也不能代替实验和数学验证。

本页是来源和行为对照，不宣称量表改造后已经提高科研质量。修复状态、离线测试和任何真实服务验收应单独记录，历史评分与科研产物保持原样。
