# 工作流编排 · orchestration

**职责**：保留 CoI 完整调用链作为起点，集中管理上游快照、本仓库补丁与运行准备；各功能目录只导航到同一份源代码。

- **输入**：固定的 CoI 上游快照、本仓库维护的补丁及本地准备目标。
- **输出**：快照校验结果、应用补丁后的本地运行副本；不产出模型结果或研究结论。
- **已实现的本地入口**：[coi_agent.py](coi_agent.py) 与 [coi_patches.json](coi_patches.json)。它们校验原始快照，按补丁准备被忽略的 `projects/` 目录；不导入/运行上游模块、不安装依赖、不联网、不调用模型。

## 离线使用

在仓库根目录运行：

```bash
python scripts/coi.py inspect
python scripts/coi.py prepare --destination projects/coi-agent-runtime
```

[CLI 入口](../../scripts/coi.py) 的 `inspect` 检查快照身份与文件完整性；`prepare` 先校验，再把修补副本写入新的私有子目录，并附来源与变更记录。已有目录不覆盖，目标必须位于 `projects/` 内；这一步没有执行上游代码。

当前五项维护补丁涉及链结果字段顺序、Azure 布尔配置、链长度参数拼写，以及空检索和格式异常时的新颖性判定。保留上游默认的单链设置；尚未实现总成本预算或所有循环的可靠终止机制，不提供无人值守运行入口。

## 源码与维护边界

- [third_party/coi_agent/upstream](../../third_party/coi_agent/upstream/) 是集中保存的原始源码，保留 [LICENSE](../../third_party/coi_agent/upstream/LICENSE)，不直接修改。
- [上游 main.py](../../third_party/coi_agent/upstream/main.py) 的流程是：配置/模型 → `DeepResearchAgent.generate_idea_with_chain()` → `generate_experiment()` → `improve_experiment()` / `ReviewAgent.review_experiment()` → `result.json`。
- [agents.py](../../third_party/coi_agent/upstream/agents.py)、[检索器](../../third_party/coi_agent/upstream/searcher/sementic_search.py)、[LLM.py](../../third_party/coi_agent/upstream/LLM.py) 和 [prompts](../../third_party/coi_agent/upstream/prompts/) 共同构成上游流程。源代码已导入不代表依赖已安装或端到端可运行。
- 原始源码的问题通过维护补丁修正于副本。离线检查只能验证其检查范围；不能据此宣称真实检索/模型服务已接通或补丁通过科研效果验证。

上游 [README](../../third_party/coi_agent/upstream/README.md) 中的安装、服务启动与运行命令是来源材料，不是本仓库已执行的步骤。未来实际运行涉及 API 凭据、模型费用、外部检索、PDF 下载与解析服务，必须另行确认授权、依赖、预算和停止条件。`projects/` 的 Git 忽略规则也不能代替真实沙箱。

## 参考与扩展

已有流程规范见[研究工作流](../../docs/workflow.md)、[项目模板](../../templates/README.md)及[架构契约](../../docs/architecture.md)；工具/论文事实继续存放在 [catalog](../../catalog/README.md)。Agent Laboratory、AiiDA 和其他[编排工具参考](../../catalog/tools.md)尚未集成。

**下一接入点**：先用受控小任务验证配置、依赖、输入输出、失败与预算，再把经人工审核的 CoI 产物映射到项目的文献、假设和设计草稿。自动实验与写作需独立实现，不能从 CoI 的方案生成能力推断出来。

[返回模块索引](../README.md) · [实验执行边界](../execution/README.md)
