# 测试用例生成模块优化 Spec

## Why

当前用例生成模块（testcase-designer）存在"机械化"问题：AI 按清单逐项打勾生成用例，缺乏业务理解深度、场景代入感和跨模块关联分析能力，导致产出的用例格式正确但缺乏针对性和实战价值。

## What Changes

- 在 `requirement-analyzer` 中新增"业务上下文摘要"阶段，在功能点拆分前先理解业务全貌
- 改造 `testcase-designer` 的生成策略，从"功能点驱动"升级为"场景驱动 + 功能点驱动"双模式
- 新增"分层生成"机制：先生成核心场景（少量高质量），再按需展开边界/异常
- 强制要求 AI 生成具体测试数据，而非"输入有效数据"等空泛描述
- 新增跨功能点关联分析能力，识别功能间的依赖和影响
- 优化 `quality-reviewer` 审查维度，增加"场景深度"和"数据具体性"检查

## Impact

- Affected specs: 无（首次优化）
- Affected code:
  - `backend/claw_5skill_final/skills/requirement-analyzer/SKILL.md` — 新增业务上下文摘要
  - `backend/claw_5skill_final/skills/testcase-designer/SKILL.md` — 生成策略重构
  - `backend/claw_5skill_final/skills/quality-reviewer/SKILL.md` — 新增审查维度
  - `backend/claw_5skill_final/schemas/function_points.template.yaml` — 新增业务上下文字段
  - `backend/claw_5skill_final/schemas/testcase_package.template.yaml` — 新增场景化字段
  - `backend/app/tasks/case_generation.py` — 适配新的 prompt 结构和中间产物

## ADDED Requirements

### Requirement: 业务上下文摘要（Business Context Summary）

`requirement-analyzer` 在功能点拆分前，必须先产出一份"业务上下文摘要"，包含：
1. 系统/产品定位（这个系统是做什么的）
2. 目标用户角色（谁在用）
3. 核心业务流程（主要用来做什么）
4. 关键业务约束（必须遵守的规则）

#### Scenario: 正常需求文档
- **WHEN** 用户提供一份完整的 PRD 文档
- **THEN** `requirement-analyzer` 先输出 `BusinessContext.yaml`，再进入功能点拆分
- **AND** `testcase-designer` 在生成用例时读取该摘要，确保用例符合业务定位

### Requirement: 场景驱动生成（Scenario-Driven Generation）

`testcase-designer` 在生成用例时，除了按功能点逐条生成外，还需识别"端到端业务场景"，将多个功能点串联成完整用户路径。

#### Scenario: 登录 + 操作 + 审批场景
- **WHEN** 功能点包含"登录"、"提交申请"、"审批"等多个关联功能点
- **THEN** 除了每个功能点的独立用例外，额外生成"端到端场景用例"
- **AND** 场景用例包含完整的用户路径、数据流转和跨模块验证点

### Requirement: 分层生成机制（Layered Generation）

用例生成改为两阶段：
1. **第一阶段**：只生成核心场景用例（每个功能点 1-2 条高价值用例）
2. **第二阶段**：根据质量审查结果或用户指令，按需展开边界/异常/回归用例

#### Scenario: 默认分层生成
- **WHEN** 用户未指定生成模式
- **THEN** 系统默认执行两阶段生成
- **AND** 第一阶段产出后暂停，展示核心用例摘要供用户确认
- **AND** 用户确认后继续第二阶段展开

### Requirement: 具体测试数据生成（Concrete Test Data）

每条用例的 `test_data` 和 `steps` 中必须包含具体的数据值，而非空泛描述。

#### Scenario: 表单提交场景
- **WHEN** 功能点涉及表单输入（如用户名、手机号、日期）
- **THEN** `test_data` 必须包含具体值（如 `test_user_01`、`13800138001`、`2026-04-01`）
- **AND** `steps` 中必须引用这些具体数据值
- **AND** `expected_results` 中必须包含可观察的具体结果

### Requirement: 跨功能点关联分析（Cross-FP Impact Analysis）

`testcase-designer` 在生成用例前，先分析功能点之间的依赖关系和影响链路。

#### Scenario: 数据删除影响关联
- **WHEN** 功能点 A 是"创建用户"，功能点 B 是"删除用户"，功能点 C 是"用户订单列表"
- **THEN** 生成"删除用户后，订单列表展示"的关联用例
- **AND** 关联用例标记 `cross_fp_dependencies` 字段

### Requirement: 增强质量审查维度

`quality-reviewer` 新增以下审查维度：
1. **场景深度**：用例是否有足够的业务场景代入感，而非纯功能验证
2. **数据具体性**：测试数据是否具体可执行，而非"输入有效数据"
3. **关联覆盖**：跨功能点的关联场景是否被识别和覆盖
4. **用户路径完整性**：端到端场景是否覆盖了关键用户路径

#### Scenario: 审查发现空泛用例
- **WHEN** 用例的 `test_data` 为空泛描述（如"有效数据"）
- **THEN** 审查结论不能为 `pass`
- **AND** 在 `findings` 中明确指出哪些用例数据不够具体
- **AND** 生成 `repair_tasks` 要求补充具体数据

## MODIFIED Requirements

### Requirement: FunctionPoints 模板扩展

`FunctionPoints.yaml` 每个功能点新增以下可选字段：
1. `business_context` — 该功能点所属的业务场景描述
2. `related_fps` — 关联功能点列表（用于跨 FP 分析）
3. `user_journey_step` — 在用户旅程中的位置（如"登录后第一步"）

### Requirement: TestcasePackage 模板扩展

`TestcasePackage.yaml` 每条用例新增以下字段：
1. `scenario_type` — 场景类型：`standalone`（独立）/ `e2e`（端到端）/ `cross_fp`（跨功能点）
2. `cross_fp_dependencies` — 跨功能点依赖列表（仅 `cross_fp` 类型使用）
3. `user_persona` — 执行该用例的用户角色画像描述

### Requirement: 生成策略从纯清单驱动改为场景优先

`testcase-designer` 的"生成顺序"章节重构：
1. 先识别端到端业务场景，生成场景用例
2. 再按功能点生成独立用例（正常→边界→异常）
3. 最后补充跨功能点关联用例
4. 全程贯穿"具体数据代入"原则
