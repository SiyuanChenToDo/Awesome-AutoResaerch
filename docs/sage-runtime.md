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
- Semantic Scholar 适配器只访问官方 graph HTTPS endpoint，不追随重定向，不访问论文中的下载 URL。模型 SDK 的重定向和环境代理自动继承也关闭；原 `OPENAI_PROXY_URL` 行为未迁移，需代理的网络环境不能假定兼容。
- 提供方错误归类，避免在日志中原样输出响应体、凭据或秘密 URL；项目产物本身仍可能包含敏感研究内容。

这些是应用层限制，不是 OS/容器沙箱、独立权限域、金融预算保证、可恢复远端任务队列或提示注入安全证明。真实实验执行尚不存在。

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
