# 从 CoI-Agent 到 SAGE：来源、模块与行为对照

SAGE = **Scientific Agent for Grounded Exploration（基于证据探索的科研智能体）**。这是对 CoI-Agent 的研究提案链进行功能拆分、契约化和受限运行的改造，不是给上游仓库换名，也不声称复现其论文效果。

## 1. 来源与维护边界

- 上游：[DAMO-NLP-SG/CoI-Agent](https://github.com/DAMO-NLP-SG/CoI-Agent)，论文 [Chain of Ideas](https://arxiv.org/abs/2410.13185)。固定提交：`ac94317ff2d1997f362747edc2c9e5f0fdc9c450`。
- [third_party/coi_agent/upstream](../third_party/coi_agent/upstream/) 的 15 个原始文件逐字节保留，来源/排除项见 [manifest.json](../third_party/coi_agent/manifest.json)。原项目名、引用、拼写和文件名不改。
- SAGE 的派生代码与提示词在 [sage/](../sage/)；各功能模块有自己的逻辑和 `prompts.py`，不是运行时从 `agents.py` 动态提取或导入。
- Apache-2.0 来源、修改说明和许可证见 [NOTICE.md](../NOTICE.md)、[许可说明](../LICENSE-NOTICE.md)和[许可证副本](../LICENSES/CoI-Agent-Apache-2.0.txt)。这不表示上游认可 SAGE。
- 原 `scripts/coi.py inspect/prepare` 及五个补丁保留为归档兼容工具，不能替代新运行包或证明原上游流程安全。
- 仓库 URL `https://github.com/SiyuanChenToDo/Awesome-AutoResaerch` 和分支 `feat/ai-research-workbench` 保持不变。

## 2. 源方法 → SAGE 模块

下表依据已归档源代码与本仓库实现，不把未在上游主流程调用的方法误称为上游已完成能力。

| 上游来源/方法 | SAGE 归属与职责 | 保留/改变 |
|---|---|---|
| `DeepResearchAgent.get_search_query()` | [discovery](../sage/discovery/)：`Discovery.queries()` | 生成查询；JSON 字符串数组严格解析，不回退为不明确的空输入 |
| `generate_idea_with_chain()` 的查询/改写/锚点部分 | discovery：`anchors()`、`search()` | 有限查询与空结果改写，稳定 ID/标题去重 |
| `SementicSearcher.search_papers_async()` / `search_async()` | [providers.py](../sage/providers.py) + discovery | Semantic Scholar 题录/摘要；固定服务域名、超时、有限响应；不带 PDF 下载 |
| `search_related_paper_async()` | discovery：`related()` + `PaperSource.related()` | 分开 citations / references 方向，向文献链传递来源身份 |
| `rerank_papers()` / cosine helpers | discovery：`rank()`、`cosine()`；provider 可选 embedding | 有配置则嵌入余弦重排；否则显式记录词项匹配回退 |
| `read_paper_content()` / `read_paper_content_with_ref()` | [literature](../sage/literature/)：`paper_content()` | 拼接已提供的摘要或 local article sections/references，加入证据范围 |
| `get_paper_idea_experiment_references_info()` / `get_article_idea_experiment_references_info()` | literature：`extract()` | 产生 `Evidence`，不再通过位置元组交换字段 |
| `deep_research_paper_with_chain()` 的相关性/前后向遍历 | literature：`relevant()`、`build_chain()` | 前向被引优先，再用后向参考补链；每段有界、去重、记停止原因 |
| 同方法中的趋势与内联实体综合 | [ideation](../sage/ideation/) | 将 `Chain` 综合为趋势/实体，保留原证据 |
| 同方法中的未来方向/想法/定稿/再生成 | ideation | 独立候选生成与有限新颖性再生成，保留拒绝尝试 |
| `check_novel()` / `get_check_novel_search_query()` | [review](../sage/review/)：`Review.novelty()` | 检索范围内相似性判断；空证据/无法解析保留未知 |
| `judge_idea()` / `generate_idea_with_chain()` 的选择部分 | review：`rank()` | 六维、双向有序两两投票，保留比较，稳定处理并列 |
| `ReviewAgent.get_search_query()` / `get_suggestions_from_papers()` | review：`literature_suggestions()` | 相关文献检索与建议形成实际可调用链；不把原方法存在等同原主流程已使用 |
| `ReviewAgent.review_experiment()` | review：`experiment()` | 产生方案评审意见，仍为模型建议 |
| `generate_experiment()` | [experiment_design](../sage/experiment_design/) | 从想法及来源实验描述生成方案，状态为 proposal-only |
| `refine_experiment()` / `get_paper_info_for_refine_experiment()` | experiment_design | 补充查询、检索、提取相关证据、修订并保留历史 |
| `improve_experiment()` | experiment_design + review，由 [orchestration](../sage/orchestration/) 组织 | 有限评审/修订，不自增无限“直到通过”循环 |
| `LLM.py` 的 response / embedding 与 Azure 配置 | providers.py；[runtime.py](../sage/runtime.py) 管理调用 | 延迟加载 OpenAI SDK、显式布尔解析、主/便宜模型注入、单次请求与外层统一重试 |
| `main.py` 的入口/参数/结果文件 | `python -m sage`；orchestration | 不读取上游 config，不 import 上游，不在导入时外联；写结构化提案与审计 |
| 上游没有实验/写作 runner | [execution](../sage/execution/) / [writing](../sage/writing/) | CoI 提案入口仍不执行；后续 Agent Laboratory 衍生链见 [独立对照](agent-laboratory-migration.md) |

## 3. 全部原始提示词函数的去向

原 [deep_research_agent_prompts.py](../third_party/coi_agent/upstream/prompts/deep_research_agent_prompts.py)、[review_agent_prompts.py](../third_party/coi_agent/upstream/prompts/review_agent_prompts.py)、[juder_prompts.py](../third_party/coi_agent/upstream/prompts/juder_prompts.py) 中的 19 个函数均有维护中的分模块位置。函数名保留来源对应关系；例如 `direciton` 的历史拼写不是产品名。

| 新 `prompts.py` | 原提示词函数 |
|---|---|
| [discovery](../sage/discovery/prompts.py) | `get_deep_search_query_prompt`；`get_deep_rewrite_query_prompt` |
| [literature](../sage/literature/prompts.py) | `get_deep_reference_prompt`；`get_deep_judge_relevant_prompt` |
| [ideation](../sage/ideation/prompts.py) | `get_deep_trend_idea_chains_prompt`；`get_deep_generate_future_direciton_prompt`；`get_deep_generate_idea_prompt`；`get_deep_final_idea_prompt` |
| [experiment_design](../sage/experiment_design/prompts.py) | `get_deep_generate_experiment_prompt`；`get_deep_refine_experiment_prompt`；`get_deep_refine_experiment_search_query_prompt`；`get_deep_paper_info_prompt_for_refine_experiment` |
| [review](../sage/review/prompts.py) | `get_deep_check_idea_novel_search_query_prompt`；`get_deep_check_idea_novel_prompt`；`get_judge_idea_all_prompt`；`get_judge_experiment_all_prompt`；`get_review_search_related_paper_prompt`；`get_review_suggestions_from_papers_prompt`；`get_review_experiment_design_suggestions_prompt` |

保留提示词不代表所有函数都用于默认主链。例如 `get_judge_experiment_all_prompt` 是可供扩展的方案比较模板；主链的实际选择对象是候选想法。上游内联的实体综合也拆入 SAGE 的构思实现。源快照不改，维护版本具有修改声明。

## 4. 明确的行为修正与安全偏离

### 命名契约替代位置元组

上游链返回和聚合解包的顺序不一致，可能把趋势/实验/实体串位。SAGE 使用 `Paper`、`Evidence`、`Chain`、`Candidate`、`NoveltyAssessment`、`ExperimentPlan`、`RunResult`，读写命名字段；错误不靠补齐一组 `None` 元组隐藏。

### 新颖性是有范围的判断

上游空检索可返回通过，且再生成循环没有总次数界限。SAGE 明确区分：

- `not_established`：没有充分比较证据或输出不可靠，结论未知。
- `similar_work_found`：模型在已检索内容中找到相似工作；关联来源。
- `no_similar_work_found`：模型在本次检索内容中未找到相似工作；不表示全球首次。

格式错误按统一有限重试处理；无法建立判断时不能变成“新颖”。再生成次数、查询/链长、候选数、review 轮数、总调用数和时间均有上限。

### 重排与六维比较明确口径

有 embedding 配置时采用向量余弦重排，未配置时使用可见的词项匹配回退，不能声称与上游 embedding 实验等价。两两比较保留 novelty、relevance、significance、clarity、feasibility、effectiveness 六维；原提示词遗漏的 relevance 已补齐。累计投票不是标准 Elo。单候选不会产生跨候选比较；并列采用稳定选择，不作统计优势宣称。

### 全文获取是显式偏离

上游自动下载 PDF、调用 SciPDF/GROBID 并以标题构造文件路径。SAGE 不采用这条默认路径：

- live 默认读取 Semantic Scholar 题录/摘要，记录 `abstract_only`。
- 可用 `--articles` 显式提供已获授权的本地 article JSON，记录 `user_supplied_full_text`。
- 不自动下载 PDF、不调用全文解析服务、不访问题录中的任意全文 URL。
- 传入“全文”标签不认证它完整/真实；仍由研究者核对来源、许可与实际阅读范围。

源提示词中的“全文”“顶会”“已具备实验细节”等假设在维护版本/公共证据政策中被约束为实际输入范围。没有全文时不得补写细节；要求的是简洁依据说明，不是私有推理链。

### 软件契约审计与科学评价分开

确定性契约检查独立于模型生成回答，按稳定规则核对结构和关联，避免模型自行宣告产物通过；它不验证论文本身、证据支持程度、实验效果、因果解释或最终测试隔离。CoI 提案入口的 `scientific_validation` 保持 `not_performed`；实验迭代与报告另由显式 laboratory 入口提供，不能从提案生成推断已执行。

### 传输与日期过滤取舍

模型 SDK 禁用自动重试、重定向和环境代理自动继承；上游 `OPENAI_PROXY_URL` 行为未迁移。Semantic Scholar 使用固定官方 graph HTTPS 入口，不跟随重定向。时间范围过滤统一应用于发现、引用、判新与修订；低精度/缺日期记录无法证明落在窗口内时保守排除，不补造日期。

### 离线验证与联网行为分开

离线 fake providers 经过同一控制器、模块、解析与预算路径，可测试成功和负向边界；固定材料不能支持科研效果结论。live 适配器有超时、有限响应与外层请求预算，不代表已完成真实 API 兼容性、召回率、费用或模型质量验证。重试/最大输出 token 的预留不是真实美元预算；CoI 提案入口不执行代码；后续 Docker 适配器的存在不证明生产隔离、可信审批或独立科学评价已完成。

## 5. 运行与回归入口

```bash
python -m sage doctor
python -m sage run --mode offline --topic "证据约束的研究想法生成" --output projects/sage-demo
python scripts/check.py
```

产物、live 环境与 local article 格式见[运行说明](sage-runtime.md)。目录/项目原命令继续兼容，并通过 `python -m sage catalog ...` / `python -m sage project ...` 暴露。旧归档 inspect/prepare 继续存在；它与 SAGE 的模块化实现分别验证，不需要启动上游依赖。

本次不改变其他工具状态：autoresearch 是用户指定的计划完成，仍 `not_run` / `not_integrated`；Agent Laboratory 的后续代码迭代和报告迁移现见[独立对照](agent-laboratory-migration.md)，不改变 CoI 本身的复现边界。后续科研效果验证应单独预注册基线、任务、预算与人工参与，而不是从软件检查通过推断。
