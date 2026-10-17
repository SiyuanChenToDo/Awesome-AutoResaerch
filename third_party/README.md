# 第三方来源归档

- [CoI-Agent](coi_agent/README.md)：Apache-2.0，固定提交的 15 个原始文件，包含实际研究链与提示词。原始上游流程未联网运行。

- [Agent Laboratory](agent_laboratory/README.md)：MIT，固定提交的 4 个原始文件（许可、角色、MLESolver 与 PaperSolver）；仅为选定源码快照，不是可直接运行的完整上游仓库。

原始快照集中保存并逐字节校验，不因 SAGE 品牌更名而修改名称、引用或文件内容。升级时重新检查许可/署名、文件范围和哈希，显式更新 manifest 并重新跑离线检查。

[SAGE 运行包](../sage/)是维护中的功能拆分与改造，不在运行时导入这里的原始模块。派生文件保留来源和修改声明；源码方法映射、偏离与许可证见[迁移说明](../docs/sage-migration.md)和[许可说明](../LICENSE-NOTICE.md)。旧归档 prepare 工具仅为兼容路径。
