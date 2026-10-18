# ARIS / CORAL 实际接入入口

这是可运行的增量实现，范围小于[整体整合方案](aris-coral-integration.md)。不安装上游 skills、不启动自动发布；上游源码与依赖单独安装。

## ARIS 方法与原版门控

`research` 配置现在启用 `claim_review=true`。也可以在 `--config` JSON 中显式设置：

```json
{"claim_review": true, "max_research_claims": 3, "queries_per_claim": 2, "evidence_mode": "capsule"}
```

流程由同一控制器执行：每个候选按不同分析视角生成 → 从实际读过的证据提取拟议主张与反证条件 → 按主张有界检索 → 对最近工作逐条比较 → 形成整体的有范围判定。讨论改动候选后也重新走此路径。补充检索仍服从日期、请求、token 和时间预算。

`NoveltyAssessment.research_claims` 保留每条主张、输入来源、查询、实际比较来源、差异、证据限制与决定性试验。`review_receipt` 保留 idea/dossier 哈希、请求与响应模型、响应 ID/哈希、预算中的调用序号、独立性与原版 ARIS 门控结果。引文 ID 检查不证明语义支持；分数和 ready 不等于科学有效。

原版 ARIS 门控是可选外部执行依赖，显式配置其目录：

```bash
export SAGE_ARIS_ROOT=/path/to/Auto-claude-code-research-in-sleep
```

适配器只运行固定提交 `15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee` 中经 SHA-256 核对的 `tools/review_gate.py`，通过标准输入之外的无密钥参数调用 `llm-chat` 分支。不匹配则拒绝。未配置目录时收据明确 `native_aris_gate=null`，不能声称调用了原版代码。

默认 reviewer 复用主模型，标为 provisional。独立 reviewer 可以使用：

```bash
export SAGE_REVIEWER_MODEL=YOUR_REVIEWER_MODEL
export SAGE_REVIEWER_MODEL_PROVIDER=YOUR_PROVIDER
export SAGE_REVIEWER_OPENAI_BASE_URL=https://YOUR_API_ENDPOINT
export SAGE_REVIEWER_OPENAI_API_KEY=YOUR_REVIEWER_KEY
```

未覆盖的连接项沿用主配置。请求仍走 SAGE Runtime 统一预算。模型族关系来自响应和配置，不是第三方身份认证；同族/未知关系不会自动变成独立接受。原版门控的 `stop` 也只用于判断是否值得继续研究。

## 固定真实论文语料

用于接口限流后的明确恢复验证、输入消融和复现实验，而非伪装当前联网查新：

```bash
python -m sage run --mode live --allow-live --config reviewed-config.json \
  --paper-corpus /absolute/path/recorded-corpus.json \
  --topic "YOUR QUESTION" --output projects/fixed-corpus-run
```

语料格式为 `sage.paper_corpus.v1`，包含 `provenance` 与 `papers`（Paper 字段，可含已获授权的 article sections）。有大小/数量上限，语料哈希进入 checkpoint identity，实际阅读范围标为 `recorded_*`。检索为本地词项匹配，后续仍可用真实模型重排/提炼。收据记录未进行新联网检索；本地命中不能确立全球新颖性。输入文件是研究者提供的数据，哈希不认证其真实性。

遇到 HTTP 429 的原联网运行保留为失败，不移除限流标记，不用新语料目录冒充原运行自动成功。固定语料运行使用新的身份、目录和显式范围。

## CORAL 任务级执行

新增 `coral-evaluate`，与原有标量 MSE 后端分开。目前只启用 `reviewed_integration_smoke`：可信 grader + 冻结的合成表达式与探针 + 经审查的 Python 脚本。不是通用训练器或 CORAL 编码代理池。

在独立 Python 3.11–3.13 环境安装固定 CORAL 源码及其依赖。实际调用原版 `SubprocessGrader.grade`，由原版 worker 加载继承 `TaskGrader` 的自有评分器；调用前核对安装包中三个关键源码文件哈希。该实现不依赖 gateway 或启动 UI。

```bash
python -m sage coral-evaluate --contract /absolute/path/task.json \
  --coral-python /absolute/path/coral-env/bin/python \
  --allow-execution --approved-contract-digest REVIEWED_CANONICAL_SHA256 \
  --output projects/coral-development-check
```

契约 `sage.coral_task.v1` 必须提供任务、父提案摘要、数据/评分器/候选解释器/全部候选的 SHA-256、尝试关系以及单次/总时间预算。规范哈希使用 `sage.checkpoints.digest`。修改任何输入、未知 parent、重复 attempt 或不匹配批准摘要均拒绝；新输出目录避免覆盖历史。

首次评分任务是 add/sub/mul 前缀树的语义保持简化：固定表达式在固定数值探针上比较输出，正确性通过后计算平均节点压缩比例。数值探针一致不证明符号恒等；数据是合成开发材料，不是独立科学 benchmark。基线、无效输出、错误语义、超时与成功候选都计入尝试总数。

当前可信 grader 在 Linux root 管理进程下，使用已冻结且非 root 用户可执行的独立 Python 解释器，把候选降为 nobody 用户执行；不继承 API 凭据，并设置 CPU、内存、文件和描述符上限。语法限制只是附加审查，不是安全沙箱。没有网络隔离；因此只接受本次人工/代理审查过的 smoke 脚本，不能据此运行任意不可信研究代码。CORAL 的 worktree、daemon、多代理、islands 和自演化记忆尚未接入。

输出 `contract.json`、`result.partial.json`、`result.json`、每次调用的 stdout/stderr，以及原版评分器返回的 ScoreBundle、包版本和源码哈希。评分失败不返回虚构指标，最佳候选只从真实成功测量中选择。所有产物保存在忽略的项目目录。

## 验证边界

离线回归负责来源、审查记录、预算、冻结契约和错误传播；真实服务与原版接口验证另记在私有项目产物。联网检索、固定语料上的真实模型调用、原版机械门控与合成任务执行分别报告。它们都不能直接证明比原版 ARIS/CORAL/CoI/Agent Laboratory 更好。


模型代码格式适配器 `parse_candidate_script` 显式识别单个 code 标签、单个 Python fence 或完整 Python 源码，保留原回复与脚本哈希。它不修改原模型调用的失败状态，不批准执行，也不证明代码安全；执行仍须经过脚本审查与冻结契约。


查新检索有意保留每个查询最多六条提供方顺序的候选，不由生成模型的相关性重排预先排除可能的相似工作；最终模型比较仍须逐条指出重合、差异和证据限制。锚点发现仍保留配置的重排方式。语义重排解释在 1,200 字符硬上限内保留全文和哈希，控制器生成并标记 180 字符预览；格式投影不改论文 ID 或分数，超出原始硬上限仍有限重试并保留失败。
