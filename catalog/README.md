# 机器可读目录

- [tools.md](tools.md)、[papers.md](papers.md)、[benchmarks.md](benchmarks.md)、[resources.md](resources.md)：同一数据集的浏览视图。
- [records.json](records.json)：自动导入，所有条目保留原文位置，不声明已复现。
- [curation.json](curation.json)：当前项目优先队列、独立的计划任务状态，以及人工选择的借鉴模块与论文/代码关联。
- [verification.json](verification.json)：重点来源的独立元数据/README 抽查与纠错。
- [record.schema.json](record.schema.json)：记录的 JSON Schema；运行时检查由标准库脚本实现，不依赖第三方 schema 包。
- [stats.json](stats.json)：生成的实际计数，benchmark 视图与其他类型重叠。

参见 [资料维护](../docs/catalog-maintenance.md)。

`curation.json` 中的 P1/P2 是工具选型优先级，不是路线图的功能阶段编号；`excluded` 表示已移出后续复现优先队列。当前重点仅由 `current_reproduction_priorities` 列出，其他条目保留作背景资料。

`task_status: completed` 表示计划任务完成；`completion_basis` 说明依据。它与 `runtime_verification_status`、`integration_status` 分开记录：按用户要求关闭任务，不会把 `not_run` / `not_integrated` 升级成已复现或已集成。生成的来源目录与历史核验记录不随计划状态改写。

## 按功能找工具与代码

[功能模块目录](../modules/README.md)提供 8 类入口，引用本目录原记录，不另建重复清单。CoI-Agent 的固定源码与离线准备状态见[导入说明](../third_party/coi_agent/README.md)；原始 catalog 记录保持来源状态，当前接入进度单独写入 [curation.json](curation.json)。
