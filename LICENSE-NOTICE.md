# 许可说明

本仓库尚未为原创脚手架指定统一开源许可证，维护者可以在决定后单独添加。仓库公开可见不等于授予任意再许可、商用或分发权利。

- 原始清单按用户提供的内容原样归档，保留其来源与免责声明。
- 链接的论文、软件、数据、模型和服务遵守各自许可证与使用条款；本仓库不会替它们授予许可。
- GitHub 的 `NOASSERTION` 是许可证识别状态，不是一个许可证名称。使用前阅读项目 LICENSE 原文，尤其注意数据、权重和代码可能各自不同。
- [重点抽查](catalog/verification.json) 只记录查证时看到的条款信息，不提供法律结论。

## 已随仓库分发的第三方源码

[CoI-Agent](third_party/coi_agent/README.md) 固定于 `ac94317ff2d1997f362747edc2c9e5f0fdc9c450`，随附原始 [Apache License 2.0](third_party/coi_agent/upstream/LICENSE)。15 个纳入文件逐字节保留，版权与署名不删除；该上游版本没有单独 NOTICE 文件。我们的可审阅补丁位于 [coi_patches.json](modules/orchestration/coi_patches.json)，仅生成带修改声明的私有副本。第三方许可只适用于相应上游内容，不为本仓库其他原创部分新增统一许可。
