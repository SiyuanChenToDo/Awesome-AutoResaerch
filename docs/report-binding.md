# 自主报告与主稿的版本绑定

历史验收发现：文件SHA与收据完全一致，报告内部仍可能引用旧主稿、旧名单或旧指标。因此文件真实性与内容对齐分别检查。

`sage.autonomous.report.render_report` 接收主稿的**精确UTF-8字节**、代理撰写的完整中文讨论及管理器登记的综合版本。它生成三部分：绑定清单、从主JSON逐项生成的权威科学字段、完整保留的中文讨论。候选账本包含全部想法、淘汰理由、近邻工作、反证实验、预算、来源ID及可机械映射的来源URL；没有篇幅截短或摘要化替代。

清单绑定主JSON字节SHA、综合版本、候选数、候选ID及入选ID、选中候选的协议字段摘要、权威正文摘要和中文讨论摘要。主JSON不包含自己的SHA，避免自引用。综合版本来自管理器登记记录，而不是作者自述。

`validate_report` 根据当前JSON重新生成权威正文并逐字核对，因此只换头部SHA、改候选数量、替换入选名单、把单主指标改成共同主指标或追加未绑定的科学文字，都不能通过。存在结构化`protocol`的选中候选还交给协议校验器检查。正式归档与导出应调用同一函数，并传入对应收据的`synthesis_version`；导出在写入任何产物之前检查最新稿和历史最高分稿。

接口示例（不调用模型、不修改历史文件）：

```python
from sage.autonomous.report import render_report, validate_report

report = render_report(primary_bytes, chinese_discussion, synthesis_version=10)
audit = validate_report(primary_bytes, report, synthesis_version=10)
assert not audit['errors']
```

旧版自由格式报告返回`legacy_unverified`并阻断作为新规则下的正式报告导出；保留历史字节，不自动补写绑定或冒充旧版已经通过。旧JSON没有结构化协议时，即使新报告字段完全对齐，`protocol_structure`仍明确为`legacy_unverified`，不能当作协议已冻结。

这些检查只能证明版本与字段对齐。任意中文长篇讨论、JSON中的自由文本、引文蕴含和科学结论仍需语义审查；状态始终保留`narrative_semantics=not_independently_verified`、`scientific_validation=not_performed`。中文讨论不得另行定义当前主稿SHA、主次终点或实验判定；应将这类定义更新到主JSON的权威协议，再重新生成报告。对齐通过不代表实验已执行、新颖性成立、功效充分或独立验收完成。
