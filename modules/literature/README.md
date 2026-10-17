# SAGE 文献分析 · literature

**实现入口**：[sage/literature](../../sage/literature/) · [prompts.py](../../sage/literature/prompts.py)

`Literature` 把已有论文内容提取为 `Evidence`，沿前向被引和后向参考文献建立有界 `Chain`，检查新论文相关性，保留停止原因。趋势/实体综合由后续 [ideation](../ideation/README.md)完成。

- **输入**：带 ID/URL/已读范围的 `Paper`、研究问题、发现模块和长度上限。
- **输出**：想法、来源报告的实验描述、实体、参考文献，以及有序 evidence 链。字段用命名 dataclass 表达，避免上游位置元组错位。
- **证据范围**：无本地 article 时明确为 `abstract_only`；显式提供 article 的内容标为 `user_supplied_full_text`。后者只说明用户提供了文本，不认证全文完整性、来源真实性或论文结论。
- **内容边界**：只读取提供的 sections/references，不自动下载 PDF，不启动 SciPDF/GROBID；摘要中没有的细节必须保持未知。
- **失败语义**：重复/无关/耗尽来源不能触发无限循环；达不到最小链长报告证据不足。

对应 CoI 的 `get_paper_idea_experiment_references_info()`、`get_article_idea_experiment_references_info()`、`deep_research_paper_with_chain()` 的抽取/追链部分，以及正文/参考文献拼接。完整[迁移对照](../../docs/sage-migration.md)保留上游入口和安全偏离。

机器提取是待复核材料；参考关系不是因果证据，模型摘要不是独立事实验证。按[工作流 G1](../../docs/workflow.md)把关键结论与实际段落、版本、支持/反对证据核对后，整理到 [literature.md](../../templates/project/literature.md)。

[上一步：文献发现](../discovery/README.md) · [下一步：研究构思](../ideation/README.md) · [模块索引](../README.md)
