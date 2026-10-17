# 项目模板使用说明

模板面向人工负责人和受监督的研究 Agent。先生成独立项目，再填写内容，不要直接把模板改成唯一课题。根目录 README 提供项目初始化工具的实际命令。

1. 在仓库根运行 `python scripts/research.py init my-study --title "我的研究"`，自动复制模板、替换占位符并创建 `project.json`。若手工复制 `project/`，还需按示例补齐 `project.json`，否则项目检查器会报告缺失。
2. 先填写 `brief.md`、`literature.md`、`hypotheses.md` 和 `benchmark.md`。
3. 填写 `preregistration.json`。初始 `draft` 可包含 `null`，但不能启动正式研究。
4. 数据、代码、评价器和预算具备后，人工审阅并将计划状态设为 `frozen`；在 `decisions.md` 记录最终文件字节的 SHA-256、版本与批准范围。文件哈希放在外部记录，避免计划自包含哈希。
5. 真正运行后，参照 [run-record.json](run-record.json) 向 `runs.jsonl` 逐行追加真实记录；空文件表示尚无尝试。该样例不由当前脚手架执行；项目检查器仅校验运行账本的一部分结构与完整性字段。
6. 审计后填写声明账本、复盘、复现清单和经验。未支持的主张同样保留。

## JSON 约定

- `preregistration.json` 的 `schema_version` 为 1，状态为 `draft`、`frozen` 或 `superseded`（已被新版替代）。冻结后的修改需要新 protocol ID/version 与变更记录；保留原文件快照。
- `primary_metric.direction` 使用 `minimize` 或 `maximize`；`minimum_effect` 是与基线相比的正向改善幅度，必须写明绝对/相对单位。
- 种子数组记录全部预定种子。若方法确定性，明确说明重复单位及确定性，不能用重复同一输出增加样本量。
- `baselines` 与 `ablations` 建议每项包含 `id`、`description`、`config`；不适用的消融给出文字理由，不能静默遗漏。
- `max_runs` 包含基线、候选、消融、失败和重试；`max_api_cost=0` 表示不使用付费 API，`null` 表示尚未确定。其他预算同理。
- `evaluation.evaluator_path` 指向实际评分器文件，`protected_paths` 应包含该文件所在目录及 `preregistration.json`；`protected_paths`/`editable_paths` 相对课题根目录；不能用根目录全量可写来冒充白名单。真实权限需要执行器实现。
- `data.fingerprint`、`evaluation.evaluator_sha256` 及运行记录中的哈希只填真实计算值，不能用示例字符串假装完整性验证。
- `approval` 是人类决策记录的索引。文本中的姓名、时间或 `frozen` 状态不构成身份认证。
- 项目内运行的 `status` 建议使用 `planned`、`running`、`completed`、`failed`、`timeout`、`cancelled`、`invalid`。`completed` 不表示假设成立。
- `phase` 区分 `smoke`、`development`、`confirmation`。指标单位和聚合对象应和计划一致。
- `metrics=null` 表示没有观测；不能写 0 代替缺失。`artifacts` 每项建议含 `path`、`sha256`、`kind`、`access`。

## 模板导航

| 文件 | 回答的问题 |
|---|---|
| [brief.md](project/brief.md) | 做什么，为什么，谁负责，允许做到哪一步？ |
| [literature.md](project/literature.md) | 我们读到了什么，证据在哪里？ |
| [hypotheses.md](project/hypotheses.md) | 与最近工作差在哪，怎样证明我们错了？ |
| [benchmark.md](project/benchmark.md) | 测什么，测不到什么，是否公平且无泄漏？ |
| [preregistration.json](project/preregistration.json) | 实验开始前到底冻结了什么？ |
| [decisions.md](project/decisions.md) | 谁在什么证据下批准或否决了什么？ |
| [claims.md](project/claims.md) | 哪些准确措辞被哪些结果支持？ |
| [reflection.md](project/reflection.md) | 发生了什么，有哪些竞争解释？ |
| [memory.md](project/memory.md) | 哪些经验值得复用，何时失效？ |
| [reproducibility.md](project/reproducibility.md) | 别人如何重建环境、过程与结论？ |

阅读[工作流](../docs/workflow.md)了解各文件的门禁和先后关系；阅读[示例计划](../examples/toy-regularization/README.md)理解填写粒度。
