# 按研究功能导航

从“找论文”到“写结论”按功能进入，具体项目与论文记录仍以 [catalog](../catalog/README.md) 为唯一资料目录。本目录提供职责、代码位置与产物映射，不复制 JSON 条目，也不把同一份上游代码拆成多份。

## 模块地图

| 模块 | 输入 → 输出 | 当前落地 |
|---|---|---|
| [文献发现 discovery](discovery/README.md) | 问题、查询范围 → 候选论文与检索记录 | 已有离线目录搜索；导入 CoI 检索源码，在线能力未运行 |
| [文献分析 literature](literature/README.md) | 论文/PDF → 证据卡、引用与想法链 | 已有阅读模板；导入 CoI PDF/引用链源码，未运行 |
| [研究构思 ideation](ideation/README.md) | 文献链、研究问题 → 候选想法与可证伪假设 | 已有假设模板；导入 CoI 构思源码，未运行 |
| [实验设计 experiment_design](experiment_design/README.md) | 想法、相关方法 → 方案草稿与冻结协议 | 已有协议检查；导入 CoI 方案生成源码，未运行 |
| [实验执行 execution](execution/README.md) | 批准协议、代码、数据 → 原始运行与制品 | 已有记录模板；执行器待实现，CoI 无此 runner |
| [工作流编排 orchestration](orchestration/README.md) | 上游快照、配置 → 校验报告与本地准备目录 | 维护离线 CoI 适配入口与补丁；不执行模型或联网流程 |
| [评审与核验 review](review/README.md) | 想法、方案、证据 → 意见、核验记录与决定 | 已有检查表；导入 CoI 方案评审源码，未运行 |
| [科研写作 writing](writing/README.md) | 审核后的声明与证据 → 可追溯稿件 | 已有大纲与声明模板；写作 runner 待实现，CoI 无此入口 |

建议顺序：发现 → 文献分析 → 构思 → 实验设计 → 执行 → 核验 → 写作；编排横跨各阶段。每阶段的人工放行条件见[研究工作流](../docs/workflow.md)。

## 已有、已导入与待实现

- **已有本仓库能力**：目录检索、项目初始化、结构/链接检查，以及 [CoI 离线适配入口](orchestration/coi_agent.py)。离线准备不等于上游端到端运行。
- **已导入上游源码**：[CoI-Agent 原始快照](../third_party/coi_agent/upstream/)，集中保存并保持原样。工作台维护的变更放在 [coi_patches.json](orchestration/coi_patches.json)，准备时应用到被忽略的 `projects/` 运行副本。
- **待实现/未验证**：真实模型与检索服务的接通、受限实验执行、可靠预算与隔离、自动写作。本次未安装上游依赖、调用模型、下载论文或运行研究实验；方法名来自静态源码阅读。

CoI 的 `experiment` 是生成的**实验方案文本**，不是训练、实验结果或可执行制品。模型判新与模型评审也不能代替独立证据核验。

## 资料与项目状态

- 查工具：[工具目录](../catalog/tools.md)；查论文：[论文目录](../catalog/papers.md)；查评测：[评测目录](../catalog/benchmarks.md)；查服务与资料入口：[其他资源](../catalog/resources.md)。
- 看抽查依据：[verification.json](../catalog/verification.json)；看选型与任务状态：[curation.json](../catalog/curation.json)；看后续接入要求：[架构](../docs/architecture.md)与[路线图](../docs/roadmap.md)。
- Agent Laboratory 保留为后续重点，尚未导入或集成。其他参考工具也不因出现在模块页而获得“已集成”状态。
- autoresearch 保持按用户要求完成的**计划状态**，不重新加入复现队列；`not_run` / `not_integrated` 的运行与集成边界不变。

[返回仓库首页](../README.md)
