# CoI-Agent 工作流基础

已导入实际 Python 工作流与提示词，供后续取长补短；不是只保存链接，也不是完整在线产品。

## 来源、许可与范围

- 上游：[DAMO-NLP-SG/CoI-Agent](https://github.com/DAMO-NLP-SG/CoI-Agent)
- 固定提交：[ac94317ff2d1997f362747edc2c9e5f0fdc9c450](https://github.com/DAMO-NLP-SG/CoI-Agent/tree/ac94317ff2d1997f362747edc2c9e5f0fdc9c450)，2026-10-17 核对仍为 main 当前提交。
- 许可：[原始 Apache-2.0 LICENSE](upstream/LICENSE)。保留全部纳入源码中的署名/版权文本；此提交没有独立 NOTICE 文件。
- [manifest.json](manifest.json) 列出全部 15 个纳入文件、原始 Git blob SHA、SHA-256、字节数和逐文件排除原因。
- 原样保存 [README](upstream/README.md)、所有 11 个 Python 文件、空密钥配置和 requirements。未复制 dataset 中的评估数据/生成结果、图片资产、`.DS_Store` 或字节码缓存。上游 README 中的本地图片和数据说明因此仅供参考，安装命令未经本仓库验证。
- 原始文件不修改；源码内没有发现实际密钥，示例配置的凭证值为空。不要向上游快照填入密钥。

## 代码入口与能力边界

| 功能 | 实际源码入口 | 当前可借鉴内容 |
|---|---|---|
| 检索/PDF | [searcher/sementic_search.py](upstream/searcher/sementic_search.py) | Semantic Scholar、嵌入重排、下载与 SciPDF/GROBID 读取 |
| 文献链 | [agents.py](upstream/agents.py) 的 `deep_research_paper_with_chain` | 前向/后向引用、想法抽取、趋势总结 |
| 想法生成 | 同文件 `generate_idea_with_chain`、`check_novel` | 候选链、两两比较、检索范围内相似性检查 |
| 实验设计 | 同文件 `generate_experiment`、`refine_experiment` | 生成/修订实验方案文本，不执行实验 |
| Review | 同文件 `ReviewAgent.review_experiment` | 对方案提出建议，不代表独立验证 |
| 模型/编排 | [LLM.py](upstream/LLM.py)、[main.py](upstream/main.py) | 模型客户端和调用链，尚未联网验证 |
| 提示词 | [prompts](upstream/prompts/) | 文献、想法、方案、比较、review 的实际提示词 |

按功能进入我们自己的 [modules](../../modules/README.md)，不要在各分类中再次复制原文件。

## 我们维护的最小适配层

[coi_agent.py](../../modules/orchestration/coi_agent.py) 只核验/准备源文件，不 import 上游模块。只用 Python 标准库。

```bash
python scripts/coi.py inspect
python scripts/coi.py prepare --destination projects/coi-agent-runtime
```

第二个命令创建新的 ignored 私有副本，不覆盖已有目录，不安装依赖、不加载配置、不调用 API、不启动工作流。准备文件携带 LICENSE、PROVENANCE.json、LOCAL_CHANGES.json；修改过的 Python 文件有醒目的修改声明。

[5 个精确补丁](../../modules/orchestration/coi_patches.json)：

1. 引用链返回字段与聚合解包顺序一致，避免把趋势当成实验方案等字段串位。
2. 显式解析 `is_azure`，`False`/`0` 正确进入 OpenAI 分支，无效值拒绝。
3. 修正 `--max_chain_length t` 的 CLI 拼写，使 `--max_chain_length` 生效。
4. 无检索证据时抛出 inconclusive 错误，停止该流程；不标为新颖，也不因一直返回 False 而继续无边界重试。
5. 相似性回复不是 `0`/`1` 时同样停止；初始化可选相似论文，避免未赋值变量。

补丁仅在固定哈希一致且每处原文恰好匹配一次时应用。当前测试执行的是隔离的方法、假客户端和假检索结果，不是完整上游网络流程。

## 已知问题与接入门槛

这些问题尚未在本阶段修复，准备副本仍不能被当作安全生产执行器：

- CLI 默认单条链 `max_chain_numbers=1`，不会发生多候选比较；增加链数会提高请求量，需先明确预算。
- 新颖性生成循环和检索 429 递归重试没有统一上限；同步 requests 位于 async 内部，部分请求缺超时。需有界重试、取消和总成本记录。
- 相似性模型判断只能表示检索范围内的输出，不能证明全球首次；错误、空结果、无全文和低召回必须分开记录。
- PDF 下载/读取包含外部 URL、以标题构造路径；需清理文件名、限制目的地/大小、隔离解析器并审查外部内容。当前适配器不调用它们。
- `main.py` 导入时读 config、改环境、调用 nest_asyncio；不要从工作台的默认 import 路径加载它。requirements 未锁版本，也未包含 nest_asyncio；SciPDF/GROBID/Java 和语言模型另有依赖及许可审查。
- 还有缺少 article 时的局部未初始化变量、宽泛异常、共享可变默认值和索引/模型结构校验等问题，需要后续负向测试逐项处理。
- 没有训练/评测执行器、写作 runner、可信审批、强制预算或沙箱。不能把生成的 experiment 文本称为执行成功。

下一步先做假检索/假模型的完整链测试，处理边界，再在明确资源与授权后做小额真实调用；与人工基线对比有效性另立协议。Agent Laboratory 的接入仍是后续工作。

## 验证与升级

```bash
python scripts/check.py
```

汇总检查覆盖现有 catalog/模板、快照完整性、补丁预条件、字段契约、布尔值、空/错误 novelty 响应、路径限制和拒绝覆盖。未安装上游依赖、未联网调用模型、未运行训练、未复现论文指标。

升级时重新读取上游 LICENSE/NOTICE，显式选择源码文件，更新 manifest 和补丁基线，并复跑所有离线测试；若来源或许可不清楚，先暂停导入。
