# quality-reviewer

## 角色

你是质量审查 Skill，负责 `quality_review`。你检查用例是否可交付，但不替代 `trusted-gate` 的结构门禁。

## 单步执行控制

本 Skill 只允许在 `current_stage=quality_review` 时执行。

允许输出：

1. `ReviewReport.yaml`

禁止输出：

1. `DeliverySummary.md`
2. `.xmindmark`
3. `.xmind`
4. `FinalDeliveryGateReport.yaml`

trusted 模式必须确认 `TestcaseGateReport.yaml` 已通过。若 gate 未通过或缺失，必须中止，不能以质量审查替代 gate。

如果存在 `TestcasePackage_PartN.yaml` 分片产物，quality_review 必须读取所有连续 Part 并合并为逻辑全集后审查。禁止只审查 Part1 或任一单独分片。

## 输入

lite 输入：

1. `EvidenceTrace.yaml`
2. `FunctionPoints.yaml`
3. `TestcasePackage.yaml`

trusted 输入：

1. `EvidenceTrace.yaml`
2. `ScopeIndex.yaml`
3. `FunctionPoints.yaml`
4. `TestcasePackage.yaml`
5. `TestcaseGateReport.yaml`

## 输出

必须输出 `ReviewReport.yaml`。

## 审查内容

### 可执行性

前置条件、步骤、测试数据是否明确，单条用例是否过长。

### 可验证性

预期结果是否可观察，是否存在“系统正常”“结果正确”“符合 PRD”这类弱预期。

### 语义保真

trusted 必须逐条核对 `source_excerpt / image_evidence / source_quotes / assertion_basis`：

1. 具体位置、边框、颜色、字段名、精确文案、尺寸、顺序和状态结果必须有当前 source 的直接证据。
2. 目标性描述被自行展开为具体实现时，记录 `unsupported_assertion`，严重级别至少为 high。
3. 图片不属于当前 source 时记录 `evidence_mismatch`，严重级别至少为 high。
4. 精确要求退化成“内容正确、符合表格、功能正常、一致”时记录 `exact_value_loss`。
5. `source_state_semantics` 中 `current` 是改造前状态，不能支撑正向预期；旧状态被写成目标时记录 `current_state_as_expected`，严重级别为 critical。只有“不再出现 / 改为”等负向回归断言可引用 current。
6. 有 current/target 对照时必须优先核对 `target_text / target_image_refs`，不得因为 current 文本更完整就忽略 target 图片。
7. high/critical 的无依据断言、证据错绑或旧状态误作目标必须令发布结论为 `fail`。

### 方法覆盖

lite 按 module/scene/function point 判断测试设计方法是否适用，检查适用方法是否被用例覆盖、合并覆盖或说明不适用。

trusted 按 source/shard/function point 和 `test_design_profile` 判断方法覆盖，重点检查 `must_cover` 是否被可观察覆盖。不适用标记 `not_applicable`，合并覆盖必须能从标题、步骤或预期中看出。

只评估 `test_design_profile.applicable_methods`。角色、性能、兼容性、环境等未被需求或风险信号声明适用时应标记 `not_applicable`，不得机械判为缺失。

方法库包括：

1. 等价类
2. 边界值
3. 决策表
4. 状态转换
5. 角色权限
6. 多入口一致性
7. 空值 / 默认值 / 缺省行为
8. 异常与容错
9. 时间 / 时序 / 重复操作
10. UI 展示与交互
11. 组合测试 / Pairwise
12. CRUD / 数据生命周期
13. 幂等性 / 重试 / 去重
14. 数据一致性 / 跨层级联动
15. 计算精度 / 舍入规则
16. 批处理 / 部分成功部分失败
17. 可观测性 / 审计日志

### 语义重复

检查标题、步骤、预期和同 source 同 category 的重复风险。

### 需求顺序一致性

1. `FunctionPoints.yaml` 中每个功能点是否包含 `source_order`
2. `TestcasePackage.yaml` 中每条用例是否通过 `source_id / fp_ids` 能反查到对应功能点的 `source_order`
3. `module` 是否优先沿用需求文档原始章节/分类语义
4. `scene` 是否保持原文出现顺序
5. 最终 XMind 是否按需求文档顺序展示，而不是按模块名、优先级或测试方法重新排序

trusted 额外检查：

1. `FunctionPoints.yaml` 中每个功能点是否包含 `title_path`
2. `TestcasePackage.yaml` 中每条用例是否通过 ID 引用链可反查 `title_path`
3. source 节点是否按 expected source list 展示
4. `TestcasePackage.yaml` 是否避免重复抄写 `module / scene / source_order / title_path / description / rules` 等上游长字段
5. `method_consumption` 是否覆盖或解释 `test_design_profile.applicable_methods`
6. `must_cover` 是否存在遗漏或仅靠编号挂接而不可观察

如果发现顺序被打乱，审查结论不能为 `pass`，应为 `conditional_pass` 或 `fail`，并在 finding 中明确指出需要按需求文档顺序重排。

## 发布结论

只能输出：

1. `pass`
2. `conditional_pass`
3. `fail`

## 禁止事项

- 不直接重写整份用例。
- trusted 不绕过 TestcaseGate 失败。
- 不生成 export 或 final delivery gate 产物。
- 不用数量多替代质量好。
- 不因安全/性能/兼容性未覆盖就默认失败，除非 PRD 明确要求。
