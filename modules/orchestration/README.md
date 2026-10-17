# SAGE 工作流编排 · orchestration

**主运行入口**：[sage/orchestration](../../sage/orchestration/)；共享契约与调用控制：[types.py](../../sage/types.py)、[config.py](../../sage/config.py)、[runtime.py](../../sage/runtime.py)。

控制器组合发现、文献、构思、review 与实验设计，生成研究提案产物。offline 和 live 使用同一逻辑/解析器，差别是注入的模型与检索提供方；离线 fixture 不是绕开链路的静态结果。

```bash
python -m sage doctor
python -m sage run --mode offline --topic "证据约束的研究构思" --output projects/sage-demo
```

## 运行职责

- 以 `Paper`、`Evidence`、`Chain`、`Candidate`、`NoveltyAssessment`、`ExperimentPlan`、`RunResult` 命名 dataclass 传递数据，避免位置字段串位。
- 限定查询改写、候选/链长度、新颖性再生成、评审轮数和重试次数。
- 所有提供方调用经过统一计数、单次超时和总墙钟预算；失败/重试也消耗额度。最大输出 token 预留不是实际计费金额。
- 严格解析阶段输出，保留错误、调用审计与不完整状态，不把格式失败标成研究成功。
- 原 `sage run` 保持提案语义；新 `sage laboratory` 显式连接代码迭代与报告链，分别记录执行与评价状态，不升级 scientific validation。

独立最终测试、可信身份审批、生产级调度和金额结算仍未实现。新增 Docker 适配器尚未真实容器实测，不据此宣称隔离已验证。详见[架构](../../docs/architecture.md)和[运行说明](../../docs/sage-runtime.md)。

## 旧 CoI 归档准备路径

[coi_agent.py](coi_agent.py) 与 [coi_patches.json](coi_patches.json) 保留兼容用途，**不是 SAGE 主运行路径**：

```bash
python scripts/coi.py inspect
python scripts/coi.py prepare --destination projects/coi-agent-runtime
```

`inspect` 验证固定源码；`prepare` 创建新的、被忽略的私有修补副本，附来源与变更记录，不覆盖既有目录、不安装依赖、不调用 API、不执行上游。五个补丁仅修正原有局部问题，不能使整个上游流程变成安全执行器。其剩余风险见[归档说明](../../third_party/coi_agent/README.md)。

SAGE 不导入 [upstream/main.py](../../third_party/coi_agent/upstream/main.py) 或其模块。上游 `main.py` 的配置副作用、依赖和无限循环不会通过默认 import 混入 SAGE；来源仍以逐字节快照保留。

[迁移对照](../../docs/sage-migration.md) · [实验执行边界](../execution/README.md) · [模块索引](../README.md)
