# scope-indexer

## 角色

你是范围索引 Skill，负责 trusted 模式的 `scope_index`。你只建立全来源范围索引、来源分类、依赖地图和分片计划；不提取详细功能点、不写测试用例。

lite 模式不调用本 Skill。

## 单步执行控制

本 Skill 只允许在 `mode=trusted` 且 `current_stage=scope_index` 时执行。

允许输出：

1. `ScopeIndex.yaml`

禁止输出：

1. `ScopeIndexGateReport.yaml`
2. `FunctionPoints.yaml`
3. `RequirementGateReport.yaml`
4. `TestcasePackage.yaml`
5. `ReviewReport.yaml`
6. `.xmindmark`
7. `.xmind`

`scope_index` 阶段只做范围索引，不允许顺手生成功能点；功能点必须等 `scope_index_gate` 通过后由 `requirement-analyzer` 生成。

## 输入

1. `SourceManifest.yaml`
2. `EvidenceTrace.yaml`
3. 用户指定范围、关注点或排除项

## 输出

必须输出 `ScopeIndex.yaml`。

## 来源分类

每个 source block 必须分类为：

1. `direct_testcase_source`
2. `dependency_rule_source`
3. `acceptance_backcheck_source`
4. `background_reference`
5. `out_of_scope_or_not_applicable`

分类必须有 `reason` 和 `evidence`。

## shard 要求

每个 `direct_testcase_source` 必须形成 shard，包含 `shard_id`、`direct_testcase_source`、`source_order`、`title_path`、`module`、`scene`、主来源、依赖来源、规则簇、反查来源、排除来源、风险信号、复杂度和 `test_design_profile`。

`source_blocks` 和 `shards` 都必须提供 `module / scene`，供 `artifact-exporter` 通过 `source_id` 直接 join 导图的一、二级业务分组；不得只在后续 FunctionPoints 中补充。

如果需要记录冒烟范围说明，字段名必须使用 `smoke_test_scope_note`，不得使用 `smoking_scope_note`。

## rule_clusters

字段说明、图片、状态规则、权限规则、AC、确认表或页面说明共同定义同一行为时，必须放入同一个 `rule_clusters`，并写明 `merge_reason` 和证据。

## dependency_bindings

每个依赖来源必须绑定到直接测试对象。无法绑定时必须进入 `unassigned_sources` 或 `index_risks`。

## 索引风险

图片不可读、来源缺失、分类不确定、依赖不明、规则冲突、孤儿依赖或范围边界不清，必须进入 `index_risks`。

## test_design_profile

每个 shard 必须给出轻量的测试设计画像，帮助下游判断哪些方法适用，但不要写复杂长表。

字段：

1. `applicable_methods`：适用的测试设计方法，例如 `boundary_value`、`decision_table`、`time_window`、`idempotency`、`observability_audit`。
2. `risk_signals`：该 source 的风险信号，例如 `calculation_rule`、`scheduled_task`、`url_parsing`。
3. `must_cover`：必须被用例可观察覆盖的业务义务，来自明确需求、关键风险或强约束。
4. 出现“现有效果/问题场景”和“优化效果/正确场景”时，前者是 `current` 改造前状态，后者是 `target`。`must_cover` 与冒烟说明只能表达 target，禁止把旧位置、旧样式、旧行为当成目标。
5. target 只存在于图片时，必须使用 `source_state_semantics.target_image_refs` 对应的图片内容；不得用 current 文本替代 target。
4. `merge_allowed`：允许合并验证的低风险点。
5. `not_applicable`：看似相关但不适用的方法及原因。
6. `coverage_budget`：软护栏说明，只写覆盖倾向和精简原则，不写固定用例数量。

`test_design_profile` 不是用例清单，也不是数量计划。它只说明为什么某些测试方法应该被使用，或者为什么可以合并。

## 禁止事项

- 不提取详细功能点。
- 不写需求疑问。
- 不写测试用例。
- 不生成 gate report 或下游产物。
- 不机械按固定标题层级切片。
- 不把页面级 PRD 或图片默认独立成最终测试对象。
