# 示例流程

## lite 示例

输入：

```text
按 lite 模式分析 DSP - DSP平台整体交互优化.md，并生成测试用例 XMind。
```

执行：

```text
step 1: orchestrate(mode=lite)
step 2: evidence_trace(input=原始需求材料, output=EvidenceTrace.yaml)
step 3: requirement(input=EvidenceTrace.yaml, output=FunctionPoints.yaml)
step 4: testcase(input=FunctionPoints.yaml + EvidenceTrace.yaml, output=TestcasePackage.yaml)
step 5: quality_review(input=EvidenceTrace.yaml + FunctionPoints.yaml + TestcasePackage.yaml, output=ReviewReport.yaml)
step 6: export(input=TestcasePackage.yaml + ReviewReport.yaml, output=DeliverySummary.md + .xmindmark + .xmind)
```

输出：

```text
outputs/DSP - DSP平台整体交互优化/lite/EvidenceTrace.yaml
outputs/DSP - DSP平台整体交互优化/lite/FunctionPoints.yaml
outputs/DSP - DSP平台整体交互优化/lite/TestcasePackage.yaml
outputs/DSP - DSP平台整体交互优化/lite/ReviewReport.yaml
outputs/DSP - DSP平台整体交互优化/lite/DSP - DSP平台整体交互优化.xmindmark
outputs/DSP - DSP平台整体交互优化/lite/DSP - DSP平台整体交互优化.xmind
```

lite 导图示例：

```text
DSP - DSP平台整体交互优化测试用例
- 统计信息
- 模块：筛选栏优化
  - 场景：More Filters收起
    - FP-001：More Filters 二级筛选布局与收起交互
      - TC-001-001-More Filters 主流程验证
```

## trusted 示例

输入：

```text
按 trusted 模式分析 DSP - DSP平台整体交互优化.md，并生成测试用例 XMind。
```

执行：

```text
step 1: orchestrate(mode=trusted, output=SourceManifest.yaml)
step 2: evidence_trace(input=SourceManifest.yaml + 原始需求材料, output=EvidenceTrace.yaml)
step 3: scope_index(input=SourceManifest.yaml + EvidenceTrace.yaml, output=ScopeIndex.yaml)
step 4: scope_index_gate(input=SourceManifest.yaml + EvidenceTrace.yaml + ScopeIndex.yaml, output=ScopeIndexGateReport.yaml)
step 5: requirement(input=EvidenceTrace.yaml + ScopeIndex.yaml + ScopeIndexGateReport.yaml, output=FunctionPoints.yaml)
step 6: requirement_gate(input=ScopeIndex.yaml + FunctionPoints.yaml, output=RequirementGateReport.yaml)
step 7: testcase_by_source_shard(input=ScopeIndex.yaml + FunctionPoints.yaml + RequirementGateReport.yaml, output=TestcasePackage.yaml)
step 8: testcase_gate(input=ScopeIndex.yaml + FunctionPoints.yaml + TestcasePackage.yaml, output=TestcaseGateReport.yaml)
step 9: quality_review(input=EvidenceTrace.yaml + ScopeIndex.yaml + FunctionPoints.yaml + TestcasePackage.yaml + TestcaseGateReport.yaml, output=ReviewReport.yaml)
step 10: export(input=ScopeIndex.yaml + TestcasePackage.yaml + TestcaseGateReport.yaml + ReviewReport.yaml, output=DeliverySummary.md + .xmindmark + .xmind)
step 11: final_delivery_gate(input=ScopeIndex.yaml + TestcasePackage.yaml + ReviewReport.yaml + DeliverySummary.md + export 已生成的 .xmindmark + export 已生成的 .xmind, output=FinalDeliveryGateReport.yaml)
```

说明：`.xmindmark` 生成和本地 `xmindmark` 转换 `.xmind` 都属于 step 10 `export` 阶段内部动作；step 11 `final_delivery_gate` 不生成 `.xmind`，只校验 export 已生成的 `.xmindmark` 和 `.xmind` 是否满足交付条件。

输出：

```text
outputs/DSP - DSP平台整体交互优化/trusted/SourceManifest.yaml
outputs/DSP - DSP平台整体交互优化/trusted/EvidenceTrace.yaml
outputs/DSP - DSP平台整体交互优化/trusted/ScopeIndex.yaml
outputs/DSP - DSP平台整体交互优化/trusted/ScopeIndexGateReport.yaml
outputs/DSP - DSP平台整体交互优化/trusted/FunctionPoints.yaml
outputs/DSP - DSP平台整体交互优化/trusted/RequirementGateReport.yaml
outputs/DSP - DSP平台整体交互优化/trusted/TestcasePackage.yaml
outputs/DSP - DSP平台整体交互优化/trusted/TestcaseGateReport.yaml
outputs/DSP - DSP平台整体交互优化/trusted/ReviewReport.yaml
outputs/DSP - DSP平台整体交互优化/trusted/FinalDeliveryGateReport.yaml
outputs/DSP - DSP平台整体交互优化/trusted/DSP - DSP平台整体交互优化.xmindmark
outputs/DSP - DSP平台整体交互优化/trusted/DSP - DSP平台整体交互优化.xmind
```

trusted 导图示例：

```text
DSP - DSP平台整体交互优化测试用例
- 统计信息
- 模块：筛选栏优化
  - 场景：More Filters收起
    - SRC-001｜2.1 More Filters收起
      - FP-001：More Filters按钮可展开二级筛选区并支持再次收起
        - TC-001-More Filters按钮展开二级筛选区
```
