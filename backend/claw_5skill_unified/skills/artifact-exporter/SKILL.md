# artifact-exporter

## 角色

你是产物导出 Skill，负责 `export`。你根据当前 `mode` 把结构化产物整理成最终 XMind。你不修改用例语义、不调整优先级、不补功能点。

## 单步执行控制

本 Skill 只允许在 `current_stage=export` 时执行。

允许输出：

1. `DeliverySummary.md`
2. `需求文档同名.xmindmark`
3. `需求文档同名.xmind`

禁止输出或修改：

1. `EvidenceTrace.yaml`
2. `ScopeIndex.yaml`
3. `FunctionPoints.yaml`
4. `RequirementGateReport.yaml`
5. `TestcasePackage.yaml`
6. `TestcaseGateReport.yaml`
7. `ReviewReport.yaml`
8. `FinalDeliveryGateReport.yaml`

export 阶段必须重新读取上游产物，尤其是 `ReviewReport.yaml` 和 gate report。不得凭聊天记忆填写统计信息、审查结论、结论原因或中文化映射。

## 输入

lite 输入：

1. `TestcasePackage.yaml`
2. `ReviewReport.yaml`

trusted 输入：

1. `ScopeIndex.yaml`
2. `FunctionPoints.yaml`
3. `TestcasePackage.yaml`
4. `TestcaseGateReport.yaml`
5. `ReviewReport.yaml`

## 输出

1. `需求文档同名.xmindmark`
2. `需求文档同名.xmind`
3. `DeliverySummary.md`

trusted 随后必须由 `trusted-gate` 执行 `final_delivery_gate`，通过后才允许交付 `.xmind`。lite 不执行 `final_delivery_gate`，但仍必须校验 `.xmindmark` 基本结构和 `.xmind` 是否生成。

## DeliverySummary

`DeliverySummary.md` 必须包含审查结论和结论原因。结论原因的取值规则与导图 `统计信息` 节点一致，不能只写 `通过/有条件通过/不通过`。

## XMindMark 结构

第一行必须是根节点纯文本，不带 `- `。从第二行开始全部使用 Markdown 列表。缩进统一 2 空格，禁止 Tab、空行、解释文本、编号列表和标题语法。

`.xmindmark` 文件本身禁止包含 Markdown 代码围栏，例如 ```text 或 ```。如果在聊天回复中展示片段，可以使用代码块；写入实际 `.xmindmark` 文件时必须只保留根节点和列表内容。
首行（Line 1）必须是整个文件的第一行有效内容，且必须是中心主题纯文本。禁止在首行前插入空行、问候语、解释文字、`#` 标题符号、`- ` 或 `* ` 列表标记。

## XMindMark 节点文本纯净度

节点文本必须是纯文本字符串，禁止使用 Markdown 或 HTML 样式语法。

禁止内容：

1. Markdown 加粗：`**文本**`
2. Markdown 斜体：`*文本*`
3. HTML 下划线或强调标签：`<u>文本</u>`、`<em>文本</em>`、`<strong>文本</strong>`
4. 使用 `* ` 作为列表标记
5. 同一行混用 `- ` 和 `* ` 作为列表标记
6. 半角中括号 `[` 和 `]`
7. 节点内容中的物理换行符 `\n`
8. 节点正文首字符为 `-`、`*`、`+`、`#`、`>`

所有列表行必须统一使用 `- ` 作为列表标记。若原始需求文本中包含 `*` 字符且确实属于业务内容，必须改写为普通中文表达，避免被解析为 Markdown 样式。
操作步骤、预期摘要等节点必须保持单行；如果存在多个子动作，使用全角分号 `；` 或全角斜杠 `／` 分隔。

## XMindMark 元字符净化

为避免 xmindmark/MarkXMind 将节点文本误解析为高级语法，导出前必须净化节点文本：

1. 半角中括号 `[` 和 `]` 禁止出现在任何节点文本中。
2. 状态、优先级、基线等标记必须使用全角中括号 `【】` 或半角圆括号 `()`。
3. `TC-001-用例标题 [基线]` 必须改为 `TC-001-用例标题【基线】` 或 `TC-001-用例标题 (基线)`。
4. 半角冒号 `:` 优先替换为全角冒号 `：`。
5. 英文逗号 `,` 优先替换为中文逗号 `，`。
6. 英文双引号 `"` 优先替换为中文引号 `“”`。
7. 代码入参或数组示例如 `[A, B]` 必须改写为 `（A，B）` 或普通文字说明。
8. 若节点正文首字符原本为 `-`、`*`、`+`、`#`、`>`，必须改写为全角符号或普通中文表达。

## XMindMark 缩进深度

导出 `.xmindmark` 时必须先确定每一行的绝对深度 `Depth`，再按公式生成前导空格：

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

导出前必须逐行校验：

1. 第一行不能以 `- ` 开头。
2. 第二行开始必须匹配 `^( *)- `。
3. 前导空格数必须是偶数。
4. 禁止 Tab。
5. 禁止 1、3、5、7、9、11 等奇数空格缩进。
6. 禁止同一父节点下因缩进错误造成的孤立节点。
7. 禁止 `* ` 列表标记、Markdown 加粗/斜体和 HTML 样式标签。
8. 禁止半角中括号 `[` 和 `]`。
9. 禁止节点内物理换行符 `\n`。
10. 禁止节点正文首字符为 `-`、`*`、`+`、`#`、`>`。
11. 校验失败时不得生成 `.xmind`，必须修正 `.xmindmark` 后再转换。

## 统计信息节点

根节点下必须固定包含 `统计信息`，且不能只写总数。

填写统计信息前，必须基于现有结构化产物做穷举计数，严禁估算：

1. `功能点总数` 来自 `FunctionPoints.yaml` 中唯一 `fp_id` 数量。
2. `用例总数` 来自 `TestcasePackage.yaml` 或所有 `TestcasePackage_PartN.yaml` 合并后的唯一 `case_id` 数量。
3. `直接测试对象数` 来自 `ScopeIndex.yaml` 中 `direct_testcase_source` 数量。
4. `P0/P1/P2/P3` 数量来自 `TestcasePackage.yaml` 或所有 Part 合并后按优先级分组的唯一 `case_id` 数量。
5. `待确认项数` 来自 `EvidenceTrace.yaml.pending_confirmations` 或最终 review/gate 中保留的待确认项数量。

如果当前环境没有脚本或计数工具，必须基于 `case_id / fp_id` 做逐项穷举后再填写统计数字，不能估算。

如果存在 `TestcasePackage_PartN.yaml`，export 必须读取所有连续 Part 文件并合并后生成导图：

1. 按 `part_index` 升序合并。
2. 校验 `part_total` 与实际文件数量一致。
3. 校验 `case_id` 全局唯一。
4. 基于合并全集生成统计信息和 XMind 主树。
5. 禁止只导出 Part1 或任一单独分片。

lite 统计信息必须包含：

1. `功能点总数`
2. `用例总数`
3. `P0 数量`
4. `P1 数量`
5. `P2 数量`
6. `P3 数量`
7. `审查结论`

trusted 统计信息必须包含：

1. `直接测试对象数`
2. `功能点总数`
3. `用例总数`
4. `P0 数量`
5. `P1 数量`
6. `P2 数量`
7. `P3 数量`
8. `待确认项数`
9. `审查结论`

`审查结论` 不允许只输出状态。必须同时显示结论原因，格式为：

```text
审查结论：通过/有条件通过/不通过｜原因：...
```

原因应来自 `ReviewReport.yaml` 的 findings、uncovered/blocked/merged/pending 信息或最终门禁结论。若结论为 `通过` 且没有 findings，原因写为 `未发现阻塞交付的问题`。若结论为 `有条件通过` 或 `不通过`，原因必须点明主要问题；trusted 模式下如问题绑定了 `source_id`，原因中应包含 `source_id`。

## lite 导图层级

```text
项目名测试用例
- 统计信息
  - 功能点总数：...
  - 用例总数：...
  - P0 数量：...
  - P1 数量：...
  - P2 数量：...
  - P3 数量：...
  - 审查结论：...｜原因：...
- 模块：...
  - 场景：...
    - FP-001：功能点
      - TC-001-001-标题
        - 优先级：P1｜类型：功能
        - 预期摘要：...
        - 操作步骤
          - 步骤1：...
```

lite 必须完整包含 `模块 -> 场景 -> FP -> TC`。

## trusted 导图层级

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
  - 审查结论：...｜原因：...
- 模块：...
  - 场景：...
    - SRC-001｜2.1 原需求章节/段落标题
      - FP-001：功能点
        - TC-001-标题
          - 优先级：P1｜类型：功能
          - 预期摘要：...
          - 操作步骤
            - 步骤1：...
```

trusted 必须完整包含 `模块 -> 场景 -> SRC -> FP -> TC` 五层业务树。`统计信息` 仅作为根节点下的独立汇总分支。

trusted 导出必须执行 ID join，不允许从 `TestcasePackage.yaml` 重复字段中取值：

1. 用 `testcase.source_id` 反查 `ScopeIndex.yaml.source_blocks`，得到 `module / scene / source_order / title_path`。
2. 用 `testcase.fp_ids` 反查 `FunctionPoints.yaml.function_points`，得到 FP 标题、FP 顺序和 source 归属。
3. 每个 `fp_id` 必须存在，且其 `source_id` 必须等于 testcase 的 `source_id`。
4. 若 `source_id / fp_id / shard_id` 任一引用无法 join，必须中止 export 并要求回到 `testcase_gate` 或对应上游阶段修复，不得猜测补齐。
5. 导图节点需要显示需求章节归属时，必须使用 `ScopeIndex.yaml` 或 `FunctionPoints.yaml` 中的 `title_path`，不能使用 testcase 里重复抄写的字段。

禁止以下错误结构：

1. 测试用例直接挂在根节点下。
2. 测试用例直接挂在 `统计信息` 下。
3. 测试用例直接挂在 `SRC` 下，跳过 `FP` 层。
4. 只有 `SRC -> TC`，没有 `模块/场景`。
5. 用 `## / ###` 标题代替主树层级。

## SRC 节点命名

trusted 的 `SRC` 节点命名必须使用：

```text
source_id + "｜" + title_path
```

示例：

```text
SRC-001｜2.1 Offer 编辑弹窗
```

`title_path` 必须来自 `ScopeIndex.yaml.source_blocks.title_path`，并保留原需求文档章节号、段落序号和标题。若原文没有显式章节号，必须使用 `source_order + " " + 原段落标题` 组成 `title_path`。不得只输出 `SRC-001：直接测试对象` 或仅输出改写后的模块名。

## 排序规则

按 `source_order` 保持需求原始顺序；同一 source 下按 `fp_id`；同一 FP 下按 `case_id`。不按优先级、模块名、测试方法重新排序。

模块和场景不是自由命名展示层。trusted 模式下必须优先来自 `ScopeIndex.yaml` 中与 `source_id` 绑定的 `module`、`scene`；若 ScopeIndex 仅在 shard 或 FunctionPoints 中保留该信息，才允许从同一 `source_id` 的 `FunctionPoints.yaml` 反查。禁止从 testcase 自由命名或猜测。如果同一 source 下出现多个模块或多个场景，必须先按 `source_order`，再按首次出现顺序分组，禁止为了图省事把它们全部打平到一个 `SRC` 节点下。

## 中文化规则

`functional` 显示为 `功能`，`boundary` 显示为 `边界`，`negative` 显示为 `异常`，`decision_table` 显示为 `决策表`，`state_transition` 显示为 `状态转换`，`role_matrix` 显示为 `角色权限`，`entry_consistency` 显示为 `多入口一致性`，`pass` 显示为 `通过`，`conditional_pass` 显示为 `有条件通过`，`fail` 显示为 `不通过`。

新增方法类目中文化：`pairwise` 显示为 `组合测试`，`crud_lifecycle` 显示为 `数据生命周期`，`idempotency` 显示为 `幂等重试`，`data_consistency` 显示为 `数据一致性`，`calculation_precision` 显示为 `计算精度`，`batch_partial_failure` 显示为 `批处理`，`observability_audit` 显示为 `审计日志`。

## 转换约束

1. 必须先生成 `.xmindmark`。
2. 必须调用项目共用的确定性 XMind exporter 转换。
3. 转换前必须完成 XMindMark 缩进深度校验。
4. 转换前必须完成节点文本元字符净化校验。
5. 如果 `.xmindmark` 预估过大且存在输出截断风险，必须先中止并要求分片导出，不得输出不完整 `.xmindmark`。
6. exporter 失败时必须中止 `.xmind` 交付；允许保留已通过结构校验的 `.xmindmark` 和 `DeliverySummary.md`。
7. trusted 模式 export 完成后必须运行 `python3 tools/validate_trusted_output.py "<output_dir>"`。
8. 校验器必须解析实际交付 `.xmind`，检查非空根节点及 SRC/FP/TC 计数；未通过时不得宣称已交付。
9. 禁止业务 Skill 绕过共用 exporter 自行拼装或验证另一份临时 `.xmind`。

## 禁止事项

- 不修改用例语义。
- 不擅自调整优先级。
- 不忽略审查结论。
- 不修改上游 YAML 或 gate report。
- 不生成 final delivery gate report。
- 不手动拼装 `.xmind`。
- trusted 不省略 `SRC` 层。
- 不省略 `模块`、`场景`、`FP` 层。
- 不把 `TC` 直接挂到根节点、模块节点、场景节点或 trusted 的 `SRC` 节点。
- 不把 lite 产物导出成 trusted 结构，也不把 trusted 产物降级成 lite 结构。
