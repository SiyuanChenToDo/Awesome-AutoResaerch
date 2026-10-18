# 可执行的有界科研闭环

`sage closed-loop` 将证据型提案、CoI v3 共享讨论、ARIS 主张评审门控、两轮开发反馈、原生 CORAL 训练评价、一次确认评价、统计分析、报告及声明账本连接到同一次运行。当前支持一个明确的符号回归课题实例。

## 执行与边界

模型真实生成想法、方案、评审、简化策略参数和报告草稿。自有 `sr_benchmark.py` 实现 GP 训练器及全部对照；模型只提交有类型和枚举边界的策略 JSON，不能提交 Python、改变评分器或指定测试集。两次开发尝试保留全部成绩，按预定验证 R² 选择策略，随后仅启动一次新种子确认网格。

三个自有解析函数分别是多项式、三角函数和双变量交互函数。每个种子独立生成训练、验证、域内测试、域外诊断及无标签探针输入。六个方法为无简化、LSH-only、probe-verified、exact-probe、两档固定大小惩罚。函数集为加减乘、sin、cos；没有 LM 常数优化或 PTC2。LSH 为自有随机超平面与范数桶实现，**不是论文原方法的精确复现**。`exact_probe` 仅表示有限探针精确数值相等。

默认种群 40、20 代、3 个开发种子、8 个确认种子。两轮开发共 108 次训练，确认共 144 次训练，每次 840 次适应度计算。哈希、探针及墙钟开销单独记录；LSH-only 的诊断探针也计入记录，不能据此推断自然实现的门控开销。固定惩罚阶梯未必匹配最终大小分布，必须报告每个函数的经验 KS 距离。

主比较为 probe-verified 减 LSH-only 的测试 R²；最小效应 0.02。按配对训练种子聚类，2000 次 bootstrap，对五项对照的符号翻转检验做 Holm 校正。八个种子无法保证功效；固定函数上的种子区间不能外推到新任务。

## 环境及入口

Linux 上需固定版本 ARIS、CORAL 运行时，以及非 root 可读可执行的候选 Python。CORAL 原生 `SubprocessGrader.grade` 调用自有 `TaskGrader`，再以 nobody 执行可信自有训练代码。候选解释器和 SAGE 分析环境需可选依赖 `numpy==2.2.6`。子进程环境不含 API 凭据。资源上限不构成网络沙箱，因此入口不执行模型生成的任意代码。

先在将要执行的同一份源码中生成协议并检查其内容，凭据只通过环境变量配置：

```bash
python -c 'import json; from sage.execution.research import protocol; print(json.dumps(protocol(), indent=2))' > projects/protocol.json
python -c 'import json; from sage.checkpoints import digest; print(digest(json.load(open("projects/protocol.json"))))'
python -m sage closed-loop \
  --topic 'Semantic-preserving symbolic regression with matched-compression controls' \
  --paper-corpus projects/recorded-corpus.json \
  --protocol projects/protocol.json --approved-protocol-digest REVIEWED_DIGEST \
  --coral-python /absolute/coral-runtime/bin/python \
  --candidate-python /absolute/readable-runtime/bin/python3 \
  --allow-live --allow-execution --output projects/new-closed-loop
```

`--config` 覆盖 RunConfig，但必须保留主张评审和 hybrid 讨论。默认研究配置有真实 API 费用，应按授权设置预算。`SAGE_ARIS_ROOT` 指向固定原版门控。当前显式使用固定真实论文语料，没有声称本轮完成联网最新查新。未配置独立 reviewer 或测试集保管人时，该限制始终保留。

输出目录必须全新。不支持静默恢复或自动重跑最终确认；失败保留预算和原始产物，再由负责人根据已经访问的范围决定下一次运行。

## 核查产物

- `proposal.json`、`checkpoint.json`：证据、想法、查新、共享讨论、方案和实际调用、失败、重试、SDK 用量。
- `protocol.json`、`design-review.json`：执行前冻结的划分、预算、方法、指标、停止规则及模型指出的范围差异。模型评审不是审批凭据。
- `development-*`：两轮训练及反馈，只有开发验证成绩，没有确认测试指标。
- `selection.json`：确认评价前冻结的策略、来源提案哈希与选择规则。
- `confirmation/measurements.json`：每个方法、函数、种子的训练、域内/域外测试、替换轨迹和语义审计。
- `analysis.json`、`claims.json`：固定分析、区间、复杂度匹配以及未支持或仍未知的主张。
- `report.md`：程序从观测表渲染的事实。`draft.md` 单独标识未核实模型草稿；`report.json` 保留写作、审稿和修订历史。
- `closure-checks.json`、`manifest.json`、`reflection.md`：连接检查、文件哈希和下一步。哈希不是第三方时间认证，自动检查不是独立科学复核。

`completed_closed_loop` 表示该范围内的端到端执行完成。研究结论可以是 `not_supported`，新颖性也可以未确立；不代表论文规模实验完成或方法优越。
