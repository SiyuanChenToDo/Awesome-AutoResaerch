# SAGE 研究构思 · ideation

**实现入口**：[sage/ideation](../../sage/ideation/) · [prompts.py](../../sage/ideation/prompts.py)

将文献链综合为趋势和实体，生成未来方向、候选方法/动机/新颖性描述，再形成完整想法。候选使用 `Candidate` 命名契约，关联原始 `Chain`，保留失败的再生成尝试。

- **输入**：研究问题、文献证据链、生成次数上限以及 review 模块。
- **输出**：趋势/实体、方向、候选想法和检索范围内的新颖性状态；模型产生的 `human_considerations` 是待考虑因素，不是实际人类参与或批准记录。
- **有限改进**：调用 [review](../review/README.md) 的新颖性检查；发现相似工作后带失败案例重新生成，次数有上限。空检索不等于新颖；用 `not_established` 保留未知。
- **选择**：多候选由 review 做六维两两比较；分数是模型偏好，不是科学效应量或全球首次认证。

对应 CoI 的 `deep_research_paper_with_chain()` 中趋势、实体、未来方向、想法生成/定稿与再生成部分；原来内联在大方法中的逻辑已由 SAGE 模块承担。提示词函数保留来源可追溯性，拼写 `get_deep_generate_future_direciton_prompt` 作为既有函数标识保留。详见[迁移说明](../../docs/sage-migration.md)。

离线候选来自固定 fixture 回答，只验证控制流。真实研究仍需[工作流 G2](../../docs/workflow.md)：最近工作对照、替代解释和可证伪条件，人工整理到 [hypotheses.md](../../templates/project/hypotheses.md)。

[上一步：文献分析](../literature/README.md) · [下一步：实验设计](../experiment_design/README.md) · [模块索引](../README.md)
