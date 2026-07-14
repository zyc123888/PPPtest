# Claw 测试用例生成统一总提示词

这是一个可以单独发给 Claw / OpenClaw 使用的测试用例生成总提示词。

目标：

1. 支持两种模式：`lite` 和 `trusted`。
2. `lite` 用于快速生成可交付测试用例 XMind。
3. `trusted` 用于强追溯、强门禁、按需求章节归属的可信测试用例生成。
4. 不要求接收方再阅读其他 README、workflow 或 schema 文件，也能知道如何执行。
5. 最终 `.xmind` 必须由 `.xmindmark` 经项目确定性 exporter 生成，并校验实际交付归档中的 SRC/FP/TC 数量，禁止模型直接生成。

## 一、先判断 mode

执行任何任务前，必须先确定 `mode`：

1. `lite`
2. `trusted`

### 选择 lite 的情况

满足以下情况时使用 `lite`：

1. 用户只说“生成测试用例”“输出 XMind”“帮我写用例”。
2. 用户没有要求强追溯、门禁、覆盖证明或章节归属。
3. 用户更关注快速得到一版可读、可交付的用例。
4. 需求文档规模较小，图片和外部依赖较少。
5. 用户明确说“低成本”“快速版”“简版”“lite”。

lite 的特点：

1. 流程短。
2. 中间产物少。
3. token 成本低。
4. 导图更简洁。
5. 追溯能力弱于 trusted。

### 选择 trusted 的情况

满足以下情况时使用 `trusted`：

1. 用户明确说 `trusted`。
2. 用户要求“严格”“可信”“可追溯”“按原需求章节归属”。
3. 用户要求检查是否漏测、是否过度生成、是否每个需求都被消费。
4. 用户要求最终用例必须显示原需求章节号、段落标题或 source。
5. 用户要求门禁、审计、覆盖证明、review report。
6. 需求中有大量图片、表格、原型、外部链接或复杂依赖，并且用户没有明确要求低成本。

trusted 的特点：

1. 流程长。
2. 中间产物多。
3. token 成本高。
4. 每条用例有 source 归属。
5. 能解释“测了什么、为什么测、覆盖了没有、有没有过度生成”。

### mode 冲突处理

1. 用户明确指定 mode 时，以用户指定为准。
2. 用户同时要求“快”和“严格可信”时，优先 trusted，并在结果中说明成本会更高。
3. 如果用户要求比较两种结果，必须分别跑 `lite` 和 `trusted`，输出到两个不同目录。
4. 不允许同一份产物混用 `lite` 和 `trusted` 字段。

## 二、共同强制红线

无论 `lite` 还是 `trusted`，都必须遵守：

1. 结构化中间产物优先，不能只靠聊天上下文。
2. 图片链接必须先提取、下载，再对本地图片进行多模态识别。
3. 不能用正文里的“这是一张图片”或 OCR 注释替代实际识图。
4. 图片下载失败必须记录，必须进入待确认或 pending，不允许静默忽略。
5. 正文规则优先于图片推断。
6. 图片只作为界面、入口、字段、控件、状态等补充证据。
7. 不确定内容必须标记为 `inferred`、`pending` 或 `待确认`。
8. 测试用例生成不能跳回原始 PRD 和图片自由发挥，必须基于已生成的结构化功能点。
9. 质量审查不能省略。
10. 最终 `.xmind` 禁止手动拼装压缩包。
11. 必须先生成 `.xmindmark`，再用本地 `xmindmark` 转换为 `.xmind`。
12. export 前必须检查 `xmindmark --version` 或等价命令；如果本地没有 `xmindmark` 命令或命令执行失败，必须中止 `.xmind` 生成并报告缺少转换工具。
13. 最终导图展示文案必须中文化，不允许把内部英文枚举直接暴露给业务用户。
14. 默认对外只交付一个与需求文档同名的 `.xmind` 文件；其他 YAML/MD 是内部产物，除非用户明确要求。
15. 输出目录必须包含 mode，避免 `lite` 和 `trusted` 互相覆盖。
16. 推荐按单步执行协议运行，每次只执行一个 `current_stage`，不允许一口气连续生成多个阶段产物。
17. 当前阶段只能创建或修改 `allowed_outputs` 中声明的文件；生成下游文件视为阶段偷跑。
18. gate 未通过时禁止进入下游阶段。
19. export 阶段必须重新读取 `ReviewReport.yaml` 和 gate report，不能凭聊天记忆写统计信息、审查结论、原因或中文化映射。
20. 图片下载和识图必须调用当前环境真实可用的工具；没有工具时必须降级为失败待确认，不能假装完成识图。
21. 强制执行 Token 防截断控制，生成 `FunctionPoints.yaml`、`TestcasePackage.yaml` 和 `.xmindmark` 前必须评估整体输出长度，避免单次输出截断。
22. YAML 空值输出必须遵循唯一标准，严禁混用 `null`、`~`、`none` 或直接漏掉必填 key。
23. 全新 `orchestrate` 必须先完成工作区清理检查，避免历史同名产物污染本次运行。
24. Gate 必须按独立审计原则执行，任何硬约束不满足都必须返回 `status=fail`。
25. trusted 模式必须使用 ID 强引用，`TestcasePackage.yaml` 不重复抄写 `module / scene / source_order / title_path / description / rules` 等上游长字段。
26. trusted Gate 通过时必须使用 Quiet Pass 极简回执；只有失败时才展开问题明细。

### xmindmark 工具依赖

最终 `.xmind` 强依赖本地 `xmindmark` 命令。export 前必须执行：

最终 `.xmind` 必须由项目共用的确定性 exporter 从 `.xmindmark` 生成，不使用已知会产生空白文件的 `xmindmark@0.3.2` CLI。exporter 失败时可保留待转换产物，但不得宣称已交付；trusted 的 final gate 必须解析实际 `.xmind` 并复算 SRC/FP/TC 数量。

### Token 防截断控制

生成结构化大文件时必须优先防截断：

1. `steps` 和 `expected_results` 文案必须精炼、可验证，禁止冗长口语化过渡句。
2. 使用高度浓缩的专业测试术语，避免重复解释同一业务背景。
3. trusted 模式下，如果预估输出过大，必须在 `orchestrate` 阶段规划分片输出。
4. 分片输出时，`TestcasePackage.yaml` 必须拆为 `TestcasePackage_Part1.yaml`、`TestcasePackage_Part2.yaml` 等多次单步交付。
5. 每次模型调用应保留足够输出余量，不允许为了单文件完整性冒险输出超长 YAML。
6. export 阶段如果 `.xmindmark` 预估过大，必须先输出分片计划或要求分批导出，禁止输出可能被截断的不完整 `.xmindmark`。
7. export 阶段填写统计信息前，必须基于 `case_id`、`fp_id`、`source_id` 和待确认项做穷举计数，不能估算。
8. 如果存在 `TestcasePackage_PartN.yaml`，`testcase_gate / quality_review / export / final_delivery_gate` 必须读取所有连续 Part 并合并检查；禁止只检查或导出 Part1。
9. trusted 的 `TestcasePackage.yaml` 或每个 `TestcasePackage_PartN.yaml` 必须包含 `xmind_grouping_contract`。

### YAML 空值标准

所有 YAML 中间产物必须遵循严格类型占位符规范：

1. 列表为空时写 `field_name: []`。
2. 文本为空时写 `field_name: ""`。
3. 对象为空时写 `field_name: {}`。
4. 禁止输出 `null`、`~`、`none`。
5. 必填 key 即使为空也必须保留，不允许省略。
6. 字符串值如果包含冒号、中括号、减号、井号、英文逗号、英文双引号或换行，必须使用双引号完整包裹，并对内部双引号做转义。

建议输出目录：

```text
outputs/<需求文档名>/lite/
outputs/<需求文档名>/trusted/
```

### 工作区清理协议

开始全新的 `orchestrate` 阶段时，必须先检查当前 `output_dir`：

1. 必须生成本次唯一 `run_id`，并写入阶段计划或 `SourceManifest.yaml`。
2. 如果 `output_dir` 中存在历史生成的下游产物，禁止直接复用。
3. 历史下游产物包括 `EvidenceTrace.yaml`、`ScopeIndex.yaml`、`FunctionPoints.yaml`、`RequirementGateReport.yaml`、`TestcasePackage.yaml`、`TestcaseGateReport.yaml`、`ReviewReport.yaml`、`DeliverySummary.md`、`*.xmindmark`、`*.xmind`、`FinalDeliveryGateReport.yaml`。
4. 发现历史产物时，必须优先归档到 `_archive/<timestamp_or_old_run_id>/`。
5. 如需物理删除历史产物，必须先取得用户明确授权。
6. 未完成清理、归档或确认文件属于当前 `run_id` 前，禁止进入 `evidence_trace` 或任何下游阶段。
7. 后续阶段只能读取当前 `run_id/output_dir` 内的上游产物，不得跨运行目录读取同名 YAML 或 XMindMark 文件。

`run_id` 格式必须为：

```text
run_<yyyyMMdd-HHmmss>_<4位随机大写字母数字>
```

示例：`run_20260703-153022_A7K9`。不得使用 `test1`、`run001` 或纯日期。

`_archive` 默认保留最近 3 次归档。超过 3 次的旧归档只能提示用户确认删除或压缩；未获得明确授权时，不得自动物理删除旧归档。

## 三、单步执行协议

为避免长会话状态漂移，默认不要一次性把总提示词、完整 PRD 和所有阶段目标交给模型连续跑完。应采用“单步 Prompt + 上游产物注入”的机制。

每次调用必须在 Prompt 顶部声明：

```yaml
mode: lite | trusted
current_stage: <stage_name>
output_dir: <输出目录>
allowed_inputs:
  - <当前阶段允许读取的输入>
allowed_outputs:
  - <当前阶段允许生成的输出>
forbidden_outputs:
  - <禁止本阶段生成的下游产物>
gate_required_before:
  - <进入本阶段前必须通过的 gate，没有则写 not_applicable>
stage_done_condition:
  - <本阶段完成条件>
```

如果缺少 `allowed_inputs` 中的必需文件，必须中止并说明缺失文件，不得跳过阶段或直接从原始 PRD 推断下游结果。

### lite 单步阶段

| current_stage | allowed_inputs | allowed_outputs | forbidden_outputs |
|---|---|---|---|
| orchestrate | 用户请求、需求文档路径、模式参数 | 执行计划说明 | FunctionPoints.yaml、TestcasePackage.yaml、ReviewReport.yaml、.xmindmark、.xmind |
| evidence_trace | 原始需求材料、图片链接、本地附件 | EvidenceTrace.yaml | FunctionPoints.yaml、TestcasePackage.yaml、ReviewReport.yaml、.xmindmark、.xmind |
| requirement | EvidenceTrace.yaml、用户范围说明 | FunctionPoints.yaml | TestcasePackage.yaml、ReviewReport.yaml、.xmindmark、.xmind |
| testcase | FunctionPoints.yaml、EvidenceTrace.yaml | TestcasePackage.yaml | ReviewReport.yaml、.xmindmark、.xmind |
| quality_review | EvidenceTrace.yaml、FunctionPoints.yaml、TestcasePackage.yaml | ReviewReport.yaml | .xmindmark、.xmind |
| export | TestcasePackage.yaml、ReviewReport.yaml | DeliverySummary.md、需求文档同名.xmindmark、需求文档同名.xmind | FunctionPoints.yaml、TestcasePackage.yaml、ReviewReport.yaml |

### trusted 单步阶段

| current_stage | allowed_inputs | allowed_outputs | gate_required_before |
|---|---|---|---|
| orchestrate | 用户请求、需求文档路径、模式参数 | SourceManifest.yaml、执行计划说明 | not_applicable |
| evidence_trace | SourceManifest.yaml、原始需求材料、图片链接、本地附件 | EvidenceTrace.yaml | not_applicable |
| scope_index | SourceManifest.yaml、EvidenceTrace.yaml、用户范围说明 | ScopeIndex.yaml | not_applicable |
| scope_index_gate | SourceManifest.yaml、EvidenceTrace.yaml、ScopeIndex.yaml | ScopeIndexGateReport.yaml | not_applicable |
| requirement | EvidenceTrace.yaml、ScopeIndex.yaml、ScopeIndexGateReport.yaml | FunctionPoints.yaml | ScopeIndexGateReport.yaml status=pass |
| requirement_gate | ScopeIndex.yaml、FunctionPoints.yaml、ScopeIndexGateReport.yaml | RequirementGateReport.yaml | ScopeIndexGateReport.yaml status=pass |
| testcase_by_source_shard | ScopeIndex.yaml、FunctionPoints.yaml、RequirementGateReport.yaml | TestcasePackage.yaml | RequirementGateReport.yaml status=pass |
| testcase_gate | ScopeIndex.yaml、FunctionPoints.yaml、TestcasePackage.yaml、RequirementGateReport.yaml | TestcaseGateReport.yaml | RequirementGateReport.yaml status=pass |
| quality_review | EvidenceTrace.yaml、ScopeIndex.yaml、FunctionPoints.yaml、TestcasePackage.yaml、TestcaseGateReport.yaml | ReviewReport.yaml | TestcaseGateReport.yaml status=pass |
| export | ScopeIndex.yaml、FunctionPoints.yaml、TestcasePackage.yaml、TestcaseGateReport.yaml、ReviewReport.yaml | DeliverySummary.md、需求文档同名.xmindmark、需求文档同名.xmind | TestcaseGateReport.yaml status=pass |
| final_delivery_gate | ScopeIndex.yaml、FunctionPoints.yaml、TestcasePackage.yaml、ReviewReport.yaml、DeliverySummary.md、需求文档同名.xmindmark、需求文档同名.xmind | FinalDeliveryGateReport.yaml | not_applicable |

### 阶段偷跑判定

出现以下任一情况，必须退回当前阶段：

1. `scope_index` 阶段生成了 `FunctionPoints.yaml`。
2. `requirement` 阶段生成了 `TestcasePackage.yaml`。
3. `testcase_by_source_shard` 阶段生成了 `ReviewReport.yaml`。
4. `quality_review` 阶段生成了 `.xmindmark` 或 `.xmind`。
5. `export` 阶段修改了 `FunctionPoints.yaml`、`TestcasePackage.yaml` 或 `ReviewReport.yaml`。
6. 任一 gate 阶段为了继续流程而修改上游产物。

每个阶段结束时必须给出阶段回执：

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

## 四、图片和证据处理规则

如果需求文档中有 Markdown 图片链接、HTML 图片、附件图片或本地图片，必须先进入证据处理。

必须执行：

1. 提取所有图片链接。
2. 使用当前运行环境真实可用的下载工具下载图片到本地可访问路径。
3. 使用当前运行环境真实可用的视觉/多模态工具对下载成功的图片做识别。
4. 抽取图片中的页面入口、按钮、字段、控件、表格、状态、标签、弹窗、提示文案。
5. 将图片证据绑定到最接近的需求章节、段落或 source。
6. 记录下载失败、不可读、冲突、缺失项。

`EvidenceTrace.yaml` 必须包含：

1. 图片链接数量。
2. 下载成功数量。
3. 下载失败数量。
4. 图片识别结果。
5. 正文块。
6. 表格。
7. 待确认项。

如果存在图片链接，但没有图片下载和识图记录，流程必须中止。

### 图片工具要求

图片处理必须依赖真实工具结果。工程环境可以提供类似工具：

```text
download_image(url) -> local_path
vision_analyze(path) -> observed_elements
```

实际工具名以当前运行环境注册的 Agent Tool / Skill 为准。若没有可用下载工具，该图片必须记录为 `download_status=failed` 并进入 `failed_images` 和 `pending_confirmations`；若没有可用视觉识别工具，该图片必须记录为 `vision_status=failed` 或 `analysis_status=failed`，`observed_elements=[]`，并进入 `failed_images` 和 `pending_confirmations`。

禁止把 Markdown 图片 alt 文本、图片 URL 文件名、图片附近正文、人工图注或业务常识推测当成真实识图结果。

### 失败图片记录格式

如果图片下载、路径访问或视觉识别失败，必须在 `EvidenceTrace.yaml` 中以如下格式客观记录：

```yaml
failed_images:
  - image_id: "IMG-002"
    url: "http://example.com/img1.png"
    reason: "Download failed / Path inaccessible / Vision API error"
    referenced_section: "2.1 Offer 编辑弹窗"
    impact: "无法通过截图核对弹窗中具体的表单字段"
```

`failed_images`、`images` 中的失败项、`pending_confirmations` 必须互相一致；不能只在其中一个位置记录失败。

## 五、lite 模式

### lite 目标

快速生成一份可读、可交付的测试用例 XMind。

lite 不建立 source/shard/gate 链路，但必须保留：

1. `module`
2. `scene`
3. `source_order`
4. `FunctionPoints`
5. `TestcasePackage`
6. `ReviewReport`

### lite 流程

```text
orchestrate
-> evidence_trace
-> requirement
-> testcase
-> quality_review
-> export
```

### lite 产物

必须生成：

```text
EvidenceTrace.yaml
FunctionPoints.yaml
TestcasePackage.yaml
ReviewReport.yaml
DeliverySummary.md
需求文档同名.xmindmark
需求文档同名.xmind
```

默认对外交付：

```text
需求文档同名.xmind
```

### lite requirement 规则

`requirement` 阶段只基于 `EvidenceTrace.yaml` 和用户补充范围生成 `FunctionPoints.yaml`。

每个功能点必须包含：

1. `fp_id`
2. `module`
3. `scene`
4. `source_order`
5. `title`
6. `type`
7. `description`
8. `source_refs`
9. `rules`
10. `test_hints`
11. `priority_hint`
12. `source_distribution`
13. `atomicity_check`

要求：

1. `module` 优先沿用需求文档原始章节或分类。
2. `scene` 优先沿用需求文档中的段落、场景或功能标题。
3. `source_order` 必须来自原文章节号、段落序号或出现顺序。
4. 图片补充内容必须挂回最接近的原文模块下。
5. 不允许为了测试视角重新打乱原文结构。

### lite testcase 规则

`testcase` 阶段只能读取：

1. `FunctionPoints.yaml`
2. `EvidenceTrace.yaml`

每条用例必须包含：

1. `case_id`
2. `module`
3. `scene`
4. `source_order`
5. `fp_id`
6. `title`
7. `category`
8. `priority`
9. `preconditions`
10. `test_data`
11. `steps`
12. `expected_results`
13. `traceability`
14. `generation_basis`
15. `scenario_dimensions`
16. `baseline_candidate`

生成策略：

1. 先判断每个 FP 的 `applicable_methods`。
2. 只有方法能产生可观察、非重复、与证据相关的测试差异时才生成用例。
3. 可合并的低风险验证点应合并，但标题、步骤或预期中必须能看出覆盖点。
4. 不为凑数量生成低信息量用例，也不为精简遗漏明确风险、边界、条件分支或异常路径。
5. 最后标记高价值 `【基线】` 候选。

适用方法库包括：等价类、边界值、决策表、状态转换、角色权限、多入口一致性、空值/默认值、异常容错、时间/重复操作、UI 展示、组合测试、数据生命周期、幂等/重试/去重、数据一致性/跨层级联动、计算精度、批处理部分失败、可观测性/审计日志。

### lite XMind 结构

lite 导图必须使用：

```text
项目名测试用例
- 统计信息
  - 功能点总数：...
  - 用例总数：...
  - P0 数量：...
  - P1 数量：...
  - P2 数量：...
  - P3 数量：...
  - 审查结论：通过/有条件通过/不通过｜原因：...
- 模块：模块名
  - 场景：场景名
    - FP-001：功能点标题
      - TC-001-001-用例标题
        - 优先级：P1｜类型：功能
        - 预期摘要：...
        - 操作步骤
          - 步骤1：...
          - 步骤2：...
```

lite 禁止：

1. 把所有 TC 平铺到根节点。
2. 跳过 `模块` 或 `场景`。
3. 跳过 `FP`，直接挂 TC。
4. 使用 Markdown 标题 `# / ## / ###` 表达主树。

## 六、trusted 模式

### trusted 目标

trusted 不只是生成测试用例，还要证明：

1. 测了什么。
2. 为什么测。
3. 每个需求 source 是否被消费。
4. 每个功能点是否被覆盖。
5. 是否存在过度生成。
6. 最终 XMind 是否与 source list 一致。

### trusted 流程

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

说明：`collect` 和 `image_analysis` 不是独立 `current_stage`，已合并为 `evidence_trace` 阶段内部动作，由 `evidence-builder` 一次性完成输入收集、图片下载/识别和证据记录。

### trusted 产物

必须生成：

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

默认对外交付：

```text
需求文档同名.xmind
```

### trusted source 分类

`scope_index` 阶段必须把来源块分类为：

1. `direct_testcase_source`
2. `dependency_rule_source`
3. `acceptance_backcheck_source`
4. `background_reference`
5. `out_of_scope_or_not_applicable`

每个 `direct_testcase_source` 必须形成 shard。

每个 shard 必须包含：

1. `shard_id`
2. `direct_testcase_source`
3. `source_order`
4. `title_path`
5. `module`
6. `scene`
7. `assigned_primary_sources`
8. `assigned_dependency_sources`
9. `rule_clusters`
10. `backcheck_sources`
11. `excluded_sources`
12. `risk_signals`
13. `complexity_score`
14. `test_design_profile`

`test_design_profile` 必须保持简洁，包含：

1. `applicable_methods`：适用的测试设计方法。
2. `risk_signals`：风险信号。
3. `must_cover`：必须被用例可观察覆盖的业务义务。
4. `merge_allowed`：允许合并验证的低风险点。
5. `not_applicable`：看似相关但不适用的方法及原因。
6. `coverage_budget`：软护栏说明，不写固定用例数量。

如果需要记录冒烟范围说明，字段名必须使用 `smoke_test_scope_note`，不得使用 `smoking_scope_note`。

### trusted SRC 命名规则

`SRC` 节点命名必须使用：

```text
source_id + "｜" + title_path
```

示例：

```text
SRC-001｜2.1 Offer 编辑弹窗
```

要求：

1. `title_path` 必须来自原需求章节号、段落序号和标题。
2. 如果原文没有显式章节号，使用 `source_order + " " + 原段落标题`。
3. 不允许只输出 `SRC-001：直接测试对象`。
4. 不允许只输出模型改写后的模块名。

### trusted requirement 规则

`requirement` 阶段只能基于：

1. `EvidenceTrace.yaml`
2. `ScopeIndex.yaml`
3. 当前 shard 信息
4. 用户补充范围

每个 FP 必须包含：

1. `fp_id`
2. `source_id`
3. `shard_id`
4. `module`
5. `scene`
6. `source_order`
7. `title_path`
8. `title`
9. `type`
10. `description`
11. `source_refs`
12. `rules`
13. `test_hints`
14. `priority_hint`
15. `source_distribution`
16. `atomicity_check`

必须输出消费回执：

1. `scope_index_consumption`
2. `dependency_binding_consumption`
3. `index_risk_consumption`

### trusted testcase 规则

`testcase_by_source_shard` 阶段只能读取：

1. `ScopeIndex.yaml`
2. `FunctionPoints.yaml`
3. `RequirementGateReport.yaml`

每条用例必须包含：

1. `case_id`
2. `source_id`
3. `shard_id`
4. `fp_ids`
5. `title`
6. `category`
7. `priority`
8. `preconditions`
9. `test_data`
10. `steps`
11. `expected_results`
12. `evidence_refs`
13. `design_method`
14. `scenario_dimensions`
15. `baseline_candidate`

trusted testcase 必须采用 ID 强引用：

1. `module / scene / source_order / title_path` 从 `ScopeIndex.yaml` 或同源 `FunctionPoints.yaml` 通过 `source_id` 反查，禁止在 testcase 中重复抄写。
2. FP 的 `description / rules / test_hints` 只保留在 `FunctionPoints.yaml`，禁止在 testcase 中重复抄写。
3. 证据只保留 `evidence_refs` ID 列表，禁止复制证据原文。
4. 设计依据只保留 `design_method` 短字段；合并说明写入 `feature_point_consumption.reason`，且保持一句话。

`FunctionPoints.yaml` 中 `mergeable=true` 的 FP 可以与同 source 的其他 FP 合并覆盖，但必须满足：

1. 合并后的用例 `fp_ids` 显式包含该 FP。
2. `feature_point_consumption.consumption_result` 写为 `merged_into_case`。
3. `case_refs` 指向实际承载该 FP 的用例。
4. `reason` 用一句话说明合并依据。
5. 步骤或预期中必须能观察到该 FP 的覆盖点。

source 分片生成策略：

```text
for each direct_testcase_source:
  collect source-bound FPs
  read test_design_profile
  cover must_cover obligations first
  generate observable cases for applicable methods
  merge same-source duplicates
  output consumption receipts
  renumber globally
```

禁止：

1. 跨 source 静默合并用例。
2. 只挂 FP 编号但步骤和预期不可观察。
3. 用固定条数作为生成目标。
4. source 无用例也无阻塞说明。
5. 未解决风险被写成确定预期。
6. 重复输出 `module / scene / source_order / title_path / description / rules / traceability / generation_basis.rationale` 等上游长字段。

### trusted gate 规则

Gate 通过时必须使用 Quiet Pass 极简回执：

```yaml
gate: "requirement_gate"
status: "pass"
checked_artifacts:
  - "ScopeIndex.yaml"
  - "FunctionPoints.yaml"
blocking_issues: []
recovery_plan:
  strategy: "none"
  return_to: ""
  rerun_scope:
    source_ids: []
    shard_ids: []
    fp_ids: []
    case_ids: []
  preserve_artifacts: []
  regenerate_artifacts: []
  reason: ""
```

`gate` 和 `checked_artifacts` 必须替换为当前门禁和真实已检查产物。通过时禁止输出逐项解释、长 reason、长 summary 或重复上游字段。

Gate 失败时必须同时输出 `recovery_plan`，但仍必须立即中止，不能继续生成下游产物。

`recovery_plan.strategy` 只能取：

1. `local_rerun`：只重跑受影响的 source/shard/fp。
2. `stage_rerun`：重跑当前 gate 对应的完整上游阶段。
3. `upstream_rerun`：回到更早阶段重建 source 或 FP。
4. `manual_confirm`：需要用户补充信息。
5. `none`：gate 通过。

`testcase_gate` 若只发现少量 FP 未覆盖、同 source 用例重复、步骤/预期不可观察，应优先返回 `local_rerun -> testcase_by_source_shard`，并列出具体 `source_ids / shard_ids / fp_ids / case_ids`。只有上游 source/FP 归属错误时，才扩大到 `requirement` 或 `scope_index`。

如果 `strategy=local_rerun`，但 `rerun_scope.source_ids`、`shard_ids`、`fp_ids` 和 `case_ids` 全部为空，必须判定 recovery_plan 无效并重新输出明确范围。

任何 Gate 判定为不通过时，必须立即中止后续 pipeline 执行，不允许假装通过，也不允许继续生成下游产物。仍必须输出对应 gate report，同时最终答复必须使用如下模板：

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

原因分析必须来自 gate report 的 `blocking_issues`，不能编造额外问题。

#### scope_index_gate

检查：

1. source block 分类是否完整。
2. direct source 是否都有 shard。
3. dependency binding 是否完整。
4. rule_clusters 是否有 evidence。
5. 图片失败是否进入 pending。
6. unassigned_sources 和 index_risks 是否处理。

#### requirement_gate

检查：

1. expected source list 是否被消费。
2. FP 是否都有合法 `source_id`。
3. FP 是否继承 `shard_id / source_order / title_path`。
4. 是否存在无来源 FP。
5. dependency binding 是否被消费。
6. index risk 是否被解决、提问、排除或退回。
7. 未解决风险是否被错误写成确定功能点。

#### testcase_gate

检查：

1. 每个 FP 是否被覆盖、合并、阻塞或不适用。
2. 每个 direct source 是否有用例、阻塞或不适用说明。
3. 用例是否包含合法 `source_id / shard_id / fp_ids`，并能通过 ID join 反查 `source_order / title_path`。
4. `must_cover` 是否被可观察覆盖。
5. 是否存在高风险重复。
6. 覆盖是否在步骤或预期中可观察。
7. 是否能挂接到 `模块 -> 场景 -> SRC -> FP -> TC`。
8. `TestcasePackage.yaml` 是否避免重复抄写上游长字段。
9. `applicable_methods` 是否被消费、合并或说明不适用。

#### final_delivery_gate

检查：

1. `.xmindmark` 结构是否正确。
2. `.xmind` 是否已生成。
3. 导图 source 节点是否与 expected source list 一致。
4. 统计信息是否一致。
5. 导图是否中文化。
6. 是否存在 `root -> TC`、`SRC -> TC`、`模块 -> TC`、`场景 -> TC` 等扁平结构。
7. `.xmindmark` 是否存在 Markdown 代码围栏、Tab 或奇数空格缩进。
8. `.xmindmark` 是否存在半角中括号、Markdown 元字符污染或未净化特殊字符。

### trusted XMind 结构

trusted 导图必须使用：

```text
项目名测试用例
- 统计信息
  - 直接测试对象数：...
  - 功能点总数：...
  - 用例总数：...
  - P0 数量：...
  - P1 数量：...
  - P2 数量：...
  - P3 数量：...
  - 待确认项数：...
  - 审查结论：通过/有条件通过/不通过｜原因：...
- 模块：模块名
  - 场景：场景名
    - SRC-001｜2.1 原需求章节/段落标题
      - FP-001：功能点标题
        - TC-001-用例标题
          - 优先级：P1｜类型：功能
          - 预期摘要：...
          - 操作步骤
            - 步骤1：...
            - 步骤2：...
```

trusted 禁止：

1. 省略 `SRC` 层。
2. 省略 `FP` 层。
3. 把 TC 直接挂到 SRC 下。
4. 把所有 TC 平铺到根节点。
5. 用标题层级语法代替主树。
6. source 节点与 expected source list 不一致。

## 七、XMindMark 通用格式

`.xmindmark` 必须使用“根节点纯文本 + Markdown 列表”的唯一格式。

注意：`.xmindmark` 文件本身禁止包含 Markdown 代码围栏，例如 ```text 或 ```。只有在聊天里展示片段时才可以使用代码块；写入实际文件时必须去掉代码围栏。
首行（Line 1）必须是整个文件的第一行有效内容，且必须是中心主题纯文本。禁止在首行前插入空行、问候语、解释文字、`#` 标题符号、`- ` 或 `* ` 列表标记。

强制要求：

1. 第一行必须是根节点纯文本，不带 `- `。
2. 从第二行开始，每一行子节点都必须以 `- ` 开头。
3. 根节点直属子节点必须顶格写 `- `。
4. 更深层子节点必须统一比父节点多 2 个空格缩进。
5. 禁止使用 Tab。
6. 禁止在主树中插入空行。
7. 禁止在主树中插入解释文字、注释、编号列表或普通段落。
8. 禁止使用纯缩进无 `- ` 的写法。
9. 禁止使用 `# / ## / ###` 标题层级语法。
10. 禁止使用 Markdown 加粗 `**文本**`、斜体 `*文本*` 或 HTML 下划线/强调标签。
11. 严禁使用 `* ` 作为列表标记，所有列表行必须统一使用 `- `。
12. 严禁在同一行混用 `- ` 和 `* `。
13. 严格禁止节点文本中包含半角中括号 `[` 和 `]`。
14. 节点标题中的半角冒号、英文逗号、英文双引号等特殊字符，应优先转换为全角字符。
15. 严禁在任何单个节点内容中使用物理换行符 `\n`。
16. 任何节点正文首字符严禁使用 `-`、`*`、`+`、`#`、`>`。

节点文本必须是纯文本字符串。若原始需求文本中包含 `*` 字符且确实属于业务内容，必须改写为普通中文表达，避免被解析为 Markdown 样式。
如果操作步骤或预期结果中包含多个子动作，必须在单行内使用全角分号 `；` 或全角斜杠 `／` 分隔，不能在同一节点内换行。

### 元字符净化规则

`.xmindmark` 节点文本必须规避 xmindmark/MarkXMind 元字符冲突：

1. 半角中括号 `[` 和 `]` 禁止出现在任何节点文本中。
2. 状态、优先级或特殊标记统一使用全角中括号 `【】`，或半角圆括号 `()`。
3. 严禁输出：`- TC-001-用例标题 [基线]`。
4. 必须输出：`- TC-001-用例标题【基线】` 或 `- TC-001-用例标题 (基线)`。
5. 半角冒号 `:` 优先替换为全角冒号 `：`。
6. 英文逗号 `,` 优先替换为中文逗号 `，`。
7. 英文双引号 `"` 优先替换为中文引号 `“”`。
8. 如果节点文本来自代码片段、数组或参数示例，例如 `[A, B]`，必须改写为 `（A，B）` 或文字说明，不能保留半角中括号。
9. 如果节点正文首字符原本为 `-`、`*`、`+`、`#`、`>`，必须改写为全角符号或普通中文表达。

### 缩进深度规则

生成 `.xmindmark` 时，必须先确定每一行的绝对深度 `Depth`，再按公式生成前导空格：

```text
leading_spaces = (Depth - 1) * 2
```

根节点是第一行纯文本，记为 `Depth 0`，不参与列表缩进公式。从第二行开始：

| Depth | 含义 | 前导空格 |
|---:|---|---:|
| 1 | 根节点直属子节点，例如 `统计信息`、`模块：...` | 0 |
| 2 | 二级节点，例如统计项、`场景：...` | 2 |
| 3 | 三级节点，例如 lite 的 `FP-...`、trusted 的 `SRC-...` | 4 |
| 4 | 四级节点，例如 lite 的 `TC-...`、trusted 的 `FP-...` | 6 |
| 5 | 五级节点，例如 lite 的用例属性（操作步骤等）、trusted 的 `TC-...` | 8 |
| 6 | 六级节点，例如 lite 的操作步骤子项（步骤1）、trusted 的用例属性（操作步骤等） | 10 |
| 7 | 七级节点，例如 trusted 的操作步骤子项（步骤1） | 12 |

转换前必须逐行校验：

1. 第一行不能以 `- ` 开头。
2. 第二行开始必须匹配 `^( *)- `。
3. 前导空格数必须是偶数。
4. 禁止 Tab。
5. 禁止 1、3、5、7、9、11 等奇数空格缩进。
6. 禁止 Markdown 加粗、斜体、HTML 样式标签和 `* ` 列表标记。
7. 禁止半角中括号 `[` 和 `]`。
8. 禁止节点内物理换行符 `\n`。
9. 禁止节点正文首字符为 `-`、`*`、`+`、`#`、`>`。
10. 校验失败时不得生成 `.xmind`，必须修正 `.xmindmark` 后再转换。

转换命令建议：

```bash
xmindmark -f xmind "<需求文档同名>.xmindmark" -o "<输出目录>"
```

如果该命令不可用，必须中止并报告：

```text
缺少 xmindmark 转换工具，无法生成最终 .xmind 文件。
```

## 八、展示层中文化

内部字段可以使用英文枚举，但最终导图必须中文化。

类型映射：

1. `functional` -> `功能`
2. `boundary` -> `边界`
3. `negative` -> `异常`
4. `decision_table` -> `决策表`
5. `state_transition` -> `状态转换`
6. `role_matrix` -> `角色权限`
7. `entry_consistency` -> `多入口一致性`

审查结论映射：

1. `pass` -> `通过`
2. `conditional_pass` -> `有条件通过`
3. `fail` -> `不通过`

导图统计信息中的 `审查结论` 必须补充原因，不能只显示状态。原因来自 `ReviewReport.yaml` 的 findings、未覆盖、阻塞、待确认或最终门禁结论；`通过` 且无 findings 时写 `未发现阻塞交付的问题`，`有条件通过` 或 `不通过` 时写主要问题，trusted 模式下优先带上相关 `source_id`。

## 九、最终回复规则

默认最终回复只说明：

1. 已生成 `.xmind`。
2. `.xmind` 的文件路径。
3. 如果有阻塞、待确认或风险，简要说明。

不要默认把内部 YAML、MD、下载图片目录全部列出来，除非用户明确要求。

## 十、最小执行示例

### lite 示例

用户：

```text
按 lite 模式分析 xxx.md，并生成测试用例 XMind。
```

执行：

```text
step 1: orchestrate
step 2: evidence_trace
step 3: requirement
step 4: testcase
step 5: quality_review
step 6: export
```

导图：

```text
xxx测试用例
- 统计信息
- 模块：...
  - 场景：...
    - FP-001：...
      - TC-001-001-...
```

### trusted 示例

用户：

```text
按 trusted 模式分析 xxx.md，并生成测试用例 XMind。
```

执行：

```text
step 1: orchestrate
step 2: evidence_trace
step 3: scope_index
step 4: scope_index_gate
step 5: requirement
step 6: requirement_gate
step 7: testcase_by_source_shard
step 8: testcase_gate
step 9: quality_review
step 10: export
step 11: final_delivery_gate
```

导图：

```text
xxx测试用例
- 统计信息
- 模块：...
  - 场景：...
    - SRC-001｜2.1 原需求章节/段落标题
      - FP-001：...
        - TC-001-...
```
