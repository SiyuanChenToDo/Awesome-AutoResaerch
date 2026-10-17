# 贡献指南

目标是提升研究决策质量与复现能力，不是单纯增加链接或星数。

## 添加资料

1. 以公开的一手论文、官方仓库或机构页面为依据，记录访问日期。
2. 新资料可以整理为 Markdown 快照，再用 `scripts/catalog.py import-snapshot` 导入。稳定 source ID 与 SHA256 保证可追溯。
3. 机器提取按规范 URL 去重；论文预印本、正式版与代码之间的关系由 `catalog/curation.json` 的 `related_ids` 人工表达，不能只凭相似标题合并。
4. 不直接编辑 `catalog/records.json`、`catalog/{tools,papers,benchmarks,resources}.md` 或 `catalog/stats.json`。它们由 `catalog.py build` 生成。
5. 字段修正与一手抽查写入 `catalog/verification.json`，说明证据链接、日期、核验范围和未验证的部分；保留原文错误供审计。
6. 重点选型写入 `catalog/curation.json`，给出为何借鉴、何时使用、局限和对应阶段，不用热门程度代替技术判断。

## 添加可执行能力

- 先提出适配器契约、数据边界、资源上限、停止条件和离线测试。
- 任何真实模型、GPU、远程或付费执行都属于后续集成，需要独立授权和预算。
- 新能力必须有成功、失败、重试/恢复、越界和重复运行测试。
- 不在 CI 中下载大模型、数据集或运行第三方研究仓库；CI 只校验脚手架。

## 提交前

```bash
python scripts/catalog.py build
python scripts/check.py
```

在 PR 中明确：修改范围、来源与许可、已运行检查、未验证能力，以及是否包含可公开研究信息。欢迎负结果、复现失败报告和元数据纠错。
