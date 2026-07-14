# 用例生成2统一 Skill 方案迁移计划

## 1. 背景和目标

参考目录：

`/Users/zhangyongcheng/Desktop/zyctest/claw_5skill_unified/`

该目录把原 `claw_5skill_final` 和 `claw_5skill_final_v2` 合并为一套统一 Skill 流水线，通过 `mode` 区分两种执行策略：

| unified mode | 含义 | 当前项目对应 |
|---|---|---|
| `lite` | 快速生成可读 XMind，流程短、产物少、成本低 | 当前 `pipeline_mode=clone` |
| `trusted` | 可信追溯模式，带 source 索引、门禁、审计和导图结构校验 | 当前 `pipeline_mode=trusted_v2` |

本计划目标不是推翻当前 `用例生成2`，而是在现有双模式基础上吸收 unified 方案的优点：

1. 模式命名更清晰：从 `clone/trusted_v2` 逐步演进为 `lite/trusted`。
2. Skill 和 schema 分层更清晰：`schemas/lite` 与 `schemas/trusted` 分开，避免模板混用。
3. trusted 模式补齐 source 级证明链：`SourceManifest`、`FinalDeliveryGate`、XMind 结构一致性校验。
4. 保留当前已做的组合门禁：后端确定性校验 + 模型语义 handoff review，不退回纯模型自评，也不退回纯结构校验。
5. 最终形成可分享、可解释、可回归验证的用例生成方案。

## 2. 当前项目现状

当前 `用例生成2` 已具备统一方案的部分基础。

| 能力 | 当前状态 | 证据 |
|---|---|---|
| 前端模式选择 | 已有 `复刻模式 / 可信改进模式` | `frontend/src/views/case/generator2/index.vue` |
| 后端双流程调度 | 已有 `clone / trusted_v2` 分支 | `backend/app/tasks/case_generation_v2.py` |
| trusted 范围索引 | 已有 `scope_index` | `case_generation_v2.py` |
| trusted 三段门禁 | 已有 `scope_index_gate / requirement_gate / testcase_gate` | `case_generation_v2.py` |
| 组合门禁 | 已接入确定性校验 + 模型 handoff review | `case_generation_v2.py` |
| schema 分层 | 未完成，当前仍主要从扁平 `schemas/` 读模板 | `_load_skill_template()` |
| SourceManifest | 未完成 | 无独立产物 |
| FinalDeliveryGate | 未完成 | 无导出后结构审计产物 |
| trusted XMind SRC 层级强约束 | 部分完成，未形成最终交付 gate | 需要补齐 |

## 3. 设计原则

1. 不破坏原 `用例生成`。
2. `用例生成2` 保持双模式：轻量模式服务速度，可信模式服务可解释和审计。
3. 旧任务兼容：历史 `pipeline_mode=clone/trusted_v2` 继续可读、可重跑。
4. 新命名逐步迁移：内部支持 `lite/trusted`，前端可先显示新名，后端保留旧值映射。
5. 不把 `trusted-gate` 改成纯模型门禁。当前组合门禁更适合项目实际问题。
6. 所有新增可信产物必须落库为 V2 artifact，不影响 V1 表和 V1 报告目录。
7. 任何模型失败不能静默降级为“看起来成功”的占位产物。
8. `.xmind` 交付必须有结构一致性校验，不只检查文件是否存在。

## 4. 推荐最终流程

### 4.1 lite 模式

目标：快速生成一版可读 XMind。

```text
orchestrate
-> evidence_trace
-> requirement
-> testcase
-> quality_review
-> export
```

默认产物：

```text
EvidenceTrace.yaml/json
FunctionPoints.yaml/json
TestcasePackage.yaml/json
ReviewReport.yaml/json
DeliverySummary.md
需求文档同名.xmindmark
需求文档同名.xmind
```

前端显示建议：

`轻量模式：快速生成 XMind`

### 4.2 trusted 模式

目标：回答“测了什么、为什么测、覆盖了没有、有没有过度生成、导图是否与结构化产物一致”。

```text
orchestrate
-> collect
-> image_analysis
-> evidence_trace
-> source_manifest
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

默认产物：

```text
SourceManifest.yaml/json
EvidenceTrace.yaml/json
ScopeIndex.yaml/json
ScopeIndexGateReport.yaml/json
FunctionPoints.yaml/json
RequirementGateReport.yaml/json
TestcasePackage.yaml/json
TestcaseGateReport.yaml/json
ReviewReport.yaml/json
DeliverySummary.md
需求文档同名.xmindmark
需求文档同名.xmind
FinalDeliveryGateReport.yaml/json
```

前端显示建议：

`可信模式：按 source 追溯、预算和门禁生成`

## 5. 分阶段实施计划

### Phase 0：冻结现状和建立对照基线

优先级：P0

目标：避免迁移时无法判断是变好了还是变差了。

工作项：

1. 固定 2 到 3 份代表性需求文档作为回归样本。
2. 对每份样本分别记录当前 `clone` 和 `trusted_v2` 的输出。
3. 保存关键指标：
   - 直接测试对象数
   - 功能点数
   - 用例数
   - P0/P1/P2/P3 分布
   - 待确认数量
   - 重复用例数量
   - XMind 是否可打开
   - 任务耗时
   - 失败阶段和错误信息
4. 形成 `before` 快照报告。

建议文件：

`docs/case_generator2_unified_baseline_report.md`

验收标准：

1. 至少 2 份样本文档完成旧流程基线记录。
2. 每份样本有可下载 XMind 和 review 报告。
3. 指标可复算，不只写人工描述。

### Phase 1：引入 unified 规则目录，但不切流量

优先级：P0

目标：先把规则资产放进项目，暂不改变运行逻辑。

工作项：

1. 将 `claw_5skill_unified` 复制到后端规则目录，例如：
   - `backend/claw_5skill_unified/`
2. Dockerfile 增加复制 unified 目录。
3. docker-compose 增加只读挂载。
4. 新增配置项：
   - `CASE_GENERATION_UNIFIED_RULES_DIR=claw_5skill_unified`
5. 保持当前 `CASE_GENERATION_RULES_DIR=claw_5skill_final` 不变。
6. 增加一个后端自检函数，确认 unified 目录存在且关键文件完整。

不做：

1. 不改默认生成模式。
2. 不改历史任务重跑逻辑。
3. 不让生产流程直接读取 unified。

验收标准：

1. 容器内存在 `/app/claw_5skill_unified/README.md`。
2. 容器内存在 `schemas/lite` 和 `schemas/trusted`。
3. 后端启动不受影响。
4. 原 `clone` 和 `trusted_v2` 流程仍可创建任务。

### Phase 2：mode 兼容层

优先级：P0

目标：把内部模式统一为 `lite/trusted`，同时兼容旧任务。

工作项：

1. 后端新增 mode normalize：

```text
clone -> lite
trusted_v2 -> trusted
lite -> lite
trusted -> trusted
```

2. `CaseGenerationV2JobCreate.pipeline_mode` 允许：
   - `clone`
   - `trusted_v2`
   - `lite`
   - `trusted`
3. 新任务前端默认仍可先提交 `clone`，但后端内部统一存储 `effective_mode`。
4. 最近任务和结果详情显示新中文名：
   - `lite/clone` 显示为 `轻量模式`
   - `trusted/trusted_v2` 显示为 `可信模式`
5. 重跑历史任务时保持原始 `pipeline_mode`，但执行时走 normalize 后的模式。

验收标准：

1. 旧任务 `clone` 可正常重跑。
2. 旧任务 `trusted_v2` 可正常重跑。
3. 新建 `lite` 任务可进入轻量流程。
4. 新建 `trusted` 任务可进入可信流程。
5. 非法 mode 返回 400/422。

### Phase 3：schema 按 mode 分层加载

优先级：P0

目标：避免 lite 和 trusted 共用模板导致字段污染。

工作项：

1. 改造 `_load_skill_template()`，增加 `mode` 参数。
2. lite 模式读取：

```text
claw_5skill_unified/schemas/lite/*.template.*
```

3. trusted 模式读取：

```text
claw_5skill_unified/schemas/trusted/*.template.*
```

4. `_load_claw_skill_context()` 支持读取 unified skill 文档。
5. 当前老目录作为 fallback。
6. 测试覆盖模板加载路径。

验收标准：

1. lite 模式不会读取 trusted-only 模板，例如 `scope_index.template.yaml`。
2. trusted 模式能读取 `source_manifest / scope_index / gate_report` 模板。
3. 缺少模板时任务失败并提示具体缺失文件，不静默使用空 schema。
4. 单测验证不同 mode 的模板路径。

### Phase 4：trusted 增加 SourceManifest

优先级：P1

目标：在 evidence 和 scope_index 之间建立 expected source list 的来源基础。

工作项：

1. 新增阶段：

```text
source_manifest
```

2. 新增产物：

```text
SourceManifest.yaml/json
```

3. SourceManifest 至少包含：
   - source block id
   - source order
   - title path
   - source type
   - raw location
   - whether direct testcase candidate
   - linked image/table/AC references
4. `scope_index` 必须基于 SourceManifest 识别 direct source。
5. `scope_index_gate` 校验 SourceManifest 中所有 source block 是否被分类。

验收标准：

1. trusted 任务必产出 SourceManifest。
2. SourceManifest 中每个 source block 有稳定 ID。
3. ScopeIndex 中的 direct source 能追溯到 SourceManifest。
4. 未分类 source 会导致 gate 失败或进入风险清单。

### Phase 5：trusted 补 FinalDeliveryGate

优先级：P1

目标：导出后校验交付物，不只校验中间产物。

工作项：

1. 新增阶段：

```text
final_delivery_gate
```

2. 新增产物：

```text
FinalDeliveryGateReport.yaml/json
```

3. 校验项：
   - `.xmindmark` 存在且格式合法。
   - `.xmind` 存在且可解析。
   - trusted XMind 层级为 `模块 -> 场景 -> SRC -> FP -> TC`。
   - SRC 节点数量与 expected source list 一致。
   - 无未知 SRC。
   - 无重复 SRC。
   - 用例统计与 TestcasePackage 一致。
   - P0/P1/P2/P3 统计一致。
4. gate 失败时任务状态建议：
   - 结构性失败：任务失败，不交付 XMind。
   - 轻微统计差异：任务条件通过，但明确提示。

验收标准：

1. trusted 成功任务必须有 FinalDeliveryGateReport。
2. 人工篡改 xmindmark 后 gate 能识别缺失/重复/层级错误。
3. 前端结果详情能展示 final delivery gate 结论。
4. gate 未通过时不会把 XMind 当成可信交付物。

### Phase 6：前端分享和展示优化

优先级：P1

目标：让结果可分享，而不是只能开发者读 artifact。

工作项：

1. 前端模式文案改为：
   - `轻量模式`
   - `可信模式`
2. 结果详情显示统一摘要：
   - 模式
   - source 数
   - 功能点数
   - 用例数
   - gate 结论
   - final delivery gate 结论
3. 增加“复制分享摘要”按钮。
4. 分享摘要建议格式：

```text
任务：xxx
模式：可信模式
结果：通过 / 有条件通过 / 失败
直接测试对象：N
功能点：N
用例：N
待确认：N
超预算 source：N
导出：XMind 已通过交付校验
```

5. 下载区按模式展示：
   - lite：XMind、ReviewReport、DeliverySummary
   - trusted：XMind、ScopeIndex、GateReports、ReviewReport、DeliverySummary
6. 任务列表短文案控制长度：
   - `31 条用例 · 13 个对象 · 通过`

验收标准：

1. 用户无需打开 JSON，也能理解结果是否可信。
2. 分享摘要复制后可直接发给他人。
3. 任务列表文字不溢出。
4. lite 不展示 trusted-only 指标。
5. trusted 显示 gate 和 final delivery gate。

### Phase 7：回归测试和对比报告

优先级：P0

目标：证明迁移没有只是在“改名”，而是真正可用。

工作项：

1. 对 Phase 0 的样本文档分别跑：
   - lite
   - trusted
2. 输出对比报告：
   - 功能点数量
   - 用例数量
   - source 覆盖率
   - gate 结论
   - XMind 是否可打开
   - 任务耗时
   - 失败率
3. 补后端单测：
   - mode normalize
   - schema mode loading
   - SourceManifest gate
   - FinalDeliveryGate
4. 补前端手工验收清单。

验收标准：

1. `pytest backend/tests/test_platform_api.py -q` 通过。
2. `npm --prefix frontend run build` 通过。
3. Docker 重建并健康：
   - backend healthy
   - frontend healthy
   - worker running
4. 两个样本文档均能完成 lite。
5. 至少一个样本文档能完成 trusted 并通过 final delivery gate。

## 6. 优先级总表

| 优先级 | 项目 | 原因 |
|---|---|---|
| P0 | Phase 0 基线 | 没有基线就无法判断迁移收益 |
| P0 | Phase 1 引入 unified 目录 | 低风险，先准备规则资产 |
| P0 | Phase 2 mode 兼容层 | 避免历史任务断裂 |
| P0 | Phase 3 schema 分层加载 | 防止 lite/trusted 字段污染 |
| P0 | Phase 7 回归测试 | 证明可上线 |
| P1 | Phase 4 SourceManifest | 提升 trusted 可信链路 |
| P1 | Phase 5 FinalDeliveryGate | 防止导出结果和结构化产物不一致 |
| P1 | Phase 6 前端分享展示 | 让结果可读、可分享 |
| P2 | 长文档 source 并行重跑增强 | 等 trusted 基础稳定后再做 |
| P2 | 独立多 agent 调度 | 最后考虑，不作为当前稳定性前提 |

## 7. 分享策略

### 7.1 给业务/测试同学分享

只展示：

1. 模式选择说明。
2. 用例数量来源。
3. gate 结论。
4. 待确认项。
5. XMind 下载。

不展示：

1. 模型 prompt。
2. 内部 retry 细节。
3. 原始 JSON 全量内容。

### 7.2 给研发同学分享

展示：

1. mode 到 pipeline 的映射。
2. artifact 列表。
3. gate 规则。
4. 失败处理策略。
5. 回归样本和测试命令。

### 7.3 给管理者分享

展示：

1. lite 用于快速产出。
2. trusted 用于可信交付和审计。
3. 迁移后能解释用例数量和覆盖来源。
4. 风险：trusted 成本和耗时更高，需要模型稳定性。

## 8. 风险和处理

| 风险 | 影响 | 处理 |
|---|---|---|
| unified schema 与当前代码字段不一致 | 模型输出校验失败 | 先 fallback 老 schema，逐步切换 |
| trusted 阶段变多导致更慢 | 用户体验下降 | lite 保持默认快速模式 |
| final delivery gate 过严 | 成功率下降 | 先 warning，再逐步改为阻断 |
| 历史任务重跑失败 | 用户无法对比旧结果 | 保留 `clone/trusted_v2` 兼容 |
| 模型 gate 不稳定 | 偶发失败 | 保留确定性 gate，模型 gate 失败时明确错误，不伪成功 |
| XMind 解析不稳定 | 交付物不可用 | final delivery gate 必须检查 xmindmark 和 xmind |

## 9. 不建议做的事

1. 不建议直接删除 `clone/trusted_v2`。
2. 不建议直接把 unified 整包替换 `claw_5skill_final`。
3. 不建议一开始就改成独立多 agent 并行。
4. 不建议把 trusted 设为默认模式。
5. 不建议只改前端文案而不改后端 mode/schema。
6. 不建议让模型自评替代后端 gate。

## 10. 最终验收标准

功能验收：

1. `/case/generator2` 可选择 `轻量模式` 和 `可信模式`。
2. 旧任务 `clone/trusted_v2` 仍可打开和重跑。
3. lite 模式输出 XMind，流程不被 trusted gate 拖慢。
4. trusted 模式输出 SourceManifest、ScopeIndex、GateReports、FinalDeliveryGateReport。
5. trusted 模式能解释 source、FP、case、budget、gate、delivery 之间的关系。

质量验收：

1. 后端单测通过。
2. 前端 build 通过。
3. Docker 容器重建后健康。
4. 至少 2 份样本文档完成回归对比。
5. trusted 的 XMind 层级通过 final delivery gate。

分享验收：

1. 任务详情页能复制分享摘要。
2. 分享摘要包含模式、结果、数量、gate 结论和导出状态。
3. 不需要打开 JSON 就能判断结果是否可用。

上线验收：

1. 默认仍使用轻量模式。
2. 可信模式由用户主动选择。
3. 失败错误能定位到具体阶段。
4. 所有新增产物只写入 V2 独立任务，不影响原 `用例生成`。

## 11. 建议先做的最小闭环

第一轮只做以下内容：

1. 引入 `backend/claw_5skill_unified`。
2. 增加 mode normalize：`clone/lite`、`trusted_v2/trusted`。
3. schema 按 mode 分层加载。
4. 前端文案改为轻量/可信，但兼容历史值。
5. 补 FinalDeliveryGate 的最小版本，只校验 `.xmindmark` 层级和用例统计。
6. 跑一份样本文档对比。

这轮完成后，再决定是否继续做 SourceManifest 和更严格的 source 守恒。
