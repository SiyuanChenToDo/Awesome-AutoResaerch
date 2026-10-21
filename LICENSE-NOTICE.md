# SAGE 许可说明

SAGE（Scientific Agent for Grounded Exploration，基于证据探索的科研智能体）包含来自 CoI-Agent 的 Apache-2.0 派生代码/提示词，以及本仓库原创的契约、工具、文档与测试。**本仓库尚未为所有原创部分指定统一开源许可证**；公开可见不等于自动授予任意再许可、商用或分发权利。

- 原始清单按用户提供的内容归档，保留来源、原文件名与免责声明，不因产品更名而改写。
- 链接的论文、软件、数据、模型和服务遵守各自许可/条款；本仓库不能替它们授予许可。
- GitHub 的 `NOASSERTION` 是许可证识别状态，不是许可证名称。使用前阅读 LICENSE 原文，数据、权重与代码可能分别授权。
- [重点抽查](catalog/verification.json)仅记录查证时看到的信息，不提供法律结论。

## CoI-Agent 来源与派生代码

上游：[DAMO-NLP-SG/CoI-Agent](https://github.com/DAMO-NLP-SG/CoI-Agent)，Li et al.；固定提交 `ac94317ff2d1997f362747edc2c9e5f0fdc9c450`。原始完整引用保留在[上游 README](third_party/coi_agent/upstream/README.md)。

- 归档的 15 个原始文件逐字节保留，包括原 [Apache License 2.0](third_party/coi_agent/upstream/LICENSE)；该固定提交没有独立 NOTICE 文件。范围和哈希见[来源清单](third_party/coi_agent/manifest.json)。
- `sage/` 中从上游拆分/改写的提示词、研究链和适配器保留来源与醒目的修改声明，适用的 Apache-2.0 文本另存 [LICENSES/CoI-Agent-Apache-2.0.txt](LICENSES/CoI-Agent-Apache-2.0.txt)。
- [NOTICE.md](NOTICE.md)列明派生关系与修改；[迁移对照](docs/sage-migration.md)逐项说明方法归属与行为偏离。不得删除适用署名，也不得暗示上游认可 SAGE。
- 旧 [coi_patches.json](modules/orchestration/coi_patches.json)仅由兼容准备器生成带修改记录的私有归档副本；它不是 SAGE 运行依赖。

第三方许可适用于对应上游及派生部分，不自动为本仓库所有原创部分新增统一许可证。分发或进一步修改前应审查各部分的具体权利和义务。

## Agent Laboratory 来源与派生代码

上游 [SamuelSchmidgall/AgentLaboratory](https://github.com/SamuelSchmidgall/AgentLaboratory)，固定提交 `d9017d90e329112d2a80b7712f37ee9094d2cd27`。MIT License，Copyright (c) 2025 Samuel Schmidgall。完整许可见 [LICENSES/Agent-Laboratory-MIT.txt](LICENSES/Agent-Laboratory-MIT.txt)，原文件和哈希见[来源归档](third_party/agent_laboratory/README.md)。维护中的执行、写作与报告评审派生部分保留来源和修改说明；[迁移表](docs/agent-laboratory-migration.md)列明实际改造及未迁移功能。该许可不改变本仓库其他原创部分的许可状态。


## ARIS 与 CORAL 可选接入

ARIS 方法派生的主张拆解、查新与候选视角保留 MIT 归属，完整许可见 [LICENSES/ARIS-MIT.txt](LICENSES/ARIS-MIT.txt)。原版门控由外部固定源码执行；CORAL 由外部固定包提供 SubprocessGrader/TaskGrader 接口，许可见 [LICENSES/CORAL-Apache-2.0.txt](LICENSES/CORAL-Apache-2.0.txt)。源码提交、修改范围与自有适配器说明见 [NOTICE.md](NOTICE.md) 和[接入文档](docs/aris-coral-runtime.md)。不因接入而改变其他部分的许可，也不表示上游背书。
