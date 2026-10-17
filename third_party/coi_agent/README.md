# CoI-Agent 不可变来源归档

这里保存 CoI-Agent 的固定源码，作为 SAGE 的来源、归因和对照材料。**CoI-Agent 保留原名；SAGE 运行时不导入本目录。** 维护中的功能代码与提示词已拆到 [sage/](../../sage/)，详见[模块地图](../../modules/README.md)与[完整迁移对照](../../docs/sage-migration.md)。

## 来源、许可与范围

- 上游：[DAMO-NLP-SG/CoI-Agent](https://github.com/DAMO-NLP-SG/CoI-Agent)；论文 [Chain of Ideas](https://arxiv.org/abs/2410.13185)。
- 固定提交：[ac94317ff2d1997f362747edc2c9e5f0fdc9c450](https://github.com/DAMO-NLP-SG/CoI-Agent/tree/ac94317ff2d1997f362747edc2c9e5f0fdc9c450)。它是导入基线，不承诺始终等于最新上游。
- 许可：[原始 Apache-2.0 LICENSE](upstream/LICENSE)。保留纳入内容的署名/版权文本；该提交没有独立 NOTICE 文件。
- [manifest.json](manifest.json)列出 15 个纳入文件、原始 Git blob SHA、SHA-256、字节数和逐文件排除原因。
- 原样保留 README、11 个 Python 文件、空密钥配置和 requirements。未复制 dataset 中的评估数据/生成结果、图片、`.DS_Store` 或缓存；上游 README 的图片和数据说明仅供来源参考。
- 快照内配置的凭据为空。不要填入密钥，也不要为了让原 README 的命令可执行而改写快照。

## 上游源码入口

| 功能 | 归档源码 | 与 SAGE 的关系 |
|---|---|---|
| 检索、重排、PDF | [searcher/sementic_search.py](upstream/searcher/sementic_search.py) | 发现/适配器来源；SAGE 不默认下载或解析 PDF |
| 引用链与想法 | [agents.py](upstream/agents.py) 的 `DeepResearchAgent` | 拆到 discovery、literature、ideation、review |
| 方案生成与修订 | 同文件 `generate_experiment`、`refine_experiment`、`improve_experiment` | 拆到 experiment_design 与控制器，仍是未执行方案 |
| 方案评审 | 同文件 `ReviewAgent` | 拆到 review；模型角色不是独立科学复核 |
| 模型/入口 | [LLM.py](upstream/LLM.py)、[main.py](upstream/main.py) | 由注入式 provider 与 SAGE CLI 替代，避免导入副作用 |
| 提示词 | [prompts](upstream/prompts/) | 19 个函数按功能迁移至维护中的 `sage/*/prompts.py` |

本次未安装并运行原始上游依赖、未联网调用原上游流程、未训练或复现论文指标。SAGE 离线测试覆盖的是新模块实现与 fake providers，不等于原论文实验复现。

## 旧 inspect / prepare：保留兼容

[归档准备器](../../modules/orchestration/coi_agent.py)只核验/准备源文件，不 import 上游模块，仅用标准库：

```bash
python scripts/coi.py inspect
python scripts/coi.py prepare --destination projects/coi-agent-runtime
```

`prepare` 创建新的 ignored 私有目录，不覆盖已有目录、不安装依赖、不加载密钥配置、不调用 API、不启动工作流。副本携带 LICENSE、PROVENANCE.json、LOCAL_CHANGES.json；修改过的 Python 文件有修改声明。

[五个精确补丁](../../modules/orchestration/coi_patches.json)处理链结果字段顺序、Azure 布尔解析、`--max_chain_length` 拼写、空新颖性检索以及格式异常的新颖性响应。补丁只在源哈希一致、匹配位置唯一时应用；空或错误判新会停止，不包装成新颖。

这条路径只为归档兼容与审查保留。SAGE 主入口是 `python -m sage run`，不依赖准备副本；不要把两个路径的测试结果或能力混写。

## 归档准备副本仍存在的风险

以下针对原始/五补丁副本，**不是声称新 SAGE 仍采用这些实现**：

- 新颖性/引用循环、429 递归重试和同步请求没有统一总预算；部分请求缺超时。
- `main.py` 导入时读 config、修改环境并调用 nest_asyncio。requirements 未锁定，SciPDF/GROBID/Java 和模型另需依赖/许可审查。
- PDF 下载/读取涉及外部 URL、标题路径和解析器，需要独立的路径、体积、域名和进程隔离。SAGE 改为 metadata/abstract 或显式本地 article。
- 仍有缺失 article、局部未初始化变量、宽泛异常、共享可变默认值和响应结构校验等问题。
- 没有真实实验/训练执行器、论文写作 runner、可信审批、OS 沙箱或独立科学评价器。名为 `experiment` 的内容是方案文本。

因此不能把 prepare 产物当作无人值守安全执行器。SAGE 的命名契约、有限预算与严格解析等改造在[迁移说明](../../docs/sage-migration.md)中单独记录，也不能等同 OS 隔离或科学有效性保证。

## 验证与升级

运行 `python scripts/check.py`。检查范围包括不可变快照、旧补丁预条件、目录/模板，以及 SAGE 离线流程与负向测试；实际通过情况以最终检查输出为准，不提前固定测试数量。

升级时重新检查上游 LICENSE/NOTICE、显式选择文件、更新 manifest 和归档补丁基线，并单独审阅 SAGE 的派生逻辑差异。来源或许可不清楚时暂停导入。Agent Laboratory 仍是后续研究对象，尚未集成。
