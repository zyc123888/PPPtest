# Claw 5 Skill 最终方案

这是一个纯 Skill 版的 AI 驱动测试用例生成方案。

目标：

1. 不依赖自定义 Python 脚本。
2. 由 Claw / OpenClaw 通过多个 Skill 分步骤完成任务。
3. 使用模型自身的多模态能力理解图片，不单独引入 OCR Skill。
4. 保留结构化中间产物，避免“只靠上下文记忆”导致结果失真。

补充前提：

需求文档中的图片可能不是本地附件，而是以链接形式存在于 Markdown 正文中。

因此在进入多模态分析前，必须先：

1. 提取图片链接
2. 下载图片到本地可读取路径
3. 再对下载后的本地图片进行多模态分析

如果有图片下载失败：

1. 必须进入 `待确认清单`
2. 必须在分析结果中明确记录失败的图片链接
3. 不允许静默忽略
4. 不允许假装已经完成了这些图片的识图分析

补充约束：

`requirement-analyzer` 虽然是一个 Skill，但它的内部分析顺序必须是：

1. 先提取图片链接并下载图片
2. 再看图片和界面证据
3. 再读正文和表格
4. 再做图片与正文的交叉对齐
5. 最后输出 `FunctionPoints`

这样设计的原因是：

1. 图片中经常先暴露入口、按钮、字段、弹窗、状态。
2. 这些信息会直接影响功能点拆分和多入口判断。
3. 如果图片是链接，必须先下载，否则模型根本无法真正识图。
4. 如果只先读正文，图片容易沦为“事后补充”，导致 UI 结构和入口维度被弱化。

## 目录结构

```text
claw_5skill_final/
├── README.md
├── workflow/
│   ├── EXECUTION_PLAN.md
│   └── EXAMPLE_FLOW.md
├── schemas/
│   ├── function_points.template.yaml
│   ├── evidence_trace.template.yaml
│   ├── testcase_package.template.yaml
│   ├── review_report.template.yaml
│   ├── delivery_summary.template.md
│   └── xmindmark.template.md
└── skills/
    ├── testcase-orchestrator/
    │   └── SKILL.md
    ├── requirement-analyzer/
    │   └── SKILL.md
    ├── testcase-designer/
    │   └── SKILL.md
    ├── quality-reviewer/
    │   └── SKILL.md
    └── artifact-exporter/
        └── SKILL.md
```

## 5 个 Skill

1. `testcase-orchestrator`
   负责识别任务模式、选择执行顺序、约束中间产物。

2. `requirement-analyzer`
   负责多模态识图 + 正文理解 + 交叉对齐 + 功能点拆分，输出 `FunctionPoints`。

3. `testcase-designer`
   负责基于 `FunctionPoints` 生成测试用例包。

4. `quality-reviewer`
   负责覆盖检查、去重、补漏、可执行性和可验证性审查。

5. `artifact-exporter`
   负责把结构化结果导出成 XMind。

## 强制实施红线

为了避免理解偏差，必须严格遵守：

1. 默认对外只交付一个 `.xmind` 文件。
2. 不要在最终回复里默认附带内部中间产物。
3. `testcase-designer` 不允许回头重读原始需求文档和原始图片。
4. `quality-reviewer` 不允许省略。
5. `artifact-exporter` 必须把展示层文案转成中文，不允许把内部英文枚举直接写进导图。
6. **必须先生成 `.xmindmark`，再使用项目共用的确定性 exporter 生成 `.xmind`；业务 Skill 禁止自行拼装，实际交付文件必须可解析且计数一致。**
7. 若任何局部规则冲突，以“最终只交付同名 `.xmind`”为最高优先级。
8. 未产出 `EvidenceTrace.yaml` 或 `FunctionPoints.yaml`，禁止进入 `testcase-designer`
9. 未产出 `TestcasePackage.yaml`，禁止进入 `quality-reviewer`
10. 未产出 `ReviewReport.yaml`，禁止进入 `artifact-exporter`
11. 如果存在图片链接，但没有图片下载和识图记录，流程必须中止

## 实施原则

1. 结构化中间产物优先，不能只靠聊天上下文。
2. 正文规则优先于图片推断。
3. 图片信息属于补充证据，不是唯一事实源。
4. 生成与审查必须拆开，不能“生成即交付”。
5. 导图是展示层，不是主事实源。
6. 模块划分和展示顺序必须跟随需求文档原始分类和章节顺序，方便按原文对照阅读。
7. 不要按测试经验、优先级、模块名字母序重新规划导图模块。

## 推荐执行顺序

```text
testcase-orchestrator
  -> requirement-analyzer
  -> testcase-designer
  -> quality-reviewer
  -> artifact-exporter
```

## 默认交付物

默认对外交付只保留：

1. `需求文档同名.xmind`

其余文件属于内部中间产物或调试产物，不作为默认交付：

1. `FunctionPoints.yaml`
2. `EvidenceTrace.yaml`
3. `TestcasePackage.yaml`
4. `ReviewReport.yaml`
5. `需求文档同名.xmindmark`
6. `TestCases_Full.md`
7. `DeliverySummary.md`

## 识图定义

识图是强制动作，不是建议动作。

必须满足：

1. 先下载图片
2. 再对实际图片做视觉分析
3. 不能用正文中的图片描述替代识图
4. 不能因为正文已经详细，就跳过图片分析
5. 图片分析失败必须进入 `待确认清单`

## 门禁与检查点

必须严格执行：

1. `requirement-analyzer` 完成后，必须同时产出：
   - `EvidenceTrace.yaml`
   - `FunctionPoints.yaml`
2. 如果需求中存在图片链接，但没有 `EvidenceTrace.yaml`，流程中止
3. 如果存在下载失败图片，但没有 `待确认清单`，流程中止
4. `testcase-designer` 只允许读取：
   - `FunctionPoints.yaml`
   - `EvidenceTrace.yaml`
5. 最终内部必须给出一段执行证明摘要，至少说明：
   - 发现图片链接数量
   - 下载成功数量
   - 下载失败数量
   - 图片识别证据数量
   - 来自正文的功能点数量
   - 来自图片补充的功能点数量
   - 待确认项数量

## XMind 转换约束

1. 必须先生成并校验 `.xmindmark`。
2. 必须使用项目共用的确定性 exporter 生成 `.xmind`。
3. exporter 失败或实际文件无法解析时必须中止交付。
4. 业务 Skill 不得自行拼装或验证另一份临时 `.xmind`。

## 最终导图输出规范

最终主要交付是中文 XMind。

为了保证 `.xmind` 导出稳定，不要使用过深的树形层级。导图层级应尽量控制在 5-6 层的稳定范围内。

`xmindmark` 文件必须使用“根节点纯文本 + 子节点标准 Markdown 列表”的唯一格式，不要混用其他树表示法。

原因：

1. 标题层级语法在实际导出时更容易导致层级扁平。
2. 混用“纯缩进文本”和“列表语法”容易导致父子节点解析失败。
3. 标准 Markdown 列表语法已经过实际导出验证，更适合本方案。

### XMindMark 唯一合法格式

必须严格遵守：

1. 第一行必须是根节点纯文本，不带 `- `
2. 从第二行开始，每一行子节点都必须以 `- ` 开头
3. 根节点直属子节点必须顶格写 `- `
4. 更深层子节点必须统一比父节点多 2 个空格缩进
5. 禁止使用 Tab
6. 禁止在主树中插入空行
7. 禁止在主树中插入解释文字、注释、编号列表、普通段落
8. 禁止使用纯缩进无 `- ` 的写法
9. 禁止使用 `# / ## / ###` 标题层级语法

### 整棵 XMind 树固定结构

必须严格按以下层级输出：

1. 根节点：`项目名 + 测试用例`
2. 根节点下固定一个子节点：`统计信息`
3. 根节点下固定若干 `模块`
4. `模块` 下固定若干 `场景`
5. `场景` 下固定若干 `功能点`
6. `功能点` 下固定若干 `CaseID-标题`
7. `CaseID-标题` 下固定字段节点：`优先级：...｜类型：...`
8. `CaseID-标题` 下固定字段节点：`预期摘要：...`
9. `CaseID-标题` 下固定字段节点：`操作步骤`
10. `操作步骤` 下再展开：`步骤1` / `步骤2` / `步骤3 ...`

排序要求：

1. `requirement-analyzer` 必须为每个功能点生成 `source_order`
2. `testcase-designer` 必须把对应功能点的 `source_order` 继承到每条用例
3. `artifact-exporter` 必须按 `source_order` 导出模块、场景、功能点和用例
4. 不允许按模块名、优先级、测试方法重新排序
5. 如果图片或原型补充了正文未写出的点，应挂到最接近的原文模块下，不要新建打乱顺序的模块

额外命名约束：

1. 最终 `.xmind` 文件名必须与需求文档同名，只替换扩展名。
2. `.xmindmark` 导图源文件应与 `.xmind` 使用同一基名，但默认不对外交付。
3. 不要默认输出 `TestCases.xmind`、`output.xmind` 这类通用名。

示例：

- 输入：`ADX Ad Block 支持HTML keyword 屏蔽.md`
- 输出：`ADX Ad Block 支持HTML keyword 屏蔽.xmindmark`
- 输出：`ADX Ad Block 支持HTML keyword 屏蔽.xmind`

### 展示层中文化规则

最终 `.xmind` 中展示的文案必须使用中文。

至少包含以下映射：

1. `functional` 显示为 `功能`
2. `boundary` 显示为 `边界`
3. `negative` 显示为 `异常`
4. `decision_table` 显示为 `决策表`
5. `state_transition` 显示为 `状态转换`
6. `role_matrix` 显示为 `角色权限`
7. `entry_consistency` 显示为 `多入口一致性`
8. `pairwise` 显示为 `组合测试`
9. `crud_lifecycle` 显示为 `数据生命周期`
10. `idempotency` 显示为 `幂等重试`
11. `data_consistency` 显示为 `数据一致性`
12. `calculation_precision` 显示为 `计算精度`
13. `batch_partial_failure` 显示为 `批处理`
14. `observability_audit` 显示为 `审计日志`
15. `pass` 显示为 `通过`
16. `conditional_pass` 显示为 `有条件通过`
17. `fail` 显示为 `不通过`

### 测试设计方法库补充

`testcase-designer` 在判断功能点适用性时，除等价类、边界值、决策表、状态转换、角色权限、多入口一致性、空值默认值、异常容错、时间时序和 UI 展示外，还必须识别以下方法是否适用：

1. `pairwise`：多条件组合较多但全量组合会爆炸时，覆盖两两组合和高风险组合。
2. `crud_lifecycle`：配置对象、任务、Campaign、Adset、Creative 等存在创建、查看、编辑、删除、禁用、恢复或复制时，覆盖数据生命周期。
3. `idempotency`：批单同步、定时任务、接口回调、告警发送或重复点击可能重复触发时，覆盖幂等、重试和去重。
4. `data_consistency`：存在上游到下游、列表到详情、配置到生效结果等链路时，覆盖数据一致性和跨层级联动。
5. `calculation_precision`：涉及金额、预算、百分比、eCPM、DVR、汇率、比例或数量计算时，覆盖小数、0、大值、舍入、截断和单位换算。
6. `batch_partial_failure`：存在批量同步、批量创建、批量配置或批量发送时，覆盖全部成功、部分成功部分失败、失败明细和可重试范围。
7. `observability_audit`：存在自动执行、系统关停、审批、告警、同步或配置生效时，覆盖日志、告警记录、审计字段和追踪关联。

这些方法只能在功能点确实具备适用条件时展开，不能为了凑数量机械生成专项用例。

### 字段到导图层级映射

1. 根节点
   - 取自 `project`
2. `统计信息`
   - 导出阶段聚合生成
3. `模块`
   - 取自 `module`
4. `场景`
   - 取自 `scene`
5. `功能点`
   - 取自 `fp_id + "：" + title`
6. `CaseID-标题`
   - 取自 `case_id + "-" + title`
7. `优先级：...｜类型：...`
   - 由 `priority + "｜" + category` 组合生成
8. `预期摘要：...`
   - 取自 `expected_results` 的压缩摘要
9. `操作步骤`
   - 取自 `steps`
10. `步骤1...`
   - 取自逐条步骤

### 单个用例节点完整结构

必须是：

```text
CaseID-标题
  ├─ 优先级：P1｜类型：功能
  ├─ 预期摘要：...
  └─ 操作步骤
      ├─ 步骤1：...
      ├─ 步骤2：...
      └─ 步骤3：...
```

### XMindMark 书写示例

必须写成这种标准列表树：

```text
项目名测试用例
- 统计信息
  - 功能点总数：9
  - 用例总数：28
  - P0 数量：9
  - 审查结论：有条件通过
- 模块：后端过滤
  - 场景：Publisher 全局 HTML Keyword 过滤
    - FP-001：支持 HTML keyword 过滤规则
      - TC-001-001-新增规则正常保存
        - 优先级：P0｜类型：功能
        - 预期摘要：规则保存成功且列表正确展示
        - 操作步骤
          - 步骤1：进入功能页面
          - 步骤2：填写合法内容
          - 步骤3：点击保存
```

下面这种写法禁止使用：

```text
- 项目名测试用例
  - 统计信息
    - 功能点总数：9
```

### 统计信息节点要求

根节点下必须固定有一个 `统计信息` 节点，至少包含：

1. `功能点总数`
2. `用例总数`
3. `P0 数量`
4. `P1 数量`
5. `P2 数量`
6. `P3 数量`
7. `审查结论`

### 模块与场景划分规则

1. 必须先按 `source_order` 保持需求文档原始分类和章节顺序
2. 在原文顺序内按 `module` 分组
3. 每个 `module` 下再按 `scene` 分组
4. 不能把所有功能点直接平铺在根节点下
5. 不能跳过 `scene` 层直接从 `module` 进入 `功能点`

### 禁止事项

1. 不要再额外拆出单独的 `标题` 包装层，导致层级过深
2. 不要把所有信息平铺在同一层
3. 不要把所有信息塞进一个长文本节点
4. 不要继续沿用 7 层以上的深树结构
5. 不要用 `# / ## / ###` 标题层级语法表达 XMind 主树
6. 不要混用“纯缩进文本”和“标准 Markdown 列表”
7. 不要把根节点写成列表项
8. 不要使用除 2 空格之外的其他缩进宽度
9. 不要在主树中插入空行、注释和说明文字
