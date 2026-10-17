# 实验设计 · experiment_design

**职责**：把候选想法变为明确的比较与停止规则，冻结数据、评价器、预算和反证标准。

- **输入**：假设、相关方法与实验描述、模型评审意见、现实资源约束。
- **输出**：方案草稿；人工确认后填写 [preregistration.json](../../templates/project/preregistration.json)、[benchmark.md](../../templates/project/benchmark.md) 与 [decisions.md](../../templates/project/decisions.md)。
- **已有**：[research.py](../../scripts/research.py) 检查项目/协议的基本结构；通过检查不等于科学有效或获得执行授权。

## CoI 源码入口（已导入，未运行）

- [agents.py](../../third_party/coi_agent/upstream/agents.py)：`DeepResearchAgent.generate_experiment()` 根据想法、相关实验与实体生成方案；`improve_experiment()` 调用评审后迭代；`refine_experiment()` 检索补充文献并改写方案；`get_paper_info_for_refine_experiment()` 提取用于修订的信息。
- [deep_research_agent_prompts.py](../../third_party/coi_agent/upstream/prompts/deep_research_agent_prompts.py)：方案生成、补充检索与修订提示词。

上述方法返回的是方案文本。CoI 不负责冻结评分器、创建训练任务、运行代码或测量真实指标；方案不能直接充当批准协议。需补齐基线、数据版本、种子、预算、分析方法、失败记录与停止条件，经[工作流 G3](../../docs/workflow.md)后才可进入执行。

## 参考与扩展

选择评测时先读[基准选择指南](../../docs/benchmark-selection.md)与[评测目录](../../catalog/benchmarks.md)。[工具目录](../../catalog/tools.md)中的 research-loop / steer 提供设计参考，尚未接入；Agent Laboratory 也仍未集成。

**下一接入点**：将自由文本方案映射为可校验的草稿字段，缺失值保留为未知；对可比预算、反证条件及评价污染做人工审查，不自动设为 `frozen`。

[上一步：研究构思](../ideation/README.md) · [下一步：实验执行](../execution/README.md) · [返回模块索引](../README.md)
