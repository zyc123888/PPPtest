# 对齐 claw_5skill_final —— 完整对比与改造方案（Document B）

> 对比对象：
> - 原始方案：`/Users/showard01/Desktop/zyctest/claw_5skill_final/`（5 个 SKILL.md + workflow + schemas + 总纲）
> - 当前实现：`backend/app/tasks/case_generation.py`（约 3600 行）+ `config.py`
> 状态：**仅对比与规划，未据此改动代码**（此前已做的 A2/max_tokens/有条件导出 不在本文回滚范围）

---

## 0. 总纲层面的根本偏离

原始方案《给Claw的单文件总提示词版.md》开宗明义：

- 第 3 行：「这是一个**纯 Skill 版的 AI 驱动**测试用例生成方案」
- 第 7 行：「**不依赖自定义 Python 脚本**」
- 第 8 行：「由多个 Skill 分步骤完成任务」
- 实施原则：生成与审查拆开、导图是展示层、模块顺序跟随原文

**当前实现的本质偏离**：后端用大量 Python 承担了本应由 AI/Skill 完成的"内容生产与判断"职责——造用例、改标题、改步骤、改预期、改优先级、按密度补齐、自动修复循环。这正是原始方案 testcase-designer「禁止事项」里逐条禁止的行为。

> 一句话：**后端从"编排器 + 工具层"越界成了"用例作者 + 质检员 + 返工工头"。**

---

## 1. 逐 Skill / 逐阶段对比

### 1.1 testcase-orchestrator（编排）

| 原始要求 | 后端实现 | 判定 |
|---|---|---|
| 判断模式 full/generate_only/review_only/delta | 只有隐式 full（`_build_orchestration_plan` 写死 `mode:"full"`） | ⚠️ 部分缺失（可接受，产品默认 full） |
| 门禁：缺中间产物即中止 | 有 `_gate` 门禁 | ✅ 基本对齐 |
| 强制后续 Skill 读上一步产物 | celery 串行 + 持久化中间 JSON | ✅ 对齐 |

**结论**：编排层基本对齐，问题不大。

### 1.2 requirement-analyzer（需求分析）

| 原始要求 | 后端实现 | 判定 |
|---|---|---|
| 图片先下载再多模态识图（阶段 0/1） | `_download_image_links` + `_analyze_images` | ✅ 对齐 |
| 输出 EvidenceTrace + FunctionPoints | 有 | ✅ |
| `module/scene` 沿用原文章节顺序、`source_order` 必填 | `_extract_sections` + 继承 source_order | ✅ 基本对齐 |
| 每个功能点字段（fp_id/module/.../source_distribution/test_hints…） | 有校验 | ✅ |
| **由 AI 划分需求分组** | 后端 `_assign_requirement_groups` **用 Python 生成 REQ-xx 分组** | ❌ 越界（应由分析阶段语义决定，而非 Python 按 module 机械编号） |
| 一次完整分析 | 后端**按 `_REQUIREMENT_BATCH_TEXT_LIMIT=700` 切批 + 文本截断** `_compact_sections_for_ai` | ⚠️ 工程妥协（为省 token），但会**割裂上下文**，是之前截断报错的根源 |
| priority_hint 由分析给出 | 后端 `_normalize_priority` 用关键词覆盖改写 | ❌ 越界 |

### 1.3 testcase-designer（用例设计）—— 偏离最严重区

| 原始要求（SKILL.md 行号） | 后端实现 | 判定 |
|---|---|---|
| 按测试设计方法生成（等价类/边界/决策表/状态/角色/多入口…） | 提示词里有要求，但**结果被后端模板覆盖** | ❌ 名存实亡 |
| **365「不能只堆数量，不判断场景价值」** | `_MIN_CASES_PER_FUNCTION_POINT=5` + `target_case_count_for_fp`(返回5) **强制凑数** | ❌ 直接违反 |
| **366「不能制造大量同质用例」** | `supplement_case_density` + `supplemental_variants_for_fp` **机械造同质用例** | ❌ 直接违反 |
| **361「不能写空泛步骤和预期」** | `_build_variant_steps`/`_build_variant_expected_results` **是一整套写死的模板步骤/预期** | ❌ 直接违反（自相矛盾：后端造模板，审查判模板不可执行） |
| 332「generation_basis 写 method+rationale」 | 模板用例写死 `"后端按功能点内容补齐{label}用例"` | ❌ 违反 |
| 成功标准「新人可照着执行/预期可观察」 | 后端 `_build_specific_steps`/`_ensure_specific_expected_results`/`_naturalize_case_title` **代笔重写** | ❌ 越界（应由 AI 写、reviewer 判，不该后端代笔） |
| 数量门槛 = 无（仅 reviewer 要求"≥1 条/FP"） | 后端 `_gate(... 用例密度不足)` **硬性凑不够就失败** | ❌ 凭空发明的门禁 |
| 标签/优先级规则 | `_normalize_priority`+`_RISK_PRIORITY_TERMS`、`_sanitize_expected_phrase`+`_GENERIC_EXPECTATION_REPLACEMENTS` 一堆**正则替换** | ❌ 越界 |

> 这一节是病灶核心：**density 补齐 + 模板代笔 + 凑数门禁**全部是后端发明，且违反原始明文。

### 1.4 quality-reviewer（质量审查）

| 原始要求 | 后端实现 | 判定 |
|---|---|---|
| 审查覆盖率/去重/可执行/可验证/优先级/基线/顺序 | AI 调用 + 校验 | ✅ 基本对齐 |
| 覆盖率门槛 = **每个 FP 至少 1 条** | 被 `_MIN..=5` 密度门禁覆盖 | ❌ 偏离原始口径 |
| **138「不直接重写整份用例」** | 后端 `_repair_testcase_package_with_review` **驱动整轮返工重写** | ❌ 越界 |
| 结论 pass/conditional_pass/fail **仅作展示** | 原本 `_gate(fail→禁止导出)` 硬阻断（**已被我改成有条件导出**） | ✅ 已对齐（本轮改动） |
| **原始无"修复→复审"循环** | 后端 `_TESTCASE_REPAIR_MAX_ROUNDS` 自动返工循环 | ❌ 凭空发明，且是耗时与失败的主因 |

> 关键发现：**原始流程 = 分析→设计→审查→导出，一条直线。审查只产出报告与结论，结论显示在 XMind 统计节点里，从不阻断、从不触发返工循环。** 后端的"返工循环 + 硬阻断"是双重发明。

### 1.5 artifact-exporter（导出）

| 原始要求 | 后端实现 | 判定 |
|---|---|---|
| 先生成 .xmindmark 再用 `xmindmark` CLI 转 .xmind | `_convert_xmindmark` 调 CLI | ✅ 对齐 |
| **禁止脚本手动拼 .xmind 压缩包** | 未手动拼 | ✅ 对齐 |
| 同名交付、只交付一个 .xmind | 有同名 + 清理 | ✅ 对齐 |
| 统计信息节点 / 中文化 / source_order 排序 / 固定层级 | `_build_xmindmark` Python 确定性生成 | ⚠️ **结果对齐，但实现方式偏离**（原始是 AI skill 产出 xmindmark；后端用 Python） |

> 导出层是**唯一一个"用 Python 但合理"的灰色地带**：xmindmark 格式约束极严（缩进/无空行/无标题语法/层级固定），Python 确定性生成其实**比 LLM 更稳**。详见第 3 节的取舍建议。

### 1.6 数据格式（schemas）对比

| 字段 | 原始模板（YAML） | 后端契约（JSON） | 判定 |
|---|---|---|---|
| 中间产物格式 | YAML | JSON（`response_format: json_object`） | ⚠️ 形式不同，不影响语义 |
| `test_data` | 对象数组 `{name, value}` | 字符串数组 `["..."]` | ❌ 字段形态偏离 |
| `source_refs` | 对象数组 `{source_type, doc, section, quote}` | 字符串数组 | ❌ 形态偏离 |
| `atomicity_check` | 对象 `{passed, issues}` | 字符串 | ❌ 形态偏离 |
| `steps` | `{step_no, action}` | 同 | ✅ |
| `expected_results` | 字符串数组 | 同 | ✅ |
| `review_flags` | 有 `{executable_risk, ambiguity_risk}` | 无 | ⚠️ 缺失 |

---

## 2. "本该 AI 实现、却用后端硬编码"的错误清单

按"应回归 AI / 可删除 Python"优先级排序：

| # | 后端硬编码 | 原始应由谁做 | 处置 |
|---|---|---|---|
| E1 | `supplement_case_density` / `target_case_count_for_fp` / `_MIN_CASES_PER_FUNCTION_POINT` 密度凑数 | testcase-designer（AI 按价值生成） | **删除** |
| E2 | `supplemental_variants_for_fp` / `build_supplemental_case` 变体目录 | 同上 | **删除** |
| E3 | `_build_variant_steps` / `_build_variant_expected_results` 模板步骤/预期 | AI 生成具体步骤 | **删除** |
| E4 | `_build_specific_steps` / `_build_specific_expected_results` / `_ensure_specific_expected_results` 代笔重写 | AI 生成 + reviewer 判 | **删除** |
| E5 | `_build_specific_case_title` / `_naturalize_case_title` 标题重写 | AI 命名 | **删除** |
| E6 | `_sanitize_expected_phrase` + `_GENERIC_EXPECTATION_REPLACEMENTS` 正则换词 | AI 措辞 | **删除** |
| E7 | `_repair_testcase_package_with_review` / `_extract_repair_tasks` / `_TESTCASE_REPAIR_MAX_ROUNDS` 返工循环 | 原始无此环节 | **删除** |
| E8 | 密度门禁 `_gate(... 用例密度不足)` | reviewer 仅查"≥1/FP" | **删除/改为软 finding** |
| E9 | `_normalize_priority` + `_RISK_PRIORITY_TERMS` 优先级改写 | AI 标 + reviewer 查 | **删除/弱化** |
| E10 | `_assign_requirement_groups` Python 分组 | 分析阶段语义产出 | **改为 AI 产出，后端只兜底** |
| E11 | `_compact_sections_for_ai` 截断 + `_build_requirement_section_batches` 切批 | 原始一次完整分析 | **弱化/提阈值**（保留批处理但减少割裂） |
| E12 | 反模板正则门禁 `_GENERIC_*_PATTERNS` 作为硬 gate | reviewer 的 finding | **降级为软提示** |

**应保留的合理后端**（基础设施，非内容生产）：
- celery 任务编排、DB 持久化、阶段进度
- 图片下载（I/O）、`xmindmark` CLI 转换（规范要求）
- 模型调用封装、JSON 解析/截断重试、取消/超时
- `_build_xmindmark` 确定性导出（见第 3 节取舍）

---

## 3. 整体改造方案（以 claw_5skill_final 为准，能 AI 就 AI，少走代码）

### 设计原则
1. **后端只做编排 + 工具 + 持久化**，不做内容生产与改写。
2. 用例的"数量、措辞、步骤、优先级、标题"全部交回 AI，由 prompt/SKILL 约束、由 reviewer 评判。
3. 数量唯一硬规则回归原始：**每个 FP ≥ 1 条**。
4. 审查只产出报告与结论，**永远导出**，结论显示在 XMind 统计节点（已对齐）。
5. 格式以 schemas 模板为准。

### 阶段划分（建议按序，每阶段可独立验证、可回滚）

**Phase 1 — 拆除越界 Python（净减代码，风险中）**
- 删除 E1–E8、E12 对应函数与调用（testcase-designer 后处理、density、repair 循环、密度门禁、反模板硬门禁）。
- `_build_testcase_package` 收敛为：调 AI → 轻量结构校验（字段齐全 + ≥1/FP 覆盖）→ 全局去重 + 重编号（保留我已加的 `_dedupe_cases_global`/`_renumber_cases_global`）。
- 主流程移除 repair 段，审查后直接导出（有条件导出已就位）。
- **影响**：用例数量会下降到"AI 按价值生成"的真实量（不再硬凑 5 条/FP）；模板废话用例消失；critical「不可执行」finding 从根上减少。**这是产出变化，需你确认可接受。**

**Phase 2 — 把要求写进 Prompt/SKILL（纯提示词，风险低）**
- 确认后端注入的是**最新原始** SKILL.md + schema（核对 `CASE_GENERATION_RULES_DIR` 指向的 `backend/claw_5skill_final` 与桌面原始版一致；不一致则同步）。
- 把原 testcase-designer 的「方法库/场景矩阵/禁止事项/成功标准」完整作为 system prompt（替代被删的后端代笔逻辑）。
- 关掉抽取/设计阶段的 `<thinking>` 以提速（审查保留）。

**Phase 3 — 格式对齐 schemas（中风险，可选）**

> 原范围（4 项字段形态）已确认属实，并经 Phase 2 覆盖度审计扩充为下列 A–E 五组。统一原则：**以原始 claw_5skill_final 的 schemas 模板为准对齐字段形态，中间产物维持 JSON**（见 §4 决策2），只对齐结构、不改落盘格式。

**A. 字段形态降维还原（原 Phase 3 四项，已确认）**
- `test_data`：字符串数组 → 对象数组 `{name, value}`（源 `testcase_package.template.yaml`）。
- `source_refs`：字符串数组 → 对象数组 `{source_type, doc, section, quote}`（源 `function_points.template.yaml`）。
- `atomicity_check`：字符串 → 对象 `{passed, issues}`（源 `function_points.template.yaml`）。
- 补 `review_flags`：`{executable_risk, ambiguity_risk}`，contract / validator / normalize / 导图渲染均需补（整字段当前缺失）。

**B. evidence_trace 形态还原（审计新增·真遗漏）**
- `image_summary`：当前是一句中文字符串 → 还原为对象 `{image_link_count, download_success_count, download_failed_count, image_observation_count, pending_confirmation_count}`。
- 补 `images[]` 缺失字段：`local_path / download_status / source_type / observed_elements / mapped_function_points / notes`；字段名回正 `source_url`→`image_url`。
- 补 `pending_confirmations[]` 缺失字段：`pending_id / source / ref_id`；字段名回正 `reason`→`message`。

**C. function_points 字段补全（审计新增·真遗漏）**
- 补源模板已定义但代码未实现的字段：`actors / entries / preconditions / inputs(对象数组 {name,type,required,constraints}) / outputs / states(对象数组 {from,event,to}) / exceptions / dependencies`。
- 顶层元数据补全：`version / project / analyzed_at / source_documents`。
- `source_order` 类型与源模板对齐（源为字符串）或在 plan 中明确统一为数字（择一，避免两边漂移）。

**D. review_report 结构约束（审计新增·真遗漏）**
- `summary` 当前仅 `release_readiness` 一个子键入契约 → 补齐源模板 8 子字段（testcase_count/duplicate_count/.../overall_score/release_readiness）。
- `coverage / method_coverage / dimension_matrix / evidence_trace / execution_proof / findings` 当前只校验「键存在」→ 按源模板补内部结构约束（findings 元素 `{finding_id, severity, type, case_id, fp_id, message, suggestion}`）。

**E. delivery_summary 生成（审计新增·真遗漏）**
- `delivery_summary.template.md` 当前**整模板未生成**。按原始方案补交付摘要产物（项目/功能点数/用例数/审查结论/内部文件清单/风险提示），或显式决议「仅以 XMind 统计节点等价替代、不单独生成」并在此记录。

**F. quality-reviewer 约束补强（审计新增·真遗漏）**
- 当前实质审查项（7 维度完整性 / 10 种方法覆盖 / 去重 / 可执行 / 可验证 / 优先级 / 基线 / **需求顺序一致性**）几乎只靠 SKILL.md 注入，内联无兜底、门禁只校验结构键存在。
- 按原始 SKILL.md 把上述检查项写进内联 constraints，并对「方法名出现≠真覆盖」「数量多≠覆盖好」等禁止事项加兜底，使审查不因注入失效而退化为空报告。

**Phase 4 — 导出层取舍（保留 Python，但需结构对齐原始总纲）**
- `_build_xmindmark` **维持 Python 确定性生成**：xmindmark 格式约束极严，Python 比 LLM 更不易违规；这与原始"导图是展示层、格式必须稳定"的目标一致。
- 若你坚持纯 AI，可改由 artifact-exporter 产出 xmindmark + 后端只跑 `_validate_xmindmark` + CLI 转换（风险更高，不推荐作为首选）。
- **结构对齐（审计新增·按原始总纲修正，仍用 Python）**：
  - **补回独立 `scene` 层** —— 当前 scene 被并入功能点节点，违反总纲:352「不能跳过 scene 层直接从 module 进入功能点」。层级应为 根→统计信息→module→scene→FP→CaseID→字段节点。
  - **category 中文映射补全** —— 当前缺 `decision_table/state_transition/role_matrix/entry_consistency` → 决策表/状态转换/角色权限/多入口一致性（总纲:258-261）。
  - CaseID 节点字段拆分（优先级｜类型 当前压成一行 → 按总纲:280 拆为独立子节点）为可选项，视层级深度权衡（注意总纲:359 控制在 5–6 层）。
  - 代码额外多插的「需求分组(requirement_group)」层：原始总纲无此层，决定保留则在此注明理由，否则随 scene 层调整一并移除。

### 工作量与代码净变化预估
- Phase 1：**净删约 600–900 行**（删模板库/density/repair），改 `_build_testcase_package` 与主流程约 80 行。
- Phase 2：几乎纯 prompt，代码 < 50 行。
- Phase 3：契约与 normalize 调整约 100–150 行。
- Phase 4：默认不动。

---

## 4. 关键决策（已拍板）

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 用例数量会下降（不再硬凑 5 条/FP，回归 AI 按价值生成 + ≥1/FP） | ✅ **接受** |
| 2 | 中间产物 JSON 还是 YAML | ✅ **全程维持 JSON**（模型 I/O + 落盘都 JSON；YAML 会丢 `json_object` 强约束、中文易解析失败、并使刚修好的截断重试失效） |
| 3 | 导出层 Python 还是 AI artifact-exporter | ✅ **维持 Python 确定性生成**（xmindmark 格式约束极严，Python 更稳） |
| 4 | 是否保留 generate_only/review_only/delta 模式 | ✅ **只做 full**（现状已是隐式 full） |

## 5. 实施进度

- **Phase 1（拆除越界 Python）**：✅ 已完成并部署。净删约 680 行（3640→2960）。删除 density 凑数、模板代笔、返工循环、模板硬门禁；用例设计收敛为「调 AI → 轻校验 → ≥1/FP 覆盖兜底 → 全局去重重编号」；审查改为单次定稿 + 有条件导出。
  - **收尾核实（审计）**：①`_MIN_CASES_PER_FUNCTION_POINT` 机制已摘除——代码除定义行(57)外**无任何引用**，density 凑数函数全删；docker-compose 的 `CASE_GEN_MIN_CASES_PER_FUNCTION_POINT` 现为**死环境变量**，建议连同模块变量一并清理。②E7「审查驱动返工重写」(`_repair_testcase_package_with_review`)**已删**；`_TESTCASE_REPAIR_MAX_ROUNDS` 现驱动的是 `case_generation.py:2302` 的「**≥1/FP 覆盖兜底**」补齐循环（只对零用例的 FP 重生成），符合原始 claw「每 FP ≥1 条」，**保留**；建议改名（如 `_COVERAGE_BACKFILL_MAX_ROUNDS`）消除「返工」误导。
- **Phase 2（纯提示词）**：✅ 已完成并部署。发现后端打包的 SKILL.md 是**增强版**（比桌面原始版多「黄金示例」+ thinking 引导，且已在每次调用注入），故 Phase 2 主体本已生效。本次精修：①testcase-designer 内联 constraints 改为忠实承载原始方法库 + 按价值生成（不堆数量），并要求 generation_basis 写 method+rationale；②审查报告改为"非通过即附带 artifact"（conditional_pass 也附带，人工可见改进建议），summary 区分 通过/有条件通过/未通过；③`<thinking>` 经评估**保留**（质量机制，Phase 1 带它跑出好结果）。
  - **覆盖度审计（逐文件对照 15 个源文件）**：Phase 2 非「只看一个文件」，三个 AI skill 各有独立 constraints+contract+门禁，但深度递减（designer 最全 / requirement 中 / reviewer 最薄），且未完整覆盖。模式系统 `generate_only/review_only/delta` 缺失——**已确认为产品决策（只做 full），不补**。其余真遗漏项（evidence_trace 形态 / function_points 字段 / review_report 结构 / delivery_summary / reviewer 约束）已并入扩充后的 Phase 3（A–F 组）。
- **Phase 3（字段形态对齐 + schema 补全，保持 JSON）**：✅ 已完成（A–F 六组）。A 还原 test_data/source_refs/atomicity_check 对象形态 + 补 review_flags；B evidence_trace image_summary 还原为对象 + images/pending 字段补全（权威 canonical 重建）；C function_points 补 actors/entries/preconditions/inputs/outputs/states/exceptions/dependencies + 顶层元数据，source_order 统一为数字；D review_report summary 补齐 8 子字段 + 各块契约结构化；E delivery_summary.md 内部产物生成；F quality-reviewer 内联 constraints 补强（7 维度/10 方法/去重/可执行/可验证/优先级/基线/顺序一致性）。统一以兼容旧形态的强转实现（_coerce_*），中间产物维持 JSON。**验证**：py_compile 通过、强转函数自检通过、后端测试 **60 全通过**。原 2 个 stale 测试（断言 Phase 1 已移除的「标题强化重写 + 模板标题硬门禁」E3/E4/E5）已重写为断言新行为（generic 标题/步骤由 AI+reviewer 把关、Python 不再代笔/硬门禁），并补充 Phase 3 字段形态断言。
- **Phase 4（导出层）**：维持 Python；**结构对齐已完成**——`_build_xmindmark` 移除非总纲的 requirement_group 层、补回独立 scene 层（根→统计信息/模块→场景→功能点→CaseID-标题→优先级｜类型·预期摘要·操作步骤→步骤），用例节点按总纲「单个用例完整结构」渲染；新增 `_METHOD_LABELS`/`_method_label` 并在统计信息出「方法分布」中文化（决策表/状态转换/角色权限/多入口一致性等）。树深 7 层 = 总纲固定结构，未超「7 层以上」红线。验证：py_compile + 样例渲染（scene 层、层级正确）+ 后端测试 60 全通过。

## 6. 待你确认（Phase 2 衍生）
- 后端打包的 `backend/claw_5skill_final/skills/*/SKILL.md` 是**增强版**（含黄金示例），桌面原始版 `zyctest/claw_5skill_final` 没有。当前后端用的是增强版（质量更好）。是否要把「黄金示例」回写到桌面原始版，统一为单一事实源？（涉及修改你的原始文件，需你同意）

## 7. 待办：黄金示例重新引入（已暂时移除）
- **现状**：三个 Skill（testcase-designer / requirement-analyzer / quality-reviewer）的「黄金示例」段落已从后端增强版 SKILL.md 中**移除**，`<thinking>` 引导保留。
- **移除原因**：原黄金示例用 markdown 扁平 bullet（`- title: …`）展示，与实际输出 schema（嵌套结构 + 完整字段）不一致，易被模型当成可模仿的输出形态，反而抬高格式出错率。
- **后续重新添加时的要求**：
  1. 示例形态须与实际输出 schema 对齐（要么用真实片段，要么显式标注「仅示意内容质量，非输出格式」）。
  2. 措辞统一——本项目中间产物全程维持 JSON（见 §4 决策2），重新引入时结尾「最终 JSON」表述需与该策略一致；勿混入 yaml。
  3. 保留「平庸 vs 专家」对照的质量锚点价值（这是当初引入黄金示例的核心目的）。
