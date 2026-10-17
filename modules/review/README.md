# SAGE 评审与核验 · review

**实现入口**：[sage/review](../../sage/review/) · [prompts.py](../../sage/review/prompts.py)

本模块承担三类不同工作，产物不能互相替代：

1. **检索范围内的新颖性检查**：生成查询、检索相似论文、解析明确的相似性状态。无检索证据为 `not_established`；未发现相似工作仍不能证明全球首次。
2. **模型比较与方案建议**：按 novelty、relevance、significance、clarity、feasibility、effectiveness 六个维度两两比较候选；另对实验方案给出意见并从相关文献提取建议。模型判断不等于实验结果。
3. **独立于生成回答的确定性契约检查**：检查结构、选择和证据关联等输出契约。该检查不让模型给自己的结果签发“有效”标签，但也不是独立科学评价器、权限隔离或真实性认证。

对应 CoI 的 `check_novel()`、`get_check_novel_search_query()`、`judge_idea()` 以及 `ReviewAgent.get_search_query()`、`get_suggestions_from_papers()`、`review_experiment()`。原 `juder_prompts.py` 的想法/方案比较和 review 提示词均迁移到本模块，归档文件名不改。提示词完整清单见[迁移对照](../../docs/sage-migration.md)。

六维累计比较不是标准 Elo 评级；原提示词只要求五项输出、调用方却读取 relevance，SAGE 显式补齐并严格校验六项。格式错误不当平局吞掉，有限重试耗尽后留下失败状态。

真正的科学复核仍按[工作流 G4/G5](../../docs/workflow.md)检查全部尝试、反例、统计不确定性、评分器身份及原始证据，并记录人工决定。PaperBench 等[评测候选](../../catalog/benchmarks.md)尚未被此结构检查替代或自动运行。

[实验设计](../experiment_design/README.md) · [科研写作边界](../writing/README.md) · [模块索引](../README.md)
