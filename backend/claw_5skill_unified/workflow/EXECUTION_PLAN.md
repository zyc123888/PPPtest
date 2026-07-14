# 执行计划

## mode 选择

入口必须先确定 `mode`：

1. `mode=lite`
2. `mode=trusted`

不得同时混跑两种模式。一个任务只能选择一个 mode；如果用户要求对比两种结果，应分别生成两个 output 目录。

## 执行方式

默认按 `SINGLE_STEP_PROTOCOL.md` 单步执行。不要把总提示词、完整 PRD 和所有阶段目标一次性交给模型连续跑完。

每一步必须声明：

1. `mode`
2. `current_stage`
3. `allowed_inputs`
4. `allowed_outputs`
5. `forbidden_outputs`
6. `gate_required_before`
7. `stage_done_condition`

若本阶段产出了 `forbidden_outputs` 中的文件，视为阶段偷跑，必须退回当前阶段重跑。

## 启动前工作区检查

全新运行进入 `orchestrate` 前，必须检查 `output_dir`：

1. 本次运行必须生成唯一 `run_id`。
2. 如果目录中存在历史 `EvidenceTrace.yaml`、`ScopeIndex.yaml`、`FunctionPoints.yaml`、`TestcasePackage.yaml`、`ReviewReport.yaml`、`*.xmindmark`、`*.xmind` 或 gate report，不得直接复用。
3. 历史产物必须归档到 `_archive/<timestamp_or_old_run_id>/`，或在用户明确授权后删除。
4. 未完成清理、归档或 `run_id` 校验前，禁止进入下游阶段。

`run_id` 格式固定为 `run_<yyyyMMdd-HHmmss>_<4位随机大写字母数字>`，例如 `run_20260703-153022_A7K9`。`_archive` 默认保留最近 3 次归档；超出部分只能提示用户确认删除或压缩，未授权不得自动删除。

## lite

适用：快速生成可交付 XMind，不要求 source 级可信门禁。

```text
orchestrate
-> evidence_trace
-> requirement
-> testcase
-> quality_review
-> export
```

lite 门禁：

1. 缺少 `EvidenceTrace.yaml`，禁止进入 testcase。
2. 缺少 `FunctionPoints.yaml`，禁止进入 testcase。
3. 缺少 `TestcasePackage.yaml`，禁止进入 quality_review。
4. 缺少 `ReviewReport.yaml`，禁止进入 export。
5. `.xmind` 必须由项目确定性 exporter 从 `.xmindmark` 生成；export 后必须解析实际 `.xmind` 并核对根节点和 SRC/FP/TC 数量。
6. 如果 `xmindmark` 缺失或执行失败，只能保留 `.xmindmark` 和 `DeliverySummary.md` 作为待转换产物，不能宣称 `.xmind` 已交付，不能用脚本或手工压缩包替代转换。

lite 图片证据门禁：

1. 有图片链接但 `EvidenceTrace.yaml` 未记录 `download_status`，禁止进入 requirement。
2. `download_status=success` 但没有 `vision_status` 或识图结果，禁止把图片作为确定证据。
3. 没有可用下载/识图工具时，必须写入失败状态和待确认项。
4. 下载或识图失败时，`failed_images`、`images` 失败项和 `pending_confirmations` 必须一致。

lite 使用模板：

```text
schemas/lite/evidence_trace.template.yaml
schemas/lite/function_points.template.yaml
schemas/lite/testcase_package.template.yaml
schemas/lite/review_report.template.yaml
schemas/lite/xmindmark.template.md
schemas/lite/delivery_summary.template.md
```

lite XMind 规则：

1. 结构为 `模块 -> 场景 -> FP -> TC`。
2. 按 `source_order` 保持需求文档顺序。
3. 最终文案中文化。
4. `.xmindmark` 必须按 Depth 生成缩进，前导空格数为 `(Depth - 1) * 2`，禁止 Tab 和奇数空格。
5. 节点文本必须是纯文本，禁止 Markdown 加粗、斜体、下划线或 `* ` 列表标记。
6. 节点文本禁止半角中括号 `[` 和 `]`，特殊标记使用 `【】` 或 `()`。
7. 节点内容必须单行，禁止物理换行符 `\n`；多子动作使用 `；` 或 `／`。

## trusted

适用：严格追溯、source 守恒、门禁检查和最终交付审计。

```text
orchestrate
-> evidence_trace
-> scope_index
-> scope_index_gate
-> requirement
-> requirement_gate
-> testcase_by_source_shard
-> testcase_gate
-> quality_review
-> export
-> final_delivery_gate
```

说明：`collect` 和 `image_analysis` 不是独立 `current_stage`，已合并为 `evidence_trace` 阶段内部动作。阶段矩阵中只允许使用 `current_stage=evidence_trace`。

trusted 门禁：

1. 缺少 `SourceManifest.yaml`，禁止进入 evidence 后续阶段。
2. 缺少 `EvidenceTrace.yaml`，禁止进入 `scope_index`。
3. 缺少 `ScopeIndex.yaml`，禁止进入 `scope_index_gate`。
4. `ScopeIndexGateReport.yaml` 未通过，禁止进入 `requirement`。
5. 缺少 `FunctionPoints.yaml`，禁止进入 `requirement_gate`。
6. `RequirementGateReport.yaml` 未通过，禁止进入 `testcase_by_source_shard`。
7. 缺少 `TestcasePackage.yaml`，禁止进入 `testcase_gate`。
8. `TestcaseGateReport.yaml` 未通过，禁止进入 `quality_review`。
9. `ReviewReport.yaml` 结论为 `fail`，禁止默认导出。
10. `FinalDeliveryGateReport.yaml` 未通过，禁止交付 `.xmind`。
11. 如果 `xmindmark` 命令缺失或转换失败，`final_delivery_gate` 必须失败并回到 `export`，不得把 `.xmindmark` 作为最终 `.xmind` 交付。
12. `final_delivery_gate` 必须运行本地硬校验器，并把通过结果作为放行依据：

```bash
python3 tools/validate_trusted_output.py "<output_dir>"
```

该命令返回非 0 时，`FinalDeliveryGateReport.yaml` 必须 `status=fail`，并按错误类型回到 `export`、`testcase_by_source_shard`、`requirement` 或 `scope_index`。

Gate 独立审计原则：

Gate 不是生成助手，而是独立审计员。任何硬约束不满足，都必须立即判定 `status=fail`，写出 `blocking_issues`，指定 `return_to`，并输出中止模板。禁止为了推进流程而忽略问题、代填字段、把不确定解释为通过，或因为整体看起来接近而放行。

Gate Quiet Pass：

Gate 通过时必须输出极简回执，禁止展开逐项解释、长 reason 或重复上游字段。

```yaml
gate: "requirement_gate"
status: "pass"
checked_artifacts:
  - "ScopeIndex.yaml"
  - "FunctionPoints.yaml"
blocking_issues: []
```

Gate 失败时才允许展开 `blocking_issues / return_to / return_reason`，并必须立即中止后续 pipeline。

Gate 失败局部恢复：

Gate 失败时必须同时输出 `recovery_plan`，用于减少不必要的全链路重跑。`strategy` 只能是 `local_rerun`、`stage_rerun`、`upstream_rerun`、`manual_confirm` 或 `none`。

1. `local_rerun`：只重跑受影响的 `source_id / shard_id / fp_id / case_id`。
2. `stage_rerun`：重跑当前 gate 对应的完整上游阶段。
3. `upstream_rerun`：回到更早阶段修正 source 或 FP。
4. `manual_confirm`：需要用户补充信息后再继续。
5. gate 通过时使用 `none`。

`testcase_gate` 若只发现少量 FP 未覆盖、同 source 用例重复、步骤/预期不可观察，应优先返回 `local_rerun -> testcase_by_source_shard`，并列出具体 `source_ids / shard_ids / fp_ids / case_ids`。只有上游 source/FP 归属错误时，才扩大到 `requirement` 或 `scope_index`。

Gate 失败中止动作：

任何 gate 判定为不通过时，必须立即中止后续 pipeline 执行，输出对应 gate report，并使用以下最终答复模板：

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

禁止在 gate 失败后继续生成下游阶段产物。

trusted 图片证据门禁：

1. 有图片链接但 `EvidenceTrace.yaml.images` 未记录下载工具、下载状态、识图工具或识图状态，禁止进入 `scope_index`。
2. 图片下载或识图失败时，必须进入 `pending_confirmations`，并在 `scope_index.index_risks` 中体现。
3. 不能把 alt 文本、URL 文件名、图注或上下文描述当作图片识别证据。
4. 下载或识图失败时，`failed_images`、`images` 失败项和 `pending_confirmations` 必须一致。

trusted 使用模板：

```text
schemas/trusted/source_manifest.template.yaml
schemas/trusted/evidence_trace.template.yaml
schemas/trusted/scope_index.template.yaml
schemas/trusted/gate_report.template.yaml
schemas/trusted/function_points.template.yaml
schemas/trusted/testcase_package.template.yaml
schemas/trusted/review_report.template.yaml
schemas/trusted/xmindmark.template.md
schemas/trusted/delivery_summary.template.md
```

trusted XMind 规则：

1. 结构为 `模块 -> 场景 -> SRC -> FP -> TC`。
2. `SRC` 节点命名必须使用 `source_id + "｜" + title_path`。
3. 禁止 `root -> TC`、`SRC -> TC`、`模块 -> TC`、`场景 -> TC` 等扁平结构。
4. 按 `source_order` 保持需求文档顺序。
5. 最终文案中文化。
6. `.xmindmark` 必须按 Depth 生成缩进，前导空格数为 `(Depth - 1) * 2`，禁止 Tab 和奇数空格。
7. 节点文本必须是纯文本，禁止 Markdown 加粗、斜体、下划线或 `* ` 列表标记。
8. 节点文本禁止半角中括号 `[` 和 `]`，特殊标记使用 `【】` 或 `()`。
9. 节点内容必须单行，禁止物理换行符 `\n`；多子动作使用 `；` 或 `／`。

trusted ID 强引用规则：

1. `ScopeIndex.yaml` 保留 source 的 `module / scene / source_order / title_path`。
2. `FunctionPoints.yaml` 保留 FP 的 `description / rules / test_hints / title_path`。
3. `TestcasePackage.yaml` 只保留 `case_id / source_id / shard_id / fp_ids / title / category / priority / steps / expected_results / evidence_refs / design_method` 等用例差异字段。
4. `TestcasePackage.yaml` 禁止重复抄写 `module / scene / source_order / title_path / description / rules / traceability / generation_basis.rationale`。
5. `testcase_gate` 和 `final_delivery_gate` 必须校验 `source_id / fp_ids / shard_id` 可 join 到上游产物。
6. `artifact-exporter` 必须通过 ID join 拼接导图层级和章节标题，禁止猜测补齐。

## YAML 与输出体量规则

1. 所有 YAML 中间产物禁止使用 `null`、`~`、`none`。
2. 列表为空时输出 `[]`，文本为空时输出 `""`，对象为空时输出 `{}`。
3. 必填 key 即使为空也必须保留。
4. 字符串包含冒号、中括号、减号、井号、英文逗号、英文双引号或换行时，必须使用双引号包裹。
5. 生成 `FunctionPoints.yaml`、`TestcasePackage.yaml`、`.xmindmark` 前必须评估输出体量。
6. trusted 模式预估输出过大时，必须在 orchestrate 阶段规划 `TestcasePackage_PartN.yaml` 分片，避免单次输出截断。
7. export 阶段填写统计信息时，必须基于 `case_id / fp_id / source_id` 做穷举计数，禁止估算。
8. 如果存在 `TestcasePackage_PartN.yaml`，`testcase_gate / quality_review / export / final_delivery_gate` 必须读取所有连续 Part 并合并检查；禁止只检查或导出 Part1。
9. trusted 的 `TestcasePackage.yaml` 或每个 `TestcasePackage_PartN.yaml` 必须包含 `xmind_grouping_contract`。
10. export 后必须用 `tools/validate_trusted_output.py` 穷举核对 `source_id / fp_id / case_id`，禁止人工估算统计信息。

## 测试设计适用性规则

lite 和 trusted 都使用测试设计方法库，但不得用固定用例条数作为生成目标。

lite：

1. 每个 FP 先判断 `applicable_methods`。
2. 只有方法能产生可观察、非重复、与证据相关的测试差异时才生成用例。
3. 可合并验证点必须在标题、步骤或预期中可观察。
4. 不为凑数量生成低信息量用例，也不为精简遗漏明确风险、边界、条件分支或异常路径。

trusted：

1. `ScopeIndex.yaml.shards[].test_design_profile` 必须声明适用方法、风险信号、must_cover、允许合并项和不适用原因。
2. `coverage_budget` 是软护栏，不是目标数量。
3. `testcase_gate` 必须检查 `must_cover` 是否被覆盖，`applicable_methods` 是否被消费、合并或说明不适用。
4. 高风险验证点不得因为精简被删除；低风险重复点可以合并。

## 输出目录规则

建议输出目录：

```text
outputs/<需求文档名>/lite/
outputs/<需求文档名>/trusted/
```

如果只跑一种模式，也应在目录名中包含 mode，避免覆盖另一种模式产物。
