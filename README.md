<p align="center">
  <img src="assets/sage-hero.svg" alt="SAGE — Scientific Agent for Grounded Exploration。连接文献来源、证据链与研究提案。" width="1200">
</p>

<h1 align="center">SAGE · 基于证据探索的科研智能体</h1>

<p align="center">
  从研究问题出发，把文献发现、证据链、想法生成与实验方案连起来。<br>
  保留来源、失败和不确定性，让每一步都能回看。
</p>

<p align="center">
  <a href="#quickstart">快速开始</a> ·
  <a href="#capabilities">功能地图</a> ·
  <a href="#coi">与 CoI 的关系</a> ·
  <a href="docs/sage-runtime.md">运行指南</a> ·
  <a href="docs/roadmap.md">路线图</a>
</p>

---

**Scientific Agent for Grounded Exploration** 是一个科研猜想发现与证据工作台。新增原生自主入口使用 [CORAL](https://github.com/Human-Agent-Society/CORAL) 管理 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)，加载 [ARIS](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep) 研究技能，自行调研、提出猜想、查新、批评和修订。既有模块化提案、实验与写作代码位于 [sage/](sage/)，包含对 [CoI-Agent / Chain of Ideas](https://github.com/DAMO-NLP-SG/CoI-Agent) 与 [Agent Laboratory](https://github.com/SamuelSchmidgall/AgentLaboratory) 的功能拆分与改造。

**当前软件验证**：509 项离线测试已在 AutoDL Linux 和 Windows 通过（Windows 跳过 3 项 Unix 专用权限检查），包含随后修复的团队默认工具预算。原生 DSH 会话续接已修复并完成真实恢复验收，见[续接验证](docs/native-session-validation-20261018.md)。四研究者、两轮互评的真实团队闭环已完成：4 份初稿、8 次互评、8 次修订、2 版综合和 2 次正式评分，167 项产物完整性检查通过，见[团队运行验证与边界](docs/native-team-validation-20261018.md)。此前 run-10 是[单主研究者历史运行](docs/native-conjecture-validation-20261018.md)。团队过程完成不证明科研质量提高，产物仍是待实验与独立复核的猜想。

**历史验证范围**：较早的 `sage closed-loop` 使用固定真实论文语料和固定符号回归程序，完成了开发、确认、统计、报告和反算核对。它验证子实验的工程连接，不能当作全自主科研的证明。详见[闭环验证](docs/closed-loop-validation-20261018.md)、[写作修复验证](docs/writing-validation-20261018.md)与[较早的接入验证](docs/aris-coral-validation-20261018.md)。

<a id="capabilities"></a>

**自主猜想入口**：`sage autonomous` 由原生 CORAL 管理器运行 DeepSeek Harness，挂载 ARIS 原始研究技能，调用 SAGE 的真实检索和跨章节证据提炼工具。默认四位独立会话的研究者、两轮同伴互评，经过冻结提案、逐条修订和协调者综合；见[团队协议与验收](docs/native-team-protocol.md)及[安装与使用](docs/autonomous-conjectures.md)。现有模块拆分与证据卡类别保持原样。只有单一模型 API 时，输出是待验证猜想，同家族多会话互评不算 ARIS 跨家族独立验收。

**完整论文写作更新**：已移除原先每节一段、160 词 / 1400 字符的篇幅限制。新增 `sage write-paper`，支持完整正文、公式、已核对的引文、实测图表、整篇多视角评阅与修订，以及 LaTeX / Markdown 输出；见[完整论文入口](docs/full-manuscript.md)。它将论文完整性与科研结论是否成立分别记录。原 `write-report` 保留为证据账本兼容入口。

## 从一个问题，到一份可追溯的提案

```text
研究问题 → 查询与检索 → 文献链与证据 → 候选想法 → 比较与筛查 → 实验方案
                                         ↑                      ↓
                                  有界的新颖性再生成       评审与补充证据修订
```

| 能力 | 现在可以做什么 | 代码 |
|---|---|---|
| **发现文献** | 查询生成、空结果改写、Semantic Scholar 检索、去重、日期过滤与重排 | [discovery](sage/discovery/) |
| **连接证据** | 前向被引 / 后向参考文献链、相关性判断、证据提取和阅读范围记录 | [literature](sage/literature/) |
| **形成想法** | 趋势与实体综合、未来方向、候选生成、定稿和有界再生成 | [ideation](sage/ideation/) |
| **CoI 博士生讨论** | 每人独立文献链与候选，带来源的互评、明确采纳/拒绝、有限修订及博士后规划交接；显式开启 | [discussion](sage/discussion/) |
| **比较与评审** | 检索范围内的新颖性筛查、六维两两比较、文献建议与方案评审 | [review](sage/review/) |
| **设计方案** | 实验方案、补充检索与证据支持的修订；保留修订历史 | [experiment_design](sage/experiment_design/) |
| **组织流程** | 类型契约、统一调用与时间预算、审计记录、结构检查与错误保留 | [orchestration](sage/orchestration/) |
| **代码与实验迭代** | Agent Laboratory 衍生的 EDIT/REPLACE、失败修复、候选保留与尝试记录；执行必须显式选择后端 | [execution](sage/execution/) |
| **报告草稿** | 按节写作、评审与修订，保留来源、运行状态和未验证标签 | [writing](sage/writing/) |

### 三个始终可见的边界

- **证据读到哪里，就写到哪里。** standard 模式默认读取题录与摘要；显式选择 research 配置可获取官方 arXiv 正文、选段提炼证据卡，记录未读范围和缺失项；也支持本地 article JSON。[证据输入说明](docs/ideation-evidence.md)
- **没有证据时，保留未知。** 没搜到相似论文不证明全球首次；空证据或无效回复不能变成“新颖”。
- **先把软件链跑通，再验证科研效果。** 离线 fixtures、契约检查和模型评分分别有用途，均不能替代真实实验与独立科学评价。

<a id="quickstart"></a>
## 5 分钟离线起步

Python **3.10+**，标准库即可运行。无需 API key、GPU、第三方依赖或网络调用。

```bash
git clone https://github.com/SiyuanChenToDo/Awesome-AutoResaerch.git
cd Awesome-AutoResaerch
git switch codex/flow-reliability

python -m sage doctor
python -m sage run --mode offline --topic "证据约束的研究想法生成" --output projects/sage-demo
python scripts/check.py
```

离线模式用固定的合成论文与假模型回答，经过同一控制器完成检索、追链、提取、构思、比较、方案与评审修订。它验证软件流程；更换 topic 不会让 fixtures 变成该领域的真实研究发现。

运行后在 `projects/sage-demo/` 查看：

| 文件 | 你能看到什么 |
|---|---|
| `result.json` | 候选、来源与证据链、筛查与比较、方案及修订、错误和契约检查 |
| `audit.jsonl` | 阶段、调用尝试、成功/失败与停止原因；非不可篡改日志 |
| `config.json` | 本次运行限制；不保存 API 密钥 |

`projects/` 默认不入 Git。`--output` 必须使用新的目录，以免覆盖研究记录。更多参数：`python -m sage run --help`。

<details>
<summary><strong>需要真实文献和模型？展开查看 live 入口</strong></summary>

先按[运行指南](docs/sage-runtime.md)配置 OpenAI/Azure 主模型、便宜模型、凭据和请求限制，再显式选择：

```bash
python -m sage run --mode live --allow-live --topic "你的研究问题" --output projects/sage-live
```

live 会把研究问题与检索/阅读内容发送给所选模型服务，并向 Semantic Scholar 发送检索请求。运行前确认数据可外传及模型费用；配置了凭据本身不会触发 live。

DeepSeek + arXiv 已做真实服务验证；Semantic Scholar 引用图与 embedding 服务尚未完成真实验证。standard 未配置 embedding 时使用词项匹配；research 使用有配置的 embedding 或显式模型语义重排。`--articles` 按检索结果 ID/标题附加授权 article JSON。[research 配置与预算](docs/ideation-evidence.md)

</details>

<a id="coi"></a>
## 与 CoI-Agent 的关系

SAGE 保留了 CoI 的核心研究提案方法，并拆为可以独立维护的功能模块。**它不是与原版逐行、逐行为相同的复刻。** 原始源码作为不可变来源保留，运行时不导入上游快照。

| 你关心的内容 | 当前情况 |
|---|---|
| **有原来的提示词吗？** | 19 个原始提示词函数全部有分模块迁移位置，并加入来源范围、结构化输出等修改。19 是迁移覆盖数；部分为扩展模板，并非全部进入默认主链。 |
| **有搜索代码吗？** | 有。包括 Semantic Scholar 查询、查询改写、引用关系、日期过滤、去重及可选 embedding 重排；未配置 embedding 时使用词项匹配。 |
| **有完整研究逻辑吗？** | 查询 → 文献链 → 提取 → 构思 → 判新/再生成 → 比较 → 方案/评审修订已实现并离线验证。 |
| **有哪些有意差异？** | 命名契约替代位置元组；循环与调用有上限；未知新颖性不再误判通过；默认全文下载/解析路径未迁移。 |
| **已经复现原论文效果吗？** | 尚未运行原始上游流程或复现科研指标。真实 DeepSeek + arXiv 提案服务已验证接通；没有证明优于上游。laboratory 链另有代码迭代与报告草稿，自动投稿未提供。 |

提示词入口：[检索](sage/discovery/prompts.py) · [文献](sage/literature/prompts.py) · [构思](sage/ideation/prompts.py) · [方案](sage/experiment_design/prompts.py) · [评审](sage/review/prompts.py)

逐项方法、19 个函数和行为差异见 **[CoI → SAGE 迁移对照](docs/sage-migration.md)**。其中 `get_judge_experiment_all_prompt` 为可扩展的方案比较模板，默认主链实际比较候选想法。六维投票不宣称与上游行为或效果等价。

<a id="laboratory"></a>
## 接入 Agent Laboratory：从方案到代码与报告

CoI 提案链继续负责文献与研究方案；Agent Laboratory 的方法被拆入现有功能模块，负责下一段流程：

```text
研究方案 → 代码候选 → 执行反馈/明确未执行 → 有界修复与改进 → 保留候选与失败 → 分节报告 → 评审修订
```

- **代码编辑与修复**：迁移 MLESolver 的 EDIT/REPLACE 操作、尝试历史与最佳候选机制；循环有预算，失败不会被删除。
- **结果与评价分开**：模型意见不当作测量指标；离线合成 fixtures 只验证软件行为。真正的任务指标需要固定评价契约和获准的执行后端。
- **报告写作**：借鉴 PaperSolver 的章节化草稿与评审修订；未执行方案、软件测试和真实实验分别标注，不凭模型回答补造结果。
- **来源可查**：MIT 原始来源与修改说明保留；运行时不导入上游大脚本。此次是机制级拆分，未承诺复制原版全部功能或复现论文成绩。

```bash
# 提案 → 代码候选 → 报告草稿；不执行生成代码
python -m sage laboratory --mode offline --output projects/sage-lab-dry

# 仅允许内置的合成 fixture，验证修复、固定评价与报告链
python -m sage laboratory --mode offline --backend fixture --allow-execution --output projects/sage-lab-fixture
```

真实候选执行另需显式 Docker 后端、预安装固定镜像和冻结协议；本次未在 Docker 中做真实运行验证。当前内置评价契约为开发集标量预测 MSE，不能直接当成任意 AI 研究任务的完整评价器。

使用方法、默认 dry-run、执行后端要求和逐项迁移范围见[Agent Laboratory 迁移与运行说明](docs/agent-laboratory-migration.md)。原 `sage run` 仍是提案入口，不会因接入新模块自动开始实验。

## 将 CoI 融入博士生讨论

新增可选的 `hybrid` 讨论模式，位于生成候选之后、准备实验计划之前：

```text
各自的 CoI 文献链与候选 → 博士生发展提案 → 环形互评 → 采纳/拒绝与修订
                                              ↓
                         博士后选择与规划要求 → 实验计划 → 代码迭代 → 报告
```

每位博士生保留原始来源链、候选和修订历史。旧版 v1/v2 保持角色来源约束；research 使用 v3，共享已读取的证据卡，来源归属作为溯源信息。未知或失败的事实意见不能直接采纳；方法学意见可提出控制实验而不伪造引文。采纳要求由控制器跨轮保留并绑定到实验计划，修订后的想法重新检查相似工作。

```bash
python -m sage laboratory --mode offline --discussion-mode hybrid --backend fixture --allow-execution --output projects/sage-hybrid
```

默认开启 hybrid 时为 **2 位博士生、1 轮互评**；支持 2–4 位、1–3 轮，仍受同一个总调用预算限制。旧命令默认 `discussion-mode none`，方便关闭讨论做对照。角色共用模型并不等于独立专家。

组合提示词提供 `v1` / `v2` / `v3` 版本选择并记录哈希；research 默认 v3，4 个候选/角色、2 轮讨论。真实服务冒烟验证使用 2 个候选/角色、2 轮；4 角色版本目前仅有离线验证。尚未通过对照实验证明任一版本科研质量更优。

详见[讨论机制与参数](docs/coi-laboratory-discussion.md)与[验证记录](docs/hybrid-validation.md)。离线测试检查数据传递、来源归属和预算；不能据此断言讨论提高科研质量。

ARIS 的多视角构思、逐主张查新和评审收据已接入 research 提案路径，可调用固定原版评审门控。CORAL 原生 SubprocessGrader 支持受审查的表达式小测试，以及 `closed-loop` 的固定 GP 训练与留出评价。编码代理池、通用科研代码生成执行和独立科学复核尚未接入。[运行入口与边界](docs/aris-coral-runtime.md) · [整体整合设计](docs/aris-coral-integration.md)

## 慢慢建设，先把每一步做实

| 阶段 | 状态与下一步 |
|---|---|
| **基础与提案链** | 已提供：模块化代码、提示词、离线控制器、项目模板和来源记录 |
| **真实服务验证** | 已验证 DeepSeek + arXiv 提案链与失败处理；引用图、embedding、完整规模与科研质量对照仍待验证；记录 token/请求消耗，不等于账单费用 |
| **更多方法接入** | Agent Laboratory 的代码迭代与报告机制已分模块接入；原始项目未独立运行 |
| **受限实验执行** | 已有有界尝试与显式后端入口；生产隔离、可信审批、任务恢复仍需单独验收 |
| **独立评价与写作** | 报告草稿链已接入；独立科学评价、完整证据重建与真实研究质量仍待验证 |

[完整路线图](docs/roadmap.md)按验收条件推进，不承诺日期。karpathy/autoresearch 的计划任务按用户要求标为 `completed`，不再进入复现优先队列；其运行仍是 `not_run`，集成仍是 `not_integrated`。

## 导航与资料

| 我想…… | 从这里开始 |
|---|---|
| 跑通 SAGE、配置模型或查看产物 | [运行指南](docs/sage-runtime.md) |
| 了解模块、契约和科研人工门禁 | [模块地图](modules/README.md) · [架构](docs/architecture.md) · [研究工作流](docs/workflow.md) |
| 查工具、论文与评测 | [工具](catalog/tools.md) · [论文](catalog/papers.md) · [评测](catalog/benchmarks.md) · [精读路线](docs/reading-path.md) |
| 新建自己的研究项目 | [项目模板](templates/README.md) · [未执行的计划示例](examples/toy-regularization/README.md) |
| 核对来源和真实性边界 | [来源快照](sources/README.md) · [机器可读目录](catalog/records.json) · [抽查与纠错](catalog/verification.json) |
| 维护资料或贡献代码 | [贡献指南](CONTRIBUTING.md) · [资料维护](docs/catalog-maintenance.md) · [安全边界](SECURITY.md) |
| 使用或调整项目标志 | [SVG 资产与说明](assets/README.md) · [完整 logo](assets/sage-logo.svg) · [图标](assets/sage-icon.svg) |

<details>
<summary><strong>目录、项目工具与仓库结构</strong></summary>

```bash
python -m sage catalog search "hypothesis"
python -m sage catalog search --category benchmark
python -m sage project init my-first-study --title "我的第一个研究项目"
python -m sage project check-project projects/my-first-study
```

原入口 `python scripts/catalog.py ...` 和 `python scripts/research.py ...` 继续支持。项目初始化只创建 `draft` 模板，不调用模型、不运行实验；`--ready` 检查基本字段/路径，不代表科学有效或执行批准。目录收录不等于已核验或已集成。

```text
sage/                     自有运行包、分模块提示词、提供方与契约
assets/                   原创 SVG 标志与 README 横幅
modules/                  功能文档与旧 CoI 归档准备器
third_party/              CoI-Agent 与 Agent Laboratory 的来源快照、许可与清单
catalog/ · sources/       可检索目录、独立核验记录与原始资料
docs/                     运行、迁移、工作流、架构与路线图
templates/ · examples/    项目模板与明确标注未执行的计划示例
scripts/ · tests/         兼容工具、统一离线检查与回归测试
projects/                 默认不入 Git 的本地研究产物
```

`python scripts/coi.py inspect` / `prepare --destination projects/coi-agent-runtime` 保留用于核验归档、生成带五个补丁的私有副本，不安装或运行上游依赖，也不是 SAGE 主运行路径。风险见[归档说明](third_party/coi_agent/README.md)。

</details>

## 来源与许可

SAGE 的方法与派生提示词来自 [DAMO-NLP-SG/CoI-Agent](https://github.com/DAMO-NLP-SG/CoI-Agent)，对应论文 [Chain of Ideas](https://arxiv.org/abs/2410.13185)。固定来源、原始文件哈希、Apache-2.0 许可和修改说明均保留，见 [CoI 归档](third_party/coi_agent/README.md)、[NOTICE](NOTICE.md)与[许可说明](LICENSE-NOTICE.md)。上游名称和引用不因 SAGE 品牌而改写，也不表示上游背书。

Agent Laboratory 派生部分使用其 MIT 来源，版权归属与修改范围见 [Agent Laboratory 迁移说明](docs/agent-laboratory-migration.md)和 [NOTICE](NOTICE.md)。两个上游的许可证分别适用，不将 MIT 部分写成 Apache-2.0。

**本仓库尚未为全部原创部分指定统一开源许可证。** 第三方许可适用于对应部分；公开可见不自动授予全部内容的任意使用权。

仓库地址继续使用 `Awesome-AutoResaerch`，开发分支为 `feat/ai-research-workbench`。SAGE 是产品名称。当前以 CLI 和 GitHub README 为入口，后续逐步扩展。

---

<p align="center"><strong>让想法有来处，让未知被看见。</strong></p>
