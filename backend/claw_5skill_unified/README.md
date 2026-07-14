# Claw Testcase Generation Unified

中文名：测试用例生成统一 Skill 流水线。

本目录把 `claw_5skill_final` 和 `claw_5skill_final_v2` 合并为一套入口，按 `mode` 选择执行策略：

1. `lite`：轻量模式，继承 `claw_5skill_final` 思路，流程短、产物少、成本低。
2. `trusted`：可信模式，继承 `claw_5skill_final_v2` 思路，带 source 索引、门禁和导图结构校验。

原始两套目录不删除、不覆盖，作为历史参照保留。

## 推荐执行方式

推荐使用“单步 Prompt + 上游产物注入”的方式执行，避免长会话一次性跑完整链路导致状态漂移。

核心要求：

1. 每次只执行一个 `current_stage`。
2. 每次只允许读取当前阶段声明的 `allowed_inputs`。
3. 每次只允许生成当前阶段声明的 `allowed_outputs`。
4. gate 未通过时禁止进入下游阶段。
5. export 阶段必须重新读取 `ReviewReport.yaml` 和 gate report，不能凭上下文记忆写统计信息、审查结论或中文化映射。

完整协议见 `workflow/SINGLE_STEP_PROTOCOL.md`。

## 图片工具要求

图片证据必须来自真实工具执行结果。运行环境应提供图片下载和视觉识别能力，例如 `download_image(url)` 与 `vision_analyze(path)` 这类 Agent Tool；实际工具名以当前环境为准。

如果没有可用下载工具或视觉识别工具，不能假装已识图，必须把对应图片标记为失败并进入待确认清单。

## 工程稳定性要求

1. YAML 中间产物禁止使用 `null`、`~`、`none`。列表为空写 `[]`，文本为空写 `""`，对象为空写 `{}`，必填 key 不得省略。
2. 生成 `FunctionPoints.yaml`、`TestcasePackage.yaml`、`.xmindmark` 前必须评估输出体量，避免单次输出截断。
3. trusted 模式预估输出过大时，必须规划 `TestcasePackage_PartN.yaml` 分片输出，避免单次输出截断。
4. XMindMark 节点文本禁止半角中括号 `[` 和 `]`，特殊标记使用 `【】` 或 `()`。
5. 全新运行前必须检查并清理 `output_dir` 中的历史下游产物，避免旧 YAML 或 XMindMark 污染当前运行。
6. trusted gate 必须按独立审计原则执行；任何硬约束不满足都必须 `status=fail`，不得为了推进流程而放行。
7. trusted 模式必须使用 ID 强引用：`TestcasePackage.yaml` 只保留 `source_id / shard_id / fp_ids` 和用例差异字段，不重复抄写 `module / scene / title_path / description / rules` 等上游长字段。
8. trusted gate 通过时必须使用 Quiet Pass 极简回执；只有失败时才展开 `blocking_issues / return_to / return_reason`。
9. trusted gate 失败时必须输出 `recovery_plan`，优先给出局部重跑范围；例如 `testcase_gate` 的少量 FP 未覆盖应回到 `testcase_by_source_shard` 并限定具体 `source_id / shard_id / fp_id`，不得默认要求整条 trusted 流程重跑。
10. `run_id` 必须使用 `run_<yyyyMMdd-HHmmss>_<4位随机大写字母数字>` 格式，例如 `run_20260703-153022_A7K9`。
11. 如果输出被拆分为 `TestcasePackage_PartN.yaml`，后续 gate、review、export 和 final gate 必须合并所有 Part 后检查和导出。
12. trusted 的 `TestcasePackage.yaml` 或每个 Part 必须包含 `xmind_grouping_contract`。
13. `_archive` 默认保留最近 3 次归档；超出部分只能提示用户确认删除或压缩，未授权不得自动删除。
14. trusted 交付前必须运行本地硬校验器，不能只依赖模型自述或 gate 文案：

```bash
python3 tools/validate_trusted_output.py "outputs/<需求文档名>/trusted"
```

该校验器会检查 YAML 引用链、SRC/FP/TC 覆盖、统计一致性、`.xmindmark` 层级和本地 `xmindmark` 转换回读。命令返回非 0 时，`final_delivery_gate` 必须失败并回到对应阶段修复。

## 测试设计方法适用性

lite 和 trusted 都必须使用测试设计方法库，但不能用固定条数驱动生成。

lite 使用“轻量适用性判断”：每个 FP 先判断哪些方法适用，只为可观察、非重复、与证据相关的测试差异生成用例；可合并的低风险验证点应合并，不为凑数量生成低信息量用例。

trusted 使用“来源守恒 + 风险驱动适用性判断”：每个 source/shard 通过 `test_design_profile` 声明 `applicable_methods`、`must_cover`、`merge_allowed`、`not_applicable` 和 `coverage_budget`。`coverage_budget` 是软护栏，不是目标数量；`must_cover` 必须被用例可观察覆盖，或明确阻塞/不适用原因。

方法库包括等价类、边界值、决策表、状态转换、角色权限、多入口一致性、空值/默认值、异常容错、时间/重复操作、UI 展示、组合测试、数据生命周期、幂等/重试/去重、数据一致性/跨层级联动、计算精度、批处理部分失败、可观测性/审计日志。

## 本地硬校验器

`tools/validate_trusted_output.py` 是 trusted 模式的本地审计工具，目标是把“可信”从模型承诺变成产物可证明。

它会执行：

1. `validate_trusted_output`：校验 `ScopeIndex.yaml -> FunctionPoints.yaml -> TestcasePackage.yaml` 的 ID 引用链、source 覆盖、FP 覆盖、用例唯一性、gate 状态和 `ReviewReport.yaml` 统计。
2. `validate_xmindmark`：校验 `.xmindmark` 首行、缩进、非法元字符、树结构、统计节点和重复 TC。
3. `repair_or_report`：默认不自动改业务内容，只输出明确错误清单；修复后重新运行同一命令确认。

常用命令：

```bash
python3 tools/validate_trusted_output.py "outputs/DSP - DSP平台整体交互优化/trusted"
python3 tools/validate_trusted_output.py "outputs/<需求文档名>/trusted" --format json
```

## XMind 转换依赖

最终 `.xmind` 由项目内受测试的确定性 exporter 从 `.xmindmark` 生成。当前不使用已知会生成空白文件的 `xmindmark@0.3.2` CLI。

1. exporter 失败时允许保留已校验的 `.xmindmark` 和 `DeliverySummary.md`，但禁止宣称 `.xmind` 已交付。
2. trusted 模式下，缺少、空白或无法解析的实际 `.xmind` 必须令 `final_delivery_gate` 失败。
3. 业务 Skill 不得自行构造第二份临时 `.xmind`；只能调用项目共用 exporter。
4. final gate 必须解析实际交付文件，并复算根节点及 SRC/FP/TC 数量。

## 何时使用 lite

适合：

1. 快速生成一版可读 XMind。
2. 用户没有要求强追溯、强门禁或审计证明。
3. 需求规模较小，主要目标是测试设计覆盖。

lite 主流程：

```text
orchestrate
-> evidence_trace
-> requirement
-> testcase
-> quality_review
-> export
```

lite 默认产物：

```text
EvidenceTrace.yaml
FunctionPoints.yaml
TestcasePackage.yaml
ReviewReport.yaml
需求文档同名.xmindmark
需求文档同名.xmind
DeliverySummary.md
```

lite 导图结构：

```text
项目名测试用例
- 统计信息
- 模块：...
  - 场景：...
    - FP-001：功能点
      - TC-001-001-标题
        - 优先级：P1｜类型：功能
        - 预期摘要：...
        - 操作步骤
```

## 何时使用 trusted

适合：

1. 用户要求严格按原需求章节/段落归属。
2. 需要回答“测了什么、为什么测、覆盖了没有、有没有过度生成”。
3. 需要保留 source、shard、test_design_profile、gate、review 等可信证明。

trusted 主流程：

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

trusted 默认产物：

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

trusted 导图结构：

```text
项目名测试用例
- 统计信息
- 模块：...
  - 场景：...
    - SRC-001｜2.1 原需求章节/段落标题
      - FP-001：功能点
        - TC-001-标题
          - 优先级：P1｜类型：功能
          - 预期摘要：...
          - 操作步骤
```

## 默认模式选择

1. 用户明确说 `lite`：使用 lite。
2. 用户明确说 `trusted`：使用 trusted。
3. 用户要求“严格”“可信”“按章节归属”“可追溯”“检查覆盖”“门禁”“不要过度生成”：使用 trusted。
4. 用户只说“生成测试用例 / 输出 XMind”，且没有强追溯要求：使用 lite。
5. 如果需求包含大量图片、表格、外部依赖，且用户没有强调成本优先：建议 trusted。

## 目录结构

```text
claw_5skill_unified/
├── README.md
├── workflow/
│   ├── EXECUTION_PLAN.md
│   ├── SINGLE_STEP_PROTOCOL.md
│   └── EXAMPLE_FLOW.md
├── schemas/
│   ├── lite/
│   └── trusted/
├── skills/
│   ├── testcase-orchestrator/
│   ├── evidence-builder/
│   ├── scope-indexer/
│   ├── requirement-analyzer/
│   ├── trusted-gate/
│   ├── testcase-designer/
│   ├── quality-reviewer/
│   └── artifact-exporter/
└── reference/
    ├── README.lite-source.md
    ├── README.trusted-source.md
    ├── EXECUTION_PLAN.lite-source.md
    └── EXECUTION_PLAN.trusted-source.md
```

## 文件操作原则

1. `claw_5skill_final` 和 `claw_5skill_final_v2` 是历史来源，不在统一版运行中修改。
2. 新需求的输出应写入独立 output 目录，不写回 `schemas/`、`skills/` 或 `reference/`。
3. `schemas/lite` 只服务 lite，`schemas/trusted` 只服务 trusted，避免混用字段。
4. `.xmind` 必须由 `.xmindmark` 经项目确定性 exporter 生成，并解析实际交付文件复核 SRC/FP/TC 数量；禁止模型直接生成或未经校验地拼装。
