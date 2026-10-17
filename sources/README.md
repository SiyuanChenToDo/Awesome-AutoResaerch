# 原始资料与导入边界

[2026-10-14 自动研究全景清单](snapshots/2026-10-14-autoresearch.md) 为本次用户提供的 Markdown 文件原样归档，共 685 行；原始文件名 `AutoResearch-专线清单-2026-10.md`。文内另有 10 月 16 日的复核声明，因此快照日期记录文首声明，不等同于所有内容的采集时间。

SHA256：`bc4141eb87f1260846acfafb148e836edeb3329a411ec86ec7d3a85f8adf51f6`

[manifest.json](manifest.json) 保存来源身份与哈希；[import-report.json](import-report.json) 保存提取差异与未提供附件。

## 本次实际得到什么

- 147 个规范化 GitHub owner/repo，与来源报告一致。
- 175 个 Markdown 外链中的唯一 arXiv ID，来源报告为 176。保留差异，不补造缺失论文。
- 370 个规范 URL 记录：147 个工具、182 个论文类 URL、41 个其他资源。
- 39 个 benchmark 分类 URL 是这些记录的交叉视图，不代表 39 个完全去重的基准。正式出版入口、预印本和博客有时属于同一工作。

## 原文的缺失配套文件

原文链接了以下路径，但它们未随附件提供。本仓库没有这些原始资料，不能伪造或声称已经导入：

- `literatures/data/`
- `literatures/data/autoresearch-repos.csv`
- `literatures/data/autoresearch-papers.csv`
- `research/01-papers.md`
- `research/02-repos.md`
- `research/03-hf-and-products.md`
- `research/04-benchmarks-and-risks.md`

因此原始归档页中的这些相对链接会不可用；新目录与工作流不依赖它们。正常文档的相对路径仍纳入离线检查。

## 纠错原则

原始快照保留原样，错误与更新写入 [独立抽查记录](../catalog/verification.json)。本次发现的重点问题包括时间线中 AI Scientist-v2 的论文链接实际指向 PaperBench，以及许可证口径需区分代码、文档和 GitHub 识别状态。

来源自己的“已核验”“最新”“实测”等字样只是该来源的声明，不转化为本仓库的新核验结论。未逐条重新访问全部外链，也未试跑任何第三方研究代码。
