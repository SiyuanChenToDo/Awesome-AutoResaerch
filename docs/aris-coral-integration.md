# ARIS / CORAL 源码分析与 SAGE 接入方案

日期：2026-10-18。本文保留接入前的完整设计。逐主张筛查、评审收据、原版 ARIS 门控和受限 CORAL TaskGrader 适配器现已实现；当前入口、限制与运行范围见[实际接入说明](aris-coral-runtime.md)。其余规划仍不代表已实现，不会因本文自动执行实验。

2026-10-19 阅读提示：本文的“当前”描述属于上述早期设计时点。后续原生研究者调度、会话恢复、固定轮次互评和综合门禁已实现，现行范围见[自主猜想入口](autonomous-conjectures.md)和[团队协议](native-team-protocol.md)。它们仍不意味着通用实验执行、独立科学验收或全部长期设计已经落地。

## 固定分析对象

| 项目 | 本次克隆的提交 | 许可 | 主要形态 |
|---|---|---|---|
| [ARIS](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep) | `15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee` | MIT | Markdown 工作流、共享契约、状态/评审工具与模型 CLI 桥接 |
| [CORAL](https://github.com/Human-Agent-Society/CORAL) | `0123dfb939b35228cf2c1fde224cd0561e727408` | Apache-2.0 | Python 实验组织、工作区、评分守护进程、编码代理适配与共享记忆 |

以下链接固定在上述提交，避免把未来版本当成本次分析依据。不是对上游论文效果的独立复现，也不依据 star 数推断质量。

## 推荐分工

保留 SAGE 为研究记录、预算与状态的唯一控制层：CoI 衍生的证据链负责可追溯调研，ARIS 提供可改造的方法和评审流程，Agent Laboratory 衍生模块继续承担规划/写作，CORAL 作为可选实验执行系统。先补强 ideation 和调研，再扩展实验端。

```text
研究 brief / 已有论文与代码
  → SAGE 检索、去重、选段阅读、证据卡
  → ARIS 式多视角候选与主张拆解
  → 每条主张的最近工作、反证与差异矩阵
  → 有来源的质疑/回应、评审来源记录
  → 固定试验协议、预算与评分器
  → 可选 CORAL 开发实验：提交 → 固定版本评分 → 尝试记录
  → SAGE 核对结果与主张、独立确认性评价、报告
  → 有条件接纳的长期研究记忆
```

这是完整设计目标。当前只落地逐主张筛查、评审收据与受限 CORAL 任务适配；长期记忆、多代理演化和通用研究任务仍未实现。新的 CORAL 任务入口独立于现有标量执行器。

## ARIS 实际怎样工作

1. **调研先于筛选。** [research-lit](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee/skills/research-lit/SKILL.md) 组合本地论文、可用知识库和多种联网源，记录来源是否实际贡献；默认不是完整全文精读。SAGE 应保留结构化证据卡，并借用其覆盖缺口管理与来源贡献记录，不能把搜索工具宣称找到的材料自动算已读。
2. **多视角生成，再机械合并。** [idea-creator](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee/skills/idea-creator/SKILL.md) 先做 landscape，再通过多种分析视角生成候选；去重与客观预算可行性先行，避免执行者仅凭“感觉弱”提前删除候选。评审排序分配试验名额；未入选不等于被反证。它还设计小试验，用实测而非只靠叙事重排。
3. **逐主张查新。** [novelty-check](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee/skills/novelty-check/SKILL.md) 提取 3–5 条核心技术主张，多种查询找最近工作，再交外部模型比较问题、机制和差异。它强调“附近有人研究”不是否决理由，方法创新与发现创新应区分；推荐 PROCEED / CAUTION / ABANDON。其默认有年份/会议限定且倾向宽容，移植时应动态设置日期并补历史奠基工作；SAGE 必须保留 `insufficient_evidence`，不能把可继续探索写成已确立创新。
4. **深评审和攻防。** [research-review](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee/skills/research-review/SKILL.md) 对方法、关键主张、最小修复与实验设计做迭代对话；[kill-argument](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee/skills/kill-argument/SKILL.md) 使用新上下文形成最强反对论证，再逐点回应，输出仍未解决的关键问题。用于 idea 时应改写为方法/证据审查，不能把论文阶段模板原样套上。
5. **有文件不等于有评审。** [idea_discovery_gate.py](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee/tools/idea_discovery_gate.py) 核对阶段、产物章节、reviewer 与 verdict ID；同族 provisional 与 accepted 区分。[review_gate.py](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee/tools/review_gate.py) 对不同后端有不同决策分支，不能概括成所有后端都强制同一种跨模型校验；部分身份来自调用者声明。SAGE 应统一记录实际返回模型、族、输入哈希、审查材料范围和收据，不从角色名推断独立性。
6. **闭环依赖宿主执行能力。** [research-pipeline](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee/skills/research-pipeline/SKILL.md) 串联发现、实验桥、有限评审循环与写作交接。Markdown 写着会执行，不等于当前服务器已经具备模型 CLI、GPU 任务或可验证的实验环境。

ARIS 最适合优先吸收：研究 brief、调研覆盖表、多视角候选、逐主张查新、最强反驳和评审来源收据。保留“可以继续研究”与“有证据支持”的区别，不移植固定模型名、固定评分阈值作为科学结论。

## CORAL 实际怎样工作

1. **输入是任务、种子代码与 grader。** [task validation](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/coral/task/validation.py) 检查配置并对种子运行评分；[GraderInterface](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/coral/grader/protocol.py) 是异步 `grade(codebase_path, tasks) → ScoreBundle`。这比 SAGE 当前 `predict(code, scalar_features) → list` 更通用，也要求我们真正提供任务级实现与评分器。
2. **代理工作区和被评分版本分开。** [worktree](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/coral/workspace/worktree.py) 管理工作区；[grader daemon](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/coral/grader/daemon.py) 对提交建立独立 checkout 再评分，防止评分过程中代码继续变化。attempt 保存提交、状态和反馈。适合补强当前代码编辑后的实验记录。
3. **共享知识并保留探索分支。** [notes](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/coral/hub/notes.py)、skills、尝试记录以及可选 islands 让代理交换经验或隔离探索方向；[deep-researcher](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/coral/template/agents/deep-researcher.md) 模板要求缺口表、原始来源与笔记对应。它有调研能力，但其核心优势是实验组织，不应替换我们的证据提炼与查新逻辑。
4. **停滞后反思/转向。** [heartbeat 配置](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/coral/config.py) 支持按次数或 plateau 触发；[pivot](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/coral/hub/prompts/pivot.md) 鼓励实现尚未尝试的结构方向。SAGE 只能在剩余已授权预算内采用；模板建议的多次试验不能覆盖停止条件。
5. **隔离必须看实际配置。** 同一 [config.py](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/coral/config.py) 中 sandbox 默认关闭、宿主用户隔离默认未配置，sandbox network 默认 open；工作区不是 OS 安全边界。当前版本提供 Docker 用户隔离，也提供 srt/bubblewrap 等宿主方案，故“没有 Docker 就绝对不能接”不准确，但必须实际验证所选方案，尤其不能让编码代理以服务器 root 身份读取评分私有区和凭据。
6. **预算分类不等于总成本。** [types.py](https://github.com/Human-Agent-Society/CORAL/blob/0123dfb939b35228cf2c1fde224cd0561e727408/coral/types.py) 区分 real / grader_error / tune；`max_real_attempts` 不能单独覆盖失败、调参、GPU 时间和模型成本。SAGE 外层仍需累计所有类别，超时终止整个进程树并保留运行痕迹。
7. **评分与科学结论分开。** 它支持真实计算 grader，也支持 rubric 模型 grader；分数的证据性质由具体实现决定。开发集 leaderboard 会被反复优化，最终确认集仍须另行冻结与隔离。共享有效技巧也不等于已证明一般规律。

CORAL 当前 Python 要求为 `>=3.11,<3.14`，依赖配置、HTTP、gateway 等；代理 CLI 需另外安装并认证。已有 DeepSeek API key 不等于 CORAL 的 DeepSeek Harness 编码代理可直接工作，后者是单独运行时。

## 具体接入位置与新增契约

| 能力 | 现有模块 | 建议改动 | 验收产物 |
|---|---|---|---|
| brief 与调研覆盖 | discovery / literature | 记录问题、机制、强基线、反例、实现、评测六类 coverage；只对缺口补检索 | 来源贡献表、未覆盖项及停止理由 |
| 多视角 idea | ideation | 同一证据库按瓶颈、机制、效率、反例等视角生成；按假设去重，保留淘汰理由 | 候选来源/视角、方法步骤、可证伪预测 |
| 逐主张查新 | review | 将现有候选级 nearest-work 扩展为主张级比较；新增历史检索和反对证据查询 | claim × 最近工作 × overlap/delta/unknown |
| 外部评审与攻防 | discussion / providers | reviewer 单独可配置；冻结同一证据包，记录身份与收据；采用控制器管理的修改账本 | ReviewReceipt、未解决关键异议及修订依据 |
| 小试验桥 | experiment_design / execution | 方案转为任务契约、种子代码和固定 grader；有外部执行条件后才开始 | baseline 结果、协议/代码/评分器哈希 |
| 实验组织 | 新的可选 coral adapter | 独立环境/子进程调用固定版本 CORAL，导出 task YAML，回收全部 attempt | ExperimentReceipt、指标、原始日志与成本 |
| 长期记忆 | 新的 memory 模块 | 导入有来源的经验，保留反证、适用条件与复查状态 | candidate/admitted/contested/retired 记录 |

建议三个新增的数据契约（设计草案，不是现有 API）：

- `ResearchClaim`：claim_id、可验证主张、假设/方法步骤、support/counter source IDs 与定位、最近工作差异、未知项、falsifier。不能把模型推断标成来源事实。
- `ReviewReceipt`：artifact/input hashes、实际 provider/model/family、材料范围、独立性（same-family/cross-family/unknown）、verdict、关键异议、响应收据和消耗。跨模型只是减少部分共同偏差，不是独立科学认证。
- `ExperimentReceipt`：协议/数据划分/评分器/代码提交哈希、parent attempt、环境、种子、退出状态、原始日志、开发指标、资源消耗与失败分类。评分器异常不得当成方法失效；两者都计总资源预算。

CORAL adapter 应与当前标量后端分开：保留旧 `ExecutionBackend.predict`，另设任务级 runner，而不是强迫所有研究变成一维 MSE。CORAL 中提交、grader 和 run 的 ID 映射回 SAGE 的项目与 attempt ID；外部 agent、检索与 gateway 的消耗通过回执计入。凭据只在运行环境注入，不出现在导出的 YAML、日志或任务提示中。

## 实施顺序与验收

**第一阶段：先提升输入与筛选。** 在已有证据卡上加 coverage、ResearchClaim、逐主张最近工作与反证、多视角候选。保留旧模式，做同论文/同模型/同预算输入消融；由人工核对事实支持率、关键信息覆盖、最接近工作遗漏和候选可执行性。不要将多写几个提示词当成质量提升完成。

**第二阶段：评审可信记录。** 加独立 reviewer 配置与收据、简短攻防、未解决问题进入计划。单模型时记录 provisional；空检索、无效模型身份或未读资料不能升级 accepted science。验证未知引文、伪造收据、跨轮要求丢失和预算超限等失败情况。

**第三阶段：CORAL 最小闭环。** 用独立环境与隔离用户，先在可复算的本地小任务上跑 seed baseline → 一个改变 → grader → 回收结果。先单代理验证，随后才比较多代理；验收评分代码不可写、私有答案不可读、超时后无孤儿进程、所有失败计费、提交和日志能复核。该小任务只能证明接通。

**第四阶段：真实科研。** 为选中课题补数据、算法、强基线与统计协议，再运行预算内最小试验与独立确认评价。没有这些输入，接入 CORAL 也只会更快搜索一个未定义的问题。

## 不应直接复制的部分

- 不安装整套 ARIS skills 覆盖现有入口；选择机制后在 SAGE 自有模块改写，保留 MIT 来源与修改记录。上游提示词不授予模型执行/发布权限。
- 不把两套调度器同时作为顶层控制器；SAGE 控制项目生命周期，CORAL 只管理一次获准的实验会话。
- 不让优化代理同时修改种子、评分器、测试集与成功阈值；不把“模型评审通过”当作实验成功。
- 不直接开放无界 parallel、heartbeat 或长期 memory 晋升；预算、停止、记忆接纳均需可核对。
- 不把两个仓库的完整副本提交进自有运行包。本次克隆用于外部源码分析；真正派生代码应按 MIT / Apache-2.0 分别记录来源、许可与修改。

结论：优先采用 ARIS 的问题分解、候选广度与有记录的评审，保留 SAGE 的证据卡/未知状态/预算账本；待任务级评分与隔离具备后，用 CORAL 补齐实验执行组织。当前没有足够实验证据判定任一整套上游优于现有实现。
