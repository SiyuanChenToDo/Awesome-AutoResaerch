# 评审与核验 · review

**职责**：区分模型建议、来源抽查和实验复核，审查方案是否可检验、主张是否被证据支持。

- **输入**：想法、实验方案、相关文献；执行后另加入冻结协议、全部运行记录与原始制品。
- **输出**：评审建议、问题清单与人工决定，分别进入 [decisions.md](../../templates/project/decisions.md)、[claims.md](../../templates/project/claims.md) 和 [reproducibility.md](../../templates/project/reproducibility.md)。
- **已有**：来源[核验记录](../../catalog/verification.json)、检查表和离线结构校验；独立实验评价器待实现。

## CoI 源码入口（已导入，未运行）

- [agents.py](../../third_party/coi_agent/upstream/agents.py)：`ReviewAgent.review_experiment()` 产生方案修改建议并保存评审日志；`DeepResearchAgent.improve_experiment()` 消费建议后修订。
- 同文件的 `ReviewAgent.get_search_query()` / `get_suggestions_from_papers()` 是额外可见方法，不应把其存在误写为主入口均已调用。
- [review_agent_prompts.py](../../third_party/coi_agent/upstream/prompts/review_agent_prompts.py) 定义评审提示词；[juder_prompts.py](../../third_party/coi_agent/upstream/prompts/juder_prompts.py) 的 `get_judge_idea_all_prompt()` 由 `agents.py` 中的 `judge_idea()` 调用，服务于候选想法比较。

CoI 的模型角色分工不构成独立科学复核，方案建议也不是实验验证。`check_novel()` 是相似工作检索辅助，不能认证创新。真正的结果核验应按[工作流 G4/G5](../../docs/workflow.md)检查失败、反例、统计不确定性及证据链。

## 参考与扩展

[评测目录](../../catalog/benchmarks.md)中的 PaperBench 可作为细粒度复现 rubric 的阅读对象；[工具目录](../../catalog/tools.md)中的 steer / research-loop 提供冻结与审计机制参考，均未集成。先按[基准选择指南](../../docs/benchmark-selection.md)区分想法质量、工程复现和科学效果。

**下一接入点**：形成独立的“声明 → 原始证据 → 评价器版本”检查，保留异议与不确定结论；让审查角色无法改写被审证据，而不是只换一个模型角色名。

[上一步：实验执行](../execution/README.md) · [下一步：科研写作](../writing/README.md) · [返回模块索引](../README.md)
