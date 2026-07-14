# Trusted Testcase Generation Skill Pipeline

中文名：可信测试用例生成 Skill 流水线。

一句话定义：先建立证据，再定义直接测试对象，按 source 分片生成功能点和用例，并通过确定性门禁证明来源、覆盖、适用方法、质量和导出一致性可信。

## 核心目标

1. 证明本次需求“测了什么、为什么测、覆盖了没有、有没有过度生成”。
2. 所有下游阶段必须 100% 消费上游输入，并留下 consumption receipt。
3. 图片、截图、原型、表格、AC、确认表和页面说明都必须进入证据或范围索引。
4. 默认最终只交付一个与需求文档同名的 `.xmind` 文件。
5. `.xmind` 必须由 `.xmindmark` 经项目确定性 exporter 生成，并验证实际交付归档，禁止模型直接生成。

## 主流程

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

## 核心产物链

```text
SourceManifest.yaml
EvidenceTrace.yaml
ScopeIndex.yaml
ScopeIndexGateReport.yaml
FunctionPoints.yaml
RequirementGateReport.yaml
TestcasePackage.yaml
TestcaseGateReport.yaml
ReviewReport.yaml
DeliverySummary.md
需求文档同名.xmindmark
需求文档同名.xmind
FinalDeliveryGateReport.yaml
```

默认对外交付只保留 `需求文档同名.xmind`。其他文件都是内部可信产物，除非用户明确要求，不作为默认交付清单展示。

## Skill 划分

```text
skills/
├── testcase-orchestrator/
├── evidence-builder/
├── scope-indexer/
├── requirement-analyzer/
├── trusted-gate/
├── testcase-designer/
├── quality-reviewer/
└── artifact-exporter/
```

## 职责边界

### testcase-orchestrator

判断模式，建立 `SourceManifest.yaml`，维护 expected source list，调度阶段和门禁。不直接分析需求、不写用例、不导出。

### evidence-builder

负责 `collect / image_analysis / evidence_trace`。提取图片链接、下载图片、识图、抽取正文/表格/AC/截图证据，输出 `EvidenceTrace.yaml`。

### scope-indexer

负责 `scope_index`。建立全来源范围索引，分类 source block，识别 `direct_testcase_source`，绑定依赖、规则簇、反查来源、复杂度和测试设计画像，输出 `ScopeIndex.yaml`。

### requirement-analyzer

负责 `requirement`。只基于 `EvidenceTrace.yaml` 和 `ScopeIndex.yaml` 生成功能点，输出 `FunctionPoints.yaml` 和消费回执。

### trusted-gate

负责 `scope_index_gate / requirement_gate / testcase_gate / final_delivery_gate`。只做确定性检查，不做模型自评，不补需求，不写用例。

### testcase-designer

负责 `testcase_by_source_shard`。按 `direct_testcase_source` 分片生成用例，输出 `TestcasePackage.yaml` 和消费回执。

### quality-reviewer

负责 `quality_review`。检查弱步骤、弱预期、不可验证、方法覆盖、语义重复和发布结论。

### artifact-exporter

负责 `export`。生成 `.xmindmark`，调用 `xmindmark` 转换 `.xmind`，不修改用例语义。

## 关键机制

### direct_testcase_source 守恒

`ScopeIndex.yaml` 识别出多少个 in-scope `direct_testcase_source`，后续 requirement、testcase、export、final_delivery_gate 都必须能对应多少个。某 source 被排除、依赖化或不可测时，必须在进入 testcase 前记录原因。

### source 分类

每个来源块必须分类为：

1. `direct_testcase_source`
2. `dependency_rule_source`
3. `acceptance_backcheck_source`
4. `background_reference`
5. `out_of_scope_or_not_applicable`

### rule_clusters

字段说明、页面截图、状态规则、权限规则、AC、确认表或页面说明共同定义同一行为时，必须放入同一个 `rule_clusters`，先形成统一业务口径，再拆功能点。

### dependency_bindings

每个依赖来源必须绑定到直接测试对象，或进入 `unassigned_sources / index_risks`。页面级 PRD、截图、字段表、状态机、权限表或 AC 不得静默脱离主测试对象。

### consumption_receipt

每个下游阶段必须对上游输入留下消费回执。允许结果：

1. `converted_to_output`
2. `merged_into_output`
3. `blocked_by_question`
4. `not_applicable_with_reason`
5. `returned_to_upstream`

不允许静默跳过、只引用编号但步骤/预期不可观察、只消费摘要或按印象重做。

### xmind_tree_contract

最终导图不是宽松展示，而是强契约结构。必须满足：

1. `FunctionPoints.yaml` 中的 FP 必须带 `module / scene / source_id / shard_id / source_order / title_path`
2. `TestcasePackage.yaml` 中的 testcase 必须带 `module / scene / source_id / shard_id / source_order / title_path / fp_ids`
3. XMind 必须能从这些字段唯一构造 `模块 -> 场景 -> SRC -> FP -> TC`
4. 任一字段缺失或导图层级跳变，都应被 gate 拒绝

### source-sharded testcase

```text
for each direct_testcase_source:
  read source-bound function points
  apply test_design_profile
  generate source-local cases
  merge same-source duplicates
  emit consumption receipts
  renumber globally
```

### final_delivery_gate

导出后必须复核最终 `.xmindmark / .xmind`：source 节点与 expected source list 一致，无缺失、重复、未知 source，统计信息与结构化产物一致。
`final_delivery_gate` 不能只依赖 gate 文案或模型自述，必须运行本地硬校验器：

```bash
python3 tools/validate_trusted_output.py "<output_dir>"
```

只有命令返回 0，且没有待人工确认的阻塞问题时，才允许 `FinalDeliveryGateReport.yaml` 标记 `status=pass`。
如果命令返回非 0，必须把脚本输出中的错误转成 `blocking_issues`，并按错误类型回退到 `requirement`、`testcase_by_source_shard` 或 `export` 修复，禁止改写为通过。

## XMind 规则

`xmindmark` 必须使用根节点纯文本 + Markdown 列表。推荐结构：

```text
项目名测试用例
- 统计信息
- 模块：模块名
  - 场景：场景名
    - SRC-001｜2.1 原需求章节/段落标题
      - FP-001：功能点
        - TC-001-标题
          - 优先级：P1｜类型：异常
          - 预期摘要：...
          - 操作步骤
            - 步骤1：...
```

必须完整包含 `模块 -> 场景 -> SRC -> FP -> TC` 层级，不能把所有用例平铺在根节点，也不能直接挂在 `SRC` 下跳过 `FP`。`SRC` 节点命名必须使用 `source_id + "｜" + title_path`，其中 `title_path` 必须保留原需求文档章节号或段落序号，例如 `SRC-001｜2.1 Offer 编辑弹窗`。如果原文没有显式章节号，则使用 `source_order + " " + 原段落标题` 组成 title_path。最终文案必须中文化，不暴露内部英文枚举。

## 转换工具约束

1. 必须先生成 `.xmindmark`。
2. 必须通过项目内受测试的确定性 exporter 生成 `.xmind`，不依赖已知会产生空白文件的 `xmindmark@0.3.2` CLI。
3. 禁止业务阶段自行拼装或生成另一份临时 `.xmind`；交付目录只能有 exporter 生成的正式文件。
4. trusted 最终交付前必须再次执行 `python3 tools/validate_trusted_output.py "<output_dir>"`，验证 YAML 引用链、SRC/FP/TC 覆盖、统计信息、`.xmindmark` 层级和实际交付 XMind 的结构、根节点及计数一致。

## 成功标准

合格结果必须能回答：

1. 直接测试对象有哪些。
2. 每个 source 的证据是什么。
3. 每个 source 关联哪些依赖和反查来源。
4. 每个 source 转成哪些功能点。
5. 每个功能点是否被覆盖、合并、阻塞或排除。
6. 每个 source 的 must_cover、适用方法和重复风险是否处理。
7. 最终 XMind 是否与 expected source list 一致。
8. 本地硬校验器是否返回 0，并证明 trusted 产物链和导图结构自洽。
