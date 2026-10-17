# SAGE 科研写作 · writing

**实现位置**：[sage/writing](../../sage/writing/)。借鉴 Agent Laboratory 的 PaperSolver 章节化写作、评审和有限修订机制，实际提示词与代码按职责维护，运行时不导入上游脚本。

- **输入**：提案、允许引用的证据、代码尝试记录和明确的执行/评价状态。
- **处理**：章节草稿 → 报告评审 → 有界修订；保留来源与未知标签。
- **输出**：研究报告草稿。dry-run、合成 fixture 与真实后端观测必须区分；没有运行证据时不写成真实实验结果。

逐项迁移范围、产物与命令见[Agent Laboratory 对照](../../docs/agent-laboratory-migration.md)。原 CoI 提案命令仍不自动写论文；新的 laboratory 入口显式组合报告链。

这不是完整原版复刻：不自动编译或执行生成的 LaTeX、不自动投稿，不承诺模型草稿具有事实正确性或达到发表质量。模型评分与内部评审不能代替独立科学验证。

公开前按[工作流 G5](../../docs/workflow.md)核验每个定量声明、真实 run ID、引用、许可、隐私与负责人批准。编写报告不授予发表或联系第三方的权限。

[评审与核验](../review/README.md) · [模块索引](../README.md)
