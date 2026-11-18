# OmniTest 优化复核报告（2026-11-13）

> 范围：对既有《platform_optimization_master_plan_2026-10-28.md》的落地状态复核 + 一轮独立代码核查的增量发现。  
> 方法：静态代码走查（api.py / tasks 管线 / 前端 / CI / 部署配置），未运行服务、未调用真实模型。证据以 `file:line` 标注。



---

## 一、结论摘要

1. **旧优化文档质量高、但勾选状态严重落后于实现。** 244 条任务仅 26 条勾选，然而 git 提交与测试文件表明 A（上下文一致性）、C（业务闭环）、D（权限归属）、F（迁移管理）已相当程度落地并配了回归测试。文档需要与实现同步，否则「剩余工作量」失去可信度。
2. **最该优先做的是可靠性与成本，不是新功能。** 本轮独立核查确认三条「严重」级问题全部集中在 AI 生成/执行链路：**幂等缺失（重复计费）、执行产物无限增长、依赖库 cryptography 版本过旧**。
3. **部署与前端工程质量明显高于后端业务层。** 多阶段非 root 镜像、健康检查 + 失败自动回滚、部署锁、分队列 worker、路由懒加载、按需引入均已到位，值得保留。
4. **后端仍在「拆单体」的半途。** `api.py` 7060 行仍是巨无霸，已抽出 `project_workspace_api.py`，但鉴权/RBAC 缺乏统一依赖抽象（`permissions.py` 仅 11 行纯函数，472 处 `Depends` 分散）。

---

## 二、对旧优化文档的评估

**优点（应保留）：**

- 用 A/B/C/D 四级证据标注每条任务，来源可追溯。
- 明确「反过度设计清单」，避免把单体拆成微服务、把统一用例大表引入进来等错误方向。
- 提供回归矩阵与「实施前必须决策的问题」，工程落地性强。

**问题：勾选未同步，掩盖了真实进度。** 对照证据：

| 旧文档阶段    | 文档勾选 | 实际代码/测试证据                                                                                                              | 结论  |
| -------- | ---- | ---------------------------------------------------------------------------------------------------------------------- | --- |
| A 上下文一致性 | 少    | `e2e/tests/workspace_context_switch/drawer_isolation/link_picker/selection_scope.spec.js`                              | 已落地 |
| C 业务闭环   | 少    | `test_requirement_trace_coverage.py`、`test_plan_copy_atomic.py`、`test_case_export_filters.py`                          | 已落地 |
| D 权限与归属  | 少    | `test_permissions.py`、`test_project_member_guards.py`、`test_case_update_project_guard.py`、`test_batch_review_guard.py` | 已落地 |
| F1 迁移管理  | 少    | `alembic/`、`db_migrate.py`、`database-migrations.md`                                                                    | 已落地 |

> 建议：先做一次「勾选回填」，把已实现并验证的任务打勾，剩余未勾选的才是真实待办。

---

## 三、独立核查发现（增量）

### 严重（S）

**S1. 生成/执行不幂等，可重复执行并重复计费。**

- 生成：`tasks/case_generation_v2_pipeline/engine.py:4409-4446` 仅 `ensure_attempt/mark_attempt_running` 后直接 dispatch，不校验请求 ID、不原子占用；配合 Celery late-ack 崩溃重投，同一 attempt 可被再次执行并再次调用模型。
- 执行：`services.py:758-766` 对任何非 CANCELLED 状态都直接置 RUNNING，`services.py:786-808` 无执行所有权校验，取消可被晚到结果覆盖。
- 建议：DB 唯一任务租约 + 终态短路 + 阶段/分片检查点；重复投递只确认、不调模型。

**S2. 执行产物无限增长，磁盘可被打满。**

- `tasks/executions.py:246-271, 1978-2061` 每轮保存截图、trace、JSON/JUnit；清理仅覆盖生成目录（`case_generation_runtime.py:564-674`），执行产物无保留期/配额。
- 建议：统一保留期 + 容量/数量配额 + 周期清理，纳入 watchdog。

**S3. 依赖库 cryptography 版本过旧。**

- `requirements.txt:13` 锁定 `cryptography==41.0.7`（2023 年发布），已含公开 CVE；且该库用于 Fernet 加密模型密钥（`core/secrets.py`），属高价值目标。
- 建议：升级到 43/44+ 并回归密钥加解密。

### 高（H）

**H1. api.py 仍为 7060 行单体，RBAC 无统一抽象。**

- 已拆出 `project_workspace_api.py`（1567 行），但 `api.py` 仍是巨无霸；`permissions.py` 只有 `project_role_allows` 一个纯函数，472 处 `Depends` 内联分散。
- 建议：继续按领域拆（execution / case / report / generation），并沉淀 `require_project_role(role)` 依赖注入。

**H2. LLM 调用缺退避、限流与成本核算。**

- `engine.py:1662-1801` 三次尝试以立即重试为主，仅分片有 2–6s 等待；无 Celery autoretry/backoff、无 provider 级限流、无降级模型。
- `tasks/model_client.py:40-48` 成本字段恒为 None。
- 建议：指数退避 + jitter + 尊重 Retry-After；工作空间/provider 限流；价格表计费。

**H3. 可观测性不足。**

- 进度靠轮询 `progress_json`（无 WebSocket/SSE）；trace 主要在 `finish_attempt` 落盘，崩溃即丢；无结构化日志、Prometheus/OpenTelemetry、失败告警。
- 建议：统一 trace/job/run ID，实时追加审计，导出指标并告警。

### 中（M）

**M1. 前端 token 存 localStorage + 富文本 v-html 输出。**

- `stores/auth.js:8`、`lib/api.js:65` 用 localStorage 存 token；`views/project/workspace/Defects.vue:215/221/227` 三处 `v-html` 输出 description/reproduce_steps/resolution，依赖后端 nh3 清洗。
- 建议：优先 HttpOnly Cookie（或至少 CSP + 后端清洗单测覆盖三处富文本入口）。

**M2. 多处 setInterval 轮询，无退避。**

- `dashboard/index.vue:394`（5s）、`execution/index.vue:397`（5s/30s）、api/ui/performance case 页面轮询。
- 建议：确认 `onUnmounted` 清理；活跃期轮询、空闲退避；后续引入 SSE。

**M3. CI 未跑前端单测、无覆盖率门槛。**

- `stack-tests.yml` 覆盖 backend pytest + 13 个 e2e spec，但未调用 `frontend` 的 `vitest`/`typecheck`（package.json 已有脚本），无覆盖率门槛，无 worker 专项测试。
- 建议：CI 增加 `npm run test`/`typecheck` 步骤；pytest 加覆盖率阈值。

**M4. 生产缺数据库备份/回滚。**

- `deploy/deploy.sh` 只回滚镜像 tag；`backend` 启动时自动 `db_migrate upgrade`，而 `database-migrations.md` 明示 baseline 不可逆 → 镜像可回滚但 schema 不能。
- 建议：迁移前自动 `mysqldump` 快照；制定 schema 回滚预案。

---

## 四、已做得好、应保留

- **部署链路**：多阶段非 root 镜像（`Dockerfile`）、健康检查 + 失败自动回滚 + 部署锁（`deploy.sh`）、分队列 worker（execution / case_generation / beat）、资源限额与日志轮转、命名卷持久化、Redis appendonly。
- **前端**：路由全懒加载（`router/index.js` `() => import()`）、Element Plus 按需引入 + JS tree-shaking（`vite.config.js`）、手动分包。
- **测试**：17 个后端测试文件 + 13 个 e2e spec，覆盖权限、原子性、追溯、隔离等关键正确性契约。
- **迁移**：已引入 Alembic 版本管理（F1 已解决）。

---

## 五、优先级行动清单

| 优先级 | 事项                                | 对应问题 |
| --- | --------------------------------- | ---- |
| P0  | 生成/执行幂等租约 + 终态短路 + 重复投递测试         | S1   |
| P0  | 执行产物保留策略与磁盘配额                     | S2   |
| P0  | 升级 cryptography 并回归密钥加解密          | S3   |
| P1  | LLM 退避/限流/降级 + 成本核算               | H2   |
| P1  | 统一 RBAC 依赖 + 继续拆 api.py           | H1   |
| P1  | 结构化日志/指标/告警                       | H3   |
| P1  | 生产数据库备份与 schema 回滚预案              | M4   |
| P2  | CI 补前端单测与覆盖率门槛                    | M3   |
| P2  | 前端 token 迁移 HttpOnly Cookie / CSP | M1   |
| P2  | 轮询退避，逐步转 SSE                      | M2   |
| P2  | 回填旧优化文档勾选状态                       | 二    |

---

## 六、诚实边界（未验证）

- 未运行服务与真实模型，S1/S2 的运行时复现依赖子代理的源码证据，落地前建议先加一条最小复现测试。
- 未核对 `frontend/src` 全部 `setInterval` 的 `onUnmounted` 清理是否齐全（已见 `pollTimer/timer` 变量，大概率已处理，但未逐处确认）。
- 未审计 `.env` 明文值、nginx TLS 终止配置与生产 `IMAGE_TAG` 是否滥用 `latest`（本地 compose 无 tag，生产有 `${IMAGE_TAG:-latest}` 兜底）。
