# Awesome AutoResearch · AI 科研工作台

从工具清单走向自己的研究闭环：**发现问题 → 证据阅读 → 可证伪假设 → 受控实验 → 独立复核 → 可追溯写作 → 经验积累**。

这是一套面向人工智能研究的轻量、文件优先脚手架。先把研究协议和产物定义清楚，再按需接入检索、模型与实验工具。现阶段可运行的是**资料导入、检索、目录生成、项目初始化与完整性校验**；新增 CoI-Agent 固定版本源码、离线完整性检查与补丁准备。第三方研究系统尚未安装依赖或进行联网实测。

> 仓库地址保留原拼写 `Awesome-AutoResaerch`，展示名称使用 AutoResearch。

## 当前项目计划（2026-10-17）

- **已完成**：[karpathy/autoresearch](https://github.com/karpathy/autoresearch) 按用户要求标为计划任务完成，移出后续复现优先队列；保留历史资料与借鉴记录。
- **CoI-Agent 基础已导入**：按 Apache-2.0 固定保存实际源码，按功能分类导航，提供 5 个离线准备补丁；见[源码与边界](third_party/coi_agent/README.md)。联网运行和真实实验仍未进行。
- **后续研究**：[Agent Laboratory](https://github.com/SamuelSchmidgall/AgentLaboratory) 继续保留为重点，尚未导入或接入。

这里的“已完成”是计划状态，不是独立运行或性能复现证明。autoresearch 的运行核验仍为 `not_run`，工作台集成仍为 `not_integrated`。CoI-Agent 单独标记为 `source_imported`，不等于可投入联网运行。具体状态与后续验收见[当前项目计划](docs/roadmap.md#当前项目计划2026-10-17)。

## 从这里开始

1. 先从[功能模块目录](modules/README.md)找工具和代码，再看 [研究超级工作流](docs/workflow.md)，明确每一步的输入、产物和人工放行条件。
2. 看 [精读与工具借鉴路线](docs/reading-path.md)，选择一个最小闭环，避免先搭一堆框架。
3. 用下面的命令创建第一个研究项目，填写 [项目模板](templates/README.md)。
4. 通过 [基准选择指南](docs/benchmark-selection.md) 确定要评估的是想法质量、工程复现、研究创新还是过程可信度。
5. 按 [阶段路线图](docs/roadmap.md) 逐步接入真实工具。

## 5 分钟本地起步

Python 3.10+，只用标准库；不需要 API key、GPU、第三方依赖或联网。

```bash
git clone https://github.com/SiyuanChenToDo/Awesome-AutoResaerch.git
cd Awesome-AutoResaerch
# 本脚手架合并前，切换到 PR 分支：
git switch feat/ai-research-workbench

python scripts/catalog.py validate
python scripts/catalog.py search "hypothesis"
python scripts/catalog.py search --category benchmark
python scripts/research.py init my-first-study --title "我的第一个 AI 研究项目"
python scripts/research.py check-project projects/my-first-study
python -m unittest discover -s tests -v
```

初始化不会调用模型或执行实验；初始状态为 `draft`。填写协议后，用 `check-project ... --ready` 检查最基本的可执行前提。机器校验不替代对科学有效性、伦理、安全、授权和预算的人工判断。

`projects/` 默认被 Git 忽略，防止把未发表想法、数据、日志和密钥意外推送到公开仓库。经确认可公开的精简案例放到 `examples/`。

## 资料地图

| 入口 | 内容 |
|---|---|
| [功能模块](modules/README.md) | 找文献、读文献、想法、实验设计、执行、编排、复核、写作的代码与工具入口 |
| [CoI-Agent 源码](third_party/coi_agent/README.md) | 固定版本源码、许可、来源哈希、已修补与待改进边界 |
| [工具](catalog/tools.md) | 来源清单中的 147 个 GitHub 项目，保留逐条来源定位 |
| [论文](catalog/papers.md) | 182 个论文类 URL，其中 175 个唯一 arXiv ID；不同版本/出版入口可能对应同一工作 |
| [评测](catalog/benchmarks.md) | 从来源评测章节提取的 39 个 URL，作为论文/资源记录的视图，不重复存储 |
| [其他资源](catalog/resources.md) | 机构、产品、社区和资料入口 |
| [机器可读目录](catalog/records.json) | 370 个规范 URL，保留每次出现的位置和原始 URL |
| [抽查与纠错](catalog/verification.json) | 重点模块的一手元数据/README 抽查，明确未运行代码 |
| [原始快照与限制](sources/README.md) | 原文完整保留、SHA256、缺失附件和统计差异 |

所有导入记录初始标记为 `source_imported / not_integrated`。这表示“用户清单收录过”，不表示本仓库确认了论文结论或软件质量。抽查事实单独存放，来源快照永不悄悄改写。Stars、榜单与性能数值不作为默认选型依据。

## 项目结构

```text
catalog/                  可检索目录、分类、重点选型与独立核验记录
sources/                  原始资料、来源清单、内容哈希与导入限制
modules/                  按研究功能分类的入口与我们维护的离线适配层
third_party/coi_agent/    CoI-Agent 固定版本原始源码、Apache-2.0 与来源清单
docs/                     工作流、架构、基准选择、精读路线、阶段路线图
templates/project/        一个研究项目的协议、证据、实验与决策模板
examples/                 可公开的示例计划，明确标注未执行
scripts/                  零依赖资料/项目工具及 CoI 源码准备，不承担模型或实验执行
tests/                    离线回归测试
.github/                  资料贡献模板、PR 检查表和最小 CI
projects/                 本地私有研究工作区，默认不入 Git
```

## CoI-Agent：先导入，再逐步优化

实际工作流源码保存在 [third_party/coi_agent/upstream](third_party/coi_agent/upstream/)，包括检索、引用链、想法生成、实验方案、review 与提示词。我们维护的分类入口、离线适配器和精确补丁独立放在 [modules](modules/README.md)，不复制多份代码。

```bash
# 只核对源码哈希与集成状态，不导入上游依赖
python scripts/coi.py inspect
# 可选：在不入 Git 的目录准备修补副本，不安装或运行
python scripts/coi.py prepare --destination projects/coi-agent-runtime
```

5 个局部补丁修正链结果字段顺序、Azure 布尔解析、CLI 参数拼写，以及空检索/无效模型回复被误判为新颖的问题。补丁仅应用于私有准备副本，原始源码不变。CoI-Agent 生成的是想法和实验方案；本阶段没有训练执行器、完整写作链、预算沙箱或已复现结果。真实运行前需处理[已知问题与接入门槛](third_party/coi_agent/README.md#已知问题与接入门槛)。

## 设计取舍

- 研究者决定问题、预算、证据标准与最终结论，Agent 提议与执行被明确限定的步骤。
- 假设和论文结论必须能回溯到来源、协议、运行与制品；拒绝把漂亮摘要当实验结果。
- 先做强基线、固定预算与独立评估，再考虑树搜索、多 Agent、知识图谱或自进化。
- 同时保存失败、负结果与停止理由，避免只积累“成功经验”。
- 适配器按协议组合，参考 [架构设计](docs/architecture.md)；不复制第三方项目的高权限默认设置。
- 当前文件哈希、Git 和检查表用于发现变更，不构成对恶意执行的安全隔离。

## 维护与贡献

见 [贡献指南](CONTRIBUTING.md)、[资料维护](docs/catalog-maintenance.md)、[安全与数据边界](SECURITY.md) 和 [许可说明](LICENSE-NOTICE.md)。

```bash
# 重建自动生成的目录（不改原始快照、人工抽查和选型文件）
python scripts/catalog.py build
# 导入新的 Markdown 清单，使用新的快照 ID，避免覆盖旧证据
python scripts/catalog.py import-snapshot path/to/new-list.md --id 2026-11-research --date 2026-11-01
# 完整离线检查
python scripts/check.py
```
