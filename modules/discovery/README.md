# SAGE 文献发现 · discovery

**实现入口**：[sage/discovery](../../sage/discovery/) · [prompts.py](../../sage/discovery/prompts.py)

把研究问题变成有限、可记录的检索过程。`Discovery` 生成查询，在空结果时有界改写，去重并选择锚点，读取引用/被引关系；提供给文献模块的是带稳定 paper ID、URL 和证据范围的 `Paper`。

- **输入**：问题、查询/候选/改写上限、时间过滤、`PaperSource`，可选本地 article 映射。
- **输出**：锚点与相关论文、查询/调用审计；没有可用证据时明确停止，不生成论文。
- **重排**：提供方明确启用 embedding 时使用余弦相似度；否则使用记录在审计中的词项匹配回退，不冒称上游嵌入效果。
- **提供方**：offline fixtures 或可选 Semantic Scholar metadata adapter；live 默认只有题录/摘要，不下载 PDF。

对应 CoI 的 `get_search_query()`、`generate_idea_with_chain()` 的发现部分以及 `SementicSearcher.search_async()` / `search_related_paper_async()` / `rerank_papers()`。上游文件名 `sementic_search.py` 保持原样；新逻辑不导入上游。完整[迁移与偏离](../../docs/sage-migration.md)说明了有限重试、重排和全文获取取舍。

本地资源目录仍可独立查询：`python -m sage catalog search "Chain of Ideas"`。这是离线目录搜索，与 live 文献发现不是同一数据源。

检索为空或召回不足不能支持“不存在相关工作”；PaperQA、GPT Researcher 等[目录工具](../../catalog/tools.md)继续只是参考，未因列名而集成。

[运行说明](../../docs/sage-runtime.md) · [下一步：文献分析](../literature/README.md) · [模块索引](../README.md)
