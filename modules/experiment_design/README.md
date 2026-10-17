# SAGE 实验设计 · experiment_design

**实现入口**：[sage/experiment_design](../../sage/experiment_design/) · [prompts.py](../../sage/experiment_design/prompts.py)

从选定想法、来源实验描述和实体生成实验方案，再依据模型评审意见检索补充文献、提取相关信息并修订。生成、评审与证据驱动修订是实际模块调用，不是文档占位。

- **输入**：候选想法、相关方法/实验描述、实体、review 反馈、修订轮数与资源上限。
- **输出**：`ExperimentPlan` 及修订记录，状态保持 `proposal_only`。
- **补充证据**：修订前生成查询、检索来源、提取与意见相关的信息；缺失证据不能补成已知结果。
- **不能做的事**：不启动训练、不执行任意代码、不测量指标、不冻结或批准研究者的真实实验协议。

对应 CoI 的 `generate_experiment()`、`improve_experiment()`、`refine_experiment()` 和 `get_paper_info_for_refine_experiment()`，四个对应提示词位于本模块。方案评审提示词归属 [review](../review/README.md)，跨模块调用由控制器组织。完整来源见[迁移对照](../../docs/sage-migration.md)。

经人工核对后再填写 [preregistration.json](../../templates/project/preregistration.json)、[benchmark.md](../../templates/project/benchmark.md) 和 [decisions.md](../../templates/project/decisions.md)。`python -m sage project check-project ... --ready` 只检查结构/路径等前提；[工作流 G3](../../docs/workflow.md)中的预算、数据、评价器和执行批准仍需负责人确认。

[上一步：研究构思](../ideation/README.md) · [下一步：实验执行边界](../execution/README.md) · [模块索引](../README.md)
