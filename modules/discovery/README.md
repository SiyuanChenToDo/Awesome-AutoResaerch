# 文献发现 · discovery

**职责**：把研究问题变成可复查的检索过程，找出候选论文、最近工作、强基线与反例；全文证据分析交给 [literature](../literature/README.md)。

- **输入**：问题、检索式、时间范围、来源范围、条目/成本上限，可选锚点论文。
- **输出**：候选论文、检索时间与条件、纳入/排除理由、失败与访问限制，整理到 [literature.md](../../templates/project/literature.md)。
- **已有**：[catalog.py](../../scripts/catalog.py) 可离线搜索已收录资料，例如在仓库根运行 `python scripts/catalog.py search "Chain of Ideas"`。这只查询本地目录，不是在线论文搜索。

## CoI 源码入口（已导入，未运行）

- [agents.py](../../third_party/coi_agent/upstream/agents.py)：`DeepResearchAgent.get_search_query()` 生成查询；`generate_idea_with_chain()` 选择锚点论文。
- [searcher/sementic_search.py](../../third_party/coi_agent/upstream/searcher/sementic_search.py)：`SementicSearcher.search_papers_async()` 请求 Semantic Scholar；`search_async()` 筛选候选并可下载全文；`rerank_papers()` 使用嵌入重排；`search_related_paper_async()` 找引用/被引论文。类名与文件名保留上游拼写。

这是源代码中的在线流程，需要外部服务及相应授权；模块页和离线适配器不会触发它。搜索为空、PDF 不可读或 API 失败都必须保留为缺失，不能解释为“不存在相关工作”。

## 参考与扩展

从[工具目录](../../catalog/tools.md)中的 PaperQA、GPT Researcher 和[其他资源](../../catalog/resources.md)查找替代检索入口；它们均为参考，未接入本模块。原始来源与核验范围见 [catalog](../../catalog/README.md)。

**下一接入点**：按[文献检索适配器契约](../../docs/architecture.md)增加结构化来源 ID、稳定 URL/版本、访问状态、内容哈希和费用记录；先验证召回与失败语义，再连接模型。

[下一步：文献分析](../literature/README.md) · [返回模块索引](../README.md)
