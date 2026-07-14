# 用例生成2可信改进模式执行进度节点说明

本文档说明 `/case/generator2` 在“可信改进模式”下，右侧“执行进度”里各节点实际做什么。内容按当前后端实现整理，对应 `backend/app/tasks/case_generation_v2.py` 的 `_run_trusted_v2_pipeline`。

## 总览

可信改进模式不是直接从需求一次性生成用例，而是按以下链路执行：

```text
任务编排
→ 收集输入
→ 图片识别
→ 范围索引
→ 范围门禁
→ 需求分析
→ 需求门禁
→ 用例设计
→ 用例门禁
→ 可信复核
→ 导出交付物
```

核心目标是让结果可解释：

- 先确认“哪些对象应该直接生成测试用例”。
- 再确认每个对象的功能点、预算和消费情况。
- 最后确认用例是否覆盖了功能点、是否超预算、是否存在弱预期或模糊步骤。

## 1. 任务编排 orchestrate

前端显示：`任务编排`

后端阶段 key：`orchestrate`

### 做什么

启动可信改进流程，确认当前任务使用的是 `trusted_v2` 模式。

这一阶段主要做初始化：

- 读取任务输入。
- 初始化任务状态为 `RUNNING`。
- 清空当前任务旧产物。
- 创建新的执行进度数组。
- 确认后续流程走可信改进链路，而不是复刻模式。

### 输入

- 任务 ID。
- 任务提交时保存的 `input_payload_json`。
- 生成模式 `pipeline_mode=trusted_v2`。

### 输出

没有单独产物文件。主要更新任务进度：

- running：正在启动可信改进流程。
- success：执行模式：trusted_v2。

### 失败情况

一般不会在该节点失败。若任务已取消，会直接退出。

## 2. 收集输入 collect

前端显示：`收集输入`

后端阶段 key：`collect`

### 做什么

收集需求正文和图片链接。

具体包括：

- 从粘贴文本、上传文档内容或需求链接中解析 Markdown 文本。
- 提取 Markdown 章节。
- 提取图片链接。
- 下载图片到任务输出目录。

### 输入

- 需求 Markdown。
- 图片链接。
- 任务输出目录。

### 输出

内部数据：

- `markdown_text`
- `image_links`
- `downloaded_images`

如果有图片，会下载到任务目录下的 `images/`。

### 前端能看到什么

成功摘要类似：

```text
已收集 19 个章节，发现 32 张图片链接
```

### 失败情况

如果需求正文为空，会直接失败：

```text
输入内容为空
```

如果图片下载失败，通常不会直接中断任务，而是进入后续待确认或风险信息。

## 3. 图片识别 image_analysis

前端显示：`图片识别`

后端阶段 key：`image_analysis`

### 做什么

对下载成功的图片调用模型识别，优先提取图片里的 UI、字段、交互、业务规则和不确定点。

这一阶段的目的不是直接生成用例，而是把图片证据转换成可被后续需求分析使用的结构化信息。

### 输入

- 已下载图片列表 `downloaded_images`。
- 模型配置。

### 输出

内部数据：

- `image_analysis`

典型字段包括：

- 图片 ID。
- 图片摘要。
- UI 元素。
- 需求提示。
- 风险或不清晰点。

### 前端能看到什么

成功摘要类似：

```text
已识别 32 张图片
```

### 失败情况

模型调用失败可能导致任务失败。部分图片识别失败时，通常会被记录为风险或待确认。

## 4. 范围索引 scope_index

前端显示：`索引` 或阶段列表里的 `范围索引`

后端阶段 key：`scope_index`

### 做什么

这是可信改进模式最关键的新节点。

模型会先根据需求正文和图片识别结果，建立“直接测试对象索引”。它回答的问题是：

> 这份需求里，哪些东西应该被当成独立测试对象来生成用例？

它不是简单按标题层级切分，而是按“独立可测功能/交互/规则”识别。

### 输入

- 需求 Markdown。
- 图片识别结果 `image_analysis`。
- 模型配置。

### 输出产物

`scope_index.json`

核心结构：

```json
{
  "direct_testcase_sources": [
    {
      "source_id": "SRC-001",
      "title": "More Filters 二级菜单展开与收起",
      "source_order": 1,
      "primary_sections": [],
      "dependency_sections": [],
      "rule_clusters": [],
      "complexity": "simple|medium|complex",
      "case_budget": {
        "min": 1,
        "target": 3,
        "max": 5
      },
      "smoking_scope_note": "..."
    }
  ],
  "dependency_bindings": [],
  "index_risks": []
}
```

### 关键字段说明

| 字段 | 含义 |
|---|---|
| `source_id` | 直接测试对象 ID，后续功能点和用例都要追溯到它 |
| `title` | 直接测试对象名称 |
| `source_order` | 原文顺序，用于保持输出顺序 |
| `primary_sections` | 主要来源章节 |
| `dependency_sections` | 依赖来源章节，例如字段表、规则补充、图片说明 |
| `rule_clusters` | 规则簇，描述这个 source 下的重要规则 |
| `complexity` | 复杂度 |
| `case_budget` | 该 source 建议生成用例数量范围 |
| `smoking_scope_note` | 范围说明，避免把不该展开的内容展开 |

### 前端能看到什么

成功摘要类似：

```text
已建立 15 个直接测试对象
```

### 失败情况

如果模型没有返回可用的 `direct_testcase_sources`，会失败。

## 5. 范围门禁 scope_index_gate

前端显示：`范围门禁`

后端阶段 key：`scope_index_gate`

### 做什么

这是后端确定性校验，不依赖模型自评。

它检查 `scope_index.json` 是否可信、完整、可继续流转。

### 输入

- `scope_index.json`

### 输出产物

`scope_index_gate.json`

### 主要检查项

| 检查项 | 说明 |
|---|---|
| source 是否存在 | 必须有 `direct_testcase_sources` |
| source_id 是否重复 | 不允许重复 |
| title 是否为空 | 每个 source 必须有标题 |
| primary_sections 是否存在 | 每个 source 应有主要来源 |
| complexity 是否合法 | 只能是 `simple`、`medium`、`complex` |
| case_budget 是否完整 | 必须有 min/target/max |
| case_budget 是否合理 | min <= target <= max |
| dependency_bindings 是否孤儿 | 依赖绑定必须指向存在的 source |

### 成功标准

`passed=true`

前端显示：

```text
范围门禁通过
```

### 失败情况

如果失败，任务中断。错误类似：

```text
scope_index_gate 未通过：N 个阻断问题
```

## 6. 需求分析 requirement

前端显示：`需求分析`

后端阶段 key：`requirement`

### 做什么

基于已经通过门禁的 `scope_index` 生成功能点。

这一阶段不再自由发挥，而是要求每个功能点必须绑定一个 source。

### 输入

- `scope_index.json`
- 需求 Markdown。
- 图片识别结果。
- 模型配置。

### 输出产物

前端 artifact 类型：`function_points`

文件名：

```text
trusted_function_points.json
```

同时后续会生成：

```text
requirement_handoff.json
```

### 输出内容

核心包括：

- `function_points`
- `scope_index_consumption`
- `pending_confirmations`

### 关键字段说明

| 字段 | 含义 |
|---|---|
| `function_points[]` | 功能点列表 |
| `fp_id` | 功能点 ID |
| `source_id` | 所属直接测试对象，必须存在 |
| `source_title` | source 标题 |
| `rules` | 规则说明 |
| `pending_confirmations` | 仍无法确认的问题 |
| `scope_index_consumption` | 每个 source 是否被转换、合并、阻塞或不适用 |

### 前端能看到什么

成功摘要类似：

```text
已生成 51 个功能点
```

## 7. 需求门禁 requirement_gate

前端显示：`需求门禁`

后端阶段 key：`requirement_gate`

### 做什么

后端确定性检查功能点和 source 的关系是否可信。

它回答：

> 每个直接测试对象有没有被处理？每个功能点有没有明确来源？

### 输入

- `scope_index.json`
- `requirement_handoff`

### 输出产物

`requirement_handoff.json`

里面包含：

```json
{
  "requirement_handoff": {},
  "requirement_gate": {}
}
```

### 主要检查项

| 检查项 | 说明 |
|---|---|
| source 是否都被消费 | 每个 direct source 必须出现在 `scope_index_consumption` |
| 消费结果是否合法 | 只能是 converted、blocked、not_applicable、merged 等合法状态 |
| FP 是否有 source_id | 功能点不能没有来源 |
| FP source_id 是否存在 | 不能指向未知 source |
| consumption 引用的 fp_id 是否存在 | 不允许引用不存在的功能点 |

### 成功标准

`passed=true`

前端显示：

```text
需求门禁通过
```

### 失败情况

失败会中断任务：

```text
requirement_gate 未通过：N 个阻断问题
```

## 8. 用例设计 testcase

前端显示：`用例设计`

后端阶段 key：`testcase`

### 做什么

按 source 分组生成测试用例。

这也是可信改进模式区别于原始用例生成的重要节点。它不是直接把所有功能点一起丢给模型，而是按 source shard 逐个生成：

- 每个 source 只处理自己的功能点。
- 每个 source 有自己的用例预算。
- 每个用例必须能追溯到 source 和 fp。
- 生成后会进行统一编号和重复合并。

### 输入

- `scope_index`
- `requirement_handoff`
- 模型配置。

### 输出产物

前端 artifact 类型：`testcase_package`

文件名：

```text
trusted_testcase_package.json
```

### 输出内容

核心包括：

- `testcase_shards`
- `testcases`
- `feature_point_consumption`
- `duplicate_case_groups`
- `duplicate_case_count`
- `shard_failures`
- `shard_skips`

### 前端能看到什么

运行中会显示类似：

```text
正在生成 SRC-001 用例（4 个功能点，预算上限 8）
```

成功后：

```text
已生成 53 条测试用例
```

### 失败情况

如果某些 source shard 模型调用失败，会记录失败 source。

失败消息类似：

```text
以下 source shard 生成失败：SRC-014；错误：...
```

如果有 shard 失败，系统会尽量保留已生成的部分产物，方便定位和重跑单个 source。

## 9. 用例门禁 testcase_gate

前端显示：`用例门禁`

后端阶段 key：`testcase_gate`

### 做什么

后端确定性校验用例是否可信。

它回答：

> 功能点有没有被覆盖？source 有没有超预算？用例是否能追溯？

### 输入

- `scope_index`
- `requirement_handoff`
- `testcase_handoff`

### 输出产物

`testcase_handoff.json`

里面包含：

```json
{
  "testcase_handoff": {},
  "testcase_gate": {}
}
```

### 主要检查项

| 检查项 | 说明 |
|---|---|
| FP 是否被消费 | 每个功能点必须 covered、merged、blocked 或 not_applicable |
| 用例引用的 fp_id 是否存在 | 不允许用例指向未知功能点 |
| 用例引用的 source_id 是否存在 | 不允许用例指向未知 source |
| source 用例数是否超预算 | 超过 `case_budget.max` 会记录 |
| feature_point_consumption 是否引用真实 case_id | 不允许引用不存在的用例 |
| 覆盖 source 数 | 统计有用例覆盖的 source |
| 覆盖 FP 数 | 统计有用例覆盖或合并覆盖的功能点 |

### 成功标准

`passed=true`

前端显示：

```text
用例门禁通过
```

### 失败情况

失败会中断任务：

```text
testcase_gate 未通过：N 个阻断问题
```

## 10. 可信复核 review

前端显示：`可信复核`

后端阶段 key：`review`

### 做什么

汇总可信指标，并复用原始“用例生成”的质量审查能力做语义质量审查。

这一阶段包含两类检查：

1. trusted_v2 自己的可信指标。
2. 原始用例生成已有的质量审查。

### 输入

- `scope_index`
- `requirement_handoff`
- `testcase_handoff`
- 三个 gate 结果。
- 标准化后的 `function_points`
- 标准化后的 `testcase_package`
- 图片证据和待确认项。

### 输出产物

`trusted_review_report.json`

### 输出内容

核心字段：

```json
{
  "summary": {},
  "gates": [],
  "sources_detail": [],
  "quality_summary": {},
  "standard_review_report": {},
  "semantic_review": {},
  "method_coverage": {},
  "dimension_matrix": {},
  "semantic_findings": []
}
```

### 可信指标说明

| 指标 | 含义 |
|---|---|
| `source_count` | 直接测试对象数 |
| `function_point_count` | 功能点数 |
| `testcase_count` | 用例数 |
| `function_point_consumption_rate` | 功能点消费率 |
| `source_coverage_rate` | source 覆盖率 |
| `merged_coverage_count` | 合并覆盖数量 |
| `duplicate_case_count` | 重复用例数量 |
| `over_budget_source_count` | 超预算 source 数 |
| `pending_confirmation_count` | 待确认数量 |
| `gate_passed` | 三个 gate 是否全部通过 |

### 质量审查说明

`standard_review_report` 来自原始用例生成质量审查能力，关注：

- 弱预期。
- 模糊步骤。
- 不可验证预期。
- 重复或同质用例。
- 方法覆盖情况。
- 维度覆盖情况。
- release readiness。

为了兼容前端，目前也保留 `semantic_review` 字段，它和 `standard_review_report` 指向同类审查结果。

### 前端能看到什么

成功摘要：

```text
可信指标和语义质量审查已汇总
```

## 11. 导出交付物 export

前端显示：`导出交付物`

后端阶段 key：`export`

### 做什么

导出最终可下载产物。

当前会导出：

- Markdown 摘要。
- JSON 中间产物。
- XMind 文件。

### 输入

- `trusted_review_report`
- `testcase_handoff`
- 标准化后的功能点。
- 标准化后的用例包。

### 输出产物

| artifact 类型 | 文件名示例 | 说明 |
|---|---|---|
| `markdown` | `trusted_delivery_summary.md` | 可信改进模式交付摘要 |
| `xmind` | `xxx.xmind` | 最终 XMind 用例 |
| `trusted_review_report` | `trusted_review_report.json` | 可信复核报告 |
| `scope_index` | `scope_index.json` | 范围索引 |
| `requirement_handoff` | `requirement_handoff.json` | 需求交接和需求门禁 |
| `testcase_handoff` | `testcase_handoff.json` | 用例交接和用例门禁 |

### XMind 导出说明

用例生成2 现在复用统一的 XMind 导出逻辑：

- 先把 trusted_v2 的功能点和用例转换成标准结构。
- 再生成 XMindMark。
- 最后通过统一 common 模块写出 XMind ZIP。

这样可以避免“原始用例生成可打开，但用例生成2打不开”的分叉问题。

### 前端能看到什么

成功摘要：

```text
已导出 Markdown、JSON 和 XMind 产物
```

任务最终摘要类似：

```text
可信改进模式已生成 53 条用例并导出 XMind，覆盖 15 个直接测试对象
```

## 进度百分比如何计算

前端不是按真实耗时计算百分比，而是按阶段完成数计算。

trusted_v2 一共有 11 个阶段：

```text
orchestrate
collect
image_analysis
scope_index
scope_index_gate
requirement
requirement_gate
testcase
testcase_gate
review
export
```

计算方式大致是：

- success 阶段计为完成。
- running 阶段计入一部分进度。
- failed 阶段停在失败位置。

所以某个阶段耗时很长时，百分比可能长时间不动，这是正常的。比如：

- 图片多时，`图片识别` 会久。
- source 多或模型慢时，`用例设计` 会久。
- 模型审查慢时，`可信复核` 会久。

## 失败时如何看问题

建议按以下顺序看：

1. 看当前失败阶段。
2. 看阶段 summary。
3. 看右侧产物 JSON。
4. 如果是 trusted_v2，优先看：
   - `scope_index_gate.json`
   - `requirement_handoff.json`
   - `testcase_handoff.json`
   - `trusted_review_report.json`

常见定位：

| 失败阶段 | 优先查看 |
|---|---|
| 范围索引 | `scope_index.json` 是否为空或结构异常 |
| 范围门禁 | `scope_index_gate.json` 的 issues |
| 需求门禁 | `requirement_handoff.json` 的 requirement_gate |
| 用例设计 | 是否有 source shard 失败 |
| 用例门禁 | `testcase_handoff.json` 的 testcase_gate |
| 可信复核 | 模型审查错误或 trusted_review_report |
| 导出交付物 | XMind 导出日志或 xmind artifact |

## 和复刻模式的区别

复刻模式接近原始“用例生成”：

```text
需求 → 功能点 → 用例 → 审查 → XMind
```

可信改进模式增加了这些关键节点：

```text
范围索引
范围门禁
需求门禁
按 source shard 用例生成
用例门禁
可信指标汇总
```

所以 trusted_v2 更慢，但可解释性更强：

- 能解释为什么是这些测试对象。
- 能解释每个对象生成了多少用例。
- 能检查 source 是否漏掉。
- 能检查功能点是否消费。
- 能检查是否超预算。
- 能保留 source 级失败和重跑能力。
