# SAGE 精读与工具借鉴路线

目标不是拼装最多的 Agent，而是形成一个研究者能判断、能停止、能复核的小闭环。下列顺序是本仓库的设计建议，不是性能排行榜。重点来源抽查范围见 [verification.json](../catalog/verification.json)，完整选择与关联见 [curation.json](../catalog/curation.json)。

## 当前重点与已完成任务

SAGE 已将 **CoI-Agent**（[Chain of Ideas 论文](https://arxiv.org/abs/2410.13185)）的核心提案链与提示词按功能拆分，先读[源方法与模块对照](sage-migration.md)，再看每个模块的实际实现及离线边界。[Agent Laboratory](https://github.com/SamuelSchmidgall/AgentLaboratory) 的代码迭代与报告机制也已拆入 SAGE，见[迁移对照](agent-laboratory-migration.md)；原始项目未独立运行，真实科研效果未验证。具体验收见[当前项目计划](roadmap.md#当前项目计划2026-10-17)。本页不将尚未检查的代码能力写成事实。

[karpathy/autoresearch](https://github.com/karpathy/autoresearch) 已按用户要求标为 `task_status: completed`，不再进入后续复现优先队列。固定训练预算、窄代码修改面、保留/丢弃记录仍作为历史借鉴；全成本与硬件可比性的核验边界保留。计划完成不代表独立复现，运行核验仍为 `not_run`，SAGE 集成仍为 `not_integrated`。

## 背景路线第一轮：先建立可信最小闭环

下表保留SAGE 设计背景，不替代上述当前项目优先队列。

| 读什么 | 要借鉴的机制 | 在这里落实为 | 仍需验证 |
|---|---|---|---|
| [PaperQA](https://github.com/Future-House/paper-qa) | 带来源的文献问答 | 阅读卡与 evidence ID；未来 retrieval adapter | 召回率、引用定位、文档许可 |
| [ResearchAgent](https://arxiv.org/abs/2404.07738) | 文献到研究想法的迭代 | 最近相关工作对照、机制与反证卡 | 本次仅来源收录，精读后再决定实现 |
| [Can LLMs Generate Novel Research Ideas?](https://arxiv.org/abs/2409.04109) | 如何评价想法而非只看生成速度 | 候选新颖性与可行性分别打分；人工判断 | 原始研究设计与外推边界，尚未独立深读 |
| [research-loop](https://github.com/junjunjunbong/research-loop) / [steer](https://github.com/xieyulai/steer) | 冻结规则、账本、评估隔离 | 预注册、evaluator hash、失败记录与人工审计 | 真正的隔离/执行器尚未集成；research-loop v0.3 非 GPU/远程通用底座 |
| [PaperBench](https://arxiv.org/abs/2504.01848) | 细粒度复现 rubric | claim → evidence → artifact 追溯 | 未来再运行正式基准；本次没有基准成绩 |

最小落地方式：一个问题、3–5 篇最近相关论文、一张可证伪假设卡、一个简单基线、一个受控候选方法、一个冻结评估器、完整失败记录，以及一页证据支持的结论。

## 背景路线第二轮：闭环稳定后，再提高探索效率

- [AI Scientist-v2](https://github.com/SakanaAI/AI-Scientist-v2) 和 [论文](https://arxiv.org/abs/2504.08066)：借鉴渐进式假设树、实验分支与手稿接口。先审许可证；README 明确 v2 不总是优于 v1。
- [SciAgentsDiscovery](https://github.com/lamm-mit/SciAgentsDiscovery)：作为知识图谱辅助跨论文组合的待核验候选。图边必须有来源与置信级别，不能把图上的连接当作机制证据。
- [AiiDA](https://github.com/aiidateam/aiida-core)：只有当复杂计算、恢复、调度与溯源真的成为瓶颈，再考虑引入；P0 的 JSONL 足以先定义契约。

## 不默认引入的依赖

[AutoGen](https://github.com/microsoft/autogen) 的当前 README 已标记停止维护并推荐其他框架，因此不作为新系统默认底座。选任何新框架都要重新验证维护状态、许可、迁移成本和最小功能需求。

## 每篇精读都回答六个问题

1. 它解决的是哪一段研究工作，输入与输出是什么？
2. 优势来自模型能力、工具、任务约束还是评估设定？
3. 对照是否充分，预算与人工参与是否公平？
4. 失败、负结果、污染和不确定性是如何处理的？
5. 哪个机制可以独立拆出来复用，最低成本怎么检验？
6. 哪些结论只是作者报告，哪些我们已经独立复核？
