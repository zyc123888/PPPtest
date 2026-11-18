# OminiTest 全量功能可用性与交互体验深度评估报告

**评估日期**：2026-11-18  
**评估范围**：OminiTest 前端全部视图（21 个 Vue 页面）与后端全量路由、执行引擎（`api.py`、`project_workspace_api.py`、`tasks/executions.py`、`midscene_runner.js` 等）  
**核心结论**：项目呈现出明显的**“重门面铺设、轻闭环打通”**特征。侧边栏与界面模块表面完整，但存在大量**写死 `disabled` 的空壳按钮**、**前后端契约矛盾（操作必报 400/500）**以及**在关键节点断头的业务链路**。

---

## 一、还不到可用 / 空架子外表 / 运行必挂的“假功能”与断头路（10 项，P0）

| 序号 | 模块与功能 | 现状与“空架子”表现 | 根因定位与代码证据 |
| :--- | :--- | :--- | :--- |
| **1** | **AI 用例生成（V1 & V2）结果无法入库** | **“造完即孤岛”**：V1 和 V2 耗费大量 Token 解析文档、提炼功能点、生成结构化 JSON 用例包（`testcase_package`），但最后**只能下载静态 `.xmind` 文件到本地**，平台内无任何入口将其一键入库到用例中心、转为 API/UI 用例或挂载到项目需求。 | `frontend/src/views/case/generator/index.vue`、`frontend/src/views/case/generator2/index.vue` 仅实现下载 `.xmind`/`.xmindmark`；`backend/app/api.py`（第 2345–3300 行）无将 `CaseGenerationJob` 结果写入 `APICase`/`UICase` 的转换接口。 |
| **2** | **Midscene 视觉引擎无法执行交互动作** | **运行必挂**：UI 用例选择 `Midscene (AI)` 引擎后，只要包含 `click` 或 `fill` 步骤，运行时 100% 报错退出；即使仅执行 `open_url` + `assert_ai` 成功，HTML 报告也经常抓不到。 | 1. `backend/app/tasks/executions.py`（第 1701–1723 行）与 `backend/midscene/midscene_runner.js`（第 230–234 行）漏传了 `@midscene/core@1.10.8` 强制要求的 `MIDSCENE_MODEL_FAMILY`。<br>2. `midscene_runner.js`（第 292–310 行）在 `agent.destroy()` 落盘报告**之前**即扫描目录，时序颠倒。 |
| **3** | **API 用例“即时调试（Send）”不支持多步场景与数据集** | **假调试**：在接口用例编辑器切到「场景编排（Scenario）」配置多步接口或「数据驱动（Datasets）」时，右侧仍常驻 `Send` 面板。但点击 `Send` **完全忽略场景步骤和数据集**，只请求顶层单接口的 `method` + `path`。 | `frontend/src/views/case/api/index.vue`（第 1280–1299 行 `runQuickDebug`）与 `backend/app/api.py`（第 3575–3660 行 `debug_api_case`）仅读取顶层 `payload.method` / `payload.path`，未解析 `steps_json` 和 `datasets_json`。 |
| **4** | **用例中心「批量评审」前后端死锁** | **点确认必报 400**：勾选「草稿（DRAFT）」用例点击「批量评审」，弹窗默认选中 `IN_REVIEW` 并提供 4 个状态选项。点确定后后端直接报错 `400 批量评审仅支持通过或拒绝`；选 `APPROVED` 又报 `400 仅待评审状态用例允许执行通过或拒绝`，且全系统无批量提交待评审入口。 | 前端 `frontend/src/views/case/index.vue`（第 247–254、344 行）默认 `IN_REVIEW`；后端 `backend/app/api.py`（第 3468–3480 行 `batch_review_cases`）硬性拦截非 `APPROVED/REJECTED` 目标态及非 `IN_REVIEW` 初始态。 |
| **5** | **环境「校验」与执行「重跑」漏算项目变量池** | **误报预检失败**：只要用例使用了「项目变量池」或内置动态变量（`{{timestamp}}`、`{{uuid}}`、`{{random_int}}`），在环境管理页点「校验」或执行中心点「重跑」会**直接报错 400 缺失变量**。 | 正常执行调用 `build_variable_context(project, environment)`；但环境校验 `backend/app/api.py`（第 404–459、490 行）与重跑 `rerun_execution`（第 6365 行）仅拿 `env.variables_json` 校验，漏掉项目级变量与动态变量。 |
| **6** | **测试计划不支持性能用例，塞入后执行必败** | **半截管道**：用例中心可勾选 `PERF` 用例批量加入计划，但测试计划仅认 `API` 和 `UI`；一旦执行包含 `PERF` 用例的计划，直接落入 `else` 分支判定为 `FAILED（未知用例类型）`。 | `frontend/src/views/plan/index.vue`（第 118–123 行）、`backend/app/api.py`（第 5683–5686 行）及 `backend/app/tasks/executions.py`（第 2195–2219 行）均未接入 `PerformanceCase`。 |
| **7** | **项目管理、工作空间、测试计划均无「编辑」功能** | **建完即锁死**：项目一旦创建，如果 `base_url` 填错或需改名，**全系统没有任何界面可以修改**（项目工作台设置页也是纯只读）。工作空间与测试计划同样只能新增和删除，无法编辑。 | `frontend/src/views/project/index.vue`、`frontend/src/views/project/workspace/Settings.vue`（第 68–76 行 `el-descriptions`）、`frontend/src/views/workspace/index.vue`、`frontend/src/views/plan/index.vue` 均无编辑入口。 |
| **8** | **多处写死 `disabled` 的“纯装饰假按钮”** | 1. 项目管理页工具栏「更多 -> 导入 / 导出」写死禁用。<br>2. API 编辑器 `form-data` 的 `File（未启用）` 写死禁用；`binary` 模式无文件选择器，只能手填 Base64。<br>3. 顶部导航栏写死绿色标签 `前端在线`，无健康度探针。 | 1. `frontend/src/views/project/index.vue`（第 46–57 行）<br>2. `frontend/src/views/case/api/index.vue`（第 285–312、344–356 行）<br>3. `frontend/src/layout/components/Header.vue`（第 19 行） |
| **9** | **迭代「燃尽图（Burndown）」根本不是图** | **挂羊头卖狗肉**：工作台「迭代（Iterations）」页代码类名和接口都叫 `burndown`，但界面上没有按日期演进的理想线与实际折线图，**仅有一个静态 `<el-progress>` 进度条**。 | `frontend/src/views/project/workspace/Iterations.vue`（第 26–39 行）与 `backend/app/project_workspace_api.py`（第 402–425 行）仅返回当前任务完成数，无时间序列统计。 |
| **10** | **用例「历史版本对比（Diff）」形同虚设** | **假快照对比**：前端写了对比 `steps_json`、`headers_json`、`body_json`、`assertions_json`、`concurrency` 的 Diff 逻辑，但展示出来永远是空对比——后端快照根本没存这些字段，还把 `PerformanceCase` 类型写死存成了 `"UI"`。 | `backend/app/api.py`（第 1184–1209 行 `_case_snapshot`）仅保存基础表头字段，且第 1186 行写死 `"API" if isinstance(case, APICase) else "UI"`；前端 `case/index.vue`（第 572–608 行）因此失效。 |

---

## 二、实现得不好、逻辑半吊子、急需优化修改的后端与业务设计（8 项，P1）

1. **删除项目（`delete_project`）漏删 13 张关联表，极易报 500 外键冲突或留满库脏数据**
   - `backend/app/api.py`（第 1692–1708 行）只手动删除了 `TestPlan`、`TestRun`、`APICase`、`UICase`、`Environment` 等基础表，完全漏删 `PerformanceCase`、`UIBatchRun`、`CaseChangeHistory`、`CaseGenerationJob`、`CaseGenerationV2Job`、`ProjectMember`、`ProjectNotificationSetting`、`Iteration`、`Requirement`、`ProjectTask`、`Defect`、`DefectRecord`、`Activity`。
2. **项目权限模型的“创建人自我踢出”怪癖**
   - `backend/app/api.py`（第 166–185 行 `_can_access_project` 与第 1663 行 `create_project`）：创建项目时未将创建人自动插入 `ProjectMember` 作为 `owner`。一旦有人在项目设置里添加首个成员，项目从“无成员公开模式”切换为“显式成员隔离模式”，原创建人若未被顺手加入，会瞬间失去自己创建的项目的访问权限。
3. **取消执行（`cancel_execution`）是“表面改状态”，无法真正终止后台进程**
   - `backend/app/api.py`（第 6445–6472 行）与 `backend/app/tasks/executions.py`：由测试计划或 UI 批量触发的子 `TestRun.task_id` 为 `None`，调用取消接口不会发送任何 `revoke`；同时 Worker 使用 `--pool=solo` 且多步执行中未轮询数据库 `run.status == "CANCELLED"`，后台浏览器与大模型仍会继续运行并覆写状态。
4. **两套完全割裂的缺陷表（`Defect` vs `DefectRecord`）并存**
   - `backend/app/models.py` 中同时存在工作台看板使用的 `Defect`（严重度 `BLOCKER/CRITICAL/MAJOR/MINOR`）与报告弹窗（`frontend/src/views/report/index.vue` 第 285–326 行）使用的 `DefectRecord`（严重度 `P0/P1/P2/P3`），两端数据与生命周期完全不通。
5. **性能测试引擎（`PerformanceCase`）未复用连接池 + 单行 JSON 塞爆数据库**
   - `backend/app/tasks/executions.py`（第 714–868 行）：`perform_request()` 每次请求都新建并销毁 `httpx.Client()`（第 742 行），未复用 Keep-Alive 连接池，测出大量建连/TLS 握手耗时；且将多达 1,000 次请求明细全塞入 `TestRun` 单行的 `step_results_json` 与 `response_payload` 中。
6. **内置 Mock 服务同步 `time.sleep` 阻塞线程 + 不支持路径参数**
   - `backend/app/api.py`（第 1267–1306 行 `mock_service`）使用同步函数直接调用 `time.sleep(delay_ms / 1000)` 阻塞 FastAPI 线程池；路径匹配仅做字符串精确相等，不支持 `/api/users/{id}`，也未校验用例是否处于 `ACTIVE` 状态。
7. **更新接口用例（`update_api_case`）版本签名漏算字段**
   - `backend/app/api.py`（第 3853–3889 行）计算 `original_signature` 与 `next_signature` 时漏掉 `datasets_json`、`mock_enabled`、`mock_config_json`，单独修改数据集或 Mock 配置不会递增版本号或记录历史。
8. **主业务列表全部采用“后端全表返回 + 前端 `.slice()` 假分页”**
   - `/cases`、`/api-cases`、`/ui-cases`、`/performance-cases`、`/test-plans`、`/reports`、`/executions/runs` 均未实现服务端分页（`OFFSET/LIMIT` + `total`），随数据量增长接口体积与耗时将线性恶化。

---

## 三、前端交互体验很差、反直觉、存在 Bug 的 UI/UX 痛点（8 项，P2）

1. **项目协同看板分页与看板视图严重冲突（超 50 条任务消失）**
   - `Requirements.vue`、`Tasks.vue`、`Defects.vue` 切换到看板视图时直接拿当前页 50 条数据按列分组，列头计数只是当前页数量；`Tasks.vue`（第 18–26 行）在 `board` 视图下甚至隐藏了分页器，第 51 条以后的任务彻底不可见；`KanbanBoard.vue`（第 71 行）禁止同列内上下拖拽排序。
2. **「用例中心」点击跳转子页面完全丢失上下文**
   - `frontend/src/views/case/index.vue`（第 522–534 行 `openDetail`）仅裸跳 `router.push('/case/api')` 等路径，未携带 `project_id` 和 `case_id`，跳过去后用户仍需重新筛选查找；顶部「新增」按钮同理不会自动打开新建弹窗。
3. **API 用例编辑器（147KB 单文件巨石组件）布局反直觉且无未保存保护**
   - `frontend/src/views/case/api/index.vue`：必填的「所属项目（`project_id`）」藏在最底部的默认折叠面板 `el-collapse`（第 570 行）里；切到「场景编排」后 Headers/Body/断言/提取器全部退化为 4 个裸 `textarea` JSON 输入框；弹窗未配置 `before-close` 脏数据拦截，误触遮罩或 `ESC` 直接丢失编辑内容。
4. **测试计划「移除筛选结果」前端串行 `for...of` 删除且权限倒挂**
   - `frontend/src/views/plan/index.vue`（第 198、558–560 行）与 `backend/app/api.py`（第 5787 行）：测试人员（`tester`）能加用例进计划，但移除用例却要求 `admin` 权限；点击「移除筛选结果」采用前端串行 `for...of` 逐条调 `DELETE`，批量操作极慢且卡顿。
5. **UI 编辑器切换 `Midscene` 引擎时错误隐藏「禁止操作（Prohibited Actions）」**
   - `frontend/src/views/case/ui/index.vue`（第 289–316 行）写了 `v-if="temp.engine !== 'midscene'"`，把前端输入框藏了起来，而后端 `midscene_runner.js`（第 118–136 行）明明完整支持 `prohibitedActions` 安全护栏校验。
6. **工作台（Dashboard）无节制 5 秒高频轮询导致按钮闪烁**
   - `frontend/src/views/dashboard/index.vue`（第 348 行）每 5 秒无条件并发请求 3 个接口，未判断 `document.visibilityState`，且每次都置 `loading.value = true` 导致右上角按钮周期性闪烁。
7. **迭代页（Iterations）列表加载存在 N+1 并发请求风暴**
   - `frontend/src/views/project/workspace/Iterations.vue`（第 108–112 行）拉取列表后用 `.map` 并发发起 N 个 `/burndown` 请求，本应由列表接口直接聚合返回。
8. **常用工具箱（Tools）简单字符串处理走后端 HTTP 请求**
   - `frontend/src/views/tools/index.vue`（第 240–270 行）将 `JSON 格式化`、`Base64 编解码`、`哈希计算` 发送到后端 `/tools/...` 接口处理，既增加延迟又有敏感报文外泄隐患。

---

## 四、修复与改造优先级路线图

1. **阶段一：止血级 P0 修复（1~2 天，立刻恢复核心功能可用）**
   - 补齐 Midscene `MIDSCENE_MODEL_FAMILY` 透传并修正 `agent.destroy()` 报告落盘时序；放开前端 `prohibited_actions` 输入框。
   - 在 `_validate_environment_usage` 与 `rerun_execution` 中统一使用 `build_variable_context(project, environment)`。
   - 打通 `/cases/batch-review` 批量提交待评审流程，对齐前后端状态枚举。
   - 补齐 `create_project` 创建人自动入组、`delete_project` 全量级联清理及 `_case_snapshot` 完整字段快照。
2. **阶段二：打通核心业务断头路（2~3 天，消除“孤岛功能”）**
   - 为 AI 用例生成（V1 & V2）增加「一键入库到平台用例库 / 关联项目需求」闭环。
   - 补齐项目、工作空间、测试计划的「编辑」能力，清理所有写死 `disabled` 的装饰假按钮。
   - 让 API「即时调试」支持多步场景与数据集，测试计划支持接入 `PERF` 性能用例。
3. **阶段三：重构前端交互痛点（2~3 天，提升日常使用体验）**
   - 用例中心跳转携带 `?project_id=xx&case_id=xx` 并自动打开编辑器；重构 API 编辑器必填项位置与关闭保护。
   - 修复看板分页丢失与同列拖拽排序；修正测试计划移除用例权限并提供批量删除接口；优化工作台轮询与迭代页 N+1 请求。
4. **阶段四：底层性能与架构收敛**
   - 合并 `Defect` 与 `DefectRecord`；复用性能压测 `httpx.Client` 连接池；Mock 服务改为 `async def`；全量业务列表切换服务端真实分页。
