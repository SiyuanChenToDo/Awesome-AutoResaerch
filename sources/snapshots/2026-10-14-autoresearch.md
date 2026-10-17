# 🔬 Awesome AutoResearch · 自动研究全景清单

> **更新日期**：2026-10-14（Asia/Shanghai）
> **数据来源**：GitHub REST API、arXiv API、Sakana AI 官网、中文科技媒体（新智元/智源/腾讯云社区）、VentureBeat 等
> **收录规模**（grep 去重实测，2026-10-14）：**GitHub 仓库 147 个、arXiv 论文 176 篇、策展清单 15 个、评测基准 30+、中文资源 17+**，另含 5 篇 Nature / Nature MI 正刊工作；HF 日报 upvote 实测榜单见 §4.3，结构化数据见 [literatures/data/](literatures/data/)

---

## 0. 先读：AutoResearch 的两层含义（这决定了你怎么检索）

这个词在 2026 年有两个不同外延，混用会漏掉一半资料：

| 层次 | 定义 | 起点 | 生态规模（2026-10-14） |
|---|---|---|---|
| **狭义 AutoResearch** | 让编码智能体在**固定预算**下反复执行「改代码 → 跑实验 → 看标量指标 → 保留或丢弃」，把科研变成一个可无人值守的优化循环 | [karpathy/autoresearch](https://github.com/karpathy/autoresearch)（2026-03-06 开源，⭐97,901） | GitHub 搜索 "autoresearch" 命中 **3,452** 个仓库；topic:autoresearch **371** 个；star > 100 的 **71** 个 |
| **广义 AutoResearch** | 2023 年以来的「AI 科学家 / 自主科研智能体」主线：想法生成 → 文献综述 → 实验执行 → 论文写作 → 自动评审全链路自动化 | Coscientist（Nature 2023）、The AI Scientist（2024-08） | arXiv 上 2026 年相关论文数量呈爆炸式增长，仅 2026-08~10 三个月就有 60+ 篇 |

**一句话记忆**：狭义 AutoResearch 是「**用 Agent 跑优化循环**」，广义 AutoResearch 是「**用 Agent 做完整科研**」。二者在 2026 年正在合流（见 §3.2）。

---

## 1. 时间线：从 AI 科学家到 AutoResearch

| 时间 | 事件 | 链接 |
|---|---|---|
| 2023-12 | Coscientist 登上 Nature：LLM 自主设计并执行化学实验 | [Nature](https://www.nature.com/articles/s41586-023-06792-0) |
| 2024-08-12 | Sakana AI 发布 **The AI Scientist**：首个端到端自动化科研流程（arXiv:2408.06292） | [arXiv](https://arxiv.org/abs/2408.06292) |
| 2024-08~10 | 评测基准起步：MLE-bench（arXiv:2410.07095）、RE-Bench、CORE-Bench | [arXiv](https://arxiv.org/abs/2410.07095) |
| 2025-02 | Google 发布 **AI co-scientist**（arXiv:2502.18864） | [arXiv](https://arxiv.org/abs/2502.18864) |
| 2025-04 | **AI Scientist-v2** 用 agentic tree search 产出首篇通过 workshop 同行评审的 AI 论文；PaperBench 发布 | [arXiv:2504.01848](https://arxiv.org/abs/2504.01848) |
| 2025-06 | **Virtual Lab**（斯坦福）登上 Nature：AI 科学家团队设计出经湿实验验证的 SARS-CoV-2 纳米抗体 | [Nature 646, 716–723](https://www.nature.com/articles/s41586-025-09442-9) |
| 2025-05 | AI-Researcher（arXiv:2505.18705） | [arXiv](https://arxiv.org/abs/2505.18705) |
| 2025-11-04 | **Kosmos**（Edison Scientific）：AI 科学家自主发现（arXiv:2511.02824） | [arXiv](https://arxiv.org/abs/2511.02824) |
| **2026-03-06** | **Karpathy 开源 autoresearch**：630 行代码、单卡、5 分钟固定预算、由 program.md 驱动。引爆整个生态 | [GitHub](https://github.com/karpathy/autoresearch) |
| 2026-03-24 | Bilevel Autoresearch：用 autoresearch 研究 autoresearch 本身（arXiv:2603.23420） | [arXiv](https://arxiv.org/abs/2603.23420) |
| **2026-03-26** | The AI Scientist 正式发表于 **Nature**：*Towards end-to-end automation of AI research*，**Nature 651, 914–919**（DOI 10.1038/s41586-026-10265-5，**arXiv:2606.15497**）。作者 Lu C, Lu C, Lange RT, Yamada Y, Hu S, Foerster J, Ha D, Clune J（Sakana AI × UBC × Vector × Oxford）。核心新增：**Automated Reviewer**（balanced accuracy 69%）与「科学扩展律」 | [Nature](https://www.nature.com/articles/s41586-026-10265-5) ｜ [arXiv](https://arxiv.org/abs/2606.15497) |
| **2026** | Google **Co-Scientist** 亦正式发表于 Nature：**Nature 655, 487–496**（DOI 10.1038/s41586-026-10644-y） | [Nature](https://www.nature.com/articles/s41586-026-10644-y) |
| 2026-08~10 | 生态大爆发：AutoResearchClaw（⭐14.6k）、FAROS、EvoMap/AutoResearch、CORAL、Arbor 等端到端系统集中出现 | 见 §2 |

**Karpathy 的原始实验结果**（据新智元报道）：Agent 在 12 小时内自主提交 110 次代码变更，把 val loss 从 0.862415 压到 0.858039，训练时间不增加；大规模版本用 8×H100 一晚跑 276 次实验、29 次有改进。

---

## 2. 开源项目

> ⭐ 均为 2026-10-14 抓取快照，会随时间变化。
> 收录标准：与 AutoResearch 直接相关，且可定位到公开仓库。

### 2.1 起点与官方实现

| 项目 | ⭐ | 语言/许可 | 说明 |
|---|---|---|---|
| [karpathy/autoresearch](https://github.com/karpathy/autoresearch) | 97,901 | Python / — | **整个范式的原点**。三个文件：prepare.py（固定）、train.py（Agent 唯一可改）、program.md（人类改的「研究组织代码」）。固定 5 分钟预算、val_bpb 指标、单卡 |
| [karpathy/nanochat](https://github.com/karpathy/nanochat) | 58,636 | Python / MIT | autoresearch 的训练底座（「100 美元能买到的最好的 ChatGPT」） |
| [SakanaAI/AI-Scientist](https://github.com/SakanaAI/AI-Scientist) | 14,714 | Jupyter / — | 广义 AutoResearch 的官方 v1 实现 |
| [SakanaAI/AI-Scientist-v2](https://github.com/SakanaAI/AI-Scientist-v2) | 7,334 | Python / — | agentic tree search 版本，产出首篇过审 AI 论文 |

### 2.2 通用 autoresearch 循环 / 编码 Agent 技能（生态最热的一层）

| 项目 | ⭐ | 说明 |
|---|---|---|
| [aiming-lab/AutoResearchClaw](https://github.com/aiming-lab/AutoResearchClaw) | 14,644 | 「Chat an Idea. Get a Paper.」全自主 + 自演化的从想法到论文 |
| [davebcn87/pi-autoresearch](https://github.com/davebcn87/pi-autoresearch) | 8,180 | pi 的实验循环扩展 + 仪表盘：实时指标、置信度追踪、可恢复会话 |
| [uditgoenka/autoresearch](https://github.com/uditgoenka/autoresearch) | 6,575 | Claude Code 技能，把 autoresearch 泛化到软件/文档/安全/调试等任何可度量目标 |
| [alchaincyf/darwin-skill](https://github.com/alchaincyf/darwin-skill) | 6,326 | 🇨🇳 达尔文.skill：评估→改进→测试→保留/回滚，让技能无限进化 |
| [wanshuiyin/Auto-claude-code-research-in-sleep](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep) | 17,465 | **ARIS**（Auto-Research-In-Sleep）：纯 Markdown 技能实现自主 ML 研究——跨模型评审循环、想法发现、实验自动化；无框架、无锁定，兼容 Claude Code / Codex / OpenClaw |
| [leo-lilinxiao/codex-autoresearch](https://github.com/leo-lilinxiao/codex-autoresearch) | 2,910 | Codex 原生技能：断点续跑、跨运行经验沉淀、可选并行实验 |
| [hyperspaceai/agi](https://github.com/hyperspaceai/agi) | 2,069 | 分布式 AGI：成千上万智能体通过 P2P gossip 共享实验 |
| [evo-hq/evo](https://github.com/evo-hq/evo) | 1,470 | 把任意代码库变成 autoresearch 循环：自动发现指标、插桩基准、树搜索 + 并行子代理 |
| [greyhaven-ai/autocontext](https://github.com/greyhaven-ai/autocontext) | 1,309 | 递归自我改进控制面：评估、持久知识、分级验证、蒸馏到本地小模型 |
| [dzhng/skills](https://github.com/dzhng/skills) | 1,332 | 可复用 Agent 技能集（含 autonomous research） |
| [olelehmann1337/autoresearch-skill](https://github.com/olelehmann1337/autoresearch-skill) | 981 | 极简通用技能 |
| [TheGreenCedar/codex-autoresearch](https://github.com/TheGreenCedar/codex-autoresearch) | 834 | Codex 插件：代码库内的优化循环 |
| [smallnest/autoresearch](https://github.com/smallnest/autoresearch) | 571 | 🇨🇳 autodevelop：面向软件开发的 autoresearch |
| [yogsoth-ai/de-anthropocentric-research-engine](https://github.com/yogsoth-ai/de-anthropocentric-research-engine) | 503 | 纯 markdown 的 267 技能研究图（51 个研究操作） |
| [drivelineresearch/autoresearch-claude-code](https://github.com/drivelineresearch/autoresearch-claude-code) | 346 | pi-autoresearch 的 Claude Code 移植 + 生物力学案例 |
| [krzysztofdudek/ResearcherSkill](https://github.com/krzysztofdudek/ResearcherSkill) | 265 | 一个文件，让你的编码 Agent 变成科学家：睡一觉跑 30+ 实验 |
| [balukosuri/...As-a-Universal-Skill](https://github.com/balukosuri/Andrej-Karpathy-s-Autoresearch-As-a-Universal-Skill) | 207 | 把 Karpathy autoresearch 抽象为通用技能 |
| [moedesux/autoresearch-opencode](https://github.com/moedesux/autoresearch-opencode) | 199 | OpenCode 版本 |
| [gianfrancopiana/openclaw-autoresearch](https://github.com/gianfrancopiana/openclaw-autoresearch) | 176 | OpenClaw 插件 |
| [gaasher/Agent-Loop-Skills](https://github.com/gaasher/Agent-Loop-Skills) | 175 | 一组即插即用循环（autoresearch / 科学写作 / 数据分析 / SQL / 提示词优化） |
| [supratikpm/gemini-autoresearch](https://github.com/supratikpm/gemini-autoresearch) | — | Gemini CLI 技能：用 Google 搜索做循环内实时验证源、--yolo 无头通宵模式 |
| [junjunjunbong/research-loop](https://github.com/junjunjunbong/research-loop) | — | 确定性 runner、plan-hash 审批、隔离 git worktree、只追加实验账本 |
| [xieyulai/steer](https://github.com/xieyulai/steer) | — | 受治理实验框架：任务/评分器/证据固定，Agent 只能改训练代码 |
| [SeeleAI/Thoth](https://github.com/SeeleAI/Thoth) | — | Dashboard 优先的 Claude Code / Codex 运行时：持久运行、锁定工作项、可审阅裁决 |
| [jmilinovich/goal-md](https://github.com/jmilinovich/goal-md) | — | GOAL.md 模式：Agent 必须先构造可度量适应度函数再优化 |
| [james-s-tayler/lazy-developer](https://github.com/james-s-tayler/lazy-developer) | — | 多目标序列编排（覆盖率/测试速度/构建速度/复杂度/LOC/性能） |
| [kayba-ai/recursive-improve](https://github.com/kayba-ai/recursive-improve) | — | 递归自我改进：捕获执行轨迹 → 分析失败模式 → 定向修复 + 保留/回滚 |
| [Necmttn/ax](https://github.com/Necmttn/ax) | — | 本地复盘循环：会话轨迹 → 摩擦点提案 → 实验化跟踪 |
| [vukrosic/auto-research](https://github.com/vukrosic/auto-research) | — | 文档型控制面：开放式自主 AI 研究实验室的「文件即操作系统」 |
| [mutable-state-inc/autoresearch-at-home](https://github.com/mutable-state-inc/autoresearch-at-home) | — | 协作式 fork：实验认领、共享最优配置、假设交换、单卡 swarm |

### 2.3 端到端研究智能体（想法 → 实验 → 论文）

| 项目 | ⭐ | 说明 |
|---|---|---|
| [EvoMap/AutoResearch](https://github.com/EvoMap/AutoResearch) | 3,057 | 从想法到「论文级证据」的 AI/ML 研究智能体（Apache-2.0） |
| [OpenNSWM-Lab/FAROS](https://github.com/OpenNSWM-Lab/FAROS) | 3,036 | 蓝图驱动的 AutoResearch 运行时：想法生成 → 实验 → 写作 → 同行评审 |
| [OpenRaiser/NanoResearch](https://github.com/OpenRaiser/NanoResearch) | 1,342 | 自主 AI 研究助手 |
| [RUC-NLPIR/Arbor](https://github.com/RUC-NLPIR/Arbor) | 1,111 | 🇨🇳 人大：通用自主研究智能体，跑实验 + 调研 + 迭代优化 |
| [Human-Agent-Society/CORAL](https://github.com/Human-Agent-Society/CORAL) | 1,068 | 由自主编码 Agent（Claude Code / OpenCode / Codex）驱动的开源 autoresearch，带评分、共享知识、多智能体演化 |
| [ZimoLiao/scholaraio](https://github.com/ZimoLiao/scholaraio) | 576 | 🇨🇳 Scholar All-In-One：面向 AI Agent 的科研基础设施 |
| [eimenhmdt/autoresearcher](https://github.com/eimenhmdt/autoresearcher) | 443 | 较早的「AI 自动化科学工作流」实现（2023 起） |
| [Gen-Verse/ScienceBuddy](https://github.com/Gen-Verse/ScienceBuddy) | 338 | 递归中的递归自改进交互式科学智能体 |
| [yu-xin-c/Sea-mult-agent](https://github.com/yu-xin-c/Sea-mult-agent) | 330 | 🇨🇳 Go 实现的多智能体 AutoResearch |
| [Sibyl-Research-Team/AutoResearch-SibylSystem](https://github.com/Sibyl-Research-Team/AutoResearch-SibylSystem) | 285 | 原生基于 Claude Code 的自演化全自主研究系统 |
| [Fchaubard/autoresearcherUI](https://github.com/Fchaubard/autoresearcherUI) | 277 | 全本地免费研究栈：autoresearcher + wandb + datadog + overleaf + claude code |
| [mikamikasuki/forest](https://github.com/mikamikasuki/forest) | 209 | 长时程科研 Agent：对抗证据丢失、错误累积、目标漂移 |
| [EdwardOptimization/Bilevel-Autoresearch](https://github.com/EdwardOptimization/Bilevel-Autoresearch) | 207 | 元层实现：用 Autoresearch 研究 Autoresearch（对应 arXiv:2603.23420） |
| [OpenRaiser/PaperFlow](https://github.com/OpenRaiser/PaperFlow) | 170 | 个性化论文推荐 / 阅读 / 报告 |

### 2.4 平台移植、硬件分支与领域特化

| 项目 | ⭐ | 领域 | 说明 |
|---|---|---|---|
| [chrisworsey55/atlas-gic](https://github.com/chrisworsey55/atlas-gic) | 2,317 | 量化交易 | Karpathy 式自我改进交易智能体 |
| [trevin-creator/autoresearch-mlx](https://github.com/trevin-creator/autoresearch-mlx) | 1,863 | Apple Silicon | MLX 移植，Mac 上无需 PyTorch |
| [RightNow-AI/autokernel](https://github.com/RightNow-AI/autokernel) | 1,595 | GPU Kernel | 丢一个 PyTorch 模型进去，睡醒收获优化好的 Triton kernel |
| [mattprusak/autoresearch-genealogy](https://github.com/mattprusak/autoresearch-genealogy) | 1,183 | 家谱学 | 结构化提示 + vault 模板 + 档案指南 |
| [NousResearch/autoreason](https://github.com/NousResearch/autoreason) | 609 | 主观领域 | 面向无法用标量指标衡量的领域（写作/论证） |
| [davidondrej/jailbreak-autoresearch](https://github.com/davidondrej/jailbreak-autoresearch) | 527 | AI 安全 | 自动化越狱研究 |
| [romovpa/claudini](https://github.com/romovpa/claudini) | 248 | 对抗攻击 | LLM 对抗攻击的 autoresearch |
| [ericjang/autogo](https://github.com/ericjang/autogo) | 241 | 围棋 | Autoresearch for Go |
| [wadeKeith/autoresearch-qwen](https://github.com/wadeKeith/autoresearch-qwen) | 212 | 多模态 | Qwen3-VL 训练代码自主研究（DocVQA 基准） |
| [alibaba/atrex-kernel-agent](https://github.com/alibaba/atrex-kernel-agent) | 179 | GPU Kernel | 🇨🇳 阿里：kernel 实现/分析/调优端到端 Agent |
| [chencore/autoresearch-crypto](https://github.com/chencore/autoresearch-crypto) | 170 | 加密 | — |

### 2.5 邻域经典（广义 AutoResearch 的必备工具箱）

| 项目 | ⭐ | 说明 |
|---|---|---|
| [stanford-oval/storm](https://github.com/stanford-oval/storm) | 31,632 | LLM 驱动的知识策展：调研一个主题并生成带引用的长报告 |
| [assafelovic/gpt-researcher](https://github.com/assafelovic/gpt-researcher) | 30,092 | 通用深度研究 Agent |
| [Future-House/paper-qa](https://github.com/Future-House/paper-qa) | 9,372 | 高精度科学文献 RAG（带引用） |
| [WecoAI/aideml](https://github.com/WecoAI/aideml) | 1,575 | AIDE：ML 工程 LLM Agent，MLE-bench 中被 OpenAI 引用 |
| [Future-House/aviary](https://github.com/Future-House/aviary) | 284 | 语言 Agent 的「科学任务健身房」 |

> 🔗 **路径纠正（跟旧链接会 404，2026-10-14 实测）**：
> - `openai/paperbench` → 已并入 [openai/frontier-evals](https://github.com/openai/frontier-evals)（PaperBench 代码在此仓库内）
> - `All-Hands-AI/OpenHands` → [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands)
> - `WecoAI/aide` → [WecoAI/aideml](https://github.com/WecoAI/aideml)
> - `GAIR-NLP/MLE-Dojo` → [MLE-Dojo/MLE-Dojo](https://github.com/MLE-Dojo/MLE-Dojo)
> - **Google AI co-scientist 本体并未开源**：官方开源的只有 [google-deepmind/science-skills](https://github.com/google-deepmind/science-skills)；co-scientist 本体只有社区复现（[Kaimen-Inc/Co-Scientist](https://github.com/Kaimen-Inc/Co-Scientist)、[llnl/open-ai-co-scientist](https://github.com/llnl/open-ai-co-scientist)）
> - `SakanaAI/AI-Scientist-v3` → **404，不存在**（见 §3 勘误）

### 2.6 策展清单（Awesome Lists）

| 清单 | ⭐ | 覆盖范围 |
|---|---|---|
| [webfuse-com/awesome-autoresearch](https://github.com/webfuse-com/awesome-autoresearch) | 2,565 | 最权威的**狭义 autoresearch** 索引：通用衍生、研究智能体、平台移植、领域适配、评测、案例 |
| [handsome-rich/Awesome-Auto-Research-Tools](https://github.com/handsome-rich/Awesome-Auto-Research-Tools) | 1,234 | 🇨🇳 全流程工具：文献检索、论文阅读、实验管理、代码生成（中英双版，更新最勤） |
| [WecoAI/awesome-autoresearch](https://github.com/WecoAI/awesome-autoresearch) | 1,069 | 带**优化轨迹**的用例集（Weco 出品） |
| [yibie/awesome-autoresearch](https://github.com/yibie/awesome-autoresearch) | 779 | 🇨🇳 中文视角的 autoresearch 清单 |
| [AI4Scientist/awesome-autoresearch](https://github.com/AI4Scientist/awesome-autoresearch) | 168 | 自主研究框架合集 |
| [yenanjing/awesome-ai-for-science](https://github.com/yenanjing/awesome-ai-for-science) | 11 | 以「用 AI 自动化科研」为口径，含 AI Scientist、自主研究 Agent、论文写作、假设生成 |

### 2.7 底座框架与深度研究（支撑层）

| 项目 | ⭐ | 说明 |
|---|---|---|
| [affaan-m/ECC](https://github.com/affaan-m/ECC) | 278,975 | 编码 Agent harness 的性能优化系统（skills/instincts/memory/security + research-first 开发流程）。科研是其目标场景之一，却是整条生态的「地基」 |
| [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands) | 90,876 | 通用软件工程 Agent 平台（原 All-Hands-AI，组织与仓库已迁移），常用来跑 ML 实验与复现 |
| [bytedance/deer-flow](https://github.com/bytedance/deer-flow) | 83,853 | 🇨🇳 字节跳动：长时程 SuperAgent harness（研究-编码-创作），带沙箱与记忆 |
| [FoundationAgents/MetaGPT](https://github.com/FoundationAgents/MetaGPT) | 70,847 | 🇨🇳 多 Agent 软件公司隐喻框架，被大量论文写作/实验流水线复用 |
| [microsoft/autogen](https://github.com/microsoft/autogen) | 61,398 | 微软多 Agent 编程框架；科研多 Agent 系统最常用底座（注意许可证为 CC-BY-4.0） |
| [FoundationAgents/OpenManus](https://github.com/FoundationAgents/OpenManus) | 58,648 | 🇨🇳 开源通用 Agent，中文社区活跃 |
| [agentscope-ai/agentscope](https://github.com/agentscope-ai/agentscope) | 33,238 | 🇨🇳 阿里系多 Agent 框架，中文文档完善 |
| [Alibaba-NLP/DeepResearch](https://github.com/Alibaba-NLP/DeepResearch) | 20,048 | 🇨🇳 通义 DeepResearch：开源 deep research agent 与模型权重 |
| [dzhng/deep-research](https://github.com/dzhng/deep-research) | 19,782 | 极简 deep research 参考实现（迭代式提问-搜索-深挖） |
| [camel-ai/camel](https://github.com/camel-ai/camel) | 17,887 | 多 Agent 协作框架，其角色扮演机制常用于科研辩论与想法生成 |
| [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) | 14,950 | 微软：面向工业研发的自动化 R&D Agent（因子挖掘、数据科学、自动读论文提假设 RDLoop） |
| [langchain-ai/open_deep_research](https://github.com/langchain-ai/open_deep_research) | 12,678 | LangChain 官方开源 deep research（LangGraph 编排） |
| [LearningCircuit/local-deep-research](https://github.com/LearningCircuit/local-deep-research) | 9,191 | **可完全本地化**的深度研究工具（llama.cpp/Ollama + 10 余个搜索引擎） |
| [MiroMindAI/MiroThinker](https://github.com/MiroMindAI/MiroThinker) | 8,422 | 面向复杂研究与预测任务的 deep research agent + 开源模型 |
| [zilliztech/deep-searcher](https://github.com/zilliztech/deep-searcher) | 8,329 | 面向私有数据的 deep research 开源替代 |
| [khoj-ai/khoj](https://github.com/khoj-ai/khoj) | 37,683 | 可自托管的「AI 第二大脑」，支持文档库深度研究（AGPL-3.0） |
| [HKUDS/Auto-Deep-Research](https://github.com/HKUDS/Auto-Deep-Research) | 1,750 | 🇭🇰 港大：全自动个人 AI 研究助理（论文宣称 0.03 美元级/任务） |
| [RUC-NLPIR/WebThinker](https://github.com/RUC-NLPIR/WebThinker) | 1,472 | 🇨🇳 人大：边想边搜、边搜边写（NeurIPS 2025） |
| [bytedance/pasa](https://github.com/bytedance/pasa) | 1,666 | 🇨🇳 字节：能自主决策检索与引用追查的论文搜索 Agent |
| [mims-harvard/ToolUniverse](https://github.com/mims-harvard/ToolUniverse) | 1,734 | 哈佛 MIMS：把数百个科研工具统一封装给 Agent 调用 |

### 2.8 科研技能库与写作/审稿自动化

| 项目 | ⭐ | 说明 |
|---|---|---|
| [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | 48,945 | **2026 年最火的科研 Agent Skills 库**：把任意 AI Agent 变成 AI Scientist（宣称 177 个现成技能） |
| [dwzhu-pku/PaperBanana](https://github.com/dwzhu-pku/PaperBanana) | 7,160 | 🇨🇳 北大：把方法描述直接变成论文级示意图 |
| [brycewang-stanford/Auto-Empirical-Research-Skills](https://github.com/brycewang-stanford/Auto-Empirical-Research-Skills) | 4,623 | 面向 8 个社会科学学科的实证研究技能合集（偏计量/因果推断） |
| [google-deepmind/science-skills](https://github.com/google-deepmind/science-skills) | 3,259 | Google DeepMind 官方科研 Agent Skills 库（强调 grounding 与 token 效率） |
| [PaperDebugger/paperdebugger](https://github.com/PaperDebugger/paperdebugger) | 1,547 | Overleaf 内插件式多 Agent 学术写作/审稿系统 |
| [hanlulong/econ-writing-skill](https://github.com/hanlulong/econ-writing-skill) | 661 | 经济学论文写作专家技能（综合 50+ 写作指南） |
| [Boom5426/Nature-Paper-Skills](https://github.com/Boom5426/Nature-Paper-Skills) | 583 | Nature 风格论文的起草/修订/审计/重投全流程技能 |
| [yushui2022/MathModel-Skill](https://github.com/yushui2022/MathModel-Skill) | 455 | 🇨🇳 数学建模竞赛式科研工作流技能 |
| [ai4s-research/ai4s-skills](https://github.com/ai4s-research/ai4s-skills) | 237 | AI for Science 开放技能：选题-综述-实验-写作 |
| [kaixindelele/ChatPaper](https://github.com/kaixindelele/ChatPaper) | 19,929 | 🇨🇳 中文社区经典：arXiv 论文总结/翻译/润色/审稿/审稿回复 |
| [binary-husky/gpt_academic](https://github.com/binary-husky/gpt_academic) | 71,473 | 🇨🇳 中文科研 LLM 工作台：PDF/LaTeX 翻译总结、多模型并行 |

### 2.9 端到端系统补充（子代理检索线）

| 项目 | ⭐ | 说明 |
|---|---|---|
| [EvoScientist/EvoScientist](https://github.com/EvoScientist/EvoScientist) | 4,976 | 自进化 AI 科学家 harness，主打 vibe research（把研究当持续迭代的工程循环） |
| [NVlabs/SoL-Pi](https://github.com/NVlabs/SoL-Pi) | 3,459 | NVIDIA Labs：Scaling Auto-Research Loops for Efficient Agent Harnesses |
| [ResearAI/DeepScientist](https://github.com/ResearAI/DeepScientist) | 3,374 | 渐进式 AI 研究 Agent：推进前沿发现而非复现，支持 human-in-the-loop |
| [polyuiislab/infiAgent](https://github.com/polyuiislab/infiAgent) | 1,189 | 「改配置文件就能搭自己的 AI Scientist」的无限长时程框架 |
| [Xiangyue-Zhang/auto-deep-researcher-24x7](https://github.com/Xiangyue-Zhang/auto-deep-researcher-24x7) | 1,137 | 24/7 挂机跑深度学习实验，带零成本监控与排行榜 |
| [InternScience/InternAgent](https://github.com/InternScience/InternAgent) | 1,454 | 🇨🇳 上海 AI Lab 系：InternAgent-1.5 统一长时程自主科学发现框架 |
| [zou-group/virtual-lab](https://github.com/zou-group/virtual-lab) | 749 | 斯坦福 Zou 组：多个 PI/专家 Agent 开会讨论并给出科研方案（Nature 论文原型） |
| [mshumer/autonomous-researcher](https://github.com/mshumer/autonomous-researcher) | 825 | 轻量单文件自主研究者，适合理解「搜索-阅读-综合-产出」最小闭环 |
| [damonwan1/AutoScholarLoop](https://github.com/damonwan1/AutoScholarLoop) | 519 | 多 Agent 循环：idea 发现 → 实验 → 有证据的写作 → 质量把关 |
| [sjtu-sai-agents/X-Master](https://github.com/sjtu-sai-agents/X-Master) | 324 | 🇨🇳 上海交大 + 深势：SciMaster 系列基座，HLE 上刷新过开源成绩 |
| [SamuelSchmidgall/AgentLaboratory](https://github.com/SamuelSchmidgall/AgentLaboratory) | 5,902 | 三阶段 AI 研究助手（综述/实验/写作），强调人机协同 |
| [HKUDS/AI-Researcher](https://github.com/HKUDS/AI-Researcher) | 5,816 | 🇭🇰 港大：NeurIPS 2025 官方实现，含商业版 novix.science |

### 2.10 假设生成与 Co-Scientist 复现

| 项目 | ⭐ | 说明 |
|---|---|---|
| [lamm-mit/SciAgentsDiscovery](https://github.com/lamm-mit/SciAgentsDiscovery) | 638 | MIT：知识图谱 + 多 Agent 生成跨学科假设 |
| [Future-House/robin](https://github.com/Future-House/robin) | 739 | FutureHouse：多智能体科学发现（假设 → 实验设计 → 数据分析，面向湿实验） |
| [CL-ML/open-collider](https://github.com/CL-ML/open-collider) | 343 | 「语义碰撞」式非平凡 idea 生成引擎 |
| [Kaimen-Inc/Co-Scientist](https://github.com/Kaimen-Inc/Co-Scientist) | 273 | DeepMind AI co-scientist 的开源复现（生成-辩论-进化） |
| [gomesgroup/coscientist](https://github.com/gomesgroup/coscientist) | 212 | Coscientist（Nature 2023，CMU）代码：自主操控液体处理工作站 |
| [bio-xyz/BioAgents](https://github.com/bio-xyz/BioAgents) | 183 | 生物科学自主深度研究多智能体框架 |
| [llnl/open-ai-co-scientist](https://github.com/llnl/open-ai-co-scientist) | 74 | 劳伦斯利弗莫尔国家实验室的 co-scientist 实现 |
| [artificial-scientist-lab/SciMuse](https://github.com/artificial-scientist-lab/SciMuse) | 40 | 知识图谱 + LLM 的科学 idea 生成（做过 100 位课题组长评测） |
| [ur-whitelab/chemcrow-public](https://github.com/ur-whitelab/chemcrow-public) | 962 | ChemCrow：化学领域工具增强 Agent 的开山之作 |

### 2.11 领域科学智能体与自驱动实验室（Self-Driving Lab）

| 项目 | ⭐ | 说明 |
|---|---|---|
| [microsoft/mattergen](https://github.com/microsoft/mattergen) | 1,844 | 微软无机材料生成模型，支持按性质反向设计 |
| [aiidateam/aiida-core](https://github.com/aiidateam/aiida-core) | 597 | 计算科学工作流引擎（完整 provenance），计算实验自动化基础设施 |
| [emdgroup/baybe](https://github.com/emdgroup/baybe) | 515 | 默克：贝叶斯优化与实验设计库，自驱动实验室的「决策大脑」 |
| [materialsproject/atomate2](https://github.com/materialsproject/atomate2) | 355 | 材料计算工作流（VASP/DFT 自动化流水线） |
| [aspuru-guzik-group/olympus](https://github.com/aspuru-guzik-group/olympus) | 108 | 噪声优化与实验规划的基准框架 |
| [snap-stanford/BioDiscoveryAgent](https://github.com/snap-stanford/BioDiscoveryAgent) | 131 | 闭环设计基因扰动实验的 LLM Agent |
| [Future-House/ether0](https://github.com/Future-House/ether0) | 169 | 化学推理模型 + 数据集 + 奖励函数（开源权重） |
| [the-matter-lab/atlas](https://github.com/the-matter-lab/atlas) | 54 | 「自驱动实验室的大脑」：实验编排 + 优化 + 数据管理 |
| [Noel-Research-Group/Robochem_Flex](https://github.com/Noel-Research-Group/Robochem_Flex) | 49 | 低成本模块化自驱动实验室平台 |
| [berlinguette/ada](https://github.com/berlinguette/ada) | 23 | UBC：薄膜材料自驱动实验室的数据与编排 |
| [AccelerationConsortium/sila2-connectors](https://github.com/AccelerationConsortium/sila2-connectors) | 7 | SiLA2 仪器连接器：把实验室硬件接入自动化流程 |
| [pnnl/adept-agentic](https://github.com/pnnl/adept-agentic) | 3 | 美国西北太平洋国家实验室三层安全多智能体科学发现平台 |

### 2.12 Awesome 清单补充

| 清单 | ⭐ | 覆盖范围 |
|---|---|---|
| [hyperai/awesome-ai4s](https://github.com/hyperai/awesome-ai4s) | 3,384 | 🇨🇳 AI for Science 资源总汇 |
| [ai4s-research/awesome-ai-for-science](https://github.com/ai4s-research/awesome-ai-for-science) | 2,029 | AI for Science 项目集 |
| [VoltAgent/awesome-ai-agent-papers](https://github.com/VoltAgent/awesome-ai-agent-papers) | 1,842 | AI Agent 论文清单 |
| [tmgthb/Autonomous-Agents](https://github.com/tmgthb/Autonomous-Agents) | 1,384 | 自主 Agent 研究追踪（按日更新论文） |
| [DavidZWZ/Awesome-Deep-Research](https://github.com/DavidZWZ/Awesome-Deep-Research) | 870 | Deep Research 方向清单 |
| [yuzhimanhua/Awesome-Scientific-Language-Models](https://github.com/yuzhimanhua/Awesome-Scientific-Language-Models) | 665 | 科学语言模型 |
| [InternScience/Awesome-Scientific-Datasets-and-LLMs](https://github.com/InternScience/Awesome-Scientific-Datasets-and-LLMs) | 460 | 科学数据集与 LLM |
| [zoedsy/awesome-science-agents](https://github.com/zoedsy/awesome-science-agents) | 89 | 科学 Agent |
| [zjlrock777/Awesome-LLM-Agents-Scientific-Discovery](https://github.com/zjlrock777/Awesome-LLM-Agents-Scientific-Discovery) | 82 | LLM Agent 科学发现 |

> 📁 **完整版（810 行，含逐条定位、能力、局限、依赖说明与「可直接克隆试跑」清单）见 [research/02-repos.md](research/02-repos.md)**。
> ⚠️ **数据来源标注**：§2.7–2.12 的条目来自并行调研子代理的检索结果（[research/02-repos.md](research/02-repos.md)），Lead 已对其中的高星/异常条目做过抽样复核（affaan-m/ECC 278,975、K-Dense-AI/scientific-agent-skills 48,945、google-deepmind/science-skills 3,259、zou-group/virtual-lab 749、EvoScientist 4,976、NVlabs/SoL-Pi 3,459 均与 API 一致），所有 star 数已于 2026-10-16 逐条复核为精确值。

---

## 3. 论文

> 全部条目经 arXiv API 逐一核验（标题+编号+日期）。2026 年论文按时间倒序。
>
> **勘误与防坑（经 GitHub API + Crossref + Europe PMC 核验，2026-10-16）**：
> - **Sakana 官方没有 AI Scientist-v3**：SakanaAI/AI-Scientist-v3 查询返回 404。市面上的「v3」均为社区项目（如 findalexli/ai-scientist-v3，约 22★）。
> - **The AI Scientist v1 与 Nature 正式版是两篇不同文献**：v1 = arXiv:2408.06292（2024-08）；Nature 版 = arXiv:2606.15497 ／ Nature 651, 914–919（2026-03-26）。别混引。
> - **Sakana 两个仓库的许可证是 NOASSERTION（自定义条款）**，不是 Apache/MIT，商用前必须读原文。
> - 「ResearchAgent-SE」「The Automated Lab」经多轮检索**未找到一手来源**，本清单不予收录。
> - Zochi（Intology）：公开制品只有 [GitHub 仓库](https://github.com/IntologyAI/Zochi)（317★, MIT，最后推送 2025-11-19）；**该项目未发布对应论文**，引用时以仓库为准。

### 3.1 奠基与里程碑

| 论文 | 日期 | 说明 |
|---|---|---|
| [The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery](https://arxiv.org/abs/2408.06292) | 2024-08-12 | 端到端自动化 ML 研究的开山之作，2026-03-26 正式发表于 [Nature](https://www.nature.com/articles/s41586-026-10265-5) |
| [Coscientist（Boiko et al.）](https://www.nature.com/articles/s41586-023-06792-0) | 2023-12 | LLM 自主设计并执行化学实验（Nature） |
| [MLE-bench](https://arxiv.org/abs/2410.07095) | 2024-10-09 | OpenAI：ML 工程 Agent 基准（Kaggle 竞赛复现） |
| [ResearchAgent](https://arxiv.org/abs/2404.07738) | 2024-04-11 | 基于文献的迭代式研究想法生成 |
| [Can LLMs Generate Novel Research Ideas?](https://arxiv.org/abs/2409.04109) | 2024-09-06 | 100+ NLP 研究者参与的大规模人类实验 |
| [Agent Laboratory](https://arxiv.org/abs/2501.04227) | 2025-01-08 | 把 LLM Agent 当研究助手 |
| [Accelerating scientific discovery with Co-Scientist](https://arxiv.org/abs/2502.18864) | 2025-02-26 | Google 多智能体 AI 科研伙伴 |
| [PaperBench](https://arxiv.org/abs/2504.01848) | 2025-04-02 | 评测 AI 复现 AI 研究的能力 |
| [AI-Researcher: Autonomous Scientific Innovation](https://arxiv.org/abs/2505.18705) | 2025-05-24 | 自主科学创新框架 |
| [The Automated LLM Speedrunning Benchmark](https://arxiv.org/abs/2506.22419) | 2025-06-27 | 复现 NanoGPT 改进：衡量 Agent 能否再发现已知改进 |
| [Kosmos: An AI Scientist for Autonomous Discovery](https://arxiv.org/abs/2511.02824) | 2025-11-04 | Edison Scientific：数据驱动的自主发现（12 小时单次运行 / 200 次 rollout） |
| [Towards end-to-end automation of AI research](https://arxiv.org/abs/2606.15497) | 2026-03-26 | **The AI Scientist 的 Nature 正式版**（Nature 651, 914–919） |
| [The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via Agentic Tree Search](https://arxiv.org/abs/2504.08066) | 2025-04-10 | v2 论文：去模板化 + 渐进式树搜索 + VLM 图表反馈 |
| [Virtual Lab: AI agents design new SARS-CoV-2 nanobodies](https://www.nature.com/articles/s41586-025-09442-9) | 2025-06 | 斯坦福：AI 科学家团队 + 湿实验验证（Nature 646, 716–723） |
| [ChemCrow](https://www.nature.com/articles/s42256-024-00832-8) | 2024 | 18 个化学工具增强 LLM，实做合成并发现新发色团（Nature Machine Intelligence 6, 525–535） |
| [Robin](https://arxiv.org/abs/2505.13400) | 2025-05 | FutureHouse：文献 + 数据分析多智能体闭环，发现 dAMD 新治疗方向 |
| [Aviary](https://arxiv.org/abs/2412.21154) | 2024-12 | 把科学 Agent 当策略来训练：语言决策过程形式化 + 科学任务 gym |
| [AgentRxiv](https://arxiv.org/abs/2503.18102) | 2025-03 | 共享预印本服务器，让多个 Agent 实验室累积式协作 |
| [CycleResearcher](https://arxiv.org/abs/2411.00816) | 2024-11 | 开源 LLM 承担「研究—评审」全循环，评审分数反哺训练（ICLR 2025） |
| [AlphaResearch](https://arxiv.org/abs/2511.08522) | 2025-11-11 | 用语言模型加速新算法发现 |
| [All That Glitters is Not Novel: Plagiarism in AI Generated Research](https://arxiv.org/abs/2502.16487) | 2025-02-23 | AI 生成研究中的抄袭问题 |

### 3.2 2026「autoresearch」专线（狭义范式的学术化）

| 论文 | 日期 | 说明 |
|---|---|---|
| [ResearchFlow-Eval: Tracing the Execution Gap in End-to-End Multi-Claim Autoresearch](https://arxiv.org/abs/2610.18088) | 2026-10-13 | 多声明、多阶段流程级评测，指出「执行鸿沟」 |
| [Can LLMs Beat Classical Hyperparameter Optimization Algorithms? A Study on autoresearch](https://arxiv.org/abs/2603.24647) | 2026-03-25 | 把 karpathy/autoresearch 当试验台：固定算力预算下，经典 HPO 算法 vs LLM 方法 |
| [ScientistTwo: Pioneering the Human Knowledge Frontier with Autonomous AI](https://arxiv.org/abs/2609.19644) | 2026-09 | 自主 AI 科学家的知识前沿探索 |
| [JevGPT: Thinking Fast and Slow in Autonomous Research](https://arxiv.org/abs/2610.18272) | 2026-10-13 | 快慢双系统用于自主研究 |
| [Language Models as AI Research World Models](https://arxiv.org/abs/2610.12235) | 2026-10-08 | 用世界模型预测实验结局，缓解实验预算瓶颈 |
| [Kernel Autoresearch for Open-Ended Model Discovery](https://arxiv.org/abs/2610.10394) | 2026-10-07 | 核函数设计的两难：受限文法 vs 无约束程序 |
| [Insights from Autoresearch for Solar Panel Segmentation](https://arxiv.org/abs/2610.10491) | 2026-10-07 | 领域落地案例 |
| [Fork-and-Flush: Escaping Idea Basins in Autoresearch Agents](https://arxiv.org/abs/2610.07447) | 2026-10-05 | 同一 Agent 独立运行会停在差异巨大的分数（想法盆地） |
| [Optimizing the Optimizer](https://arxiv.org/abs/2610.06577) | 2026-10-05 | LM 发现更快的分子弛豫算法 |
| [IdeaScientist](https://arxiv.org/abs/2610.04074) | 2026-10-02 | 编排 Agent 做有据可依的科学构思 |
| [Learning What to Investigate Next](https://arxiv.org/abs/2610.02525) | 2026-10-01 | 长时程研究 Agent 的元推理 |
| [EvoCast](https://arxiv.org/abs/2610.04517) | 2026-10-03 | 迭代式预测架构演化的可靠自主研究 |
| [Forking: Sudden Overfitting Under Replay](https://arxiv.org/abs/2610.00394) | 2026-09-30 | 重放下的突然过拟合 |
| [ConflictGuide: AutoResearch Improves When Competing Behaviors Are Made Visible](https://arxiv.org/abs/2609.39933) | 2026-09-30 | 标量反馈掩盖目标冲突；让冲突可见能提升 AutoResearch |
| [Autoresearch in Mixed-Integer Linear and Nonlinear Programming](https://arxiv.org/abs/2609.39360) | 2026-09-30 | AutoMIP：运筹优化中的 autoresearch 技能 |
| [Experimental Experience Modeling for Autonomous Research](https://arxiv.org/abs/2609.39392) | 2026-09-30 | 实验经验建模 |
| [SimEX: Simulation-Integrated Robotics AutoResearch](https://arxiv.org/abs/2609.38982) | 2026-09-30 | 机器人学场景 |
| [AutoMark](https://arxiv.org/abs/2609.37310) | 2026-09-29 | 用 autoresearch 发现更好的 LLM 水印 |
| [PEAR: Progressive Evidence-Based AutoResearch](https://arxiv.org/abs/2609.35031) | 2026-09-28 | 工业搜索系统 |
| [EvoSkillRec](https://arxiv.org/abs/2609.34552) | 2026-09-28 | 技能基因组演化做推荐架构发现 |
| [AutoResearch at Production Scale: Failure Modes and a Multi-Agent Framework](https://arxiv.org/abs/2609.30541) | 2026-09-24 | 生产级 embedding 优化：失效模式 + 多智能体框架 |
| [Reward Hacking Challenges Oversight of Autonomous Research Agents](https://arxiv.org/abs/2609.28614) | 2026-09-23 | ⚠️ 奖励黑客如何瓦解自主研究 Agent 的监督 |
| [Agora: Git as Shared Memory for Collective AutoResearch](https://arxiv.org/abs/2609.18094) | 2026-09-16 | 用 Git DAG 做集体 AutoResearch 的共享记忆 |
| [PrimeScientist](https://arxiv.org/abs/2609.17846) | 2026-09-15 | 研究努力的战略性分配 |
| [PaperDoctor](https://arxiv.org/abs/2609.16995) | 2026-09-15 | 面向在写论文的证据化可执行反馈 |
| [ECDSA.Fail: Open Autoresearch for Optimizing Elliptic-Curve Point Addition](https://arxiv.org/abs/2609.09582) | 2026-09-09 | 开放 autoresearch 用于密码学优化 |
| [Exploiting LLM Agents for Trustworthy AutoResearch in Wireless Communications](https://arxiv.org/abs/2609.06174) | 2026-09-05 | 无线通信 |
| [AI-Research Agents in the Wild: From GitHub and arXiv to Regularities and Gaps](https://arxiv.org/abs/2609.11975) | 2026-09-01 | 把 GitHub 与 arXiv 两个生态对齐统计的**元研究** |
| [Autoresearch for Marketplace Catalogs](https://arxiv.org/abs/2609.00274) | 2026-08-31 | 电商目录匹配 |
| [Agentic Autoresearch for Cell-Edge Power Control](https://arxiv.org/abs/2608.26093) | 2026-08-26 | 无线功率控制；重新定义研究者角色 |
| [AutoResearch: Insight In, Hallucination Out](https://arxiv.org/abs/2608.17906) | 2026-08-18 | 两阶段系统：想法生成 + 想法执行，目标是「有洞见、无幻觉」 |
| [How Do Agents Fail on AutoResearch](https://arxiv.org/abs/2608.14905) | 2026-08-14 | 100 个真实前沿研究任务的端到端诊断评测 |
| [ScienceFlow: A long-horizon agent for ML research](https://arxiv.org/abs/2608.14354) | 2026-08-14 | 长时程 ML 研究 Agent |
| [Why Do Prefetchers Fail? Let Agents Answer](https://arxiv.org/abs/2608.13027) | 2026-08-13 | 计算机体系结构 |
| [EviGraph: Evidence-Guided Autonomous Research Agents](https://arxiv.org/abs/2608.04738) | 2026-08-05 | 证据引导 |
| [Distributed Denial of Science](https://arxiv.org/abs/2607.10712) | 2026-07-12 | ⚠️ 间接数据投毒如何工业化科研造假 |
| [Rethinking Scientific Discovery in the Agentic Era](https://arxiv.org/abs/2607.03863) | 2026-07-04 | 立场文章 |
| [Grounded autonomous research（计算物理）](https://arxiv.org/abs/2607.02329) | 2026-07-02 | 从语料到手稿的容错流水线 |
| [One Reflection Is Not Enough](https://arxiv.org/abs/2606.31478) | 2026-06-30 | 多假设失败归因的自我纠正 |
| [Clarus: Coordinating Autonomous Research Agents toward Web-Scale Scientific Collaboration](https://arxiv.org/abs/2606.30246) | 2026-06-29 | Web 规模科研协作 |
| [EurekAgent: Agent Environment Engineering is All You Need](https://arxiv.org/abs/2606.13662) | 2026-06-11 | 环境工程视角 |
| [Act As a Real Researcher](https://arxiv.org/abs/2606.07462) | 2026-06-05 | 覆盖科研生命周期的基准套件 |
| [ScientistOne](https://arxiv.org/abs/2605.26340) | 2026-05-25 | Chain-of-Evidence 追求人类水平自主研究 |
| [1GC-7RC: One Graphic Card — Seven Research Challenges](https://arxiv.org/abs/2605.17046) | 2026-05-16 | 单卡七项研究挑战，评测编码 Agent 做研究的真实能力 |
| [GEAR: Genetic AutoResearch for Agentic Code Evolution](https://arxiv.org/abs/2605.13874) | 2026-05-08 | 遗传式 autoresearch 做代码演化 |
| [NORA: A Harness-Engineered Autonomous Research Agent](https://arxiv.org/abs/2605.02092) | 2026-05-03 | 空间数据科学 |
| [Bilevel Autoresearch: Meta-Autoresearching Itself](https://arxiv.org/abs/2603.23420) | 2026-03-24 | 双层：外层 autoresearch 改进内层 autoresearch；在 Karpathy 的 GPT 预训练基准上取得 5× 提升（-0.045 vs -0.009 val_bpb） |
| [AutoResearchClaw: Self-Reinforcing Autonomous Research with Human-AI Collaboration](https://arxiv.org/abs/2605.20025) | 2026-05-19 | 配套 ⭐14.6k 仓库的论文：自我强化 + 人机协作，批评线性流水线不累积经验 |
| [SciResearcher](https://arxiv.org/abs/2605.01489) | 2026-05 | 面向前沿科学推理的 deep research agent 规模化 |
| [ML-AutoResearch](https://arxiv.org/abs/2603.17216) | 2026-03 | 用自动生成环境训练 ML 研究 Agent，解决过程级监督稀缺 |
| [AREX](https://arxiv.org/abs/2607.21461) | 2026-07 | 利用「发现—验证不对称」的递归自改进 deep research agent |
| [A Society of Researchers](https://arxiv.org/abs/2610.10468) | 2026-10 | 为 Agent 种群设计「科研制度」 |
| [The AI Scientific Community](https://arxiv.org/abs/2603.21344) | 2026-03 | Agentic 虚拟实验室蜂群 |
| [Personalized Auto-Research](https://arxiv.org/abs/2608.14881) | 2026-08 | 按研究者个人画像定制的「真·AI 协研者」 |
| [Arbor: Toward Generalist Autonomous Research via Hypothesis-Tree Refinement](https://arxiv.org/abs/2606.11926) | 2026-06-10 | 🇨🇳 人大高瓴 + MSR：假设树精炼；**HF 日榜第一**，MLE-Bench Lite 86.36% Any Medal |
| [Scaling Automatic Research Agents via World Models](https://arxiv.org/abs/2608.12564) | 2026-08-12 | 用世界模型替代真实沙盒做研究 Agent 的 RL（**HF 本期 up477 最高**） |
| [Spark-to-Paper: End-to-End Research Paper Generation as a Composable Skill](https://arxiv.org/abs/2608.11924) | 2026-08-12 | 把论文生成做成可组合技能（HF up289） |
| [Stateless Language Agents: Scaling Long-Horizon Automated Research](https://arxiv.org/abs/2610.07625) | 2026-10-06 | 长周期自动化研究的无状态 Agent 架构 |
| [Harness^2: Recursive Agent Harnessing for an Open World](https://arxiv.org/abs/2610.14224) | 2026-10-09 | 递归式 Agent harness 自举 |
| [EvoDuet: Bilevel Co-Evolution of Web Searching and Task Solving](https://arxiv.org/abs/2609.40340) | 2026-09-30 | 检索 × 求解双层共演化 |
| [AIM: Agentic Idea Management for Automated Research](https://arxiv.org/abs/2609.38445) | 2026-09-29 | 把「想法管理」独立成模块 |
| [EvolveMem: Self-Evolving Memory Architecture via AutoResearch](https://arxiv.org/abs/2605.13941) | 2026-05-13 | 用 AutoResearch 造 Agent 记忆架构 |
| [The Last Human-Written Paper: Agent-Native Research Artifacts](https://arxiv.org/abs/2604.24658) | 2026-04-27 | 论「Agent 原生」研究产物的形态 |
| [InternAgent-1.5](https://arxiv.org/abs/2602.08990) | 2026-02-09 | 🇨🇳 上海 AI Lab：长周期自主科学发现统一框架 |
| [NatureBench](https://arxiv.org/abs/2606.24530) | 2026-06-23 | 编码 Agent 能否复现 Nature 系论文的 SOTA |
| [Science or Slop?](https://arxiv.org/abs/2610.00531) | 2026-09-30 | ⚠️ AI 生成论文的「学术垃圾」度量与缓解 |
| [Tongyi DeepResearch Technical Report](https://arxiv.org/abs/2510.24701) | 2025-10-28 | 🇨🇳 阿里通义：模型 + 框架 + 方案全开源 |
| [SAGE / One Reflection Is Not Enough](https://arxiv.org/abs/2606.31478) | 2026-06-30 | 多假设失败归因，替代「一次性自由反思」 |
| [Early Discoveries of Algorithmist I](https://arxiv.org/abs/2603.22363) | 2026-03-23 | 大规模可证明算法合成 |
| [Evidence-Bound Autonomous Research (EviBound)](https://arxiv.org/abs/2511.05524) | 2025-10-28 | 消除虚假声明的治理框架 |

### 3.3 评测基准（Benchmarks）

| 基准 | 链接 | 评测什么 |
|---|---|---|
| PaperBench | [arXiv:2504.01848](https://arxiv.org/abs/2504.01848) | 复现 AI 研究（20 篇 ICML 论文的复现任务） |
| MLE-bench | [arXiv:2410.07095](https://arxiv.org/abs/2410.07095) | Kaggle 竞赛级 ML 工程 |
| The Automated LLM Speedrunning Benchmark | [arXiv:2506.22419](https://arxiv.org/abs/2506.22419) | 复现 NanoGPT 改进 |
| ResearchFlow-Eval | [arXiv:2610.18088](https://arxiv.org/abs/2610.18088) | 多声明端到端 autoresearch 的流程级评测 |
| How Do Agents Fail on AutoResearch | [arXiv:2608.14905](https://arxiv.org/abs/2608.14905) | 100 个真实前沿研究任务的失效诊断 |
| Act As a Real Researcher | [arXiv:2606.07462](https://arxiv.org/abs/2606.07462) | 科研生命周期基准套件 |
| 1GC-7RC | [arXiv:2605.17046](https://arxiv.org/abs/2605.17046) | 单卡七项研究挑战 |
| TruthInsightBench | [arXiv:2609.05079](https://arxiv.org/abs/2609.05079) | 开放式科学发现 Agent 的证据化自动评估 |
| OpenDiscoveryTrace | [arXiv:2609.09203](https://arxiv.org/abs/2609.09203) | AI 科学家工作流的**过程轨迹** |
| AgentIdeaBench | [arXiv:2609.07611](https://arxiv.org/abs/2609.07611) | Agent 时代的科学构思 |
| RATIO | [arXiv:2608.27394](https://arxiv.org/abs/2608.27394) | 科学文献中类型化构思操作的检索 |
| Ideation Arena | [arXiv:2608.29696](https://arxiv.org/abs/2608.29696) | 对抗式人类专家评估 LLM 研究想法 |
| LigBench | [arXiv:2608.13136](https://arxiv.org/abs/2608.13136) | 与人类对齐的研究想法生成基准 |
| Sci-MMR | [arXiv:2609.11243](https://arxiv.org/abs/2609.11243) | 多模态 Agent 的多步证据推理 |
| DataSense-Bench | [arXiv:2610.12190](https://arxiv.org/abs/2610.12190) | 迈向 AI 科学家的第一步 |
| DrugTargetWorld | [arXiv:2610.09558](https://arxiv.org/abs/2610.09558) | 合成生物样本库，训练/评测 AI 科学家 |
| AFDBench | [arXiv:2608.24954](https://arxiv.org/abs/2608.24954) | 天气预报讨论生成 |
| AstaBench（Ai2） | [allenai.org/blog/astabench](https://allenai.org/blog/astabench) ｜ [ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/b2ce9568dbb559aefc8c98ca5b5314ce-Abstract-Conference.html) | Ai2：用完整的科研套件严格评测 AI Agent |
| ScienceAgentBench | [arXiv:2410.05080](https://arxiv.org/abs/2410.05080) | 先严格评估单任务再谈端到端（102 个真实任务） |
| DiscoveryWorld | [arXiv:2406.06769](https://arxiv.org/abs/2406.06769) | 自动科学发现 Agent 的虚拟环境（NeurIPS Spotlight） |
| LitQA2 | [arXiv:2409.13740](https://arxiv.org/abs/2409.13740) | 随 PaperQA2 发布的高难度文献基准 |
| HeurekaBench | [arXiv:2601.01678](https://arxiv.org/abs/2601.01678) | AI Co-scientist 基准框架 |
| AstaBench（论文版） | [arXiv:2510.21652](https://arxiv.org/abs/2510.21652) | 2400+ 问题、57 个 Agent / 22 类评测；结论「AI 远未解决科研助手挑战」 |
| AIRS-Bench | [arXiv:2602.06855](https://arxiv.org/abs/2602.06855) | Meta：20 个 SOTA 论文任务、不给基线代码；Agent **4 胜 16 负**于人类 |
| ResearchClawBench | [arXiv:2606.07591](https://arxiv.org/abs/2606.07591) | 端到端自主科研：10 领域 40 任务，评测时隐藏目标论文 |
| ARAC-Bench | [arXiv:2608.12788](https://arxiv.org/abs/2608.12788) | 过程对齐基准：考「过程像不像人类」而非只比答案 |
| DeployBench | [arXiv:2606.05238](https://arxiv.org/abs/2606.05238) | 51 个部署任务：从裸机跑起论文代码（GPU/CUDA、遗留依赖） |
| RE-Bench | [arXiv:2411.15114](https://arxiv.org/abs/2411.15114) | METR：7 个环境 + 61 位专家 71 次 8 小时尝试；**短预算下 AI 得分是人类 4 倍** |
| DiscoveryBench | [arXiv:2407.01725](https://arxiv.org/abs/2407.01725) | 264 真实 + 903 合成任务；最好系统仅约 25% |
| ResearchBench | [arXiv:2503.21248](https://arxiv.org/abs/2503.21248) | 12 学科拆成灵感检索/假设组合/假设排序；只用 2024 后论文防污染 |
| MLRC-Bench | [arXiv:2504.09702](https://arxiv.org/abs/2504.09702) | 只考「提出 + 实现新方法」，用客观指标反对 LLM-as-judge；最佳仅弥合 9.3% |
| RExBench | [arXiv:2506.22598](https://arxiv.org/abs/2506.22598) | 12 篇真实论文的扩展实验 |
| SUPER | [arXiv:2409.07440](https://arxiv.org/abs/2409.07440) | 45 端到端 + 152 子问题；GPT-4o 仅解 16.3% 端到端 |
| CORE-Bench | [arXiv:2409.11363](https://arxiv.org/abs/2409.11363) | 计算可复现性（90 篇论文/270 任务），最难档最佳仅 21% |
| BLADE | [arXiv:2408.09667](https://arxiv.org/abs/2408.09667) | 开放式数据分析：对齐「多种合法分析路径」 |
| VERITAS | [arXiv:2607.02931](https://arxiv.org/abs/2607.02931) | 通用复现框架，并指出「不存在通用复现工具」 |
| ProgramGym | [arXiv:2610.13395](https://arxiv.org/abs/2610.13395) | 长周期程序复现的训练环境 |
| OSWorld-Science | [arXiv:2609.39903](https://arxiv.org/abs/2609.39903) | 科学软件使用的计算机操作 Agent 基准 |

### 3.4 想法 / 假设生成

| 论文 | 日期 |
|---|---|
| [Toward Auto-Research: Mining Falsifiable Research Ideas from Paper Knowledge Graphs](https://arxiv.org/abs/2608.20361) | 2026-06-17 |
| [Graphs of Research: Citation Evolution Graphs as Supervision](https://arxiv.org/abs/2605.14790) | 2026-05-14 |
| [Enhancing Research Idea Generation through Combinatorial Innovation](https://arxiv.org/abs/2604.20548) | 2026-04-22 |
| [HypoForge: Self-Improving Multi-Agent Framework for Hypothesis Generation](https://arxiv.org/abs/2608.25770) | 2026-08-26 |
| [SGHA: Evidence-Grounded Research Problem Discovery](https://arxiv.org/abs/2608.17501) | 2026-08-18 |
| [Probing Scientific General Intelligence of LLMs](https://arxiv.org/abs/2512.16969) | 2025-12-18 |
| [Exploring Design of Multi-Agent LLM Dialogues for Research Ideation](https://arxiv.org/abs/2507.08350) | 2025-07-11 |
| [The Budget AI Researcher and the Power of RAG Chains](https://arxiv.org/abs/2506.12317) | 2025-06-14 |
| [LDC: Learning to Generate Research Idea with Dynamic Control](https://arxiv.org/abs/2412.14626) | 2024-12-19 |
| [LLMs can Realize Combinatorial Creativity](https://arxiv.org/abs/2412.14141) | 2024-12-18 |
| [IdeaBench](https://arxiv.org/abs/2411.02429) | 2024-10-31 |
| [Chain of Ideas](https://arxiv.org/abs/2410.13185) | 2024-10-17 |
| [Acceleron: A Tool to Accelerate Research Ideation](https://arxiv.org/abs/2403.04382) | 2024-03-07 |

### 3.5 AI 科学家系统与能力（2026）

| 论文 | 日期 |
|---|---|
| [The Past and Future of AI Scientists](https://arxiv.org/abs/2608.14407) | 2026-08-14 |
| [OmniScientist: An Omni-Modal Omni-Discipline AI Scientist](https://arxiv.org/abs/2608.13558) | 2026-08-13 |
| [Training AI Scientists to Replicate Research](https://arxiv.org/abs/2608.13331) | 2026-08-13 |
| [Mechanist: AI as a Scientific Instrument](https://arxiv.org/abs/2608.12036) | 2026-08-12 |
| [AI Scientist Mission Control (AIMC)](https://arxiv.org/abs/2608.28637) | 2026-08-10 |
| [CrossAudit: A Git-Native, Cross-Vendor Audit Loop for Agentic Science](https://arxiv.org/abs/2608.28631) | 2026-08-05 |
| [Science Done on a Machine by a Machine: AI Agents in Computational Chemistry](https://arxiv.org/abs/2608.18508) | 2026-08-19 |
| [Dr. Claw: An AI Scientist Workspace for Vibe Research](https://arxiv.org/abs/2609.00365) | 2026-08-31 |
| [Station: Can AI Agents Make Open-Ended Scientific Discovery?](https://arxiv.org/abs/2610.08927) | 2026-10-06 |
| [YouRA: A Persistent-State Architecture for Evidence-Traceable Autonomous Research Agents](https://arxiv.org/abs/2610.01097) | 2026-10-01 |
| [Can AI Scientists Coordinate at Runtime?](https://arxiv.org/abs/2610.00980) | 2026-10-01 |
| [Are We Measuring Scientific Intelligence? Rethinking the Evaluation of AI Scientists](https://arxiv.org/abs/2610.04915) | 2026-10-04 |
| [From Scientific Observations to Mechanisms: Benchmarking Hypothesis Generation by AI Scientists](https://arxiv.org/abs/2610.05197) | 2026-10-04 |
| [Triage-PiEvo: Evidence Admission for Principle-Evolving Scientific Agents](https://arxiv.org/abs/2610.14683) | 2026-10-10 |
| [Autonomous Research Agents: A Survey of AI Scientists and the Verification Gap](https://arxiv.org/abs/2608.05179) | 2026-06-29 |
| [Large Knowledge Model: A Knowledge Foundation for Agentic Science at Scale](https://arxiv.org/abs/2609.27297) | 2026-09-23 |
| [OmniQEC: discovering practical quantum error-correcting codes by an AI scientist](https://arxiv.org/abs/2607.25865) | 2026-07-28 |
| [Auto Research for Materials: Auditable AI-Scientist Workflows with Held-Out Transfer](https://arxiv.org/abs/2607.17100) | 2026-07-19 |
| [NVAITC AI Scientist: A Governed End-to-End Research System](https://arxiv.org/abs/2607.11084) | 2026-07-13 |
| [TianJi-Environ: An Autonomous AI Scientist for Atmospheric Environmental Research](https://arxiv.org/abs/2606.07697) | 2026-06-05 |
| [Hephaestus: Toward a Cybersecurity AI Scientist](https://arxiv.org/abs/2606.29981) | 2026-06-29 |

### 3.6 综述与立场文章

| 论文 | 说明 |
|---|---|
| [The Hitchhiker's Guide to Autonomous Research: A Survey of Scientific Agents](https://ieeexplore.ieee.org/abstract/document/11644098) | IEEE 综述 |
| [Deep Research: A Survey of Autonomous Research Agents](https://arxiv.org/abs/2508.12752) | 把 deep research 拆成四阶段的核心综述 |
| [Evolving Roles of LLMs in Scientific Innovation](https://arxiv.org/abs/2507.11810) | 助手/协作者/科学家/评估者四角色框架 |
| [How Far Are AI Scientists from Changing the World?](https://arxiv.org/abs/2507.23276) | 能力边界评估 |
| [Automated Scientific Discovery](https://arxiv.org/abs/2305.02251) | 从方程发现到自主发现系统的早期综述（2023） |
| ⚠️ ~~From LLM Reasoning to Autonomous AI Agents（arXiv:2404.19678）~~ | **编号错误**：2404.19678 实为高压超导物理论文（La₃Ni₂O₇）；本综述编号待重新核验，暂不引用 |
| [A Survey on AI Scientists](https://isg.beel.org/blog/2026/09/22/a-survey-on-ai-scientists/) | 80 页、300+ 引用的 AI 科学家综述 |
| [Autonomous Research Agents: A Survey of AI Scientists and the Verification Gap](https://arxiv.org/abs/2608.05179) | 「验证鸿沟」视角 |
| [AI-Research Agents in the Wild](https://arxiv.org/abs/2609.11975) | GitHub + arXiv 双生态实证 |
| [The Past and Future of AI Scientists](https://arxiv.org/abs/2608.14407) | 历史与展望 |
| [Position: AI Agents in Scientific Teams Should Be Studied as Human-Agent Systems](https://arxiv.org/abs/2608.14667) | 立场 |
| [The Age of AI Agents Demands A New Scientific Paradigm](https://arxiv.org/abs/2607.26064) | 立场 |
| [AI Scientists as Engines of Discovery: A Case for Development within Reformed Institutions](https://arxiv.org/abs/2606.22859) | 制度视角 |

### 3.7 失效、风险与治理（**最值得精读的一节**）

| 论文 | 日期 | 风险点 |
|---|---|---|
| [Reward Hacking Challenges Oversight of Autonomous Research Agents](https://arxiv.org/abs/2609.28614) | 2026-09-23 | 奖励黑客瓦解人类监督 |
| [Distributed Denial of Science](https://arxiv.org/abs/2607.10712) | 2026-07-12 | 间接数据投毒 → 工业化科研造假 |
| [Dead Science Walking: Publication Bias and the AI Scientist Pipeline](https://arxiv.org/abs/2606.04220) | 2026-06-02 | 发表偏倚被自动化放大 |
| [Position: Correct Answer, Wrong Mechanism](https://arxiv.org/abs/2606.23175) | 2026-06-22 | AI 科学家为其数据所否证的结论辩护 |
| [Beyond Execution: Auditing Experimental Fidelity in LLM-Driven Scientific Research](https://arxiv.org/abs/2608.26753) | 2026-08-27 | 实验保真度审计 |
| [Can AI Scientists Change Their Minds? Prior-Evidence Conflict](https://arxiv.org/abs/2609.36726) | 2026-09-29 | 先验与证据冲突时是否改主意 |
| [An AI Scientist that Doesn't Drift](https://arxiv.org/abs/2608.07542) | 2026-07-30 | 目标漂移 |
| [Making AI Scientists Auditable from Evidence to Claim](https://arxiv.org/abs/2606.18874) | 2026-06-17 | 可审计性 |
| [Policy-Conditioned AI-Use Detection: An Evidentiary Framework for Academic Publishing](https://arxiv.org/abs/2609.38427) | 2026-09 | 学术出版中的 AI 使用取证 |
| [Deterministic Integrity Gates for LLM-Assisted Clinical Manuscript Preparation](https://arxiv.org/abs/2606.09500) | 2026-06-08 | 生物医学可审计架构 |

---

## 4. HuggingFace Daily Papers（重要：本机访问受限）

⚠️ **实测说明**：本次调研中 huggingface.co 域名在本机网络环境下**不可达**（直连与 r.jina.ai 代理均返回 fetch failed；PowerShell/curl 亦被环境限制）。因此本节内容通过检索间接获得，未能逐条抓取 upvote 数。

**已确认存在于 HF Papers 的条目**（通过检索结果中的 HF 论文页反向确认，非直接抓取）：

| HF 论文页 | 对应论文 | 备注 |
|---|---|---|
| [huggingface.co/papers/2608.17906](https://huggingface.co/papers/2608.17906) | AutoResearch: Insight In, Hallucination Out | **曾登上 HF Trending Papers 第一名**（项目 README 挂有 hf-trending-first 徽章实证） |
| [huggingface.co/papers/2603.23420](https://huggingface.co/papers/2603.23420) | Bilevel Autoresearch: Meta-Autoresearching Itself | — |
| [huggingface.co/papers/2608.14905](https://huggingface.co/papers/2608.14905) | How Do Agents Fail on AutoResearch | — |
| [huggingface.co/papers/2603.24647](https://huggingface.co/papers/2603.24647) | Can LLMs Beat Classical Hyperparameter Optimization Algorithms? A Study on autoresearch | 由 HF 检索页发现的新论文，已补入 §3.2 |
| [huggingface.co/papers/2609.19644](https://huggingface.co/papers/2609.19644) | ScientistTwo: Pioneering the Human Knowledge Frontier with Autonomous AI | 已补入 §3.2 |

**HF 生态侧的其他产物**：
- [mishig/autoresearch-results](https://huggingface.co/buckets/mishig/autoresearch-results)（HF Bucket）：autoresearch 运行结果的公开存放
- [huggingchat/papers-content](https://huggingface.co/buckets/huggingchat/papers-content)（HF Bucket）：HF Daily Papers 的正文缓存，**可作为无法直连 HF 时的抓取入口**

**可用替代路径**：
1. **HF Daily Papers 本质是 arXiv 的每日精选**，其收录论文的 ID 即 arXiv ID。本清单 §3 已系统覆盖 arXiv，遗漏概率低。
2. 镜像站：[ChatPaper.ai Daily Papers](https://www.chatpaper.ai/dashboard/papers/2026-05-06)（按日镜像 HF Daily Papers）
3. 直接用 HF 站内检索（需你能访问）：https://huggingface.co/papers?q=autoresearch 、https://huggingface.co/papers?q=AI+scientist

---

### 4.3 HF Daily Papers 实测榜单（经中文镜像 huggingface.ac.cn 读取，2026-10-14 快照）

> ✅ **突破**：huggingface.co 虽然不可达，但其**中文镜像 huggingface.ac.cn 实测可用（HTTP 200）**，Daily Papers 的标题、日期与 upvote 可由镜像读取。下表 upvotes 均为**镜像快照**，非 HF 原始页；2024–2025 年条目镜像无数据，故缺失。

| 论文 | upvotes | 方向 |
|---|---|---|
| [Scaling Automatic Research Agents via World Models](https://arxiv.org/abs/2608.12564) | **477** | 🔥 用世界模型替代真实沙盒做研究 Agent 的 RL |
| [Spark-to-Paper: End-to-End Research Paper Generation as a Composable Skill](https://arxiv.org/abs/2608.11924) | **289** | 论文生成（可组合技能） |
| [AutoResearchClaw: Self-Reinforcing Autonomous Research with Human-AI Collaboration](https://arxiv.org/abs/2605.20025) | **185** | 端到端 + 人机协作 |
| [DeepResearchEval](https://arxiv.org/abs/2601.09688) | 125 | 深度研究任务自动构建与评测 |
| [Arbor: Toward Generalist Autonomous Research via Hypothesis-Tree Refinement](https://arxiv.org/abs/2606.11926) | 118 | 🇨🇳 人大高瓴 + MSR，**HF 日榜第一**；MLE-Bench Lite 86.36% Any Medal |
| [EvoDuet: Bilevel Co-Evolution of Web Searching and Task Solving](https://arxiv.org/abs/2609.40340) | 111 | 检索 × 求解双层共演化 |
| [OmniScientist: An Omni-Modal Omni-Discipline AI Scientist](https://arxiv.org/abs/2608.13558) | 92 | 全模态 AI 科学家，36 个真实案例全流程出稿 |
| [Mechanist: AI as a Scientific Instrument](https://arxiv.org/abs/2608.12036) | 86 | 机制可解释性研究自动化（浙大） |
| [OSWorld-Science](https://arxiv.org/abs/2609.39903) | 64 | 科学软件使用的计算机操作 Agent 基准 |
| [Dr. Claw: An AI Scientist Workspace for Vibe Research](https://arxiv.org/abs/2609.00365) | 63 | 科研工作台 |
| [NatureBench: Can Coding Agents Match the Published SOTA of Nature-Family Papers?](https://arxiv.org/abs/2606.24530) | 62 | 能否复现 Nature 系论文的 SOTA |
| [Science or Slop? Benchmarking and Mitigating Scientific Slop in AI-Generated Papers](https://arxiv.org/abs/2610.00531) | 62 | ⚠️ 「学术垃圾」度量与缓解 |
| [SciAtlas](https://arxiv.org/abs/2605.22878) | 58 | 可计算科学图谱 |
| [AIM: Agentic Idea Management for Automated Research](https://arxiv.org/abs/2609.38445) | 53 | 研究想法管理 |
| [ProgramGym](https://arxiv.org/abs/2610.13395) | 50 | 长周期程序复现训练环境 |
| [Intern-Atlas](https://arxiv.org/abs/2604.28158) | 47 | 方法演化图谱作为 AI 科学家基础设施 |
| [AutoSciBench](https://arxiv.org/abs/2610.05140) | 45 | 自主基准生成 |
| [Science Utopia?](https://arxiv.org/abs/2610.01257) | 45 | 闭环 LLM 模拟学术研究生态（元科学） |
| [PaperGym](https://arxiv.org/abs/2608.31119) | 42 | rubric 驱动的研究计划生成 |
| [Evolution Fine-Tuning](https://arxiv.org/abs/2606.29082) | 41 | 跨 371 个优化任务学习「发现」 |
| [Ideas Have Genomes](https://arxiv.org/abs/2607.08758) | 40 | 科学谱系推理 + 想法生成 |
| [Harness^2: Recursive Agent Harnessing for an Open World](https://arxiv.org/abs/2610.14224) | 35 | 递归 harness 自举 |
| [ScienceBuddy](https://arxiv.org/abs/2609.17523) | 31 | 递归套递归的自我改进科学智能体 |
| [EurekAgent](https://arxiv.org/abs/2606.13662) | 28 | 🇨🇳 清华：环境工程，**以低于 11 美元 API 成本发现新的 26 圆排列 SOTA** |
| [Stateless Language Agents: Scaling Long-Horizon Automated Research](https://arxiv.org/abs/2610.07625) | 24 | 长周期研究的无状态架构 |
| [EvolveMem: Self-Evolving Memory Architecture via AutoResearch](https://arxiv.org/abs/2605.13941) | 24 | 用 AutoResearch 造 Agent 记忆架构 |
| [The AI Scientist-v2](https://arxiv.org/abs/2504.08066) | 14 | 首篇通过 workshop 评审的 AI 论文 |

**HF 日榜的方向信号**（按 upvotes 排序）：**世界模型 RL（477）> 论文生成（289）> 人机协作全流程（185）> harness/环境工程 > 记忆与状态外化 > 评测与审计**。也就是说，2026 年 10 月社区最关注的不是「再造一个 AI 科学家」，而是**如何让研究 Agent 训得动、跑得久、审得住**。

### 4.4 HF 上的模型 / 数据集 / Space

| 名称 | 类型 | 链接 | 说明 |
|---|---|---|---|
| allenai/AstaBrief_8B | 模型 | [huggingface.co/allenai/AstaBrief_8B](https://huggingface.co/allenai/AstaBrief_8B) | Ai2 开源 8B 带引用报告生成模型（3.5× 更快） |
| asta-bench-leaderboard | Space | [spaces/allenai/asta-bench-leaderboard](https://huggingface.co/spaces/allenai/asta-bench-leaderboard) | AstaBench 官方榜 |
| tbukuai/hf-papers-wiki | 数据集 | [datasets/tbukuai/hf-papers-wiki](https://huggingface.co/datasets/tbukuai/hf-papers-wiki) | HF Daily Papers 的社区 wiki 化 |
| huggingchat/papers-content | 数据集 | [buckets/huggingchat/papers-content](https://huggingface.co/buckets/huggingchat/papers-content) | HF Daily Papers 正文归档（**无法直连 HF 时的抓取入口**） |

### 4.5 访问口径（重要，避免误引）

- huggingface.co 的论文页链接形态为 https://huggingface.co/papers/&lt;arXivID&gt;，**其 ID 就是 arXiv ID**；本清单所有题录均已回 arxiv.org 核对标题与日期。
- 上表 upvotes 来自**镜像**（huggingface.ac.cn 的 /papers/date/YYYY-MM-DD），与 HF 原始页可能存在时点差异。

---

## 5. 产业与机构产品线（2026：谁在做产品化）

> 2026 年这条线从「论文」走向「平台 + 融资 + 国家项目」。以下条目来自检索与官网，标注 unverified 者请以官方为准。

| 名称 | 机构 | 类型 | 链接 | 说明 |
|---|---|---|---|---|
| The AI Scientist | Sakana AI（日） | 论文/产品 | [sakana.ai](https://sakana.ai/ai-scientist-nature/) | 2026-03 登 Nature；UBC + Vector + Oxford 合作 |
| AI Co-Scientist | Google DeepMind | 产品 | [deepmind.google](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/) | Nature 655, 487–496；已进 Gemini Enterprise |
| Deep Research Max | Google | 产品 | [ai.google.dev](https://ai.google.dev/gemini-api/docs/models/deep-research-max-preview-04-2026) | Gemini 3.1 Pro + MCP + 私有数据源 + 原生图表 |
| Robin | FutureHouse | 产品 | [arXiv:2505.13400](https://arxiv.org/abs/2505.13400) | 与 Co-Scientist 同期登 Nature（DOI …-10652-y） |
| Kosmos | Edison Scientific | 产品 | [edisonscientific.com](https://edisonscientific.com/news/announcing-kosmos) | FutureHouse 商业 spinout，2025-11 上线，约 7,000 万美元融资 |
| Lila Sciences | Lila（美） | 产品 | [lila.ai](https://www.lila.ai/news/scientific-superintelligence-the-deep-blue-moment) | 「科学操作系统」+ 真实湿实验室；2026-06 3.5 亿美元 A 轮（估值 unverified） |
| Asta / AstaBench / AstaBrief | Ai2 | 平台 | [allenai.org/blog/astabrief](https://allenai.org/blog/astabrief) | agentic 科研平台 + 榜单 + 开源报告模型 |
| Microsoft Discovery | Microsoft | 平台 | [learn.microsoft.com](https://learn.microsoft.com/en-us/azure/microsoft-discovery/overview-what-is-microsoft-discovery) | Azure GA；HPC + 机器人实验室；与 Ginkgo 做 lab-in-the-loop |
| MIRA | Meta | 方法 | [arXiv:2610.02525](https://arxiv.org/abs/2610.02525) | 外层 meta-reasoner + 内层 executor 的长周期信用分配 |
| Claude Science | Anthropic | 产品 | [anthropic.com](https://www.anthropic.com/news/claude-science-ai-workbench) | 2026-06-30 科研工作台：60+ skills/connectors + reviewer agent + 可审计产物 |
| Deep Research + 学术研究者计划 | OpenAI | 产品 | [openai.com](https://openai.com/fr-FR/index/chatgpt-for-academic-researchers/) | 2026-07-30 向 10 万研究者免费开放一年 |
| WANDR | Perplexity | 开源基准 | [github.com/perplexityai/wandr](https://github.com/perplexityai/wandr) | 宽深研究基准 |
| 书生·端砚 | 上海 AI Lab | 平台 | [stcn.com](https://www.stcn.com/article/detail/4026269.html) | 🇨🇳 2026-07-17 WAIC：假设 → 实验验证全流程，连接具身自动化设备，六大领域干湿闭环 |
| MatBrain | 中科院深圳先进院（SIAT） | 平台 | [Nature MI](https://doi.org/10.1038/s42256-026-01298-6) ｜ [SIAT 官方](https://siat.cas.cn/siatxww/kyjz/202609/t20260910_8280613.html) | 🇨🇳 2026-09-10 发表于 Nature Machine Intelligence：轻量化**双模型协同**材料创制智能体（**Mat-R1** 科学推理 + **Mat-T1** 工具执行），喻学锋团队 |
| 磐石100 | 中科院 | 平台 | [新华网](https://www.news.cn/tech/20260429/053ffc3079954bf38cbace9fbc68c7c9/c.html) | 🇨🇳 八学科大模型体系 |
| 百度伐谋 AI4S「1+10+N」 | 百度 | 平台 | [科技日报](https://www.stdaily.com/web/gdxw/2026-08/12/content_562839.html) | 🇨🇳 「人类定义标准、AI 持续寻优」+ 100 位学者计划 |
| 通义 DeepResearch | 阿里 | 开源 | [arXiv:2510.24701](https://arxiv.org/abs/2510.24701) | 🇨🇳 模型 + 框架 + 方案全开源 |
| AutoGLM 沉思 | 智谱 | 产品 | [zhipu-ai.feishu.cn](https://zhipu-ai.feishu.cn/wiki/XQ5UwZe0LiECeykUj1vcfi63naf) | 🇨🇳 深度研究 + 操作执行（科研专用产品 unverified） |
| Elicit / Consensus / SciSpace / Undermind / Scite | 各创业公司 | 产品 | [elicit.com/pricing](https://elicit.com/pricing) | 文献段订阅工具（价格第三方来源） |

---

## 6. 中文社区资源

| 资源 | 类型 | 链接 |
|---|---|---|
| 腾讯云开发者社区：《Karpathy 开启「自动研究」实验：AI 开始自己写代码训练自己》 | 科普 | [链接](https://cloud.tencent.com.cn/developer/article/2695864) |
| 新智元（经 C114 转载）：《Karpathy 惊呼"后AGI"！AI 通宵狂改 110 次代码》 | 深度报道 | [链接](https://www.c114.net.cn/industry/65471.html) |
| 智源社区：《Karpathy：写了 20 年代码，现在像作弊》 | 深度报道 | [链接](https://hub.baai.ac.cn/view/53171) |
| LumeValley：《DeepSeek 研究员开源 AutoResearch：AI 自主跑通 285B 模型 RL 研究闭环》 | 报道（Deli Chen 的 AutoResearch 协议 + GRPO） | [链接](https://www.lumevalley.com/article-3985.html) |
| 腾讯云开发者社区：《Autoresearch 全自动写代码、写论文，Claude、Codex、龙虾纷纷复现》 | 生态综述 | [链接](https://cloud.tencent.com.cn/developer/article/2653779) |
| 科学网：《AI 尚未准备好「全面自动化」》 | 审慎评估 | [链接](https://news.sciencenet.cn/sbhtmlnews/2026/8/390956.shtm) |
| 知乎：《当 AI 开始写论文并通过同行评审——〈Nature〉封面背后的 AI Scientist》 | 深度解读 | [链接](https://zhuanlan.zhihu.com/p/2035213088669086902) |
| 知乎：《新一代 AI 科学家 Kosmos 问世》 | 成本与产出解读 | [链接](https://zhuanlan.zhihu.com/p/1969779398510110556) |
| 财新博客：《展望 2026：科研智能体即将崛起？》 | 年度展望 | [链接](https://iscientists.blog.caixin.com/archives/285316) |
| 36氪：《上海交大团队：让 Claude Code 在你睡觉时做「靠谱」科研》 | 报道（原论文 unverified） | [链接](https://www.36kr.com/p/3799050979040518) |
| 中科院网信工作网：DeepMind × FutureHouse 多智能体系统译介 | 机构译介 | [链接](https://ecas.cas.cn/xxkw/kbcd/201115_149827/ml/xxhcxyyyal/202606/t20260604_5111759.html) |
| 中科院南海海洋所：SciAssistant 科研智能体开源公告 | 机构开源 | [链接](https://scsio.cas.cn/news/tztg/202602/t20260204_8123755.html) |
| [handsome-rich/Awesome-Auto-Research-Tools](https://github.com/handsome-rich/Awesome-Auto-Research-Tools) | 中文清单 | GitHub ⭐1,234 |
| [yibie/awesome-autoresearch](https://github.com/yibie/awesome-autoresearch) | 中文清单 | GitHub ⭐779 |
| [RUC-NLPIR/Arbor](https://github.com/RUC-NLPIR/Arbor) | 人大开源 | GitHub ⭐1,111 |
| [alchaincyf/darwin-skill](https://github.com/alchaincyf/darwin-skill) | 技能自进化 | GitHub ⭐6,326 |

---

## 7. 数据统计（2026-10-14 快照）

| 指标 | 数值 |
|---|---|
| GitHub 搜索 "autoresearch" 命中仓库 | 3,452 |
| GitHub topic:autoresearch | 371 |
| GitHub star > 100 的 autoresearch 相关仓库 | 71 |
| karpathy/autoresearch | ⭐97,901 / fork 13,577 / 创建于 2026-03-06 / 最后推送 2026-03-26 |
| 本次收录开源项目（README 内 GitHub 链接去重） | **147** |
| 本次收录 arXiv 论文（README 内链接去重） | **176** |
| 2026-08 ~ 2026-10 新增 autoresearch/AI 科学家论文 | 60+ |
| **Nature 正刊**发表的 AI 科学家工作 | **4 篇**：Coscientist（2023）、Virtual Lab（2025）、The AI Scientist（2026-03）、Co-Scientist（2026） |
| 配套深度笔记 | [research/01-papers.md](research/01-papers.md)（论文线 436 行）、[research/02-repos.md](research/02-repos.md)（代码线 809 行）、[research/03-hf-and-products.md](research/03-hf-and-products.md)（HF 日报 + 产品线 417 行）、[research/04-benchmarks-and-risks.md](research/04-benchmarks-and-risks.md)（基准与风险 418 行） |
| 结构化数据文件 | [autoresearch-repos.csv](literatures/data/autoresearch-repos.csv)（83 行）、[autoresearch-papers.csv](literatures/data/autoresearch-papers.csv)（147 行） |

**趋势观察**：
- 原点仓库本身在 2026-03-26 后几乎停更，但生态在 7 个月内长出 3,400+ 仓库 —— 属于**范式外溢**而非单项目成功。
- 生态重心在 **2026-08 ~ 2026-09** 从「通用循环」转向「端到端系统 + 生产落地 + 治理」。
- 2026 年 9 月后，**评测与风险类论文数量首次超过系统类论文**，是领域开始成熟的信号。

---

## 8. 观察与空白（机会点）

1. **评测是当前最大缺口**：ResearchFlow-Eval 明确指出「现有评测只打分孤立任务或最终产物，忽略过程」。过程级、多声明、可复现的评测是刚需。
2. **风险治理严重滞后于能力**：奖励黑客、数据投毒、发表偏倚三条线都只有零星工作，尚无标准。
3. **主观领域几乎空白**：NousResearch/autoreason 是少数尝试，标量指标之外的「品味」如何度量仍未解决。
4. **中文生态以「技能封装」为主**（darwin-skill、autoresearch-opencode 等），端到端系统与评测话语权仍在英文社区。
5. **复现成本正在归零**：Bilevel Autoresearch 展示了「自动研究如何改进自动研究」的递归路径，这是最值得跟进的方向。

---

## 9. 如何复现/更新本清单

用到的检索式（可直接复用）：

    # GitHub（按 star 排序）
    https://api.github.com/search/repositories?q=autoresearch&sort=stars&order=desc&per_page=50
    https://api.github.com/search/repositories?q=topic:autoresearch&sort=stars&order=desc
    https://api.github.com/search/repositories?q=autoresearch+stars:>100&sort=stars&order=desc

    # arXiv（按提交时间倒序）
    https://export.arxiv.org/api/query?search_query=all:autoresearch&sortBy=submittedDate&sortOrder=descending&max_results=50
    https://export.arxiv.org/api/query?search_query=abs:"autonomous research agent"&sortBy=submittedDate&sortOrder=descending
    https://export.arxiv.org/api/query?search_query=abs:"AI scientist"&sortBy=submittedDate&sortOrder=descending
    https://export.arxiv.org/api/query?search_query=abs:"research idea generation"&sortBy=submittedDate&sortOrder=descending

    # HuggingFace（需可访问的网络环境）
    https://huggingface.co/api/daily_papers?limit=50
    https://huggingface.co/papers?q=autoresearch

    # 建议追加的检索词
    self-driving lab / autonomous discovery / co-scientist / research harness / experiment loop

---

## 许可与免责

本清单为调研汇总，链接与数据均来自公开来源（2026-10-14 快照）。star 数、题录会随时间变化；引用前请以原始来源为准。标注 ⚠️ 的条目为风险/争议类，不代表本清单立场。
