# 执行计划

## full

```text
orchestrate
-> collect
-> image_analysis
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

## generate_only

适用：用户已提供可信 `ScopeIndex.yaml` 和 `FunctionPoints.yaml`。

```text
orchestrate
-> requirement_gate
-> testcase_by_source_shard
-> testcase_gate
-> quality_review
-> export
-> final_delivery_gate
```

## review_only

```text
orchestrate
-> testcase_gate
-> quality_review
```

## delta

与 full 相同，但 `ScopeIndex.yaml / FunctionPoints.yaml / TestcasePackage.yaml` 必须标记 `change_type`：`added`、`changed`、`unchanged`、`removed`。

## 全模式门禁

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
11. `final_delivery_gate` 未执行 `python3 tools/validate_trusted_output.py "<output_dir>"` 或命令返回非 0，禁止交付 `.xmind`。

## source 守恒

`ScopeIndex.yaml` 中 `classification=direct_testcase_source` 且 `scope_status=in_scope` 的 source 组成 expected source list。该清单必须贯穿 requirement、testcase、review、export、final_delivery_gate。

## 消费回执

requirement 必须消费：

1. 主来源
2. 依赖来源
3. 规则簇
4. 反查来源
5. 索引风险

testcase 必须消费：

1. 功能点
2. 已确认规则
3. 依赖绑定结果
4. 索引风险处理结果
5. 需求疑问边界

## 图片规则

1. Markdown 图片链接必须提取。
2. 图片必须下载到本地后才允许识图。
3. 下载失败必须写入 `EvidenceTrace.yaml` 和 `pending_confirmations`。
4. 图片必须绑定到最近的 source section 或 direct testcase source。

## XMind 规则

1. 必须包含 `SRC` 层。
2. `SRC` 节点命名必须使用 `source_id + "｜" + title_path`，例如 `SRC-001｜2.1 Offer 编辑弹窗`。
3. `title_path` 必须保留原需求文档章节号或段落序号；无显式章节号时使用 `source_order + " " + 原段落标题`。
4. 导图业务树必须完整包含 `模块 -> 场景 -> SRC -> FP -> TC`，禁止 `root -> TC`、`SRC -> TC`、`模块 -> TC` 等扁平结构。
5. 顺序按 `source_order`。
6. `.xmind` 必须由项目确定性 exporter 从 `.xmindmark` 生成，并对实际文件执行结构和计数校验。
7. 禁止手动拼装 `.xmind`。
8. `final_delivery_gate` 必须运行本地硬校验器：

```bash
python3 tools/validate_trusted_output.py "<output_dir>"
```

9. 只有校验器返回 0，且实际交付 `.xmind` 可解析、根节点非空、SRC/FP/TC 计数与 `.xmindmark` 及 JSON 产物一致时，才允许最终放行。
