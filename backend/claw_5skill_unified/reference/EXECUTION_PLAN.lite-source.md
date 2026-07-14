# 执行计划

## 模式定义

### full

适用：

- 用户给出 PRD / Markdown / 图片，希望从需求直接生成测试用例和导图。

执行顺序：

1. `testcase-orchestrator`
2. `requirement-analyzer`
3. `testcase-designer`
4. `quality-reviewer`
5. `artifact-exporter`

### generate_only

适用：

- 用户已经提供 `FunctionPoints`，只需要生成测试用例。

执行顺序：

1. `testcase-orchestrator`
2. `testcase-designer`
3. `quality-reviewer`
4. `artifact-exporter`

### review_only

适用：

- 用户已有测试用例，只需要质量检查。

执行顺序：

1. `testcase-orchestrator`
2. `quality-reviewer`

### delta

适用：

- 用户提供旧需求和新需求，要求增量更新。

执行顺序：

1. `testcase-orchestrator`
2. `requirement-analyzer`
3. `testcase-designer`
4. `quality-reviewer`
5. `artifact-exporter`

## 所有模式共通要求

1. 每一步必须显式输出结构化结果。
2. 下一步必须读取上一步产物。
3. 若信息不足，先标记缺口，再输出部分结果，不允许直接跳步。
4. 所有推断必须标记来源：
   - `text`
   - `image`
   - `inferred`
5. 最终导图导出时，`xmindmark` 第一行必须是根节点纯文本，不带 `- `。
6. 从第二行开始，子节点必须使用标准 Markdown 列表语法。
7. 根节点直属子节点顶格写 `- `，更深层统一增加 2 个空格缩进。
8. 主树内部禁止空行、注释、说明文字和 `# / ## / ###` 标题语法。
9. 最终 `.xmind` 必须通过项目共用的确定性 exporter 从 `.xmindmark` 生成。
10. exporter 失败时流程必须中止，不得交付空白或无法解析的 `.xmind`。
11. 业务阶段不得绕过共用 exporter 自行拼装 `.xmind`。
12. 模块、场景和最终 XMind 顺序必须遵循需求文档原始分类和章节顺序。
13. `requirement-analyzer` 必须输出 `source_order`，后续 Skill 必须继承并按它排序。

## requirement-analyzer 内部顺序

虽然 `requirement-analyzer` 是单个 Skill，但它内部必须按以下顺序执行：

1. `提取图片链接并下载`
   - 先提取 Markdown 正文中的图片链接
   - 下载图片到本地可读取路径
   - 下载失败项进入 `待确认清单`
2. `图片优先扫描`
   - 再查看图片、界面截图、流程图
   - 记录可见入口、按钮、字段、标签、弹窗、状态
3. `正文解析`
   - 再读取正文、表格、规则说明
   - 提取业务规则、约束、角色、时序、异常
4. `图文对齐`
   - 对齐图片和正文
   - 识别冲突、补充遗漏、标记待确认项
5. `功能点综合输出`
   - 最后输出 `FunctionPoints`

目的：

1. 避免图片链接被直接当成“已识图内容”
2. 避免图片只被当作最后补充
3. 避免多入口、多状态、多控件信息遗漏
4. 让界面证据参与功能点主结构，而不是事后修补
