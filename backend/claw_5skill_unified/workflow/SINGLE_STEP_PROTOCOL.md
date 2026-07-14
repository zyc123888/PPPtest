# 单步执行协议

本协议用于降低长会话中的状态漂移、阶段偷跑和规则淡忘风险。无论由工程脚本调用，还是人工在同一会话中分阶段执行，都应按“单步 Prompt + 上游产物注入”的方式运行。

## 核心原则

1. 每次调用只能执行一个 `current_stage`。
2. 每次调用只注入当前阶段需要的上游产物，不依赖聊天记忆补上下文。
3. 每次调用只能创建或修改 `allowed_outputs` 中声明的文件。
4. 如果生成了非本阶段允许的下游产物，本阶段视为失败，必须删除错误产物并重跑当前阶段。
5. gate 阶段未通过时，禁止进入下游阶段。
6. export 阶段必须重新读取 `ReviewReport.yaml` 和 gate report，不允许凭记忆写统计信息、中文化映射或审查结论。
7. 每个阶段完成后必须做本阶段完成条件检查，再进入下一阶段。
8. gate 阶段返回失败时，必须使用标准中止答复模板，不得继续 pipeline。
9. 生成大体量 YAML 或 `.xmindmark` 前必须评估输出长度，避免截断；trusted 输出过大时必须分片。
10. YAML 空值必须使用类型占位符：列表 `[]`，文本 `""`，对象 `{}`。
11. 全新 `orchestrate` 必须先完成工作区清理检查，避免读取历史同名产物。
12. gate 必须按独立审计原则执行，任何硬约束不满足都必须返回失败。
13. trusted 的 `final_delivery_gate` 必须运行 `tools/validate_trusted_output.py <output_dir>`；脚本返回非 0 时不得交付 `.xmind`。

## 工作区清理协议

`orchestrate` 阶段启动新运行前，必须检查 `output_dir`：

1. 为本次运行生成唯一 `run_id`。
2. 扫描 `output_dir` 中是否存在历史下游产物。
3. 历史下游产物包括 `EvidenceTrace.yaml`、`ScopeIndex.yaml`、`FunctionPoints.yaml`、`RequirementGateReport.yaml`、`TestcasePackage.yaml`、`TestcaseGateReport.yaml`、`ReviewReport.yaml`、`DeliverySummary.md`、`*.xmindmark`、`*.xmind`、`FinalDeliveryGateReport.yaml`。
4. 发现历史产物时，必须归档到 `_archive/<timestamp_or_old_run_id>/`，或在用户明确授权后删除。
5. 未完成清理、归档或 `run_id` 校验前，不得进入下游阶段。
6. 每个阶段只能读取当前 `run_id/output_dir` 的上游文件，不得跨目录读取同名文件。

`run_id` 格式必须为 `run_<yyyyMMdd-HHmmss>_<4位随机大写字母数字>`，例如 `run_20260703-153022_A7K9`。不得使用 `test1`、`run001` 或纯日期。

`_archive` 默认保留最近 3 次归档。超过 3 次的旧归档只能提示用户确认删除或压缩；未获得明确授权时，不得自动物理删除旧归档。

## 单步调用头

每次调用 Claw 时，Prompt 顶部必须包含：

```yaml
mode: lite | trusted
current_stage: <stage_name>
output_dir: <absolute_or_relative_output_dir>
allowed_inputs:
  - <input_file_or_source>
allowed_outputs:
  - <output_file>
forbidden_outputs:
  - <downstream_file_or_pattern>
gate_required_before:
  - <gate_report_or_none>
stage_done_condition:
  - <check_item>
```

如果当前阶段缺少 `allowed_inputs` 中的必需文件，应中止并说明缺失文件，不得跳过阶段或自行从原始 PRD 推断下游结果。

## lite 阶段矩阵

| current_stage | allowed_inputs | allowed_outputs | forbidden_outputs | stage_done_condition |
|---|---|---|---|---|
| orchestrate | 用户请求、需求文档路径、模式参数 | 执行计划说明或 SourceManifest 可选摘要 | FunctionPoints.yaml、TestcasePackage.yaml、ReviewReport.yaml、.xmindmark、.xmind | mode 和 output_dir 已确定 |
| evidence_trace | 原始需求材料、图片链接、本地附件 | EvidenceTrace.yaml | FunctionPoints.yaml、TestcasePackage.yaml、ReviewReport.yaml、.xmindmark、.xmind | 图片下载/识别工具状态、failed_images、失败降级原因和待确认项已记录 |
| requirement | EvidenceTrace.yaml、用户范围说明 | FunctionPoints.yaml | TestcasePackage.yaml、ReviewReport.yaml、.xmindmark、.xmind | 每个 FP 有 module、scene、source_order、source_refs |
| testcase | FunctionPoints.yaml、EvidenceTrace.yaml、优先级/范围/覆盖侧重点 | TestcasePackage.yaml | ReviewReport.yaml、.xmindmark、.xmind | 每条用例绑定 FP，且保留 module、scene、source_order |
| quality_review | EvidenceTrace.yaml、FunctionPoints.yaml、TestcasePackage.yaml | ReviewReport.yaml | .xmindmark、.xmind | release_readiness 和 findings 已输出 |
| export | TestcasePackage.yaml、ReviewReport.yaml | DeliverySummary.md、需求文档同名.xmindmark、需求文档同名.xmind | FunctionPoints.yaml、TestcasePackage.yaml、ReviewReport.yaml | XMindMark 结构正确，xmindmark 转换成功 |

## trusted 阶段矩阵

| current_stage | allowed_inputs | allowed_outputs | forbidden_outputs | gate_required_before | stage_done_condition |
|---|---|---|---|---|---|
| orchestrate | 用户请求、需求文档路径、模式参数 | SourceManifest.yaml、执行计划说明 | EvidenceTrace.yaml、ScopeIndex.yaml、FunctionPoints.yaml、TestcasePackage.yaml、ReviewReport.yaml、.xmindmark、.xmind | not_applicable | mode、output_dir、输入来源清单已确定 |
| evidence_trace | SourceManifest.yaml、原始需求材料、图片链接、本地附件 | EvidenceTrace.yaml | ScopeIndex.yaml、FunctionPoints.yaml、TestcasePackage.yaml、ReviewReport.yaml、.xmindmark、.xmind | not_applicable | 正文、表格、图片、工具状态、failed_images、失败降级原因和待确认项已绑定来源 |
| scope_index | SourceManifest.yaml、EvidenceTrace.yaml、用户范围说明 | ScopeIndex.yaml | ScopeIndexGateReport.yaml、FunctionPoints.yaml、TestcasePackage.yaml、ReviewReport.yaml、.xmindmark、.xmind | not_applicable | direct sources、dependency bindings、shards、index risks 已输出 |
| scope_index_gate | SourceManifest.yaml、EvidenceTrace.yaml、ScopeIndex.yaml | ScopeIndexGateReport.yaml | FunctionPoints.yaml、TestcasePackage.yaml、ReviewReport.yaml、.xmindmark、.xmind | not_applicable | pass 时极简回执；fail 时 blocking_issues、return_to 已输出 |
| requirement | EvidenceTrace.yaml、ScopeIndex.yaml、ScopeIndexGateReport.yaml、当前 shard 信息 | FunctionPoints.yaml | RequirementGateReport.yaml、TestcasePackage.yaml、ReviewReport.yaml、.xmindmark、.xmind | ScopeIndexGateReport.yaml status=pass | 每个 FP 继承 source_id、shard_id、source_order、title_path |
| requirement_gate | ScopeIndex.yaml、FunctionPoints.yaml、ScopeIndexGateReport.yaml | RequirementGateReport.yaml | TestcasePackage.yaml、ReviewReport.yaml、.xmindmark、.xmind | ScopeIndexGateReport.yaml status=pass | pass 时极简回执；fail 时 expected source list 问题已输出 |
| testcase_by_source_shard | ScopeIndex.yaml、FunctionPoints.yaml、RequirementGateReport.yaml | TestcasePackage.yaml | TestcaseGateReport.yaml、ReviewReport.yaml、.xmindmark、.xmind | RequirementGateReport.yaml status=pass | 每条用例绑定 source、shard、FP，且不跨 source 合并；不重复上游长字段 |
| testcase_gate | ScopeIndex.yaml、FunctionPoints.yaml、TestcasePackage.yaml、RequirementGateReport.yaml | TestcaseGateReport.yaml | ReviewReport.yaml、.xmindmark、.xmind | RequirementGateReport.yaml status=pass | FP/source 覆盖、must_cover、方法消费、孤立用例和 ID join 检查已输出 |
| quality_review | EvidenceTrace.yaml、ScopeIndex.yaml、FunctionPoints.yaml、TestcasePackage.yaml、TestcaseGateReport.yaml | ReviewReport.yaml | .xmindmark、.xmind、FinalDeliveryGateReport.yaml | TestcaseGateReport.yaml status=pass | release_readiness、order_consistency、findings 已输出 |
| export | ScopeIndex.yaml、FunctionPoints.yaml、TestcasePackage.yaml、TestcaseGateReport.yaml、ReviewReport.yaml | DeliverySummary.md、需求文档同名.xmindmark、需求文档同名.xmind | FinalDeliveryGateReport.yaml | TestcaseGateReport.yaml status=pass | 通过 ID join 完成统计信息、中文化映射、SRC 层级、xmindmark 转换 |
| final_delivery_gate | ScopeIndex.yaml、FunctionPoints.yaml、TestcasePackage.yaml、ReviewReport.yaml、DeliverySummary.md、需求文档同名.xmindmark、需求文档同名.xmind、本地校验器输出 | FinalDeliveryGateReport.yaml | FunctionPoints.yaml、TestcasePackage.yaml、ReviewReport.yaml | not_applicable | `tools/validate_trusted_output.py <output_dir>` 返回 0；pass 时极简回执；fail 时 source list、统计、中文化、层级问题已输出 |

## 阶段偷跑判定

出现以下任一情况，必须判定为阶段偷跑：

1. `scope_index` 阶段生成了 `FunctionPoints.yaml`。
2. `requirement` 阶段生成了 `TestcasePackage.yaml`。
3. `testcase_by_source_shard` 阶段生成了 `ReviewReport.yaml`。
4. `quality_review` 阶段生成了 `.xmindmark` 或 `.xmind`。
5. `export` 阶段修改了 `FunctionPoints.yaml`、`TestcasePackage.yaml` 或 `ReviewReport.yaml`。
6. 任一 gate 阶段为了继续流程而修改上游产物。

## 阶段完成回执

每个阶段结束时，必须给出简短回执：

```text
stage: <current_stage>
status: completed | returned | blocked
created_or_updated:
  - <file>
not_created:
  - <forbidden downstream file>
next_stage: <stage_name_or_not_applicable>
gate_status: pass | return | not_applicable
recovery_strategy: none | local_rerun | stage_rerun | upstream_rerun | manual_confirm
rerun_scope: source_ids=[] shard_ids=[] fp_ids=[] case_ids=[]
```

回执不能替代产物文件；产物文件仍必须按 schema 写入输出目录。

## Gate 失败局部恢复协议

Gate 失败必须先中止，不允许继续生成下游产物。但 gate report 必须给出 `recovery_plan`，用于判断是否可以局部重跑。

`recovery_plan.strategy` 取值：

1. `local_rerun`：只重跑受影响的 source/shard/fp。
2. `stage_rerun`：重跑当前 gate 对应的完整上游阶段。
3. `upstream_rerun`：回到更早阶段重建 source 或 FP。
4. `manual_confirm`：需要用户补充信息。
5. `none`：gate 通过。

局部重跑必须满足：

1. `rerun_scope.source_ids / shard_ids / fp_ids / case_ids` 明确列出影响范围。
2. `preserve_artifacts` 明确列出不得改动的上游产物。
3. `regenerate_artifacts` 明确列出允许重写的产物。
4. 重跑完成后必须重新执行对应 gate。
5. 禁止以局部重跑为由跳过失败 gate 或修改无关 source。

`testcase_gate` 推荐恢复映射：

1. 少量 FP 未覆盖、同 source 用例重复、步骤/预期不可观察：`local_rerun -> testcase_by_source_shard`。
2. 多个 source 系统性用例设计失败：`stage_rerun -> testcase_by_source_shard`。
3. source/FP 引用无法 join 且上游归属错误：`upstream_rerun -> requirement` 或 `scope_index`。
4. 需求不明确或图片证据缺失：`manual_confirm`。

## 分片产物聚合协议

如果存在 `TestcasePackage_Part1.yaml`、`TestcasePackage_Part2.yaml` 等分片产物，后续 `testcase_gate / quality_review / export / final_delivery_gate` 必须读取所有连续 Part 文件并合并为逻辑全集后再处理。

聚合规则：

1. `part_index` 必须从 1 连续到 `part_total`。
2. 实际 Part 文件数量必须等于 `part_total`。
3. 合并后的 `case_id` 必须全局唯一。
4. 覆盖、must_cover、方法消费、重复、统计和导图导出都必须基于合并全集。
5. 禁止只读取 Part1 或任一单独分片。

## Gate 失败中止答复

如果当前阶段是 gate，且 gate report 中 `status=fail` 或 `decision=return`，最终答复必须为：

```text
【流水线中止：未通过 <Gate名称> 门禁】

原因分析：
- [问题1] xxxx
- [问题2] xxxx

待确认/待修复项：
- xxxx
- xxxx

恢复建议：
- 策略：local_rerun / stage_rerun / upstream_rerun / manual_confirm
- 回退阶段：<return_to>
- 重跑范围：source_ids=[...] shard_ids=[...] fp_ids=[...] case_ids=[...]

请解决以上问题，或补充相关背景输入后，再次运行该阶段。
```
