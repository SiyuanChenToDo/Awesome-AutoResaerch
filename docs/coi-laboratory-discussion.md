# CoI × Agent Laboratory：先讨论，再制订方案

这是可选的、有界多角色讨论模块，默认关闭。它把 CoI 的文献链、趋势、方向与候选生成嵌入 Agent Laboratory 风格的博士生提案／互评／博士后综合，再把明确接受的修改交给实验方案、代码迭代与报告。不是简单增加角色名称，也不声称复现上游多代理实验效果。

## 运行与消融

```bash
# 原流程 / 无讨论基线，默认行为不变
python -m sage laboratory --mode offline --discussion-mode none --output projects/lab-baseline
# 混合流程：默认两名博士生，一轮讨论
python -m sage laboratory --mode offline --discussion-mode hybrid --output projects/lab-discussion
# 多轮，但仍严格有界；建议与同预算基线对照
python -m sage laboratory --mode offline --discussion-mode hybrid --discussion-rounds 2 --output projects/lab-discussion-two
# 已审阅的合成 fixture 后端；不会执行任意模型生成的 Python
python -m sage laboratory --mode offline --discussion-mode hybrid --backend fixture --allow-execution --output projects/lab-discussion-fixture
```

`run` 也接受相同讨论参数，但仍止于未执行的提案。JSON `--config` 对应字段为 `discussion_mode`（`none` / `hybrid`）、`discussion_students`（2–4，默认 2）、`discussion_rounds`（1–3，默认 1）及 `discussion_prompt_version`（`v1` / `v2`，默认 `v2`）。CLI 显式值优先。

`max_candidates` 必须不小于学生数。离线文献源只有两组独立来源，选择 3–4 名学生会因证据不足停止；live 也必须实际找到足够来源，不能复制一名学生充数。两种模式使用同一 `RunConfig` 总预算，不给各角色单独重置额度。无讨论基线没有调用 `discussion.*` 阶段；默认基线和显式 `none` 保持一致。讨论通常增加调用次数，因此同样上限不代表同样实际消耗；比较时应报告实际调用、检索、预留 token 和输出，不把模型成本忽略。

## 实际数据流

1. 每名学生从不同锚点形成独立 `Candidate`、CoI 文献链、趋势、方向和想法。每个来源集合必须至少有一条其他学生未持有的来源。角色依次关注方法机制、评价反例、稳健性迁移、可行性复现；可能共享同一模型，不是独立科学专家。
2. `discussion.develop` 仅看到该学生自己的候选和来源，并给出有引用 ID、依据和不确定性的提案。开发前保存完整原始候选快照。
3. 每轮固定环形互评：学生 i 评价 i+1，最后一名评价第一名。同一轮先冻结全部提案，收齐意见再修订，避免先修订者改变后来人的输入。评审只可引用自己持有的来源；跨角色来源所有权保留在记录中。
4. 意见包含 `supported` / `unknown`、具体问题、拟改动、支持说明、证据 ID 和不确定性。无效格式、虚构／他人所有的 ID 或提供方失败会成为 `failed` 记录，有限重试也计入预算。`supported` 只表示模型自报的有来源意见，不是程序认证其科学语义成立。
5. 学生对所有收到的意见明确接受或拒绝。`unknown`、`failed` 不能被接受；接受必须同时保留来源 ID，并在修订想法中逐字包含拟改动。未接受任何新意见时不得改变想法。后续轮次不能悄悄删除已接受的控制或引用；原始提案和历次版本都保留。
6. 所有修订候选重新走原有新颖性检索，不能沿用修改前的“未发现相似工作”。博士后综合选择一个候选，给出依据与未知；每条已接受意见必须成为一条逐字保留原改动的实验要求。拒绝或失败意见不会自动进入方案。
7. 在 `ExperimentDesign.generate` 之前将交接记录注入规划输入，包括被选候选、接受的意见 ID、作者、来源 ID、来源内容／scope、控制要求。原有方案评审和细化结束后，程序再把规范控制要求附到最终方案，避免自由文本细化遗漏。`discussion_handoff` 记录之前方案和交接；这只是约束写进提案，不证明代码实际实施了实验控制。
8. `run_laboratory` 将此最终方案交给原有代码生成、受限执行后端和报告。评价 contract、授权门禁、错误保留与默认 dry-run 不变；讨论不能变更冻结评分器、偷偷执行代码或授权网络／发布。

## 输出与审计

原 `sage.run.v1` 产物新增可空的 `discussion` 字段；无讨论为 `null`。laboratory 中位于 `result.json` 的 `proposal.discussion`，包含：

- `students`：角色、候选索引、拥有的来源、`original_candidate`、初始发展、每轮修改和累计接受的意见
- `critiques`：作者／目标／轮次、成功或失败、支持说明、请求改动、来源与未知
- `prompt_history`：模板版本、模板及 schema 的 SHA-256、具体输入 SHA-256、轮次与角色
- `synthesis`：博士后选择、解释、未解决问题和规范要求
- `plan_handoff`：被选候选、意见—作者—证据映射、来源实际阅读范围、要求、是否已绑定方案

这些记录和统一 `audit.jsonl` 便于复盘，不是不可篡改日志。失败或预算中止仍保存已完成部分；学生数不足／来源重叠不合格停止，不回退为伪造成功。存在未知或失败意见的完整运行保留 `completed_with_uncertainty`，不把它们丢掉。`scientific_validation` 始终 `not_performed`。

## 提示词如何持续改进

维护中的组合提示词在 [sage/discussion/prompts.py](../sage/discussion/prompts.py)。`v1` 要求来源范围说明；`v2` 进一步要求具体控制／证伪条件、区分来源支持与推断、明示缺失证据。它们是可选择、可审查的固定模板，不是模型可自行编辑的系统提示词。轮内改进靠已审计的有限反馈和提案版本，不是无限自我优化。

后续改进应新增版本、说明修改理由，先跑固定离线回放，再在另行授权的任务／模型／预算上比较。不能覆盖旧记录，也不能因为 fixture 通过便称新提示词科研质量更好。本次没有真实模型对照、联网检索、Docker 实测或研究实验。

## 验证能证明什么

`python scripts/check.py` 包括新讨论测试和原有回归测试。合成 fixture 读取实际提示词中的意见：改变或移除意见会改变修订、选择和方案要求。默认无讨论选择候选 0；有来源控制意见被候选 1 接受后，fixture 博士后策略选择候选 1。该策略明确是测试脚本，不能解释为真实评审偏好或质量提升。

覆盖：基线兼容、独立来源状态、所有权／schema／重复键约束、未知与失败拒绝、重试和共享预算、原始版本保留、多轮约束、因果回放、规划交接和 laboratory dry-run／fixture 链路。ID 检查只能证明引用属于输入集合，不能证明源文本真实、语义支持充分或科学结论成立。实验是否实际实现讨论要求仍需独立代码／方案审查。

## 来源与改造边界

- CoI-Agent `agents.py` 的文献链与想法生成机制，提示词源 `deep_research_agent_prompts.py`，Apache-2.0；固定快照和改造映射见 [CoI 迁移说明](sage-migration.md)。新阶段复用维护中的 `Literature` / `Ideation` / `Review`，不导入上游源码。
- Agent Laboratory `agents.py: PhDStudentAgent.phase_prompt`、`PostdocAgent.phase_prompt` 的分工与讨论／计划思想，MIT，Copyright (c) 2025 Samuel Schmidgall。原实现不是此处的严格 JSON 协议；有界环评、来源所有权、保留规范修改、模板哈希及交接契约为 SAGE 新增。
- 原有工程／写作迁移见 [Agent Laboratory 指南](agent-laboratory-migration.md)。许可证及原始 attribution 保持在 [NOTICE.md](../NOTICE.md)、[LICENSE-NOTICE.md](../LICENSE-NOTICE.md) 和 [LICENSES](../LICENSES/)。不修改上游快照，不声称上游认可此改造。
