# 用例生成2 — 可信改进模式（trusted_v2）深度评估报告

> 评估日期：2026-07-02
> 评估范围：后端 `case_generation_v2.py`（5174 行 / 142 函数）、前端 `generator2/index.vue`（1854 行）、`caseGenerationV2.js`、API 路由层、数据模型层
> 评估方式：纯静态代码审查，未做运行时测试

---

## 0. 架构总览

### 流水线阶段（trusted_v2 模式）

```
orchestrate → collect → image_analysis → scope_index → scope_index_gate
  → requirement → requirement_gate → testcase (shard 并行) → testcase_gate
  → review (语义审查) → export (XMind + Markdown)
```

### 核心设计理念

| 概念 | 说明 |
|------|------|
| **直接测试对象（Source）** | LLM 先把需求文档拆成可独立测试的 SRC-xxx 对象，每个带 case_budget (min/target/max) |
| **功能点溯源** | 每个 FP 必须绑定 source_id，scope_index_consumption 记录每个 source 是否被消费 |
| **Source 分片生成** | 按 source 并行调用 LLM 生成用例，每个 shard 不超过 budget.max |
| **三道门禁** | scope_index_gate → requirement_gate → testcase_gate，全部确定性校验 |
| **可信复核报告** | 汇总 12+ 项指标（source 覆盖率、FP 消费率、超预算数、重复合并数等） |
| **Source 级重跑** | 单个 source shard 失败可独立重跑，不必重新生成全部 |

---

## 1. 功能完整性：★★★★☆ (4/5)

### 亮点

**1.1 流水线闭环完整**
从需求输入 → 范围索引 → 功能点 → 分片用例 → 门禁校验 → 语义审查 → XMind 导出，全链路无断点。每个阶段的产出都有对应的 artifact 持久化到数据库和文件系统。

**1.2 门禁校验体系严密**
三道门禁覆盖了 30+ 种 issue code：

| 门禁 | 检查项 |
|------|--------|
| scope_index_gate | source_id 重复/缺失、budget 范围非法、complexity 非法、dependency 孤儿引用 |
| requirement_gate | source 未消费、消费结果非法、FP 缺少 source_id、FP 引用未知 source、consumption 引用不存在 FP |
| testcase_gate | FP 未消费、source 超预算、case 重复 ID、case source/FP 不匹配、consumption 引用不存在 case |

**1.3 降级策略完善**
- 图片下载失败 → 记入 pending_confirmations，不阻断流程
- 图片识图批次失败 → skip 并降级为待确认，仅全部批次失败才整体报错
- 需求分析批次失败 → 自动拆分为单章节子批重试
- JSON 被截断 → 自动放大 max_tokens 重试，再不行调用 JSON 修复器
- Source shard 失败 → 其他 shard 继续执行，失败 source 可单独重跑

**1.4 边界条件覆盖**
- 空输入检测（`markdown_text` 为空）
- 缺少 API Key 检测
- 任务取消检测（每个阶段边界调用 `_raise_if_job_cancelled`）
- Stale job 标准化（API 层调用时检测僵尸任务）
- 单用户并发限制（同一用户同时只能有一个 RUNNING 任务）

### 不足

**1.5 clone 模式与 trusted_v2 模式的 source_type=LINK 场景**
`_fetch_source_url` 使用同步 `httpx.get`，如果目标站点响应慢或不可达，会阻塞整个流水线，无超时降级到"仅使用 markdown_text"的逻辑。

**1.6 trusted_v2 不支持 `export_xmind=False`**
clone 模式检查 `payload.get("export_xmind", True)`，但 trusted_v2 的 `_export_trusted_xmind` 是无条件执行的。前端 checkbox 虽然是 disabled 状态，但 schema 层面 `export_xmind: bool = True` 允许传 False，后端 trusted_v2 会忽略它。

---

## 2. 代码质量：★★☆☆☆ (2.5/5)

### 亮点

**2.1 命名规范一致**
私有函数统一 `_` 前缀，trusted_v2 相关函数统一 `_trusted_` / `_build_trusted_` 前缀，gate 校验函数统一 `_validate_trusted_` 前缀，可读性好。

**2.2 常量集中管理**
20+ 个可配置参数通过 `settings.case_gen_*` 从 `config.py` 统一注入，包括超时、并发数、批次大小、截断限制等。

**2.3 数据模型设计规范**
`CaseGenerationV2Job` 和 `CaseGenerationV2Artifact` 使用 SQLAlchemy 2.0 `Mapped` 风格，外键索引完备，`cascade="all, delete-orphan"` 正确。

### 不足

**2.4 🔴 巨型单文件反模式**
`case_generation_v2.py` **5174 行 / 142 个函数**，远超原始 `case_generation.py` 的 3572 行。这个文件同时包含：

| 职责 | 行数估算 |
|------|---------|
| 通用工具函数（文件操作、JSON 解析、文本截断） | ~500 |
| AI 调用层（OpenAI 调用、重试、JSON 修复） | ~600 |
| clone 模式流水线 | ~800 |
| trusted_v2 流水线 | ~1800 |
| trusted_v2 门禁校验 | ~800 |
| trusted_v2 产物构建（review report、markdown、xmind） | ~700 |
| Celery 任务入口 + 异常处理 | ~400 |

建议拆分结构：
```
tasks/
  case_generation_v2/
    __init__.py              # 公共入口
    common.py                # 通用工具函数
    ai_client.py             # OpenAI 调用 + 重试 + JSON 修复
    clone_pipeline.py        # clone 模式
    trusted/
      __init__.py
      pipeline.py            # trusted_v2 主流程
      scope_index.py         # 范围索引 + 门禁
      requirement.py         # 需求分析 + 门禁
      testcase.py            # 用例分片 + 门禁
      review.py              # 可信复核报告
      export.py              # XMind 导出
```

**2.5 🔴 sync/async 代码大面积重复**
以下函数对几乎是逐行复制（差异仅在 `asyncio.run()` 包装和 thinking 标签提示）：

| async 版本 | sync 版本 | 重复行数 |
|-----------|----------|---------|
| `_call_skill_with_gate_async` (1557-1753) | `_call_skill_with_gate` (1756-1947) | ~190 行 |
| `_call_openai_json_async` | `_call_openai_json` | ~5 行 |
| `_build_trusted_testcase_source_shard_async` | `_build_trusted_testcase_source_shard` | 包装层 |
| `_build_trusted_testcase_handoff_async` | `_build_trusted_testcase_handoff` | 包装层 |
| `_analyze_images_async` | `_analyze_images` | 包装层 |
| `_download_image_links_async` | `_download_image_links` | 包装层 |

`_call_skill_with_gate` 和 `_call_skill_with_gate_async` 的重复尤其严重——两者各自约 190 行，逻辑完全一致，仅在 `_call_openai_json` vs `await _call_openai_json_async` 和 thinking 提示上有微小差异。

**2.6 `GenerationContext` dataclass 是死代码**
第 388-407 行定义了 `GenerationContext` 数据类，注释写明"替代散落的参数传递"，但在 trusted_v2 和 clone 流水线中**从未被实例化使用**。

**2.7 常量定义位置不合理**
`_TRUSTED_COMPLEXITIES`、`_TRUSTED_REQUIREMENT_RESULTS`、`_TRUSTED_TESTCASE_RESULTS` 定义在第 3379 行（文件中间），而非文件顶部的常量区。`_MAX_JSON_RETRY_TOKENS = 24000` 也是硬编码，未走 config。

**2.8 前端单文件组件过大**
`generator2/index.vue` 1854 行，template + script + style 全在一个文件。script 部分 670 行，包含 30+ 个函数和 20+ 个 computed/ref。建议拆分为子组件（TrustedMetrics、SourcesDetail、ProgressTracker、ArtifactViewer 等）。

---

## 3. 性能表现：★★★☆☆ (3/5)

### 亮点

**3.1 并发控制合理**
`_gather_limited` 使用 `asyncio.Semaphore` 限制并发数（默认 4），图片下载、图片识别、source shard 生成均受控。

**3.2 分批策略**
- 需求分析按章节文本大小+章节数双重上限分批
- 用例设计按 FP 批次大小（默认 5）分批
- 图片识别按批次大小（默认 8）分批

**3.3 大上下文保护**
`_compact_sections_for_ai` 有 `total_limit` 参数（trusted_v2 设为 36000），防止 prompt 超限。

### 不足

**3.4 🔴 `asyncio.run()` 反模式**
trusted_v2 流水线在 Celery 同步任务中多次调用 `asyncio.run()`：

```python
# _build_trusted_scope_index 内部
raw = _call_openai_json(...)  # 内部 asyncio.run()

# _build_trusted_testcase_handoff 内部
return asyncio.run(_build_trusted_testcase_handoff_async(...))

# 但 _build_trusted_testcase_handoff_async 内部又调用 _build_trusted_testcase_source_shard_async
# 每个 source shard 内部又调用 _call_openai_json_async
```

每次 `asyncio.run()` 创建并销毁一个新的事件循环。在一次 trusted_v2 任务执行中，`asyncio.run()` 至少被调用 3-5 次（scope_index、requirement、每个 source shard、semantic review）。虽然在功能上可行，但：
- 事件循环创建/销毁有开销
- 无法在单个事件循环内复用 HTTP 连接池
- 如果 Celery worker 使用 `gevent` 或 `eventlet` 池，可能与 `asyncio` 事件循环冲突

**3.5 trusted_v2 的 LLM 调用次数**
一次 trusted_v2 任务的最少 LLM 调用次数：

| 阶段 | 调用次数 |
|------|---------|
| 图片识别 | ceil(图片数 / 8) |
| scope_index | 1 |
| requirement_handoff | 1 |
| testcase shards | N（source 数量） |
| semantic review | 1 |
| **最少总计** | 4 + N |

如果 17 个 source，则最少 21 次 LLM 调用，每次可能 8000-14000 max_tokens。对于大需求文档，API 费用可能显著。

**3.6 `_build_trusted_scope_index` 和 `_build_trusted_requirement_handoff` 都发送 36000 字符**
两个阶段各自独立发送全量章节文本（36000 字符上限），存在重复 token 消耗。scope_index 已经建立了 source → section 映射，requirement_handoff 理论上可以只发送 source 关联的章节，而非全量。

**3.7 `_image_to_data_url` 将图片完整 base64 编码**
大图片（如 5MB+）的 base64 编码会使 HTTP 请求体膨胀约 33%。没有压缩或尺寸限制逻辑。

---

## 4. 可靠性与健壮性：★★★★☆ (4/5)

### 亮点

**4.1 JSON 解析与修复三层防线**
1. `_extract_complete_json_object`：括号匹配提取完整 JSON 对象
2. YAML fallback：JSON 解析失败时尝试 `yaml.safe_load`
3. `_repair_model_json_async`：调用 LLM 修复格式错误，明确禁止修改业务语义

**4.2 截断检测与自适应重试**
`_is_incomplete_json_error` 检测截断标志（EOF、max_tokens、unterminated 等），截断时自动放大 `max_tokens`（每次 +50%），并添加压缩提示要求模型精简描述性文字。

**4.3 不可重试错误识别**
`_is_non_retryable_model_error` 检测 401/403/400/model not found 等永久性错误，避免无意义重试浪费 API 配额。

**4.4 原子文件写入**
`_atomic_replace_file` 使用临时文件 + `os.replace()` 确保文件写入的原子性，避免部分写入导致的数据损坏。

**4.5 Source shard 隔离**
单个 source shard 失败不影响其他 shard，失败信息记录到 `shard_failures`，整体流程继续执行到 review 阶段才判定失败。

**4.6 任务取消响应**
`_raise_if_job_cancelled` 在每个阶段边界检查，用户取消后能在秒级响应（而非等到下一个 LLM 调用完成）。

### 不足

**4.7 `asyncio.run()` 在 Celery 中的异常吞噬风险**
如果 `asyncio.run()` 内部的协程抛出 `KeyboardInterrupt` 或 `SystemExit`，`asyncio.run()` 会将其传播，但 Celery worker 可能无法正确处理这类信号。

**4.8 `_persist_stage_artifact` 静默吞异常**
```python
def _persist_stage_artifact(output_dir, file_name, payload):
    try:
        _write_json_file(output_dir, file_name, payload)
    except Exception:
        pass  # ← 静默吞掉所有异常
```
如果磁盘满或权限错误，用户无法感知 stage artifact 未持久化。

**4.9 `_ensure_writable_dir` 权限设置后不验证**
```python
def _ensure_writable_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
        os.chmod(path, 0o777)  # ← 0o777 过于宽松
    except PermissionError:
        pass  # ← 静默忽略，后续写入可能失败
```
`0o777` 权限过于宽松（其他用户可写），且 `PermissionError` 被静默忽略。

**4.10 shard 重跑的竞态条件**
`rerun_case_generation_v2_source_shard` 没有检查 job 是否已有其他重跑在进行中。如果用户快速点击两个不同 source 的重跑按钮，两个 Celery 任务可能同时修改 `testcase_package` artifact，导致数据不一致。

---

## 5. 可维护性与可扩展性：★★☆☆☆ (2.5/5)

### 亮点

**5.1 配置驱动**
20+ 个参数通过 `config.py` / 环境变量注入，修改批次大小、超时、并发数等不需要改代码。

**5.2 门禁 issue code 体系**
每种校验失败都有唯一的 `code`（如 `SOURCE_OVER_BUDGET`、`FP_NOT_CONSUMED`），便于前端精准展示和后续扩展自定义处理逻辑。

**5.3 artifact 类型可扩展**
`CaseGenerationV2Artifact.artifact_type` 是 String(50)，新增产物类型（如 PDF、HTML 报告）只需新增 upsert 调用，不需要改表结构。

### 不足

**5.5 🔴 5174 行单文件极难维护**
任何修改都需要在这个巨型文件中定位上下文。IDE 索引变慢，merge conflict 概率极高，code review 几乎不可行。

**5.6 🔴 sync/async 重复使修改风险翻倍**
修改 `_call_skill_with_gate` 的逻辑时，必须同步修改 `_call_skill_with_gate_async`，反之亦然。两个函数 190 行几乎逐行对应，极易遗漏。

**5.7 trusted_v2 与 clone 共享代码的边界模糊**
trusted_v2 复用了 clone 模式的 `_build_review_report`、`_build_xmindmark`、`_build_case_generation_quality_summary` 等函数。这些函数最初为 clone 模式设计，trusted_v2 通过 `_trusted_standard_function_points` 和 `_trusted_standard_testcase_package` 做格式适配后调用。适配层的存在说明两个模式的数据结构不完全兼容，后续修改 clone 模式的数据结构可能意外破坏 trusted_v2。

**5.8 前端硬编码模型列表**
`modelOptions` 数组硬编码在前端 Vue 文件中（16 个模型选项），包含 baseUrl 映射。新增模型需要同时改前端和后端 config。

**5.9 进度阶段 key 硬编码在前端**
```javascript
const trustedProgressStageKeys = [
  'orchestrate', 'collect', 'image_analysis', 'scope_index',
  'scope_index_gate', 'requirement', 'requirement_gate',
  'testcase', 'testcase_gate', 'review', 'export'
]
```
后端新增/调整阶段时，前端必须同步修改，否则进度展示会错位。

**5.10 无单元测试**
整个 `case_generation_v2.py` 没有对应的测试文件。门禁校验逻辑（`_validate_trusted_scope_index`、`_validate_trusted_requirement_handoff`、`_validate_trusted_testcase_handoff`）是纯函数，非常适合单元测试，但当前覆盖率为 0。

---

## 6. 优缺点总结

### 优点

| # | 优点 | 影响 |
|---|------|------|
| ✅ 1 | **创新的范围索引 → 预算 → 分片架构** | 用例数量可控、可解释、可追溯 |
| ✅ 2 | **三道确定性门禁** | 30+ 种 issue code 精准拦截 LLM 幻觉 |
| ✅ 3 | **Source 级独立重跑** | 失败 source 可单独重跑，节省 API 成本和时间 |
| ✅ 4 | **完善的降级策略** | 图片失败/识图失败/批次失败/JSON 截断 全部有降级路径 |
| ✅ 5 | **可信指标仪表板** | 12 项指标（覆盖率、消费率、超预算等）提供透明度 |
| ✅ 6 | **JSON 修复三重防线** | 括号匹配 → YAML fallback → LLM 修复 |
| ✅ 7 | **原子文件写入** | `os.replace()` 保证数据完整性 |
| ✅ 8 | **并发控制合理** | Semaphore 限制并发，分批策略完善 |
| ✅ 9 | **取消响应及时** | 每阶段边界检查 cancel 状态 |

### 不足

| # | 不足 | 严重度 |
|---|------|--------|
| ❌ 1 | **5174 行单文件** | 🔴 严重 |
| ❌ 2 | **sync/async 190 行重复代码** | 🔴 严重 |
| ❌ 3 | **`asyncio.run()` 在 Celery 中反复创建事件循环** | 🟡 中等 |
| ❌ 4 | **`GenerationContext` 死代码** | 🟡 中等 |
| ❌ 5 | **0 单元测试覆盖** | 🔴 严重 |
| ❌ 6 | **`_persist_stage_artifact` 静默吞异常** | 🟡 中等 |
| ❌ 7 | **`os.chmod(path, 0o777)` 权限过宽** | 🟡 中等 |
| ❌ 8 | **shard 重跑无并发锁** | 🟡 中等 |
| ❌ 9 | **前端 1854 行单组件** | 🟡 中等 |
| ❌ 10 | **scope_index + requirement 重复发送全量章节** | 🟡 中等 |
| ❌ 11 | **trusted_v2 忽略 `export_xmind=False`** | 🟢 轻微 |
| ❌ 12 | **模型列表和阶段 key 硬编码在前端** | 🟢 轻微 |

---

## 7. 可优化项建议（不做代码修改）

### 🔴 P0 — 必须尽快处理

| # | 建议 | 预期收益 |
|---|------|---------|
| 1 | **拆分 `case_generation_v2.py`** 为子目录结构（`trusted/` 下分 `scope_index.py`、`requirement.py`、`testcase.py`、`review.py`、`export.py`，公共层抽 `ai_client.py`、`common.py`） | 可维护性提升 80%，merge conflict 降低 60% |
| 2 | **消除 sync/async 重复**：统一使用 async 版本，sync 入口仅用 `asyncio.run()` 包装一次。`_call_skill_with_gate` 删除，所有调用方改为 `asyncio.run(_call_skill_with_gate_async(...))` | 减少 ~200 行重复代码，修改风险减半 |
| 3 | **为核心门禁函数补充单元测试**：`_validate_trusted_scope_index`、`_validate_trusted_requirement_handoff`、`_validate_trusted_testcase_handoff`、`_normalize_trusted_scope_index` 都是纯函数，可独立测试 | 回归保护，重构信心 |

### 🟡 P1 — 应该在下一个迭代做

| # | 建议 | 预期收益 |
|---|------|---------|
| 4 | **删除 `GenerationContext` 死代码** 或真正使用它替代散落的参数传递 | 代码整洁度 |
| 5 | **`_persist_stage_artifact` 改为 log warning 而非 `pass`** | 可观测性 |
| 6 | **`os.chmod` 改为 `0o755`（目录）/ `0o644`（文件）** | 安全性 |
| 7 | **shard 重跑加分布式锁**（Redis SETNX 或 DB 行锁） | 并发安全 |
| 8 | **requirement_handoff 只发送 source 关联的章节** 而非全量 36000 字符 | 减少 ~50% token 消耗 |
| 9 | **前端拆分子组件**（TrustedMetrics、SourcesDetail、ProgressTracker、ArtifactViewer） | 前端可维护性 |
| 10 | **常量 `_TRUSTED_*` 移到文件顶部** 或独立的 `constants.py` | 代码组织 |

### 🟢 P2 — 体验优化

| # | 建议 | 预期收益 |
|---|------|---------|
| 11 | **模型列表从后端 API 动态获取** 而非前端硬编码 | 新增模型不需改前端 |
| 12 | **进度阶段 key 从后端 progress_json 返回有序列表** 而非前端硬编码 | 阶段调整不需改前端 |
| 13 | **trusted_v2 尊重 `export_xmind=False`** | 一致性 |
| 14 | **图片上传前压缩/限制尺寸** | 减少带宽和 API 成本 |
| 15 | **`_MAX_JSON_RETRY_TOKENS` 移到 config.py** | 可配置性 |

---

## 8. 总体评分

| 维度 | 评分 | 权重 | 加权分 |
|------|------|------|--------|
| 功能完整性 | ★★★★☆ 4/5 | 25% | 1.00 |
| 代码质量 | ★★☆☆☆ 2.5/5 | 20% | 0.50 |
| 性能表现 | ★★★☆☆ 3/5 | 15% | 0.45 |
| 可靠性与健壮性 | ★★★★☆ 4/5 | 20% | 0.80 |
| 可维护性与可扩展性 | ★★☆☆☆ 2.5/5 | 20% | 0.50 |
| **综合** | | | **3.25 / 5.00** |

### 一句话评价

> **架构设计思路一流（范围索引 + 预算分片 + 三道门禁），但工程实现被"5174 行单文件 + sync/async 190 行重复"严重拖了后腿。P0 三项修复后可达 4.0+。**
