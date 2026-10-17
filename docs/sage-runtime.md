# 运行 SAGE

SAGE（Scientific Agent for Grounded Exploration，基于证据探索的科研智能体）运行到**有来源范围的研究提案与实验方案**。原 `run` 命令保持提案模式；新增 `laboratory` 提供有界代码生成/修复、显式执行后端与证据报告，详见文末。自动投稿未实现。

## 1. 离线运行：先验证软件链路

在仓库根目录使用 Python 3.10+：

```bash
python -m sage doctor
python -m sage run --mode offline --topic "证据约束的研究想法生成" --output projects/sage-demo
python scripts/check.py
```

offline 是默认模式，不读取 API 凭据进行外联，不需要第三方依赖。固定假模型与假论文源经过和 live 相同的控制器、模块、解析器与预算路径，覆盖查询、追链、提取、构思、比较、方案和评审修订。fixture 内容是合成演示材料；即使 topic 换成真实问题，也不能将固定回答当作该领域的研究发现。

`doctor` 检查本地配置/依赖可用性，不发送网络请求，也不输出密钥。缺少可选 live 依赖或配置不妨碍 offline 使用。

## 2. 输出与状态

`--output` 指向新的目录；已有目录拒绝覆盖。推荐在默认被 Git 忽略的 `projects/` 下保存。

| 文件 | 含义 |
|---|---|
| `result.json` | `sage.run.v1` 类型化产物：候选及证据链、选择/评分、方案与修订、错误、用量与契约审计 |
| `audit.jsonl` | 阶段/调用尝试及成功、失败、停止原因；不是不可篡改日志 |
| `config.json` | 本次运行的结构化限制配置；不保存 API 密钥 |

状态须分层阅读：

- `completed` / `completed_with_uncertainty`：提案链结束；后者仍包含新颖性未知或检测到相似工作的候选，不是实验成功。
- `stopped`：证据不足或预算耗尽等已识别停止条件；`failed` 表示提供方、解析或契约异常。检查 `errors`、`audit` 及已有的部分产物。
- `ExperimentPlan.status: proposal_only`：方案未执行。
- `execution_status: not_implemented`、`writing_status: not_implemented`：原 `run` 提案结果保留的兼容字段；仅表示该提案链不执行实验或写作，新增 `laboratory` 另有 `execution` / `report` 状态。
- `scientific_validation: not_performed`：没有完成科学有效性评价。
- `validation`：确定性输出契约检查；不是引用真实性、论文结论或实验效果认证。

重新运行请用新目录。不要把返回文件存在、CLI 正常终止或契约通过解释为研究结论成立。使用前人工核对来源、缺失证据及使用权限。

## 3. live：凭据、数据与明确选择

live 会向模型服务发送研究问题、文献内容和候选方案，向 Semantic Scholar 发送检索请求。确认数据可外传、账户可用、模型费用和资源上限后，再显式运行。只有凭据存在并不会触发 live。

OpenAI/Azure live 模型使用可选的官方 `openai` Python 包；如果选择 live，可在独立虚拟环境自行安装该依赖。offline 和 Semantic Scholar 的元数据传输使用标准库。上游 requirements 不应整体安装来运行 SAGE。

### OpenAI 配置

通过安全的环境配置提供以下变量，不把实际密钥写入仓库、命令历史或文档：

| 变量 | 用途 |
|---|---|
| `SAGE_MAIN_MODEL` | 主模型 ID；兼容 `SAGE_MAIN_LLM_MODEL`、`MAIN_LLM_MODEL` |
| `SAGE_CHEAP_MODEL` | 抽取/部分评审模型 ID；兼容 `SAGE_CHEAP_LLM_MODEL`、`CHEAP_LLM_MODEL`。可与主模型相同，但须明确配置 |
| `SAGE_OPENAI_API_KEY` | 凭据；兼容 `OPENAI_API_KEY` |
| `SAGE_OPENAI_BASE_URL` | 可选 HTTPS API endpoint；兼容 `OPENAI_BASE_URL`。未设时用 OpenAI 默认 endpoint |
| `SAGE_IS_AZURE` | 默认 false；兼容 `is_azure`，只接受明确布尔值，字符串 `False` 不会被当 true |

选择支持本适配器 chat completions 与输出参数的模型。适配器实现不等于所有模型/API 版本均已验证；本次未进行真实模型调用。

### DeepSeek：CPU 上的显式 live 提案验证

DeepSeek 使用同一个 SDK，但必须显式设置 `SAGE_MODEL_PROVIDER=deepseek`；仅修改 URL 不会切换请求协议。默认提供方仍为 `openai`。DeepSeek 分支发送文档规定的 `max_tokens`，默认地址为 `https://api.deepseek.com`，不允许同时选择 Azure。模型 ID 仍由用户配置。

截至 2026-10-17，[官方入门文档](https://api-docs.deepseek.com/)列出的模型为 `deepseek-flash` 和 `deepseek-v4-pro`；旧 `deepseek-chat` / `deepseek-reasoner` 名称已在[更新日志](https://api-docs.deepseek.com/updates/)中宣布停用。请在运行前核对账户可用模型。

`SAGE_DEEPSEEK_THINKING=disabled` 为本适配器默认值，显式关闭思考以便进行有限输出预算的连通性验证，并非声称科研质量最优。可显式设为 `enabled`；需相应审查 token、超时和费用上限。两种模式都拒绝 `finish_reason=length` 的截断输出，不将其当作完整成功。参数依据：[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)和[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)。这些本地兼容性测试不证明真实服务成功或账单上限。

在可访问 DeepSeek 和 Semantic Scholar 的机器上，用户可自行运行以下 Bash 命令。Python 需要支持本仓库类型语法；API 调用不需要 GPU、CUDA 或 Docker。先确认可发送研究内容和承担 API 费用；已泄露的密钥必须先撤销，使用新密钥，切勿发送到聊天或提交到 Git。

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install openai
export SAGE_MODEL_PROVIDER=deepseek SAGE_IS_AZURE=false
export SAGE_OPENAI_BASE_URL=https://api.deepseek.com
export SAGE_MAIN_MODEL=deepseek-flash SAGE_CHEAP_MODEL=deepseek-flash
export SAGE_DEEPSEEK_THINKING=disabled
unset SAGE_EMBEDDING_MODEL EMBEDDING_MODEL
unset SAGE_EMBEDDING_API_ENDPOINT EMBEDDING_API_ENDPOINT
# 用户只在自己的终端输入；关闭命令跟踪，输入不会回显或进入命令历史。
set +x
read -rsp 'Fresh DeepSeek API key: ' SAGE_OPENAI_API_KEY
printf '\n'
export SAGE_OPENAI_API_KEY
python -m sage doctor
python -m sage run --mode live --allow-live \
  --discussion-mode hybrid --discussion-students 2 --discussion-rounds 1 \
  --topic "Your approved research question" --output projects/deepseek-hybrid-01
unset SAGE_OPENAI_API_KEY
```

每次运行使用新输出目录。`doctor` 只检查本地配置，不测试网络或账户；live 检索仍依赖 Semantic Scholar，`--articles` 不能绕开检索。默认共享预算为 120 次模型请求、60 次检索、每次 2,000 输出 token、240,000 预留输出 token、600 秒总时限；失败/重试也计入。此限制不是货币预算保证，也不保证工作流一定在限额内完成。可通过 `--config` 明确调整，经授权后再运行。

上述 `run` 完成文献、CoI 学生讨论、提案和实验方案，不生成报告或执行实验。若要连到代码生成及报告/草稿，使用 `laboratory --backend dry-run --contract ...`，并提供人工审阅的标量 development MSE 契约；该路径同样不需要 Docker，但只检查代码语法，不能声称取得实验结果。真实执行的 CLI 后端需要另行审核的 Docker 配置；当前不支持任意实验或完整训练。详见[实验与报告范围](agent-laboratory-migration.md)。

### Azure 配置

设置 `SAGE_IS_AZURE=true`，主/便宜模型填写对应部署名称，并提供：

- `SAGE_AZURE_OPENAI_KEY` 或 `SAGE_AZURE_OPENAI_API_KEY`；兼容 `AZURE_OPENAI_KEY` / `AZURE_OPENAI_API_KEY`
- `SAGE_AZURE_OPENAI_ENDPOINT`；兼容 `AZURE_OPENAI_ENDPOINT`
- `SAGE_AZURE_OPENAI_API_VERSION`；兼容 `AZURE_OPENAI_API_VERSION` / `OPENAI_API_VERSION`

### 检索与可选 embedding

- Semantic Scholar key 可设 `SAGE_SEMANTIC_SCHOLAR_API_KEY` 或 `SEMANTIC_SCHOLAR_API_KEY`；同时兼容上游拼写 `SEMENTIC_SEARCH_API_KEY`。该 key 在适配器配置中可选，实际服务的权限/限速仍适用。
- `SAGE_EMBEDDING_MODEL` / `EMBEDDING_MODEL` 启用嵌入重排，默认复用模型客户端；不配置则以词项匹配回退，并在审计中标明。
- 单独 Azure embedding 部署可使用 `SAGE_EMBEDDING_API_ENDPOINT`、`SAGE_EMBEDDING_API_KEY` 和 `SAGE_EMBEDDING_API_VERSION`，兼容无 `SAGE_` 的 endpoint/key 及上面的 Azure API version。endpoint/key/version 需配套；该选项不是任意外部 embedding API 协议适配器。

配置完成后：

```bash
python -m sage doctor
python -m sage run --mode live --allow-live --topic "你的研究问题" --output projects/sage-live
```

`--allow-live` 是 CLI 的明确 opt-in，不替代研究组织的授权、数据许可或费用审批。离线检查和本次改造没有实际调用 live 服务，也没有验证费用、召回或科学质量。

## 4. 显式本地 article 输入

默认 Semantic Scholar 返回 metadata/abstract，不自动读取 `openAccessPdf`，不下载或解析 PDF。确有授权全文时，传入本地 JSON：

```bash
python -m sage run --mode live --allow-live --topic "你的研究问题" --articles projects/articles.json --output projects/sage-with-articles
```

JSON 顶层是从 paper ID 或精确标题到 article 的映射，例如：

```json
{
  "YOUR_PAPER_ID": {
    "sections": [
      {
        "heading": "Methods",
        "text": "Paste authorized source text here.",
        "publication_ref": ["R1"]
      }
    ],
    "references": [
      {"id": "R1", "title": "Verified reference title"}
    ]
  }
}
```

只有匹配到检索结果 ID/标题的条目才附加到论文。该选项不是 PDF 路径、不是任意全文 URL、也不是直接指定锚点的命令。`abstract_only` 与 `user_supplied_full_text` 写入证据；后者说明提供了 article 文本，不保证完整性或真实性。研究者负责源内容、许可及实际阅读范围。

live 运行时 local article 内容可能随提示词发送给模型服务，请先确认授权。不要将受限制全文或未发表材料提交到公开仓库。

## 5. 请求与资源限制

完整配置由 [RunConfig](../sage/config.py)定义，CLI 支持的覆盖参数用 `python -m sage run --help` 查看。可通过 `--config path/to/limits.json` 传 JSON 字段覆盖；不要把凭据放在该文件。显式 CLI 参数优先于配置文件，例如：

```bash
python -m sage run --mode offline --topic "有界提案演示" --max-candidates 2 --max-model-calls 60 --max-search-calls 30 --refinement-rounds 1 --output projects/sage-bounded-demo
```

JSON 可覆盖 `max_chain_length`、`min_chain_length`、`max_candidates`、`max_queries`、`search_rewrites`、`max_related`、`novelty_attempts`、`refinement_rounds`、`retry_attempts`、`max_model_calls`、`max_search_calls`、`max_tokens_per_call`、`max_reserved_output_tokens`、`request_timeout_seconds`、`max_wall_seconds`、`max_prompt_chars`、`max_response_chars`、`publication_date`。无效/未知字段会被拒绝。

`--publication-date` 接受 `YYYY`、`YYYY-MM`、`YYYY-MM-DD` 或含端点的 `start:end`，例如 `2020:2025`、`2024-01-01:2024-06-30`、`2024:`。时间条件应用于发现、引用链、判新与修订的检索路径；无法确认落在窗口内的缺日期/低精度记录会保守排除，而不是补造精确日期。较窄窗口可能令链长不足。

默认包含有限链长度、查询/改写、候选、再生成、修订轮数，以及请求/总时限。所有外部调用由 [Runtime](../sage/runtime.py)计数：

- 失败与重试计入模型/检索请求额度；SDK 自身重试关闭，避免层层叠加。
- 输出 token 按单次最大值预留；并非 provider 的实际 token 账单，也不含精确输入/embedding 金额。
- 每次调用受请求超时与剩余总墙钟时间约束；提供方另有响应大小限制。没有无限“直到新颖”或递归 429 重试。
- Semantic Scholar 适配器只访问官方 graph HTTPS endpoint，不追随重定向，不访问论文中的下载 URL。模型 SDK 的重定向和环境代理自动继承默认关闭；可按下节显式启用受限环境代理。原 `OPENAI_PROXY_URL` 行为未迁移。
- 提供方错误归类，避免在日志中原样输出响应体、凭据或秘密 URL；项目产物本身仍可能包含敏感研究内容。

这些是应用层限制，不是 OS/容器沙箱、独立权限域、金融预算保证、可恢复远端任务队列或提示注入安全证明。原 `run` 不执行实验；`laboratory` 可显式使用后文的执行后端，Docker 适配器尚未完成真实容器实测。

### 官方环境代理：显式 opt-in

默认禁用环境代理自动继承，避免未审阅的环境变量悄悄改变模型凭据与研究内容的传输路径。在执行环境要求使用官方代理时，运行 live 前设置：

```bash
export SAGE_USE_ENV_PROXY=true
# HTTPS_PROXY 由平台安全配置提供；不复制或输出代理 URL、密钥。
```

模型（包括 Azure、DeepSeek 和独立 embedding）及 Semantic Scholar 两条通路均读取 `HTTPS_PROXY` 或 `https_proxy`，并在创建配置时固定。两者同时存在但值不同、缺少代理、开关值无效或 URL 不受支持时，配置失败；不会回退直连。只支持无用户名/密码、无查询/片段/路径的 `http://host:port` CONNECT 代理。`https://` 代理、SOCKS 和带凭据代理暂不支持，会明确拒绝，不能通过改写地址绕过平台策略。

HTTP 是连接代理的协议；目标请求始终在 CONNECT 隧道内使用经过证书及目标主机名验证的 HTTPS。模型仍设置 `trust_env=False`，仅显式传入代理参数；检索通过标准库 CONNECT，API 凭据只在 TLS 建立后发给目标。不会继承 `NO_PROXY`、`ALL_PROXY`、其他端点或环境 TLS 覆盖，也不关闭 TLS 校验、不跟随重定向、不改变调用/超时/响应大小限制。平台必须已提供受信任的系统 CA；此开关不安装证书、配置代理或授予网络权限。

代理地址不进入配置 repr 或项目日志。代理拒绝仍是失败；此兼容功能不能修复平台 allowlist 或 Network secret 未生效。新增回归测试使用假 SDK/连接和真实标准库 TLS 配置检查，不证明真实代理、SDK 或认证已验证。

## 6. 兼容工具

```bash
python -m sage catalog validate
python -m sage catalog search "hypothesis"
python -m sage project init my-first-study --title "我的第一个研究项目"
python -m sage project check-project projects/my-first-study

# 原命令继续可用
python scripts/catalog.py validate
python scripts/research.py check-project projects/my-first-study

# 仅作 CoI 归档核验/准备；也支持 python -m sage provenance inspect
python scripts/coi.py inspect
python scripts/coi.py prepare --destination projects/coi-agent-runtime
```

项目模板初始化不调用模型；旧 prepare 不安装或运行上游，且不属于 SAGE 主运行路径。来源与偏离见[迁移说明](sage-migration.md)，科研人工门禁见[工作流](workflow.md)。


## Agent Laboratory 扩展入口

`python -m sage laboratory --mode offline --output projects/lab-dry` 串联原有提案链、候选代码生成与证据报告，默认只检查语法，不执行代码。

`python -m sage laboratory --mode offline --backend fixture --allow-execution --output projects/lab-fixture` 使用固定合成样例，展示候选改进、固定评分和报告链。它只分派精确匹配的已审阅样例函数，不运行任意模型代码。

真实执行提供显式 Docker backend，需要本地已安装引擎、已审核且以 digest 固定的预装镜像、冻结 contract 文件及匹配的 `--approved-contract-digest`。当前仅支持标量预测的 development MSE，目标标签不发送给模型/容器。本次未实测 Docker 或 live 服务，不宣称安全沙箱或科研效果。完整参数、契约格式、源函数映射与限制见 [Agent Laboratory 迁移指南](agent-laboratory-migration.md)。

原 `run` 产物中的 `execution_status: not_implemented` / `writing_status: not_implemented` 保留为兼容字段，含义仅限该提案运行；新能力位于 `sage.laboratory.v1` 外层 `execution` 和 `report` 字段。不得用兼容字段或模型评审评分推断科研成功。

## 可选 CoI 博士生讨论

在 laboratory 加 `--discussion-mode hybrid`，会先让默认两名博士生分别形成有来源的 CoI 提案，再互评、有限修订、由博士后综合选择，最后把接受的控制要求送入实验计划和原工程／报告流程：

```bash
python -m sage laboratory --mode offline --discussion-mode hybrid --output projects/lab-discussion
python -m sage laboratory --mode offline --discussion-mode none --output projects/lab-baseline
```

默认 `none` 保持原流程；`run` 也支持同样参数。可选 `--discussion-students 2`（2–4）、`--discussion-rounds 1`（1–3）、`--discussion-prompt-version v2`（v1/v2）。配置 JSON 使用对应下划线字段。学生数不能超过 `max_candidates`，实际独立来源不足时停止，不能复制一名学生。所有角色与后续 laboratory 阶段共享总预算。

讨论产物在 `proposal.discussion`（提案入口则为 `discussion`），包括原始版本、意见与证据所有权、接受／拒绝、模板版本与哈希，以及实验交接。未知／失败意见不自动接受；来源 ID 检查并不证明意见科学正确。相同模型的多个角色不是独立专家。完整流程、消融与验证边界见 [CoI × Agent Laboratory 讨论指南](coi-laboratory-discussion.md)。


## 可选 arXiv 元数据检索（显式启用）

`SAGE_PAPER_PROVIDER=arxiv` 选择官方 `https://export.arxiv.org/api/query`；默认仍是
`semantic_scholar`。`run` 与 `laboratory` 共用此选择，`doctor` 显示选择结果。
官方代理环境同时设置 `SAGE_USE_ENV_PROXY=true`，保持平台代理变量不变。
仅允许固定 HTTPS 元数据端点、不跟随重定向、不携带任何模型或检索凭据、
不下载 PDF。代理拒绝不会回退直连或其他主机。

```bash
export SAGE_PAPER_PROVIDER=arxiv SAGE_USE_ENV_PROXY=true
python -m sage doctor
python -m sage run --mode live --allow-live --discussion-mode hybrid \
  --discussion-students 2 --discussion-rounds 1 --max-candidates 2 \
  --topic "Your approved research question" --output projects/arxiv-hybrid
```

来源保留 arXiv 稳定 ID（去除版本用于去重）、含版本 URL、题名、作者、首次发表日期和摘要；
阅读范围为 `abstract_only`，未知引用次数为 null，不认证同行评审或下载全文。
模型查询按最多 12 个非停用词转换为 `all:` 字面词 AND 查询，提示模型输出 2–4 个关键词。
日期窗口编码为 submittedDate，并对实际元数据保守复核；有界结果为空仍是未知。

arXiv API 不提供 citation/reference graph：此选择显式改用 `Chain.relation=topic_time`。
锚点题名词 OR 查询提供主题近邻，再经原有词项重排与模型相关性判断筛选，按日期排序。
这些不是引用边、方法继承或因果历史；结构产物、审计和模型提示均标记此区别。
`related(... citations/references ...)` 直接报不支持，绝不伪造引文。讨论仍需两个具有
独有来源的候选，来源不足按原停止规则处理。该降级是对 CoI 图链方法的明确偏离。

遵循 [官方 API 使用条款](https://info.arxiv.org/help/api/tou.html)：同一进程所有 arXiv
实例串行访问，前一请求结束至少 3 秒才发下一次（失败同样计时）。等待和请求计入原时限，
取消异步等待不会提前释放传输锁；不同进程/机器需运营者统一节流，不应并行启动多个 live 作业。
只做小规模查询，不做全库抓取。接口参数依据 [官方手册](https://info.arxiv.org/help/api/user-manual.html)。

2026-10-17 本次预检查：官方代理对 `export.arxiv.org:443` 的 CONNECT 返回 403；
尚未验证真实 arXiv 返回或完整 hybrid 流程。离线 Atom、传输与主题链测试不能替代真实结果。

## 可审计检查点与有界恢复

`run` 与 `laboratory` 在新输出目录写 `checkpoint.json`。成功的结构化模型回复和检索记录按精确输入缓存；模型定稿已成功、随后 novelty 失败时，定稿仍可恢复。缓存身份包括格式版本、自有 Python 源码哈希、主题/模式/本地 article/配置哈希和非秘密提供方配置哈希。laboratory 另绑定工作流、完整评价合同摘要、执行后端与镜像，防止把另一份合同或后端的缓存当成当前批准。模型凭据、代理 URL、环境变量不写入。缓存包含研究内容，按私有文件保管。

在**同一代码、主题、配置及提供方身份**下，选择新输出目录：

```bash
python -m sage run --mode offline --topic 'same topic' --config limits.json \
  --resume previous/checkpoint.json --output next-run
```

live 仍必须显式 `--mode live --allow-live`。`--cache-only-retrieval` 禁止任何新论文请求：只有精确查询/参数的历史成功结果可以命中；不同查询不会从旧池中伪装出新检索。命中记录 `cache_hit`、输入哈希、来源与 `network_request=false`。未知命中仍保持 unavailable。

默认提供方异常仍失败。显式 `--allow-incomplete-novelty` 才允许暂时不可用的筛查返回 `not_established`，及补充规划检索保留 unavailable 后继续。初始锚点/最短链长/角色独有来源/所有权/采纳规则均不绕过。401/403 等非临时拒绝不会被该选项转成成功或未知。

429 的 Retry-After（秒数或 HTTP 日期）现可记录；429 后暂停本检查点谱系的全部新论文请求，不进行即时重试，不切换主机或直连。旧失败仍保留，缓存命中仍可使用。长等待或未知 Retry-After 不会被无界循环隐藏；当前没有自动解封检索的选项。

累计模型/检索请求、预留 token、SDK 实际 token（若提供方返回）、先前审计和活跃运行时长一起恢复，失败不归零。活跃时长不包含进程之间的离线等待。先前成功回复重放时重新执行当前验证器；缓存没有给来源增加权限。含未完成 `pending` 请求的检查点默认拒绝重发，只有显式 `--retry-uncertain` 允许另一次计费尝试；远端完成而本地未写入的窗口无法提供 exactly-once 保证。文件哈希是误改检测，不是签名、防篡改存储或安全沙箱。

`laboratory` 的 dry-run 和内置 fixture 后端支持相同恢复参数。fixture 重新计算的只是固定、无外部副作用的合成预测；恢复不会重新执行任意生成代码。Docker 后端仍明确拒绝 `--resume`，因为尚未实现容器任务身份与执行副作用恢复。旧运行目录的 result.json 或临时恢复脚本不是此检查点格式，不能直接导入。源码/配置改变会拒绝重放，不自动把旧内容升级为新版本有效证据。

例如，先前以相同默认主题、配置和后端运行过 hybrid fixture，可在新目录继续：

```bash
python -m sage laboratory --mode offline --backend fixture --allow-execution \
  --discussion-mode hybrid --resume projects/lab-before/checkpoint.json \
  --output projects/lab-after
```

laboratory 运行时逐事件刷新 `audit.jsonl`，逐阶段更新 `result.partial.json`，并提前保存 `config.json`、`contract.json`。即使进程在写作中突然退出，已完成的执行尝试、章节和调用缓存仍可检查。`result.partial.json` 表示部分状态；最终 `result.json` 仅在控制器正常结束后写入。CLI 同时打印提案、执行和报告状态及有阶段信息的错误，不把 `proposal_failed` 和空错误列表作为唯一诊断。

写作模型接收稳定的语义视图：最终提案、来源提取、负面筛查与已采纳要求；重复证据按 ID/哈希归并。调用日志、token 账单与恢复事件留在制品中，不反复拼入每个章节请求，避免重放日志变化使成功缓存失效或撑满提示词上限。

讨论上下文协议为 `sage.discussion.context.v2`。互评者保留自己的完整证据，但对方仅提供当前提案和来源身份；来源可见性不会扩大引用权限。修订阶段只补充有条件可采纳及先前已采纳意见涉及的同伴证据。综合和写作阶段保留完整原始来源文本、当前提案、负面筛查摘要与明确要求，省去重复的模型生成解读；每张卡用 `view_scope` 标明已提供的范围，用摘要关联完整提取。完整来源解读、实验描述与旧版本仍在运行制品中，实验设计模块继续接收原始证据提取；不得把提示中省略的解释当作已经读过的事实。

讨论提示使用标准 JSON Schema 明确每个字段的实际类型：ID 集合必须是唯一字符串数组，空集合写 `[]`；`requirements` 必须是对象数组，每个对象含 `critique_id` 和 `requirement`。单个字符串、字符串数组代替规划对象、null 或缺字段仍被拒绝，不做自动类型转换。此声明只改善模型的输出契约，不能替代后续来源归属、采纳关系与逐字要求的严格校验。

代码生成与修复提示给出解析器实际接受的完整命令示例：开围栏是 `REPLACE` 或 `EDIT N M`，不能在 `python` 围栏外另放一个 REPLACE。解析失败时，修复器同时接收被拒命令、明确格式诊断和冻结合同；不会因为尚未产生可解析代码就丢掉原始程序。解析器仍严格拒绝多条命令、错误索引和嵌套围栏，所有失败照常消耗尝试额度。

报告各节先生成一个不超过 1400 字符的简洁段落；越界回复会被拒绝并获得有界反馈，不自动截断。逐节请求只带章节状态和引用 ID 的提纲，不反复复制此前全部段落；完整草稿仍进入后续评审与修订。此约束限制写作链的上下文增长，并不把模型评论升级成已验证论文。

发现阶段先对候选锚点进行主题相关性筛查，拒绝的条目会记录；短证据链可以由预算内的备用锚点替换。hybrid 在锚点数量不足时提前停止，生成后也会检查有效候选数量，避免先支付构思和两两比较成本才发现无法组成讨论角色。arXiv 查询提示明确要求 2–4 个主题关键词；检索与相关性仍需实际来源支持，不降低最短证据链要求。

## 讨论上下文与规划输出

讨论协议新增 `sage.discussion.context.v1`：critique 提示显式列出 `citable_source_ids` 和目标角色不可引用来源，严格来源校验保持不变。证据正文按内容哈希去重，不同抽取不能互相覆盖；博士后只接收当前候选、完整证据表、意见/采纳关系、修订决策和历史哈希，完整历史留在 ledger。规划交接同样使用证据引用表，可无损还原采纳要求及证据卡片。核心材料仍超长则在发请求前停止，不能静默截断核心证据。默认提示上限仍 100000，本修复没有改成 200000。

模型 `finish_reason=length` 分类为 `TruncatedResponse`，绝不接纳其内容。只有规划生成/修订在原有限 retry_attempts 内附加简洁完整输出约束；单次 token 上限、总预算和验证器不变。再次截断继续失败。提示约束在真实 DeepSeek 上是否改善成功率尚未复测。

计划现在必须同时输出 `experiment` 和结构化 `plan_contract`（预算单位/上限/一次计费口径、指标分子分母和方向、独立样本单位及 n/理由、停止规则、证据限制）。缺失决定标 `unresolved`，不允许 `execution_ready=true` 或声称科学验证。输出字段通过只说明结构完整；公式是否正确、样本量是否充分、科学设计是否合理仍需独立审查。此对象不是 scalar-MSE 执行合同。

### 字段级诊断与有限反馈重试

讨论 JSON、字段类型、来源所有权、修订决定、原文保持、要求保留及综合交接使用预定义 `ValidationError` 字段/规则。审计 `validation_rejected`/`failed` 包含 stage、attempt、rule、field、响应哈希和长度，绝不回显未知 JSON 键、模型字段值或任意异常字符串。一般 InvalidResponse 无细分证据时保持 unspecified，不猜测规则。

在原 retry_attempts 内，下一次请求可附加 `field_feedback_v1`，只包含程序自有规则说明，不包含被拒绝的回复，也不自动修改结果、放宽来源权限或强制采纳。每次实际请求哈希和预算仍记录；重复违反会按原上限失败。修订提示另区分无条件可引用来源和“只有明确采纳该 supported 意见后才可引用”的来源表；peer 内容可见不等于被授权引用。

默认只记录安全诊断。显式 `--retain-rejected-responses` 才将大小受限的失败请求/回复保存在私有 checkpoint.rejections，权限 0600，带 stage/attempt/请求与响应哈希、代码身份和诊断；它们是未通过校验的不可信研究内容，不参与成功缓存，不能直接发布为脱敏日志。审计本身仍没有原文。没有 checkpoint 或回复超限时不会保存原文；标记 raw_retained_in_private_checkpoint=false。这些记录不能补回此前未保存的真实失败回复。
# Research ideation upgrade (2026-10-18)

For the recommended evidence-card input, semantic ranking, shared v3 discussion,
bounded empty-query relaxation and optional real citation graph, see the
[research ideation guide](ideation-evidence.md). Use `--profile research` on the
proposal-only `run` entry. This explicitly opts into official paper-text retrieval;
the existing standard profile remains compatible. No scientific quality gain is
implied by the profile or by software regression results.
