# SAGE 科研写作 · writing

**接口位置**：[sage/writing](../../sage/writing/)。本模块仅提供 Protocol 契约，**没有实现论文写作或投稿 runner**。

- **预期输入**：经审查的声明账本、真实结果、分析、准确引用、限制和未解决问题。
- **未来输出**：证据约束稿件，可从 [manuscript-outline.md](../../templates/manuscript-outline.md) 与 [reproducibility.md](../../templates/project/reproducibility.md) 开始。
- **当前状态**：运行产物中的 `writing_status` 为 `not_implemented`。保存研究提案或生成实验计划不等于完成论文写作。

CoI-Agent 的结果 JSON 和实验方案不含真实实验结果写作链；SAGE 不假设它提供了该能力。已读文献和方案可经人工审核用于引言、相关工作或方法草稿，尚未执行的内容保持“计划/假设”措辞。

先核对所有定量声明与真实 run ID/分析文件，再写结果、限制与讨论，最后写摘要。模型生成引用必须回到实际来源检查。按[工作流 G5](../../docs/workflow.md)完成许可、隐私、未发表信息和负责人批准；写作能力也不会自动授予投稿权限。

AI Scientist-v2、Agent Laboratory 等[参考条目](../../catalog/tools.md)只是阅读入口；Agent Laboratory 尚未导入或集成。

[评审与核验](../review/README.md) · [模块索引](../README.md)
