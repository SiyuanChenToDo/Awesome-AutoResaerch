# 文献分析 · literature

**职责**：区分论文作者的主张、实际读到的证据与研究者推断，建立可定位的证据卡和论文演进关系。

- **输入**：候选论文、获准读取的 PDF、引用信息、研究问题与已读范围。
- **输出**：方法/实验/实体摘录、引用链、局限与冲突，人工核对后写入 [literature.md](../../templates/project/literature.md)。
- **已有**：证据卡模板与[工作流 G1](../../docs/workflow.md)的人工审核要求；尚无已运行验证的全文分析后端。

## CoI 源码入口（已导入，未运行）

- [searcher/sementic_search.py](../../third_party/coi_agent/upstream/searcher/sementic_search.py)：`read_arxiv_from_path()` 调用 SciPDF 解析 PDF；`read_paper_content()` / `read_paper_content_with_ref()` 拼接正文与参考文献。
- [agents.py](../../third_party/coi_agent/upstream/agents.py)：`get_paper_idea_experiment_references_info()` / `get_article_idea_experiment_references_info()` 提取想法、实验描述、实体和参考文献；`deep_research_paper_with_chain()` 前向追被引、后向追参考文献，并生成链及趋势摘要。
- [deep_research_agent_prompts.py](../../third_party/coi_agent/upstream/prompts/deep_research_agent_prompts.py)：对应信息提取和趋势分析提示词。

上游流程依赖 PDF 解析服务与模型。链中的关联是候选解释，摘要不是逐条核验后的事实；源代码输出仍需补稳定文献 ID、版本、页码/章节等证据定位。原始快照与修补副本的边界见 [orchestration](../orchestration/README.md)。

## 参考与扩展

参考[工具目录](../../catalog/tools.md)的 PaperQA，以及[论文目录](../../catalog/papers.md)的 ResearchAgent；这里只建立阅读入口，未集成这些系统。资料来源与抽查见 [catalog](../../catalog/README.md)。

**下一接入点**：把每段提取结果映射到来源 ID、正文位置、已读范围和支持/反对证据；为解析失败、引用错配、摘要与全文冲突建立离线测试。

[上一步：文献发现](../discovery/README.md) · [下一步：研究构思](../ideation/README.md) · [返回模块索引](../README.md)
