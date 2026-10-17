# 科研写作 · writing

**职责**：把已审查的证据写成边界清晰的论文或报告，确保每项主张、数字与引用可追溯。

- **输入**：审核后的声明账本、原始结果与分析、准确引用、限制和未解决问题。
- **输出**：以 [manuscript-outline.md](../../templates/manuscript-outline.md) 为起点的稿件及 [reproducibility.md](../../templates/project/reproducibility.md)。
- **已有**：[claims.md](../../templates/project/claims.md)、写作大纲与[工作流 G5](../../docs/workflow.md)；**待实现**：证据约束的自动写作 runner。

## CoI 的边界

导入的 [main.py](../../third_party/coi_agent/upstream/main.py) 将想法、方案、文献链等写入 `result.json`；[agents.py](../../third_party/coi_agent/upstream/agents.py) 的 `generate_experiment()` 生成实验方案文本，没有论文写作、投稿或由真实结果生成图表的入口。

未来可将经人工审核的 CoI 产物用作引言、相关工作或方法设计的草稿素材；尚未执行的方案必须保留“计划/假设”措辞，不能写进结果作为已发生事实。模型生成的引用必须回到实际来源核对。

## 参考与扩展

参考[工具目录](../../catalog/tools.md)中的 AI Scientist-v2、Agent Laboratory 与写作类条目，以及[论文目录](../../catalog/papers.md)中的对应论文。它们在本模块仅为阅读入口；Agent Laboratory 尚未导入或集成，其他参考也不代表已接通。

**下一接入点**：先验证所有定量陈述都能回溯到真实 run ID 和分析文件，再生成结果、限制与讨论，最后写摘要。公开前核查许可、隐私、未发表信息和负责人批准，自动生成不构成投稿授权。

[上一步：评审与核验](../review/README.md) · [返回模块索引](../README.md)
