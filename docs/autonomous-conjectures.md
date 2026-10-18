# 只配置模型 API 的自主猜想发现

`sage autonomous` 是新的原生代理入口。它从空研究项目开始，代理自己选择论文、阅读提炼、提出猜想、检索近似工作和反证、接受批评并修订。没有预置论文库、预写猜想或固定符号回归实验。

这是对早期接入范围的纠正：旧 `closed-loop` 用的是固定实验程序，旧 ARIS 接口主要调用 `review_gate.py`，旧 CORAL 接口主要调用 `SubprocessGrader`。那些验证不能证明原生自主科研已经接通。

## 三个项目如何协作

| 组件 | 实际接入 | 职责 |
|---|---|---|
| CORAL | 原版 `AgentManager`、DeepSeek Harness runtime、grader daemon、独立提交 checkout、attempt、heartbeat | 启动持续代理，保存与评分尝试，反馈后继续探索，按预算停止 |
| ARIS | 上述五项核心技能的原始完整文件逐字写入 `AGENTS.local.md`，由 DSH 原生工作区指令加载器提供；其他完整技能目录经原生 skill-filesystem 挂载，额外工具加载以原生日志为准 | 调研、8–12 个不同候选、近似工作比较、批评、修订及 Research Wiki |
| SAGE / CoI 改造部分 | 真实检索、官方可用 arXiv 正文读取、跨章节证据卡、原文段落 ID 绑定、按需补读、来源范围和失败记录 | 给代理提供可追溯研究证据，避免只读摘要或把全文无差别塞入提示词 |
| DeepSeek Harness | 官方 `@deepseek-ai/dsh` headless 运行时 | 使用模型 API 驱动技能、文件、shell 和研究 MCP 工具 |

ARIS 和 CORAL 源码固定为 `15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee`、`0123dfb939b35228cf2c1fde224cd0561e727408`，安装在归档快照之外，不修改 `third_party`。此入口没有使用要求 Codex 登录的完整 `dsh-aris` 发行插件：它直接挂载原版技能，再使用明确标注的 SAGE API 评审传输。不能把这说成原版跨模型验收已经通过。

## 一次安装，以后只需 API

目前原生宿主适配器面向 Linux x86_64 / Python 3.12+。Windows 用户可在 AutoDL 上运行。首次安装需要 root 创建 CORAL 的非 root 代理账户；会安装固定版本 Node、pnpm、DSH、CORAL、ARIS 和 Python 依赖：

```bash
python scripts/setup_autonomous.py
```

将密钥设置在环境变量 `DEEPSEEK_API_KEY` 或 `SAGE_OPENAI_API_KEY` 中。不要把密钥写入 Git、研究提示词、公开配置或启动参数。之后运行：

```bash
python -m sage autonomous --allow-live --output projects/conjectures-001
```

可选研究方向：

```bash
python -m sage autonomous --allow-live \
  --topic "可靠、节省计算的多智能体科研系统" \
  --output projects/conjectures-002
```

没有方向时，代理自行调研 AI / 机器学习的若干子领域后选择一个可检验的问题。方向、目标期刊、预算可以配置；无需人工选论文或提供猜想。当前默认 API 型号 `deepseek-flash`，按 2026-10-18 的[官方映射](https://api-docs.deepseek.com/quick_start/pricing/)对应 DeepSeek-V4.1-Flash-1017，支持 1M tokens 上下文；也可设置 `SAGE_MAIN_MODEL`。上游模型别名会变化，实际响应记录另行保留。此原生入口目前针对 DeepSeek，通用 OpenAI-compatible 编码运行时尚未验证。

DSH 固定为一致发行的 `0.2.0-rc.2`。其 Messages 接口使用 `https://api.deepseek.com/anthropic`，SAGE 阅读/批评器的 Chat Completions 使用 `https://api.deepseek.com`，不能混用。自有 Messages 网关使用 `SAGE_DSH_BASE_URL` 单独配置，参见 [DeepSeek 官方接口说明](https://api-docs.deepseek.com/guides/anthropic_api/)。

默认四位独立会话的研究者、两轮互评，由团队产生总计 8–12 个候选，再由 slot 0 综合、批评修订并提交 CORAL。每位研究者有自己的工作区和候选历史；同家族 API 的多个上下文不能称为独立模型专家。初稿全部齐备后才开放同伴稿，每轮互评齐备后才修订，最终稿保留每个候选的来源和逐条处理意见，见[团队协议与验收要求](native-team-protocol.md)。这补齐了此前原生主线未接入团队讨论的问题；此前 run-10 仍是单主研究者的历史结果，不能用新的配置追溯改变。

可通过 `--researchers 1` 使用单研究者流程，或设置 `--researchers 2/3/4` 和 `--discussion-rounds 1/2/3`。多研究者只用 slot 0 执行 `coral eval`，其他研究者通过团队工具交换冻结提案、批评和修订。

默认 4 次 CORAL 正式提交、2 小时总时限；研究工具共享额度默认为 `160 × 研究者数`，默认四人为 640 次、单人为 160 次。显式 `--max-tools` 始终表示团队总额度，不再乘人数。本轮四人运行实际用了 205 次工具调用，原先单人额度不能直接作为四人的默认额度。可以调整 `--max-attempts`、`--max-tools`、`--wall-seconds`；它们用于约束运行，不是科研内容或每节篇幅的压缩规则。各研究者的原生 DSH 调用和重试另有自己的记录，研究工具次数不能当作总 API 调用数或费用上限。

安装记录在 `$SAGE_NATIVE_HOME/runtime.json`，默认 `~/.cache/sage/native/runtime.json`。已有环境可显式指定 `--coral-python`、`--aris-root`、`--dsh`。研究主进程也需能导入 openai、pypdf；可使用安装目录 `python/bin/python` 运行本仓库。部署脚本采用 pnpm，避免观察到的 npm 对 DSH 预发布依赖循环解析问题。

## 看哪些输出

- `launch.json`：启动时框架文件哈希、上游版本、方向，明确是否预置论文和猜想。
- `aris-inputs.json`：提供给原生 DSH 的五项原始技能、完整文件哈希与指令文件哈希。挂载目录或代理自述不算已读取证明。DSH 的默认 64 KiB 指令预算不足以容纳这些全文，入口自动扩展预算以保留正文和随后的当前任务；输入交付也不等于方法执行正确。技能文件直接通过原生指令加载器读取，避免原文 shell 示例被 CORAL 的配置插值器当成变量解析。
- `manager.log` 与 `native-run/.coral/public/logs/`：原生管理器和代理日志。
- `native-run/agents/<实际代理名>/`：每位研究者自己的 Research Wiki、`WORKFLOW_TRACE.md`、提案和修订文件；slot 0 还保存综合的 `conjectures.json`、中文 `CONJECTURES.md`。实际代理名称由 CORAL 保存。
- `native-run/.coral/public/attempts/`：各次提交、评分和失败原因；所有尝试保留。
- `service-private/evidence.json`、`events.jsonl`：管理器拥有的原始检索、阅读范围、证据卡、请求与评审收据。代理不能改写该目录。
- `result.json`：工程完成状态、实际检索/阅读/批评数量、`research_team` 团队过程汇总、框架运行中是否变化及独立验收状态。
- 顶层 `conjectures.json`、`CONJECTURES.md`：从已评分的冻结提交保留副本中直接导出的猜想与中文报告；`selected_grade` 记录对应提交和文件哈希。没有符合来源契约的提交时，不冒充成功产物。

证据卡提炼最多读取分布在文档中的 12 个片段，覆盖方法、实验、限制等部分。新版让模型选择原文段落 ID，由程序回填未经改写的原文和位置，避免模型重打公式或标点导致有效信息整批丢失。每条来源绑定单独校验，非法主张被拒绝并记录，其他有效主张保留；不能用来源 ID 绑定冒充语义蕴含证明。

每篇保留最多 40 条原子提炼及所需原文依据，传输容量为 60,000 字符，保留未读范围和被拒绝项。完整的已提取文本保存在管理器私有原文快照中；代理可用 `passages` 先查看章节索引，再按需补读至多四个原始片段。正文不可用时保留 abstract_only/metadata_only；不得补写原文没有提供的细节。

每次批评在调用模型前保存原始猜想文件、实际证据包和请求，后续修改不覆盖先前版本。批评明确检查变量定义、方向/单调性、条件和已有理论，并区分历史淘汰候选与当前选中候选。

`review-1`、`review-2` 等是按发生顺序编号的评审调用，可能分别对应不同修订版本，不能当作多个独立 reviewer 或把分数合并为共识。`grading=false` 是代理主动请求的批评，`grading=true` 是 CORAL 冻结提交触发的正式模型评价；同一个 API 型号的新上下文均保留为同家族建议。

团队的 `team` 工具另行记录研究者提案、同伴互评与逐条采纳/拒绝/未知决议。它们不与上述批评或 CORAL 正式评分混计。正式评分在团队模式下还要求团队轮次完整、综合候选来源齐全，且实际稿件 SHA 与已登记综合版本一致；源码配置和软件契约通过不代表多研究者实时运行或质量提升已验证。

评分器先核对候选是否有真实来源、提炼证据、最近工作比较、反例检索和可证伪条件，再向模型发送实际猜想文件及来源。它不运行候选代码。模型分数是提案成熟度建议，不能证明创新性、有效性或可发表性。原始文件和失败保留用于复核。

正式评分通过 root 私有 Unix socket，只接受 CORAL 的私有 grader checkout。代理研究工具的 HTTP 通道不能提交正式评分；知道研究工具令牌也不能越过文件系统权限调用评分通道。

## 单 API 与独立评审

只有一个 DeepSeek API 时，批评器使用同一模型家族的新上下文。它可以帮助系统发现错误、淘汰和改进猜想，但不能伪称跨模型独立验收。

ARIS 原始跨家族门槛不改，独立接受状态保留 `REVIEW_UNAVAILABLE / BLOCKED`。系统仍应交付清楚标记为 provisional 的、可检验的科学猜想。实验复现、独立科学评价和正式投稿属于后续阶段，不能用 API 调用成功或 grader 分数替代。

当前隔离是 CORAL 的 Linux 非 root 用户隔离，管理器和证据服务保持 root，代理无权写框架/评分器或读取 root 私有证据目录。DSH 在该账户下自动执行，不等待交互批准；这是宿主账户隔离，不是 Docker 容器，也不提供网络域名白名单。初次部署须确保项目和工具父目录可遍历，研究文件继续留在被忽略的 `projects/` 下。

接入层在启动 CORAL 管理器时清除附加用户组，防止上游只设置 UID/GID 时把 root 的附加组传给代理；并先以真实代理账户核对框架、技能和运行配置的读取权限，保存 `isolation-preflight.json`。这项宿主适配不修改原版 CORAL 源码。

DSH 将中间进度写到 stderr，当前 CORAL 的 stdout 停滞时钟会误杀仍在工作的 headless 会话，因此此入口关闭该时钟；外层总时限和原生异常退出恢复继续生效。依赖版本按已安装 CORAL 环境冻结，并可从同版本 wheel 缓存建立原生评分环境，避免重复下载和隐式升级。

### 原会话续接修复（2026-10-18）

较早运行中的 `No session_id ... starting fresh` 来自原版 CORAL 的 DSH 适配器：它固定返回空会话 ID，也未传入恢复参数。此前把限制归于 DSH headless 本身不准确；实际安装的 DSH `0.2.0-rc.2` 已支持 `--json` 和 `--session-id`。

当前入口通过 CORAL 的公开自定义 runtime 接口加载 `sage.autonomous.dsh_runtime:ResumableDeepSeekRuntime`，保留原始上游源码。适配器读取原生 `session` 事件，核对真实 ID 和工作目录，在 reflect/pivot 反馈或异常续跑时传回原 ID。DSH 自行恢复持久化消息和工具状态；新反馈提示词完整保留。外层启动器的所有 `--patch` 参数必须位于 headless 的 `--json` 参数之前。

管理器在 `session-state/` 中保存绑定 agent 和绝对工作目录的明确指针，权限为目录 0700、文件 0600，放在代理工作区之外。CORAL 的通用重启校验只识别 Claude 日志时，运行器可恢复这个明确记录，不扫描“最新会话”目录。损坏、身份冲突或原生会话不存在时明确失败，不悄悄新开会话。`runtime-config/` 是管理器拥有、代理只读的模型配置目录，避免 root 写入代理可修改的 `.dsh` 路径。跨目录迁移、跨机器恢复和分支研究历史未在本次验证。

公共 CORAL 日志只保留会话 ID、目录、事件类型和文本长度；不复制 `thinking` 或完整工具参数、结果。完整原生会话仍由 DSH 私有存储管理。软件验证用真实随机标识回忆、原始 CORAL SIGINT/反馈方法和未知会话拒绝来核对恢复，不把 warning 消失当作成功证明，见[续接验证](native-session-validation-20261018.md)。

评审器仍在新上下文中接收对应的完整稿件与证据，不共享研究者的对话历史。修复研究代理的记忆衔接不等于提高科学评分；此前运行的原始版本和分数保留，尚未完成从同一冻结检查点出发的科研质量对照。
