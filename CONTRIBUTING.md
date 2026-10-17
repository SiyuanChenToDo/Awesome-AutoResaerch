# 为 SAGE 贡献

SAGE（Scientific Agent for Grounded Exploration，基于证据探索的科研智能体）的目标是提升研究决策质量与复现能力，既不以链接数量为目标，也不把模型产出包装成科学结果。

## 添加资料

1. 以公开的一手论文、官方仓库或机构页面为依据，记录访问日期。
2. 新资料可整理为 Markdown 快照，用 `python -m sage catalog import-snapshot` 或兼容入口 `scripts/catalog.py import-snapshot` 导入；新的字节使用新的 source ID，保留 SHA256。
3. 按规范 URL 去重；预印本、正式版与代码的关联由 `catalog/curation.json` 的 `related_ids` 表达，不凭相似标题合并。
4. 不直接编辑生成的 `catalog/records.json`、目录 Markdown 或 `catalog/stats.json`，使用 `catalog.py build`。
5. 修正与抽查写入 `catalog/verification.json`，列证据、日期、核验范围和未验证部分；保留原文错误供审计。
6. 选型写入 `catalog/curation.json`，说明机制、使用条件、局限与阶段，不用热度代替技术判断。用户指定的计划状态与运行/集成状态分别记录。

## 修改运行能力

- 按功能修改 `sage/` 的逻辑与 `prompts.py`，保持明确类型和 provider 契约。执行/写作接口在实现前仍标为 Protocol-only。
- 读取[迁移对照](docs/sage-migration.md)，保留 CoI-Agent 名称、来源、Apache-2.0 署名和修改声明。不改不可变上游快照，不从它动态导入运行逻辑。
- 离线 fake providers 必须走与 live 相同的控制器和解析器。增加成功、格式错误、空结果、有限重试、预算耗尽、部分失败和输出保护测试。
- 查询、引用链、再生成与评审循环有上限；API 请求有超时，错误保留。新颖性空证据为未知；模型角色和结构审计不得改称科学验证。
- 新外部服务须先说明数据传输、依赖/许可、凭据、资源上限、失败语义与授权边界。live 实测、付费调用、GPU 和实验执行需明确授权。
- CI 只做离线验证，不下载论文/大模型/数据集，不调用外部模型，不运行上游研究流程。
- PDF 下载/解析、嵌入重排、实验执行、独立科学评价和论文写作的新增实现必须单独定义验收条件；不要由模块名称推断能力。

## 提交前

```bash
python scripts/catalog.py build
python scripts/check.py
```

在 PR 中明确修改范围、来源与许可、已运行检查、未验证能力和公开材料范围。不要提前写测试数量或科研成功结论；以最终验证结果为准。欢迎负结果、复现失败和元数据纠错。
