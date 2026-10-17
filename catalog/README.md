# 机器可读目录

- [tools.md](tools.md)、[papers.md](papers.md)、[benchmarks.md](benchmarks.md)、[resources.md](resources.md)：同一数据集的浏览视图。
- [records.json](records.json)：自动导入，所有条目保留原文位置，不声明已复现。
- [curation.json](curation.json)：人工选择的首批借鉴模块与论文/代码关联。
- [verification.json](verification.json)：重点来源的独立元数据/README 抽查与纠错。
- [record.schema.json](record.schema.json)：记录的 JSON Schema；运行时检查由标准库脚本实现，不依赖第三方 schema 包。
- [stats.json](stats.json)：生成的实际计数，benchmark 视图与其他类型重叠。

参见 [资料维护](../docs/catalog-maintenance.md)。

`curation.json` 中的 P1/P2 是工具选型优先级，不是路线图的功能阶段编号。
