# SAGE · 基于证据探索的科研智能体

**SAGE = Scientific Agent for Grounded Exploration**。从研究问题出发，连接文献发现、引用链、证据提取、想法生成与比较、实验方案和评审修订；所有生成内容保留来源范围与未验证状态。

SAGE 的运行代码位于 [sage/](sage/)，按研究功能拆分，源自对 [CoI-Agent / Chain of Ideas](https://github.com/DAMO-NLP-SG/CoI-Agent) 的模块化改造。它是可运行的研究提案工作流：离线模式用固定假数据/假模型走同一控制器，联网模式通过明确选择的模型和 Semantic Scholar 适配器运行。**实验执行与论文写作仅提供接口，尚无 runner；提案、模型评分与离线演示均不是科学结果。**

仓库地址继续使用 `Awesome-AutoResaerch`，分支继续使用 `feat/ai-research-workbench`；SAGE 是我们维护的产品名称。第三方项目名、论文引用、原始来源文件名和不可变快照保持不变。

## 5 分钟离线起步

Python 3.10+，标准库即可运行；不需要 API key、GPU、第三方依赖或网络。

```bash
git clone https://github.com/SiyuanChenToDo/Awesome-AutoResaerch.git
cd Awesome-AutoResaerch
git switch feat/ai-research-workbench

python -m sage doctor
python -m sage run --mode offline --topic "证据约束的研究想法生成" --output projects/sage-demo
python scripts/check.py
```

离线模式执行同一控制器中的查询生成（空结果时有界改写）、双向引用链、文献提取、趋势/实体综合、未来方向、想法生成与定稿、新颖性检查和有界再生成、多候选六维两两比较、实验方案生成、评审及补充证据修订。数据和模型回答来自确定性 fixtures，用于验证软件链路；不能用来评价模型质量、检索召回、研究新颖性或真实科研效果。

运行产物留在 `projects/`，该目录默认被 Git 忽略。`--output` 应使用新的目录，以免覆盖已有研究记录。查看全部参数：

```bash
python -m sage run --help
```

## 显式联网运行

```bash
python -m sage run --mode live --allow-live --topic "你的研究问题" --output projects/sage-live
```

只有明确启用 live 并提供凭据才会调用外部服务。具体模型、凭据、请求上限与可选本地 article JSON 见[运行说明](docs/sage-runtime.md)。联网会向所选模型服务发送研究问题及检索/阅读内容，并向 Semantic Scholar 发送检索请求；运行前确认材料可外传及可能的模型费用。

当前 live 检索默认只有题录与摘要。可显式提供已获授权的本地 article JSON；SAGE **不自动下载 PDF、不启动 SciPDF/GROBID、不抓取任意全文网址**。证据范围写入产物和提示词；摘要不能被描述为已读全文。适配器已实现不等于外部服务已经实测，本次改造不声称完成联网验证。

## 模块与能力边界

| 模块 | 实际职责 | 入口 |
|---|---|---|
| discovery | 查询、失败改写、候选发现与引用关系 | [模块说明](modules/discovery/README.md) · [代码](sage/discovery/) |
| literature | 证据提取与前后向文献链 | [模块说明](modules/literature/README.md) · [代码](sage/literature/) |
| ideation | 趋势/实体、未来方向、候选生成/定稿与有界再生成 | [模块说明](modules/ideation/README.md) · [代码](sage/ideation/) |
| experiment_design | 方案生成、基于补充文献与评审意见的修订 | [模块说明](modules/experiment_design/README.md) · [代码](sage/experiment_design/) |
| review | 新颖性检查、六维比较、方案评审与独立契约检查 | [模块说明](modules/review/README.md) · [代码](sage/review/) |
| orchestration | 同一控制器、类型契约、调用/时间预算、记录与错误 | [模块说明](modules/orchestration/README.md) · [代码](sage/orchestration/) |
| execution | Protocol 接口；无训练或实验 runner | [边界](modules/execution/README.md) · [接口](sage/execution/) |
| writing | Protocol 接口；无自动论文写作或投稿 runner | [边界](modules/writing/README.md) · [接口](sage/writing/) |

分模块的 `prompts.py` 与实际调用逻辑共同组成 SAGE；运行时不导入原始快照。详见[源码方法与模块对照、改动和偏离](docs/sage-migration.md)。独立契约检查校验输出结构与证据引用，不能替代独立权限域的科学评价器。

## 保留的资料与项目工具

```bash
python -m sage catalog search "hypothesis"
python -m sage catalog search --category benchmark
python -m sage project init my-first-study --title "我的第一个研究项目"
python -m sage project check-project projects/my-first-study
```

原入口 `python scripts/catalog.py ...` 和 `python scripts/research.py ...` 继续支持。项目初始化只创建 `draft` 模板，不调用模型、不运行实验；`check-project ... --ready` 是基本字段/路径检查，不代表科学有效、身份验证或执行批准。

| 资料入口 | 内容 |
|---|---|
| [功能模块](modules/README.md) | 代码职责、来源与边界 |
| [研究工作流](docs/workflow.md) · [架构](docs/architecture.md) | 人工门禁、证据契约及尚未实现的隔离要求 |
| [工具](catalog/tools.md) · [论文](catalog/papers.md) · [评测](catalog/benchmarks.md) | 用户来源清单的可检索目录；收录不等于核验或集成 |
| [机器可读目录](catalog/records.json) · [抽查与纠错](catalog/verification.json) | 来源定位和独立核验范围 |
| [来源快照](sources/README.md) · [CoI-Agent 归档](third_party/coi_agent/README.md) | 原文、固定提交、哈希、许可与排除说明 |
| [项目模板](templates/README.md) · [精读路线](docs/reading-path.md) | 研究计划、证据、反证、复核与后续阅读 |

## 当前项目计划（2026-10-17）

- [karpathy/autoresearch](https://github.com/karpathy/autoresearch)：按用户要求标为计划任务 `completed`，不再加入复现优先队列。运行核验仍是 `not_run`，集成仍是 `not_integrated`。
- CoI-Agent：固定源码作为不可变来源保留；SAGE 已按功能拆分其提示词和核心研究链，并提供离线运行路径及可选 live 适配器。未运行原始上游流程、未复现论文指标、未验证真实科研效果。
- [Agent Laboratory](https://github.com/SamuelSchmidgall/AgentLaboratory)：后续研究重点，尚未导入、运行或集成。

计划完成、源代码归档、软件运行、联网验证与科研有效性是不同状态。详细验收见[路线图](docs/roadmap.md)。

## 项目结构

```text
sage/                     SAGE 自有运行包、按功能拆分的提示词/逻辑、provider 与契约
modules/                  功能文档；orchestration 中保留旧 CoI 归档准备器
third_party/coi_agent/     CoI-Agent 不可变快照、Apache-2.0、来源清单
catalog/                  可检索资料目录、选型与独立核验记录
sources/                  原始来源清单、哈希与导入限制
docs/                     运行说明、迁移对照、工作流、架构与路线图
templates/                项目协议、证据、实验与声明模板
examples/                 可公开的计划示例，明确标注未执行
scripts/                  兼容的目录/项目/归档工具及统一离线检查
tests/                    离线回归测试
projects/                 默认不入 Git 的本地研究产物
```

旧的 `python scripts/coi.py inspect` / `prepare --destination projects/coi-agent-runtime` 继续用于核验归档与生成带五个补丁的私有副本。它们不再是 SAGE 主运行路径，不安装或运行上游依赖。原始源码和旧准备器的已知风险见[归档说明](third_party/coi_agent/README.md)。

## 维护与贡献

见[贡献指南](CONTRIBUTING.md)、[资料维护](docs/catalog-maintenance.md)、[安全边界](SECURITY.md)和[许可说明](LICENSE-NOTICE.md)。

```bash
python scripts/catalog.py build
python scripts/check.py
```

调用数/时间上限可以约束 SAGE 的请求流程，但不是金额结算、操作系统沙箱、可信审批或独立最终测试隔离。不得把模型输出当实验记录，不得隐藏失败或负结果；公开前审查 diff、隐私、来源许可和研究者授权。
