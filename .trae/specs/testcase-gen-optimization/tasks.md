# Tasks

## 阶段一：模板与 Schema 扩展（基础层）

- [x] Task 1: 扩展 FunctionPoints 模板
  - [x] SubTask 1.1: 在 `function_points.template.yaml` 中新增 `business_context` 顶层字段（系统定位、用户角色、核心流程、关键约束）
  - [x] SubTask 1.2: 在每个功能点结构中新增 `related_fps`（关联功能点 ID 列表）和 `user_journey_step`（用户旅程位置）字段
  - [x] SubTask 1.3: 新增 `e2e_scenarios` 顶层字段，用于存放端到端场景定义

- [x] Task 2: 扩展 TestcasePackage 模板
  - [x] SubTask 2.1: 在 `testcase_package.template.yaml` 每条用例中新增 `scenario_type` 字段（standalone / e2e / cross_fp）
  - [x] SubTask 2.2: 新增 `cross_fp_dependencies` 字段（跨功能点依赖列表）
  - [x] SubTask 2.3: 新增 `user_persona` 字段（用户角色画像描述）
  - [x] SubTask 2.4: 在 `generation_metadata` 中新增 `generation_phase` 字段（标记当前是第一阶段还是第二阶段产物）

## 阶段二：Skill 规则文件改造（核心层）

- [x] Task 3: 改造 requirement-analyzer — 新增业务上下文摘要
  - [x] SubTask 3.1: 在 SKILL.md 中新增"Phase 0: 业务上下文摘要"阶段，定义在功能点拆分之前执行
  - [x] SubTask 3.2: 定义 BusinessContext 的输出结构（系统定位、用户角色、核心流程、关键约束）
  - [x] SubTask 3.3: 在图文对齐阶段后、功能点综合输出前，插入业务上下文摘要步骤
  - [x] SubTask 3.4: 在功能点输出中，要求每个功能点标注 `related_fps` 和 `user_journey_step`

- [x] Task 4: 重构 testcase-designer — 场景驱动生成策略
  - [x] SubTask 4.1: 重构"生成顺序"章节，改为"场景优先"策略：先识别端到端场景 → 再按功能点生成独立用例 → 最后补充跨 FP 关联用例
  - [x] SubTask 4.2: 新增"具体数据代入"强制规则：要求每条用例的 test_data 和 steps 包含具体数据值，列出禁止使用的空泛词汇清单
  - [x] SubTask 4.3: 新增"跨功能点关联分析"章节：在生成用例前先输出 FP 依赖关系图，再基于依赖图生成关联用例
  - [x] SubTask 4.4: 新增"分层生成"章节：定义第一阶段（核心场景）和第二阶段（展开边界/异常）的生成范围和输出格式
  - [x] SubTask 4.5: 新增"用户角色画像"要求：每条用例标注 user_persona，描述执行该用例的用户角色和背景

- [x] Task 5: 增强 quality-reviewer — 新增审查维度
  - [x] SubTask 5.1: 在 SKILL.md 中新增"场景深度"审查维度：检查用例是否有业务场景代入感，而非纯功能验证
  - [x] SubTask 5.2: 新增"数据具体性"审查维度：检查 test_data 和 steps 是否包含具体可执行的数据值
  - [x] SubTask 5.3: 新增"关联覆盖"审查维度：检查跨功能点的关联场景是否被识别和覆盖
  - [x] SubTask 5.4: 新增"用户路径完整性"审查维度：检查端到端场景是否覆盖关键用户路径
  - [x] SubTask 5.5: 更新修复判定规则：空泛数据、缺少场景代入的用例不允许通过审查

## 阶段三：代码层适配（执行层）

- [x] Task 6: 适配 case_generation.py — 支持新的 prompt 结构和中间产物
  - [x] SubTask 6.1: 在 `_build_requirement_analysis` 中适配 BusinessContext 的提取和传递
  - [x] SubTask 6.2: 在 `_build_testcase_package` 中传入业务上下文和 e2e_scenarios
  - [x] SubTask 6.3: 在 `generate_for_fps_async` 的 prompt 中传入 business_context 和 e2e_scenarios
  - [x] SubTask 6.4: 在 `_build_review_report` 中传入新增的审查维度要求
  - [x] SubTask 6.5: 在 `normalize_case` 中适配新字段（scenario_type、cross_fp_dependencies、user_persona）

## 阶段四：验证与回归

- [ ] Task 7: 端到端验证（需要实际运行系统验证）
  - [ ] SubTask 7.1: 使用一份示例 PRD 文档执行完整流程，验证 BusinessContext 正确生成
  - [ ] SubTask 7.2: 验证生成的用例包含具体测试数据（非空泛描述）
  - [ ] SubTask 7.3: 验证端到端场景用例和跨 FP 关联用例被正确生成
  - [ ] SubTask 7.4: 验证 quality-reviewer 能识别并拒绝空泛用例
  - [ ] SubTask 7.5: 验证 XMind 导出在新字段下正常工作

# Task Dependencies

- [Task 3] depends on [Task 1]（requirement-analyzer 需要了解新模板结构）
- [Task 4] depends on [Task 1, Task 2]（testcase-designer 需要了解两个模板的新字段）
- [Task 5] depends on [Task 2]（quality-reviewer 需要了解新模板字段）
- [Task 6] depends on [Task 1, Task 2, Task 3, Task 4, Task 5]（代码适配需要所有规则文件就绪）
- [Task 7] depends on [Task 6]（验证需要代码适配完成）
