# 用例生成 / 用例生成2 全量审查报告

- 审查日期：2026-07-10
- 审查范围：前端、API、Celery 任务、模型调用、Skill/Schema、门禁、产物、数据库状态、容器、测试与运行结果
- 对应页面：`/case/generator`、`/case/generator2`
- 结论性质：代码审查 + 运行数据审查 + 页面实测，不是仅依据设计文档推断

## 1. 执行结论

### 1.1 总结

当前原版“用例生成”可以作为轻量基线继续使用，但它存在任务状态恢复、质量失败仍标成功、安全、历史产物清理和维护成本等问题。

“用例生成2”增加了 source、FP、消费回执、确定性门禁、局部分片重跑和结构化产物，方向是正确的；但当前“可信模式”尚不能被认定为真正可信。它主要证明了结构完整、对象有用例、统计可对账，不能证明需求语义已被用例真实覆盖。

最严重的问题不是模型慢，也不是 Agent 数量不足，而是以下四项基础契约不成立：

1. 长阶段会被 API 误判为无活跃任务，重跑又复用同一个 job，可能造成两个执行同时修改同一任务和同一产物目录。
2. 页面显示“覆盖率 100% / 门禁通过”，但同一任务存在大量 `must_cover` 缺口和 `conditional_pass`，可信指标定义失真。
3. 可信模式默认实际执行 `lite_review`，并非真正按 source shard 生成；部分 source/FP 消费回执由后端补写，追踪关系可能只是形式成立。
4. XMind 交付没有按 Skill 约定使用 CLI；当前 CLI 冒烟测试又会生成空白 XMind，而验证器仍可能判断 roundtrip 通过。

因此，当前不建议先增加更多 Agent、更多节点或更高并发。应先修复任务所有权、门禁语义和实际交付物验证，否则并发只会放大竞态、配额失败和错误成功。

### 1.2 当前成熟度判断

| 能力 | 用例生成 V1 | 用例生成2 轻量 | 用例生成2 可信 |
|---|---|---|---|
| 基本生成可用 | 可用 | 可用，基本复用 V1 | 可运行，但稳定性不足 |
| 数量可解释 | 较弱 | 较弱 | 中等，能按 source 统计 |
| 语义覆盖可信 | 较弱 | 较弱 | 尚未达到，存在错误通过 |
| 失败恢复 | 较弱 | 较弱 | 有局部重跑，但存在竞态 |
| 历史可审计 | 较弱 | 较弱 | 产物更多，但 attempt 不可追溯 |
| Skill 一致性 | 部分一致 | 部分一致 | 文档与实际调用链不一致 |
| 可维护性 | 低 | 低 | 低，V1/V2 大量复制 |
| 建议定位 | 稳定基线 | 轻量生成 | 内测/验证，不宜宣传为强可信 |

## 2. 审查范围与证据

### 2.1 重点代码

| 模块 | 文件 | 规模/说明 |
|---|---|---|
| V1 后台流程 | `backend/app/tasks/case_generation.py` | 约 3590 行 |
| V2 后台流程 | `backend/app/tasks/case_generation_v2.py` | 约 8333 行 |
| 共用 XMind 实现 | `backend/app/tasks/case_generation_common.py` | Python ZIP 导出 |
| API 与任务状态 | `backend/app/api.py` | 创建、重跑、轮询、过期判断 |
| 数据模型/请求契约 | `backend/app/models.py`、`backend/app/schemas.py` | V1/V2 Job、Artifact、模型配置 |
| V1 前端 | `frontend/src/views/case/generator/index.vue` | 约 1475 行 |
| V2 前端 | `frontend/src/views/case/generator2/index.vue` | 约 2173 行 |
| V1 Skill | `backend/claw_5skill_final/` | 与桌面最新目录基本一致 |
| Unified Skill | `backend/claw_5skill_unified/` | lite/trusted 规则、验证器 |
| 后端测试 | `backend/tests/test_platform_api.py` | 107 项测试 |

V1 与 V2 任务文件存在约 93 个同名函数；V2 基本复制了 V1 主流程，再叠加 trusted 流程。这是后续修复反复漂移的重要原因。

### 2.2 运行证据

审查时容器均在线：backend/frontend/mysql/redis healthy，worker running，Redis 默认队列长度为 0。

最新 V2 #17：

| 指标 | 实际值 |
|---|---:|
| 总耗时 | 1331 秒 |
| 直接测试对象 | 29 |
| 功能点 | 29 |
| 用例 | 71 |
| 页面 source 覆盖率 | 100% |
| 页面 FP 消费率 | 100% |
| must_cover 缺口 | 28 |
| 弱预期 | 22 |
| 语义审查 | `conditional_pass` |
| 交付门禁 | 页面显示“通过” |

页面进一步显示 29 个 source 中有 28 个为“有缺口”。这直接证明“100%”表示的是“source 下存在用例”，不是“source 的必要语义已覆盖”。

数据库中还存在以下状态矛盾：

- V2 #15：最终 `SUCCESS`，但 `error_message` 仍为“检测到 V2 任务长时间无进展且当前无活跃执行”。
- V2 #10：最终 `SUCCESS`，但 `error_message` 为“任务已手动停止”。
- 同一历史 job 重跑后会覆盖原有耗时、摘要和产物，无法区分每次 attempt。

## 3. P0：必须优先修复

### P0-1 过期判断会误杀正常长任务，重跑存在并发写入竞态

**代码位置**

- `backend/app/api.py:596`：V1 过期判断
- `backend/app/api.py:629`：V2 过期判断
- `backend/app/api.py:650`：V2 使用固定过期阈值
- `backend/app/api.py:1986`：V2 重跑接口
- `frontend/src/views/case/generator2/index.vue:945`：5 秒轮询
- `frontend/src/views/case/generator2/index.vue:1065`：详情刷新后再次拉列表

**问题**

V2 只依据阶段更新时间判断任务是否过期，并未查询 Celery active/reserved，也没有执行心跳，却把任务改为 `FAILED`，错误文案还声称“当前无活跃执行”。模型单次调用超过约 9 分钟时，正常运行就可能被误判。

GET 详情和列表接口会执行该状态修改。前端每 5 秒调用详情和多个列表接口，因此一个读取动作可能改变任务状态。

用户点击“重跑”后，系统复用相同 job ID 和相同输出目录。旧 Celery 任务可能仍在运行，新旧任务会同时：

- 更新同一行状态、进度、摘要和错误信息；
- 删除和重建同一 job 的 artifact 记录；
- 写入同一 `job_<id>` 目录；
- 最后完成者覆盖先完成者的结果。

V1 则有相反问题：有 `started_at` 后直接跳过过期判断，worker 真正丢失时可能永久显示 RUNNING。

**影响**

- 直接解释此前多次“长时间无进展，请重跑”。
- 任务可能已经成功，但数据库仍残留停止/过期错误。
- 产物属于哪次执行不可证明。
- 重跑结果数量变化不能可靠用于 A/B 对比。

**建议**

1. GET 接口只读，不允许修改任务状态。
2. 增加 `job_attempt`（或 run）表，每次运行生成独立 `attempt_id/run_id`。
3. Celery 任务启动时取得唯一 execution token；每次状态写入使用 `WHERE active_attempt_id = token` 的 CAS 条件。
4. 模型等待期间独立写 heartbeat，不能只靠阶段切换更新时间。
5. watchdog 同时检查 heartbeat、Celery active/reserved 和 worker 存活后，才将 attempt 标为 lost。
6. 重跑创建新 attempt 和独立输出目录，不删除旧 attempt 产物。

**验收**

- 模拟 12 分钟模型调用，任务不得被 GET 误判失败。
- 旧 attempt 晚于新 attempt 返回时，不能覆盖新 attempt。
- SUCCESS 行不得保留 FAILED/STOPPED 错误信息。

### P0-2 “可信覆盖率”和门禁结论存在错误成功

**代码位置**

- `backend/app/tasks/case_generation_v2.py:6152`：`MUST_COVER_NOT_COVERED` 被识别为 blocker
- `backend/app/tasks/case_generation_v2.py:6200-6212`：关键问题又进入 advisory 集合
- `backend/app/tasks/case_generation_v2.py:6429-6455`：组合门禁按降级后的 blocker 重新判断通过
- `backend/app/tasks/case_generation_v2.py:6622`：release readiness 主要由结构门禁和 warning 数决定
- `frontend/src/views/case/generator2/index.vue:249-265`：100% 与 must_cover 缺口同屏展示
- `backend/tests/test_platform_api.py:1191-1234`：测试明确期望 blocker 降级 warning 后 gate 通过

**问题**

当前指标含义是：

- source 覆盖率：source 下是否至少存在一条用例；
- FP 消费率：FP 是否存在 covered/merged/blocked 回执；
- 门禁通过：结构 blocker 经降级后是否为 0。

这些指标没有证明 `must_cover`、关键规则、方法要求和证据已经被步骤与预期结果可观察地覆盖。当前 #17 仍有 28 个 must_cover 缺口，却显示 100% 和“交付门禁通过”。

这与 `backend/claw_5skill_unified/README.md` 和 `skills/trusted-gate/SKILL.md` 的 hard constraint 语义冲突。

**建议**

短期必须先修展示和命名：

- `source 覆盖率` 改为 `source 有用例率`；
- `功能点消费率` 改为 `FP 回执完整率`；
- 顶部结论以语义审查为主，存在 must_cover 缺口时显示“有条件通过/待修复”，不能显示纯“通过”；
- 缺失值显示 `--`，不能由 `formatRate()` 显示成 `0%`。

随后修门禁策略：

- hard must_cover 未覆盖时保持 blocker，除非有结构化 waiver（理由、责任人、时间、证据）；
- source/FP 回执只证明守恒，不等价于语义覆盖；
- 语义审查、确定性门禁、交付结构门禁分别展示，不合并成一个模糊“gate 结论”；
- trusted 的最终状态至少区分 `SUCCESS`、`CONDITIONAL`、`FAILED`。

**验收**

- 28 个 must_cover 缺口的任务不能显示 100% 语义覆盖或“可信通过”。
- 所有 gate 结论可从原始 issue/waiver 确定性重算。

### P0-3 可信模式默认没有执行真正的 source shard 生成

**代码位置**

- `backend/app/tasks/case_generation_v2.py:5546`：将 lite package 映射为 trusted handoff
- `backend/app/tasks/case_generation_v2.py:5679-5693`：产物标记 `lite_review`
- `backend/app/tasks/case_generation_v2.py:5788`：真正 source shard 实现
- `backend/app/tasks/case_generation_v2.py:7753`：默认策略为 `lite_review`
- `backend/app/tasks/case_generation_v2.py:7759`：只有显式 `source_shard` 才走分片生成
- `backend/app/schemas.py:287-298`：创建请求没有 `trusted_generation_strategy`

**问题**

前端和 API 都不能设置 `trusted_generation_strategy`，因此新建 trusted 任务默认执行：先按 lite/V1 方式生成总用例包，再映射为 trusted source/FP receipts。

后端还会按同 source/FP 下“存在任意用例”补写 covered/merged 回执。方法缺口可能被解释成“已合并到该 source 的全部用例”，但没有证据证明对应方法真的被执行。

所以当前“Source 分片用例”“按 source 生成”的产品语义与实际初始生成链路不一致。

**建议**

必须二选一：

1. 可信模式真正默认走 `source_shard`，lite_review 仅作为快速预览模式；或
2. 保留当前实现，但改名为“轻量结果可信审查”，不能声称 source shard 生成。

不建议继续由后端自动制造 covered 回执。自动补写只能标记 `inferred`，并保留 `evidence_case_ids`、匹配理由和置信度；没有语义证据时应保持 gap。

**验收**

- 新建任务的实际策略在请求、DB、阶段和产物中一致。
- 每个 covered/merged 回执都能列出具体 case ID 和覆盖的可观察文本。

### P0-4 XMind 生成与 roundtrip 门禁存在假阳性

**代码位置**

- `backend/app/tasks/case_generation_common.py:277-298`：Python 手工打包 XMind ZIP
- `backend/app/tasks/case_generation.py:3168`：V1 调用共用 Python 转换
- `backend/claw_5skill_unified/tools/validate_trusted_output.py:379`：寻找临时 `.xmind`
- `backend/claw_5skill_unified/tools/validate_trusted_output.py:401-403`：仅在 reverse 结果声明统计时比较数量

**问题**

Skill 文档要求通过本地 `xmindmark` CLI 生成 `.xmind`，当前代码实际由 Python 构造 `content.json/manifest/metadata` ZIP，文档与运行事实不一致。

审查期间对容器内 `xmindmark@0.3.2` 做最小冒烟测试：CLI 生成约 1.8 KB 的空白隐藏 `.xmind`，反向转换只有 1 字节。验证器仍可能因为 reverse 文件没有声明统计而跳过数量比较，并把 `xmindmark_roundtrip` 写成 pass。

#17 实际交付的 Python XMind 约 37 KB，包含 71 个 TC；CLI 临时文件约 1.8 KB，包含 0 个 TC。最终门禁验证的不是实际交付文件，roundtrip 结论没有证明交付物有效。

**建议**

1. 立即修改验证器：找不到预期文件、空白 root、缺失 reverse 统计、TC/SRC/FP 不一致均必须失败。
2. 门禁必须解析和验证实际交付的 `.xmind`，不能只验证另一个临时文件。
3. 决策上二选一：
   - 修复并锁定一个可用的官方/可靠 CLI 版本；
   - 正式采用确定性 Python exporter，同时更新 Skill 和对齐文档，不再声称 CLI 对齐。
4. 增加真实 CLI/exporter 集成测试，禁止 mock 掩盖空白文件。

**验收**

- 空白 XMind 必须 gate fail。
- 实际下载文件解析出的 TC/SRC/FP 数量与 JSON/XMindMark 完全一致。

## 4. P1：高优先级问题

| 编号 | 问题 | 证据与影响 | 建议 |
|---|---|---|---|
| P1-1 | Celery 失败任务仍显示 task succeeded | V1/V2 顶层捕获异常、写 DB FAILED 后不重新抛出；Celery 监控无法区分业务失败 | DB 落失败后重新抛出受控异常；配置 `acks_late`、`reject_on_worker_lost`、soft/hard limit 和幂等重试 |
| P1-2 | Broker 失败后用 FastAPI daemon thread 执行 | `backend/app/api.py:876`；进程重启即丢任务，无法 revoke/inspect | broker 不可用时返回 503 或写 outbox 等待调度，不在 Web 进程跑长 AI 任务 |
| P1-3 | 无不可变 attempt 审计 | 重跑覆盖同一 job、删除旧 artifacts；无法回答“哪一次运行生成了这份文件” | Job 表示需求意图，Attempt 表示执行；artifact、stage、model trace 都绑定 attempt/run_id |
| P1-4 | trusted 模型阶段没有真正加载 Unified Skill | trusted scope/requirement/testcase 多处直接调用 `_call_openai_json`，未通过 `_load_claw_skill_context()`；修改 Skill 文件未必影响运行 | 建立统一 stage runner，所有阶段显式加载 mode 对应 README/SKILL/schema/protocol，并记录 prompt/skill 版本 hash |
| P1-5 | 单 worker + `--pool=solo` + 共用队列 | `docker-compose.yml:106`；#17 单任务占 worker 22 分钟，其他测试执行也被阻塞 | 分离 `case_generation` 与 `execution` 队列和 worker；模型并发设 provider 级总限流 |
| P1-6 | SSRF 与无限下载 | V1/V2 可请求用户 source URL 和 Markdown 图片 URL，允许 redirect，无私网拦截、大小/MIME 限制 | 只允许 http/https；DNS 解析后拦截 loopback/link-local/private；流式下载、限大小、校验 MIME；redirect 每跳复验 |
| P1-7 | API Key 明文持久化 | `AIModelConfig.api_key` 为普通字符串；数据库泄露即暴露模型凭据 | 使用 KMS/应用密钥加密，响应永不回传；区分临时 key 与保存配置 |
| P1-8 | 绝对文件路径暴露给前端 | artifact schema 返回 `file_path`，页面还会显示 fallback | API 只返回 artifact id、name、size、media type、download URL |
| P1-9 | 存储清理策略不一致 | V1/lite 成功后立即删除同项目旧 XMind；trusted 永不清理；失败/孤儿目录残留 | 统一 retention：按 attempt 保留最近 N 次/天数，删除有审计记录；页面显示过期状态 |
| P1-10 | 质量审查 fail 仍导出并标 SUCCESS | V1/V2 lite 使用 `block_on_fail=False`；`conditional_export` 变量未形成状态契约 | 引入 CONDITIONAL 状态；严重 fail 阻止正式交付，或将文件明确标为 draft |
| P1-11 | 长文档策略触发条件过于粗糙 | 章节数 `>16` 或文本 `>48k` 即走轻量索引；#17 仅约 11k 字但 18 章节，仍被拆成 5 批并产出 29 source | 按 token、图片数、预计输出量和语义密度动态选择，不用单一章节数 OR |
| P1-12 | SourceManifest 不足以复现输入 | 仅记录标题、长度、图片引用，缺 run_id、hash、revision、MIME、size、fetch time | Manifest 增加内容 hash、解析器版本、来源版本、模型和 prompt hash、run_id |
| P1-13 | 模型调用没有成本/响应追踪 | 未统一记录 token、费用、provider request ID、finish reason、重试原因 | 增加 model_call 表/trace artifact，为超时和成本优化提供真实数据 |

## 5. P2：可维护性、前端与性能问题

| 编号 | 问题 | 影响 | 建议 |
|---|---|---|---|
| P2-1 | V1/V2 大量复制 | 同一 bug 需修两次，Skill/方法库已经漂移 | 抽取 input/model/json repair/image/export/stage 公共核心；V1/V2 只保留 pipeline 策略 |
| P2-2 | 没有前端测试与 lint/typecheck | 两个超大单文件页面仅靠人工验证 | 增加 ESLint、Vitest、组件测试；为模式兼容、轮询、摘要、gate 状态加用例 |
| P2-3 | 轮询请求过多 | V2 每 5 秒详情后再拉项目列表和全量列表；artifact JSON 也随详情重复返回 | 活跃任务仅拉 detail/heartbeat；指数退避或 SSE；列表独立刷新 |
| P2-4 | artifact content 过大 | testcase handoff/package 可数百 KB，DB 与文件双存，详情每 5 秒反复传输 | 列表只返回 metadata；内容按 artifact id 懒加载；大对象仅文件/对象存储保存 |
| P2-5 | `formatRate` 把未知显示为 0% | 用户无法区分“没计算”和“确实为 0” | null/undefined 显示 `--`，0 才显示 0% |
| P2-6 | media type 映射不完整 | `source_manifest`、部分 gate JSON 可能以 octet-stream 下载 | artifact 类型注册为统一枚举并集中映射扩展名/MIME |
| P2-7 | 死配置和并发契约不清 | `CASE_GEN_MIN_CASES_PER_FUNCTION_POINT` 未使用；compose 并发 8 与阶段局部并发 2 并存 | 删除无效配置，建立 provider/job/stage 三层明确并发预算 |
| P2-8 | 广泛异常吞掉 | 多处 `except Exception: pass`，清理和附加产物失败不可观察 | 非关键错误也写结构化 warning/log artifact；只捕获预期异常 |
| P2-9 | 容器以 root 运行 | compose 用 `user: "0:0"` 覆盖 Dockerfile app 用户，worker有 root 警告 | 修复挂载目录权限后恢复非 root 用户 |
| P2-10 | 后端镜像偏大 | 当前约 614,738,528 bytes；包含 Node/xmindmark/Playwright Chromium | 移除未使用 Playwright，或拆分 exporter/vision worker，多阶段构建 |
| P2-11 | 历史列表固定 50 条 | 无分页、状态/时间过滤，后期不可用 | cursor pagination + project/status/mode/date 筛选 |
| P2-12 | 模型列表前端重复硬编码 | V1/V2 容易漂移，新增模型需改两处 | 模型 registry 由后端返回，前端只做选择和自定义输入 |
| P2-13 | 术语仍有误导 | V2 顶部“可信”、门禁“通过”比实际证据更强 | 明确结构完整、语义条件通过、交付结构通过三个不同概念 |

## 6. V1 与 V2 方法方案审查

### 6.1 V1 的优点与边界

优点：

- 流程短，用户容易理解：收集、识图、分析、设计、评审、导出。
- 对中小需求可以直接得到 XMind 初稿。
- 当前 `claw_5skill_final` 已补充测试设计方法，并减少固定数量约束，方向合理。

边界：

- 功能点、用例、证据之间没有强制 source 守恒。
- 质量 review 主要依赖模型判断，确定性可复算能力弱。
- 数量波动大：历史任务可从 37 到 215 条，难以解释差异。
- 审查 fail/conditional 不影响 SUCCESS 与导出，成功语义过宽。

建议保留 V1 作为“快速生成/人工复核”产品，不应继续向其中叠加完整 trusted 节点。只需共享底层稳定性、安全和 exporter 修复。

### 6.2 V2 轻量模式

当前轻量模式基本是 V1 的复制版本。产品上可作为新架构兼容入口，但没有必要长期维护两份近似代码。

建议：

- 执行层直接复用同一个 lite pipeline service；
- V1/V2 各自保留 job 表和页面兼容层；
- 不把 V1 函数继续复制进 V2 文件。

### 6.3 V2 可信模式

正确方向：

- SourceManifest / ScopeIndex / FP / testcase package 分层；
- 确定性 schema 和 ID 检查；
- source/FP 消费回执；
- source 局部重跑；
- 分离结构门禁和模型 review 的思路。

当前偏差：

- 实际默认从 lite 包映射 trusted，不是真 source shard 初始生成；
- Unified Skill 文档没有成为所有 trusted 模型调用的运行时输入；
- 结构守恒被包装成语义覆盖；
- blocker 被策略性降级后仍宣传 gate pass；
- 最终交付门禁没有验证实际 XMind 的真实内容；
- 没有 immutable run/attempt，无法满足可信审计。

所以 V2 不应推倒重写，但需要先收紧定义。推荐将可信链路拆成三类结论：

1. `structural_integrity`：ID、schema、计数、消费回执是否完整。
2. `semantic_coverage`：must_cover、规则、方法、可观察预期是否真实覆盖。
3. `delivery_integrity`：实际下载文件是否可打开、树结构与统计是否一致。

只有三者都达到策略要求，才显示“可信通过”。

## 7. 性能与并发判断

### 7.1 #17 时间构成

| 阶段 | 耗时 |
|---|---:|
| 编排/证据 | 约 1 分 52 秒 |
| 索引/范围门禁/分析/需求门禁 | 约 10 分 19 秒 |
| 用例基线/用例门禁 | 约 8 分 9 秒 |
| 复核 | 约 1 分 50 秒 |
| 导出/交付门禁 | 约 2 秒 |
| 总计 | 约 22 分 11 秒 |

主要耗时来自模型调用与模型输出规模，不是后端 gate。确定性 gate 通常约 1 秒。

### 7.2 是否应该用多 Agent/多并发

当前不应直接增加 Agent 数。原因：

- 单 worker 的任务状态和 attempt 所有权尚不可靠；
- provider 已发生 429 concurrency quota exceeded；
- source 拆分质量不稳定，更多并发可能更快地产生重复/错误 shard；
- 合并与语义 gate 目前仍会错误通过。

在完成 P0/P1 状态修复后，可采用受控动态并行：

- 小文档：单次 scope + 单次 requirement，避免分片开销。
- 中文档：按语义 source 分片，并发 2。
- 长文档：map-reduce，但先生成稳定 source manifest，再并发；provider 总并发集中限流。
- shard 失败只重跑该 attempt/shard，不重跑整个 job。

## 8. 安全与数据治理

需要在项目进入多人使用或非本地环境前完成：

1. URL 与图片下载 SSRF 防护、下载大小/MIME/超时限制。
2. API Key 加密存储、脱敏日志和最小返回。
3. artifact 下载鉴权，不返回服务器绝对路径。
4. 输入与产物 retention、失败任务清理、孤儿目录扫描。
5. 容器非 root；数据库密码改为 secret 注入。
6. 对上传文档做大小、扩展名、MIME 和压缩包炸弹限制。

当前 `backend/reports` 约 159 MB、17,198 个文件、约 7,968 个目录；其中 V1 约 50 MB，V2 约 33 MB。V1/V2 的保存策略不同，且存在数据库中没有对应记录的 job 目录，说明需要正式 retention 与 reconciliation job。

## 9. 测试审查

### 9.1 本次执行结果

| 检查 | 结果 |
|---|---|
| Python 核心文件 `py_compile` | 通过 |
| `backend/tests/test_platform_api.py` | 107 passed，28.54s |
| 前端 `vite build` | 通过，约 5.63s |
| 容器状态 | backend/frontend/mysql/redis healthy，worker running |

前端构建仍有两项警告：

- `auth.js` 同时静态和动态 import，不能独立拆 chunk；
- 主 JS 约 1.46 MB（gzip 约 449 KB），超过 Vite 500 KB chunk 提示阈值。

### 9.2 现有测试的盲区

- 没有真实 Celery worker 丢失、并发重跑、旧 attempt 晚返回的集成测试。
- 没有 GET 只读契约测试。
- 没有真实 xmindmark/exporter roundtrip 测试；mock 未发现空白文件。
- 没有浏览器端 V1/V2 模式兼容、轮询和 gate 展示测试。
- 部分测试把 blocker 降级 warning 并 gate 通过当成预期，导致策略错误被测试固化。
- 没有 SSRF、超大文件、redirect 到私网、压缩包炸弹测试。

测试全绿说明当前实现内部一致，但不能说明可信方案成立。

## 10. 推荐整改顺序

### 第一批：P0 正确性止血（建议最先完成）

1. 取消 GET 修改任务状态；增加 attempt token、heartbeat 和 CAS 更新。
2. 重跑创建新 attempt/目录，旧执行不能覆盖。
3. 修正可信指标和状态：`source 有用例率`、`FP 回执率`、semantic conditional。
4. must_cover blocker 不再静默降级；waiver 必须结构化。
5. 修复 XMind 实际交付文件解析与 validator 假阳性。

### 第二批：P1 运行稳定性

1. 分离 Celery 队列和 worker；任务失败正确反映到 Celery。
2. 移除 Web daemon thread fallback。
3. 明确 trusted 是 source_shard 还是 lite_review，产品与执行保持一致。
4. 让 Unified Skill 真正进入每个 trusted 模型阶段，并记录版本 hash。
5. 建立统一 retention 和 artifact 生命周期。

### 第三批：P1/P2 安全与重构

1. SSRF、下载限制、API Key 加密、路径隐藏。
2. 抽取 V1/V2 共享 pipeline core。
3. artifact 元数据与内容分离，减少轮询体积。
4. 前端测试、后端生命周期集成测试、真实 exporter 测试。

### 第四批：性能优化

1. 收集 token/耗时/重试/成本后再设动态策略。
2. 按 token 和预计输出量选择 single/batch/shard。
3. provider 级统一并发和退避。
4. 在状态与门禁正确后，再评估多 Agent。

## 11. 不建议立即做的事情

- 不要先增加更多前端节点；当前问题是结论语义，不是展示不够详细。
- 不要仅把并发从 2 调到 4/8；已有 429，且 solo worker 与 provider 限流尚未治理。
- 不要继续给 gate 增加自动“补齐/推断 covered”逻辑；这会让数字更漂亮但证据更弱。
- 不要直接切换到当前 `xmindmark@0.3.2` CLI；本次实测会生成空白文件。
- 不要再复制一份 V3 主流程；应抽共享核心和策略接口。
- 不要用“测试通过”作为方案可信的替代证据；必须增加对策略语义的反例测试。

## 12. 最终验收标准

完成整改后，至少满足：

1. 任意模型调用 15 分钟不触发错误 stale，worker 丢失又能在明确时间内标记 lost。
2. 同一 job 同时存在两个 attempt 时，旧 attempt 永远不能覆盖新 attempt。
3. SUCCESS 任务没有历史失败/停止错误残留。
4. `source 有用例率`、`FP 回执率`、`semantic coverage` 三者独立且可复算。
5. must_cover 缺口未解决/未豁免时，不能显示“可信通过”。
6. trusted 实际策略与页面名称一致，source shard 或 lite_review 不再混淆。
7. 每个 covered/merged 回执都有具体 case IDs 和匹配证据。
8. 实际下载 XMind 可打开，且解析后的 SRC/FP/TC 数与 JSON/XMindMark 一致。
9. 任务失败在 DB 与 Celery 中均为失败，可按幂等策略重试。
10. URL/图片下载不能访问私网，超大响应会被中止。
11. 历史 attempt 和产物可追溯，并按统一 retention 清理。
12. V1 与 V2 共用稳定底层实现，模式差异由策略层表达。

## 13. 最终建议

项目不需要推倒重做。V1 可保留为轻量基线，V2 的 source/FP/gate 资产也值得保留。下一步应把 V2 从“结构看起来可信”推进为“运行和结论都可证伪、可重算、可追溯”。

最优决策不是先做多 Agent，而是先完成：**不可变 attempt + 正确门禁语义 + 实际交付物验证**。这三项完成后，长文档并行才会真正提升效率，而不是更快地产生无法确认归属和质量的结果。
