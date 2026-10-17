# SAGE 实验执行 · execution

**实现位置**：[sage/execution](../../sage/execution/)。Agent Laboratory 的 MLESolver 代码编辑、失败反馈和候选选择机制已拆入此模块，来源与差异见[迁移对照](../../docs/agent-laboratory-migration.md)。

- **输入**：研究方案、冻结评价契约、有限尝试预算及明确选择的后端。
- **处理**：严格 EDIT/REPLACE → 生成候选 → 后端反馈 → 有界修复/改进 → 保留全部尝试与最佳有效候选。
- **评价**：当前固定开发集标量预测 MSE；候选提交预测，标签与指标计算由控制面持有。不把候选打印的分数或模型评审当测量。
- **输出**：代码候选、尝试与失败记录、评价状态及内容身份；不能据此宣称已完成真实科研。

## 三类后端

1. **dry-run（默认）**：保存候选而不执行；无运行指标，不产生科学结果。
2. **fixture（显式启用）**：仅允许内置合成测试路径，用于验证修复、选择与报告链。它不是任意 Python 执行器，也不是研究基准。
3. **Docker（显式启用）**：预安装固定镜像、冻结协议与明确执行授权；不自动安装或拉取镜像。此环境没有 Docker，实际容器运行和隔离尚未验证。

具体 CLI 参数和契约格式见[迁移与运行说明](../../docs/agent-laboratory-migration.md)。原 `sage run` 继续只生成 CoI 提案，不会自动调用新执行链。

生产接入还须满足[路线图 P1](../../docs/roadmap.md)与[执行适配器目标契约](../../docs/architecture.md)：可信审批、隔离与终止验证、数据/评分器保护、恢复、真实资源计量。当前有限后端与开发指标不代表全部达标；不自动下载数据、运行原始上游程序或启动 GPU 训练。

research-loop、steer、AiiDA 尚未集成。autoresearch 保持用户指定的计划 `completed`，运行/集成仍为 `not_run` / `not_integrated`。

[实验设计](../experiment_design/README.md) · [评审](../review/README.md) · [模块索引](../README.md)
