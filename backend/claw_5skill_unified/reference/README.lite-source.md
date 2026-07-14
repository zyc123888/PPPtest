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
3. 如果图片是链接，必须先下载，否则模型无法真正识图。
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

为了降低低理解能力模型跑偏的风险，必须额外遵守下面规则：

1. 默认对外只交付一个 `.xmind` 文件。
2. 不要在最终回复里默认枚举内部中间文件。
3. `testcase-designer` 不能回头重读原始需求文档和原始图片。
4. `quality-reviewer` 不能省略。
5. `artifact-exporter` 必须把展示层文案转成中文，不要把内部英文枚举原样暴露到导图。
6. 如果规则冲突，以“最终只交付同名 `.xmind`”为最高优先级。

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

## 不可跳步门禁

必须按下面门禁执行，缺少产物时流程中止：

1. 未产出 `EvidenceTrace.yaml`，禁止进入 `testcase-designer`
2. 未产出 `FunctionPoints.yaml`，禁止进入 `testcase-designer`
3. 未产出 `TestcasePackage.yaml`，禁止进入 `quality-reviewer`
4. 未产出 `ReviewReport.yaml`，禁止进入 `artifact-exporter`
5. 如果需求文档中存在图片链接，但 `EvidenceTrace.yaml` 未记录图片下载与识图结果，流程中止
6. 如果存在下载失败图片，但未进入 `待确认清单`，流程中止

## 识图定义

为避免“看正文替代识图”的偷懒行为，必须强制采用下面定义：

1. 识图是指：先下载图片，再对实际图片内容做视觉分析
2. 不能用正文中的图片描述替代识图
3. 不能因为正文已经详细，就跳过图片分析
4. 图片分析失败时，必须进入 `待确认清单`

## 执行证明摘要

最终内部必须能生成一段执行证明摘要，必须包含：

1. 发现图片链接数量
2. 下载成功数量
3. 下载失败数量
4. 图片识别证据数量
5. 来自正文的功能点数量
6. 来自图片补充的功能点数量
7. 待确认项数量

## XMind 转换工具约束

1. 必须先生成并校验 `.xmindmark`。
2. 再调用项目共用的确定性 exporter 生成 `.xmind`。
3. exporter 失败或实际文件无法解析时必须中止交付。
4. 业务 Skill 不得绕过共用 exporter 自行拼装 `.xmind`。

## XMind 导出约束

1. `xmindmark` 第一行必须是根节点纯文本，不带 `- `。
2. 从第二行开始，所有子节点都必须使用标准 Markdown 列表语法。
3. 根节点的直属子节点必须顶格写 `- `，禁止额外缩进。
4. 更深层子节点必须统一比父节点多 2 个空格缩进，禁止 4 空格、Tab 或混合缩进。
5. 主树内部禁止出现空行、说明文字、注释文本、编号列表或普通段落。
6. 不要使用 Markdown 标题层级语法去表达导图主结构。
7. 导图层级保持浅层稳定结构：
   - 项目
   - 统计信息
   - 模块
   - 场景
   - 功能点
   - `CaseID-标题`
   - `优先级：...｜类型：...`
   - `预期摘要：...`
   - `操作步骤`
   - `步骤1 / 步骤2 / 步骤3 ...`
8. 最终 `.xmind` 文件名必须与需求文档同名，只替换扩展名。
9. `.xmindmark` 导图源文件应与 `.xmind` 使用同一基名，但默认不对外交付。
10. `模块`、`场景`、`功能点` 的展示顺序必须按 `source_order` 保留需求文档原始顺序。
11. 如果需求文档已有章节号或分类标题，`source_order` 应使用原章节号或原文出现序号。

唯一合法示例：

```text
项目名测试用例
- 统计信息
  - 功能点总数：9
- 模块：示例模块
  - 场景：示例场景
    - FP-001：功能点名称
      - TC-001-001-功能正常流程
        - 优先级：P1｜类型：功能
        - 预期摘要：结果正确
        - 操作步骤
          - 步骤1：进入页面
```

## 展示层中文化规则

最终 `.xmind` 中展示的文案必须使用中文。

必须包含以下映射：

1. `functional` 显示为 `功能`
2. `boundary` 显示为 `边界`
3. `negative` 显示为 `异常`
4. `decision_table` 显示为 `决策表`
5. `state_transition` 显示为 `状态转换`
6. `role_matrix` 显示为 `角色权限`
7. `entry_consistency` 显示为 `多入口一致性`
8. `pass` 显示为 `通过`
9. `conditional_pass` 显示为 `有条件通过`
10. `fail` 显示为 `不通过`

示例：

- 输入：`ADX Ad Block 支持HTML keyword 屏蔽.md`
- 输出：`ADX Ad Block 支持HTML keyword 屏蔽.xmindmark`
- 输出：`ADX Ad Block 支持HTML keyword 屏蔽.xmind`
