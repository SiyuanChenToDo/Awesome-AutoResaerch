# 实验执行 · execution

**职责**：在批准的边界内运行代码，保留真实日志、指标、失败与全部成本。

- **输入**：冻结协议、批准范围、代码/数据/评分器版本、明确配置、种子与预算。
- **输出**：追加式运行记录、原始日志、指标与制品索引，参照 [run-record.json](../../templates/run-record.json) 和 [runs.jsonl](../../templates/project/runs.jsonl)。
- **已有**：运行记录模板与[项目检查器](../../scripts/research.py)；**待实现**：受限执行器、可信审批、强制预算和独立测试隔离。

## CoI 的边界

[main.py](../../third_party/coi_agent/upstream/main.py) 调用想法生成、`generate_experiment()` 与 `improve_experiment()`，最后把文本保存到 `result.json`。这些方法位于 [agents.py](../../third_party/coi_agent/upstream/agents.py)，没有训练、实验代码运行或指标测量入口。

因此本模块没有 CoI 实验 runner；[离线准备](../orchestration/README.md)生成运行副本也不会启动研究任务。没有真实尝试时保持账本为空，不用模型生成数值填充结果。

## 参考与扩展

- 参考[工具目录](../../catalog/tools.md)中的 research-loop、steer、AiiDA 以及[执行适配器契约](../../docs/architecture.md)；这些工具均未集成。
- autoresearch 的计划任务保持 `completed`，不进入后续复现队列；该状态不改变其 `not_run` / `not_integrated`，详见[计划状态](../../catalog/curation.json)。
- Agent Laboratory 是后续研究对象，尚未导入、集成或运行。

**下一接入点**：按[路线图 P1](../../docs/roadmap.md)从单个低风险、离线、批准代码的最小执行器开始，先验证路径隔离、预算停止、重复提交与失败保留，再讨论自动循环。

[上一步：实验设计](../experiment_design/README.md) · [下一步：评审与核验](../review/README.md) · [返回模块索引](../README.md)
