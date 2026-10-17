# SAGE 功能模块

SAGE（Scientific Agent for Grounded Exploration，基于证据探索的科研智能体）的实际运行包位于 [sage/](../sage/)。本目录说明每个模块的职责和来源；目录不再只是指向一个上游大文件。提示词和研究链逻辑按功能拆分，控制器组合各模块，运行时不导入 CoI 原始快照。

| 模块 | 输入 → 输出 | 实现状态 |
|---|---|---|
| [discovery](discovery/README.md) | 问题 → 查询、候选论文与引用关系 | 查询/改写逻辑；离线 fixtures 与可选 Semantic Scholar metadata adapter |
| [literature](literature/README.md) | 论文证据 → 摘录、双向引用链 | 真实模块逻辑；保留 abstract-only / local article 范围 |
| [ideation](ideation/README.md) | 文献链 → 趋势/实体、方向、候选与定稿 | 有界生成/再生成，空证据保持未知 |
| [experiment_design](experiment_design/README.md) | 想法/相关文献/意见 → 方案与修订历史 | 方案生成与补充证据修订；不执行实验 |
| [review](review/README.md) | 候选/方案/证据 → 新颖性、六维比较、评审与契约检查 | 模型评审和确定性结构核验；不是科学评价器 |
| [orchestration](orchestration/README.md) | 配置/提供方 → 研究提案产物与调用记录 | 同一 offline/live 控制器，有界重试与调用/时间预算 |
| [execution](execution/README.md) | 批准的协议 → 未来真实运行 | Protocol-only，runner 未实现 |
| [writing](writing/README.md) | 审核过的证据 → 未来稿件 | Protocol-only，runner 未实现 |

## 代码、来源与测试分开看

- [SAGE 运行包](../sage/)：维护中的代码、分模块提示词、类型契约和 provider 接口。离线模式用假提供方执行同一控制器，不把静态结果文件充当流程测试。
- [CoI-Agent 原始快照](../third_party/coi_agent/upstream/)：固定提交、逐字节保留，供归因与审查；不属于默认运行 import 路径。
- [旧归档准备器](orchestration/coi_agent.py)和[五个补丁](orchestration/coi_patches.json)：保留 inspect/prepare 兼容用途；与新 SAGE 运行包分离。
- [迁移对照](../docs/sage-migration.md)：逐项列出上游方法、19 个提示词函数、模块归属与行为偏离。
- [运行说明](../docs/sage-runtime.md)：离线/live 模式、凭据、可选本地文章输入和限制。

离线通过只能证明检查覆盖的软件行为。live 适配器的存在不能证明服务已实测；模型方案、模型评审和新颖性判断不能证明科学有效、全球首次或真实实验完成。

## 资料与项目状态

资料目录仍由 [catalog](../catalog/README.md)管理。研究流程的人工门禁见[工作流](../docs/workflow.md)。Agent Laboratory 尚未导入或集成；autoresearch 保持用户指定的计划 `completed`，运行与集成仍是 `not_run` / `not_integrated`。

[返回 SAGE 首页](../README.md)
