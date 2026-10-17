# SAGE 资料维护与可信度

## 三层分离

1. `sources/snapshots/`：只读式来源归档，字节不变。`sources/manifest.json` 保存来源 ID、原始文件名、快照日期和 SHA256。
2. `catalog/records.json`：从 Markdown 外链确定性抽取的唯一 URL 记录。每个记录包含所有出现位置。`source_imported` 不是独立事实核验。
3. `catalog/verification.json` 与 `catalog/curation.json`：人工核验、纠错、阅读优先级、阶段与文献/代码关联。不会被重建覆盖。

## 分类口径

`kind` 是 tool / paper / resource；GitHub 项目归 tool，arXiv、Nature、DOI 和论文平台入口归 paper，其他归 resource。类别由原始章节继承，可能有多个标签。`benchmark` 是类别，不另造第二份论文记录。

当前归类是机械索引：GitHub 中的 Awesome List 也是 tool 类型、再由 curated-list 区分；正式版与预印本 URL 可能对应同一科学工作，所以 URL 数不能直接当独立论文数量。仅解析 Markdown 链接，正文里未链接的编号或提及不会被自动变成已确认记录。

`categories` 可取 foundation、experiment-loop、end-to-end、domain-science、literature、infrastructure、skills-writing、hypothesis、benchmark、survey、risk-governance、curated-list、paper-system、industry、community、other。`curation.stages` 独立映射到 scope、literature、ideation、implementation、experimentation、evaluation、writing、review、memory。

## 常见操作

以下原始脚本继续兼容；也可使用 `python -m sage catalog ...`。目录是资源索引，与 SAGE 的实时文献检索或软件运行状态分开。

```bash
python scripts/catalog.py search "PaperBench"
python scripts/catalog.py search --kind tool --category hypothesis
python scripts/catalog.py import-snapshot new.md --id 2026-11-research --date 2026-11-01
python scripts/catalog.py build
python scripts/catalog.py validate
```

同一 source ID + 同一字节与日期重复导入是无副作用操作；不同内容必须用新的 source ID。校验会检查原文哈希、规范 URL 唯一性、行号与来源 URL、人工选型 ID 引用和仓库文档的相对文件路径。

校验不会访问互联网，也不会验证外链 HTTP 状态、论文内容、版本变化、许可证法律含义、性能可复现性或 Markdown 锚点。原文缺失的配套文件列在 [来源说明](../sources/README.md)，不通过伪造文件来消除警告。

## 项目检查器的边界

`research.py check-project`（也可用 `python -m sage project check-project`）检查项目文件/JSON、研究项目 ID、运行状态、重复 run ID；对已完成记录检查数值指标、关键字段、哈希格式；对终止记录检查带时区且有序的时间戳、非负有限消耗和币种。`--ready` 额外检查冻结计划字段、预算/种子、审批字段、评估器实际文件 SHA256，以及解析符号链接后的可写/保护路径交叠。

这些检查不会启动实验，也不验证审批人的真实身份、实际消费、运行记录所述结果的真实性、制品内容/存在性、历史协议的哈希对应、论断—运行引用或统计计算。`runs.jsonl` 当前由用户/未来执行器维护，追加式只是一项约定，尚无防改写或并发写锁。不要把一次格式通过当作实验审计完成。
