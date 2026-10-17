# SAGE 实验执行 · execution

**接口位置**：[sage/execution](../../sage/execution/)。本模块仅提供 Protocol 契约，**没有实现实验 runner**。

- **预期输入**：冻结协议、批准范围、代码/数据/评分器身份、配置、种子与预算。
- **未来输出**：真实运行记录、日志、指标和制品，参考 [run-record.json](../../templates/run-record.json) 与 [runs.jsonl](../../templates/project/runs.jsonl)。
- **当前状态**：SAGE 只生成实验方案并保留 `execution_status: not_implemented`。没有训练、Shell 研究命令、数据集下载、GPU 调度或测量输出。

CoI-Agent 的 `generate_experiment()` 也是方案文本生成。模块化迁移没有把该名字升级为真实执行能力；离线 fixture 指标不应被写成真实实验记录，尚无尝试的项目账本保持为空。

实现前须满足[路线图 P1](../../docs/roadmap.md)和[执行适配器契约](../../docs/architecture.md)：明确批准、隔离评分器/数据、真实计量与终止、幂等提交、失败保留、路径和网络权限测试。SAGE 当前请求预算不能代替这些要求。

research-loop、steer、AiiDA 等[参考工具](../../catalog/tools.md)尚未集成。autoresearch 维持用户指定的计划 `completed`，运行/集成仍为 `not_run` / `not_integrated`；Agent Laboratory 尚未导入、运行或集成。

[上一步：实验设计](../experiment_design/README.md) · [评审与核验](../review/README.md) · [模块索引](../README.md)
