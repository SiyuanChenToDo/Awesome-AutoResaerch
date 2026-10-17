# 研究构思 · ideation

**职责**：基于文献演进提出有区别、可检验的候选想法，再写成有反证条件的研究假设。

- **输入**：研究问题、文献证据与想法链、已知限制、资源约束。
- **输出**：候选想法、选择理由、创新对照、替代解释与反证条件，人工整理到 [hypotheses.md](../../templates/project/hypotheses.md)。
- **已有**：假设模板与[工作流 G2](../../docs/workflow.md)；未验证模型生成质量或新颖性。

## CoI 源码入口（已导入，未运行）

- [agents.py](../../third_party/coi_agent/upstream/agents.py)：`deep_research_paper_with_chain()` 从文献链总结趋势、提出未来方向并生成想法；`check_novel()` / `get_check_novel_search_query()` 再检索相似工作。
- `DeepResearchAgent.generate_idea_with_chain()` 聚合不同链的候选，通过同文件的 `judge_idea()` 和 [juder_prompts.py](../../third_party/coi_agent/upstream/prompts/juder_prompts.py) 中的 `get_judge_idea_all_prompt()` 做多维两两比较并选择一个候选。默认只有一条链，因此不发生跨链比较。上游变量名含 `elo`，实际代码累计比较得分，不应据此声称实现了标准 Elo 评级。
- [deep_research_agent_prompts.py](../../third_party/coi_agent/upstream/prompts/deep_research_agent_prompts.py)：趋势、方向、想法及判新提示词。

`check_novel()` 在无检索结果时返回通过，不能当“全球首次”的证据；本仓库的 [维护补丁](../orchestration/coi_patches.json) 会在准备副本中将空检索或格式异常的判定改为报错停止；循环、失败处理与结果字段仍需审查。生成的 `human` 字段来自模型输出，不是实际人工参与记录。

## 参考与扩展

阅读[论文目录](../../catalog/papers.md)中的 Chain of Ideas、ResearchAgent 与 Can LLMs Generate Novel Research Ideas?；[工具目录](../../catalog/tools.md)的 SciAgentsDiscovery 仅作候选参考，未集成。研究证据标准见[精读路线](../../docs/reading-path.md)。

**下一接入点**：保留全部候选和淘汰原因，将模型比较与人工选择分开；按检索覆盖、可行性及可证伪性评估，不把自评分升级为科学结论。

[上一步：文献分析](../literature/README.md) · [下一步：实验设计](../experiment_design/README.md) · [返回模块索引](../README.md)
