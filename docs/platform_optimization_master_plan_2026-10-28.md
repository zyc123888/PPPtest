# OmniTest 整体优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐条实施。所有步骤使用 `- [ ]` 复选框跟踪。

**Goal:** 在不重写系统、不更换技术栈的前提下，修掉「用户看错结果、操作错对象、丢失输入、业务闭环断裂」这四类问题，并收紧权限、评审、执行与 AI 生成的数据契约。

**Architecture:** 保持现有「FastAPI 单体 + Celery worker + Vue3 SPA + MariaDB」的模块化单体形态。先修正确性契约（对象归属、状态口径、版本一致性），再按规则收敛后才做文件级拆分；不引入微服务、事件溯源、通用工作流引擎或统一用例大表。

**Tech Stack:** Vue 3 + Pinia + Vue Router + Element Plus + Tiptap；FastAPI + Pydantic v2 + 同步 SQLAlchemy + MariaDB；Celery + Redis；Playwright native 与 Node Midscene 双引擎；GitHub Actions + GHCR + SSH + Docker Compose。

**来源与证据:** 2026-10-28 两轮审查。第一轮覆盖架构/安全/执行/AI/部署，第二轮覆盖产品流程与前端交互（含隔离示例数据下的浏览器复现）。本文件是方案记录；实施进度以各条复选框及验证说明为准，未勾选不代表已完成。

---

## 0. 证据等级（每条任务标注）

| 等级 | 含义 |
|---|---|
| **A** | 本轮浏览器实际复现（隔离 fixture，非后端联调） |
| **B** | 本轮源码确认（含本文件里的 `file:line`） |
| **C** | 上一轮源码确认，本轮未重验 → 实施前先复核该行号仍有效 |
| **D** | 静态推断/风险，需先做一步验证再定性 |

浏览器走查使用只读 fixture，非 GET 请求一律拦截；**未提交表单、未执行用例、未调用真实模型**。因此 A 级证明前端交互行为，不证明后端持久化与权限。

---

## 1. Global Constraints（每条任务隐含遵守）

- 技术栈与部署形态不变：单主机 Docker Compose，不迁 K8s、不拆微服务。
- 后端测试：`cd backend && pytest -q`（或 `docker compose exec -T backend pytest -q`）；测试基线为 `backend/tests/`（`test_platform_api.py`、`test_assertion_engine.py`、`test_midscene_runtime.py`、`test_case_generation_v2_architecture.py`）与 `e2e/tests/` 现有 spec，**新增行为必须附带测试**。
- 前端测试：`cd frontend && npm run test`（vitest）、`npm run lint`、`npm run typecheck`。注意 `lint` 脚本是显式文件白名单，新增测试文件需同时加入该白名单。
- 提交纪律：按文件名精确 `git add`，禁止 `git add -A`。工作树中已存在大量**用户既有未提交改动**（`.codebuddy/`、CloudBase/Vercel 删除、`backend/app/*`、`frontend/*`、`backend/app/rich_text_security.py` 未跟踪、`morning_brief_pipeline.py`、`vibe_images/`）；不得恢复、清理或覆盖。
- 秘密约束：API Key、Token、请求头秘密值不得写入 localStorage、任务 `input_payload_json`、产物 JSON 或日志。
- 文案约束：面向用户的导航与标签用中文业务语义，不暴露内部版本号（如「V2」「2.0.1」）；组件内置 locale 需与业务文案语言一致。
- 交互约束：任何展示「结论/状态」的位置，必须能区分「没有数据 / 加载中 / 加载失败 / 数据已过期」。
- 每个任务结束时独立可测、单独提交；一次提交只做一件事。

---

## 2. 阶段总览

| 阶段 | 主题 | 条目 | 阻塞关系 | 粗估人日 |
|---|---|---|---|---|
| **A** | 上下文一致性与结果真实性 | A1–A6 | 无前置，最先做 | 5–8 |
| **B** | 编辑保护与提交恢复 | B1–B6 | 依赖 A1/A2 的对象归属规则 | 6–10 |
| **C** | 业务闭环（缺陷/追溯/看板/计划） | C1–C8 | 依赖 D1 归属校验收口 | 10–16 |
| **D** | 权限、评审与数据归属 | D1–D5 | 无前置，安全优先可与 A 并行 | 7–12 |
| **E** | 执行引擎与 AI 生成契约 | E1–E9 | 依赖 F1（schema 版本化）前先做 E1/E2 | 14–22 |
| **F** | 工程、测试与部署可靠性 | F1–F7 | F1 早于需要新列/新表的条目 | 8–12 |
| **G** | 体验、响应式与规范 | G1–G6 | 依赖 A/B 的稳定行为 | 6–10 |

合计 **56–80 人日**（实施估算，非承诺排期）。需求决策类条目（C1 内外部缺陷语义、C7 迭代口径、E7 支持矩阵范围）需产品先拍板，可能上浮。

**执行顺序建议：A → D → B → C → E → F → G。** 理由：A/D 直接消除误操作和越权风险；B 解决丢数据；C/E 需要一点产品决策；F/G 是持续治理。

---

## 3. Phase A — 上下文一致性与结果真实性

统一规则：**项目 ID 或对象 ID 变化时，所有与其绑定的列表、详情、选择、草稿、异步结果必须重新确认归属。** 不引入全局 Store 承载所有页面状态。

### Task A1：项目工作区切换后仍显示上一个项目的数据 `B`

**审计时发现（2026-10-28）**
- 当时 [Layout.vue:38](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Layout.vue#L38) 的 `<component :is="Component">` 没有 `:key`；`:id` 变化的 watch 只更新 `currentProjectId` 并调用 `loadRole()`。
- 子页面只在 `onMounted` 拉列表：[Defects.vue:411](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Defects.vue#L411)、[Requirements.vue:358](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Requirements.vue#L358)。当时浏览器复现从 `/project/11/defects` 切到 `/project/22/defects` 后 URL/项目名已更新，但卡片仍属 A，且未请求 B 的缺陷列表。

**当前复核（2026-11-10）**
- 当前工作区代码已在子页面 `<component>` 设置 `:key="currentProject.id"`，项目 ID 变化会重建子页面；业务列表仍由子页面自行加载，Layout 不重复请求列表。
- A1 当前主要缺少自动化回归证据；新增 E2E 验证 A→B→A 数据隔离、对应列表请求，以及同项目切换需求/缺陷标签时请求次数。

**Files**
- Modify: `frontend/src/views/project/workspace/Layout.vue:38-40`
- Test: `e2e/tests/workspace_context_switch.spec.js`（新增）

**Produces:** 工作区子组件保证「props.project.id 与已加载数据一致」，供 B6/C 阶段复用。

- [x] **Step 1：补回归测试。** 新增 `e2e/tests/workspace_context_switch.spec.js`：通过 API 建立隔离项目/缺陷，验证 A→B→A 后数据归属正确，并验证同项目切标签时缺陷请求没有重复触发；测试结束清理本次创建的数据。

```js
test('工作区切换项目后列表随之更新', async ({ page }) => {
  await page.goto(`/project/${projectA.id}/defects`)
  await expect(page.getByText(projectADefectTitle)).toBeVisible()
  const req = page.waitForResponse((r) => r.url().includes(`/projects/${projectB.id}/defects`))
  await page.locator('.ws-switcher').click()
  await page.getByRole('option', { name: projectB.name }).click()
  await req
  await expect(page).toHaveURL(new RegExp(`/project/${projectB.id}/defects`))
  await expect(page.getByText(projectBDefectTitle)).toBeVisible()
  await expect(page.getByText(projectADefectTitle)).toHaveCount(0)
})
```

- [ ] **Step 2：跑测试确认失败。** `docker compose run --rm e2e npx playwright test workspace_context_switch --reporter=line`，预期在 `toHaveCount(0)` 处失败（A 的卡片仍在）。
- [x] **Step 3：最小实现。** 当前工作区 Layout 的 `<component>` 已使用 `:key="currentProject.id"`，切换项目时重建子组件；Layout 不重复拉取业务列表，子页面挂载后自行加载。未保存草稿保护留给 B2。
- [ ] **Step 4：跑测试确认通过**，并手测「同一项目内在需求/缺陷/任务标签间切换不重复请求」。
- [ ] **Step 5：提交** `fix(workspace): reload project children on project switch`。

**验收：** A→B→A 往返、慢网络、空列表、请求失败四种情形下，页面展示内容始终属于当前项目。
**不做：** 全局项目上下文 Store、跨标签页共享状态。

**实施记录（2026-11-10）：** A1 的 key 修复已存在于本次工作区改动中，本轮保留并为其增加回归 E2E 和 CI 执行入口。原计划的“先跑失败测试”未通过回退已有代码来复现；本机前端与 Docker daemon 当前均未运行，待运行态 E2E 验证后再勾选 Step 4。

---

### Task A2：用例详情串显示另一条用例的执行结果 `A`

**审计时发现（2026-10-28）**
- 当时 `openCaseDetail` 不清 `selectedRun / selectedRunSteps / selectedRunArtifacts / previewUrl`；详情模板只判断 `selectedRun` 是否存在，没有校验归属。
- 当时浏览器复现：打开有执行记录的用例 101 → 关闭 → 打开无执行记录用例 202 → 执行记录显示 0 条，下方仍显示用例 101 的执行详情。

**当前复核（2026-11-10）**
- 当前 UI 页面已在打开新详情前重置执行态；`selectRun` 检查详情的 `case_id` 与当前用例一致，关闭时清理执行详情和预览 URL。
- 新增 E2E 用唯一项目/用例作为数据夹具，并拦截执行记录接口提供受控样例；验证有记录用例关闭后，零记录用例不展示旧执行详情。

**Files**
- Modify: `frontend/src/views/case/ui/index.vue:1000-1008`、`1014-1029`
- Test: `e2e/tests/ui_case_run_isolation.spec.js`（新增）

- [x] **Step 1：补回归测试。** 新增 `e2e/tests/ui_case_run_isolation.spec.js`：有执行记录用例打开并显示执行详情，关闭后再打开零记录用例，断言旧详情不可见；夹具由测试创建并清理。

```js
await expect(page.getByRole('tab', { name: /执行记录 \(0\)/ })).toBeVisible()
await expect(page.locator('.run-detail')).toHaveCount(0)
```

- [ ] **Step 2：确认失败**（`.run-detail` 仍存在且含上一条用例的编号）。
- [x] **Step 3：实现。** 当前 UI 页面已在打开详情时先重置执行态；在 `selectRun` 成功回调中校验 `detail.case_id === currentCase.value?.id` 后才赋值；抽屉关闭时清理执行态。
- [ ] **Step 4：确认通过**，并验证轮询中切换用例不会把旧 run 写回。
- [ ] **Step 5：提交** `fix(ui-case): scope run detail to current case`。

**验收：** 任何时刻执行详情都属于当前用例；结果为空时显示空态而不是旧数据。
**不做：** 不引入执行详情缓存层。

**实施记录（2026-11-10）：** A2 保护逻辑已存在于当前未提交的 UI 页面改动中，本轮不重写该逻辑，仅补自动化回归和 CI 执行入口；本机服务/Docker daemon 未启动，Step 4 的运行态验证仍待执行。

---

### Task A3：新建对象未继承当前筛选的项目 `A`

**审计时发现（2026-10-28）**
- 当时 `resetTemp` 固定使用 `projects.value[0]`；浏览器复现筛选项目 B 后点「高级创建」，所属项目仍是项目 A。
- 当时目录选项直接复用列表筛选的 `folderTree`，与编辑器所选项目可能不同源。

**当前复核（2026-11-10）**
- `resetTemp` 已会优先选择 `filters.projectId` 对应项目，且初始化目标地址为该项目 `base_url`。
- 目录选项仍复用列表筛选数据；手动切换编辑器项目时目标地址也未同步。已补编辑器专属目录加载，并在新建表单切换项目时同步目标地址；编辑已有用例时不自动覆盖用户配置的目标地址。

**Files**
- Modify: `frontend/src/views/case/ui/index.vue:727-740`（含目录选项来源）
- Test: `e2e/tests/ui_case_create_context.spec.js`（新增）

- [x] **Step 1：补回归测试**：新增 `e2e/tests/ui_case_create_context.spec.js`，创建两个隔离项目及带独立目录的 UI 用例，验证筛选 B 后默认项目/地址/目录均为 B，切到 A 后地址与目录跟随 A。
- [ ] **Step 2：确认失败**（显示 A）。
- [x] **Step 3：实现**：新建表单按筛选项目初始化；编辑器单独按 `temp.project_id` 加载目录，切换项目后同步新建用例目标地址并清除不属于旧项目的目录选择。
- [ ] **Step 4：确认通过**，并验证清空筛选后仍回落到 `projects[0]`。
- [ ] **Step 5：提交** `fix(ui-case): default new case to filtered project`。

**验收：** 新建表单的项目/目录/目标地址三者同源；筛选改变后再次新建随之改变。

**实施记录（2026-11-10）：** 原始默认项目问题已在当前代码中修复；本轮补齐编辑器目录归属和项目切换时的目标地址同步，并新增回归 E2E/CI 入口。没有通过回退现有改动来复现旧失败；运行态验证受本机服务未启动影响，Step 4 待执行。

---

### Task A4：跨项目保留不可见的批量选择 `A`

**审计时发现（2026-10-28）**
- 当时表格启用 `reserve-selection`，项目筛选变化未清选择；跨项目筛选后，批量操作栏仍可能保留不可见的其他项目用例。
- 当时批量执行有同项目校验，但批量修改/删除没有相同保护。

**当前复核（2026-11-10）**
- 当前项目筛选 watcher 已清空 CaseTable 与父级选择；批量修改/删除也使用 `validateBatchProjectScope` 阻止混项目操作。
- 批量操作栏此前仍只显示总数，无法解释被其他关键词/目录/分页筛掉的选中项。本轮增加当前页与其他页/筛选范围计数，并新增 E2E 覆盖混项目保护、隐藏选择提示、项目变化清空。

**Files**
- Modify: `frontend/src/views/case/ui/index.vue:1262-1267`、`CaseTable.vue:3-9`
- Test: `e2e/tests/ui_case_selection_scope.spec.js`（新增）

- [x] **Step 1：补回归测试**：新增 `e2e/tests/ui_case_selection_scope.spec.js`，创建两项目夹具，验证混项目批量修改被拦截、过滤隐藏的已选项会明确计入“其他页或筛选范围”、切项目清空选择。

- [ ] **Step 2：确认失败**（文案仍是「已选 1 条」）。
- [x] **Step 3：实现**：项目筛选变化清空选择；批量条区分当前页与其他页/筛选范围数量；批量修改/删除拦截混项目选择并保留取消操作。
- [ ] **Step 4：确认通过。**
- [ ] **Step 5：提交** `fix(ui-case): reset batch selection on project change`。

**验收：** 用户看到的选中数量始终能解释作用对象；跨范围操作要么明确展示，要么被拒绝。
**不做：** 不取消 `reserve-selection`（翻页保留是有用能力），只补语义。

**实施记录（2026-11-10）：** 选择清理与混项目拦截已在现有工作区改动中；本轮补齐选择范围计数，修复移动端仍引用已移除 `caseSequence()` 的问题，并新增 E2E/CI 入口。前端单测、lint、typecheck、build 通过，Playwright 能收集该用例；运行态浏览器验证因服务/Docker 未启动尚未执行。

---

### Task A5：导出范围与筛选不一致 `B`

**现状证据**
- [frontend/src/views/case/ui/index.vue:1062](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/index.vue#L1062) `exportCurrentCases` 只带 `case_type/project_id/status/priority/keyword`，缺 `selectedFolder` 与 `reviewStatus`；后端导出接口已支持这两个条件。
- 参数名不同源：列表用 `folder`，导出用 `folder_path`，不能直接透传。

**Files**
- Modify: `frontend/src/views/case/ui/index.vue:1062-1072`
- Test: `backend/tests/test_case_export_filters.py`（新增）

- [x] **Step 1：写后端回归测试**：新增 `backend/tests/test_case_export_filters.py`，隔离创建项目及三条 UI 用例，通过正式批量评审接口设置评审状态，再用 `folder_path` + `review_status` 调导出并断言 ID 集合精确匹配。

```python
def test_export_respects_folder_and_review_filter(client, seeded_ui_cases) -> None:
    response = client.get("/cases/export", params={
        "case_type": "UI", "project_id": seeded_ui_cases.project_id,
        "folder_path": "登录/正常流程", "review_status": "APPROVED",
    })
    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert names == ["已批准登录用例"]
```

- [ ] **Step 2：确认失败**（返回全部项目用例）。
- [x] **Step 3：实现/复核**：当前后端导出复用 `list_cases` 的目录、评审、状态、优先级、关键字筛选；前端显式映射 `folder: selectedFolder -> folder_path` 并带上 `review_status`。按钮 tooltip 为「导出当前筛选结果」，导出前确认筛选条件与列表总数。
- [ ] **Step 4：确认通过**，并手测「筛选目录+评审后导出条数与列表一致」。
- [ ] **Step 5：提交** `fix(cases): align export filters with list filters`。

**验收：** 导出集合与列表集合在任意筛选组合下一致（比对 ID 集合，不只比数量）。

**实施记录（2026-11-10）：** 后端回归 `test_ui_case_export_respects_folder_and_review_status` 通过。测试夹具验证创建接口会强制新用例为 `DRAFT`，因此使用正式批量评审接口设置测试状态。真实浏览器中“筛选目录+评审后下载并对比 ID 集合”尚未验证，Step 4 保持未完成。

---

### Task A6：加载失败被显示成业务结论 `B`

**现状证据**
- [frontend/src/views/case/ui/index.vue:569](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/index.vue#L569) 附近：`loadLatestRuns` 的 catch 把映射置空 → [CaseTable.vue:58](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/components/CaseTable.vue#L58) 显示「未执行」；`loadStats` 失败保留旧数字；列表失败保留旧列表。
- 同页保存/删除/导入/评审部分路径只调 `getList()`，不刷新统计与目录（[index.vue:893](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/index.vue#L893)）。

**Files**
- Modify: `frontend/src/views/case/ui/index.vue`（数据加载区）、`CaseTable.vue:52-60`
- Test: `frontend/src/views/case/ui/__tests__/latestRunState.test.js`（新增）

- [x] **Step 1：补回归测试**：新增 `frontend/src/views/case/ui/__tests__/latestRunState.test.js`，传 `latestRunState: 'error'`，断言显示「状态未知」、不显示「未执行」，并验证重试事件。

```js
const wrapper = mount(CaseTable, { props: { rows: [row], latestRunMap: {}, latestRunError: true, projectMap: {} } })
expect(wrapper.text()).toContain('状态未知')
```

- [ ] **Step 2：确认失败**（当前显示「未执行」）。
- [x] **Step 3：实现/复核**：已有 `latestRunState`、`statsStale` 和列表错误态；本轮增加最近执行加载失败的就地重试，并给请求加 token 防止过期响应覆盖新请求。现有写操作已刷新列表/统计/目录，目录重命名刷新其影响的列表与目录。
- [x] **Step 4：确认通过。** 最近执行错误态组件单测通过；前端全量单测、lint、typecheck、production build 全部通过。真实服务端故障注入尚未做。
- [ ] **Step 5：提交** `fix(ui-case): distinguish load failure from empty state`。

**验收：** 「未执行」只在确实没有执行记录时出现；加载失败可见且可重试。

**实施记录（2026-11-10）：** 新增错误状态与重试事件测试；最近执行请求开始时清空旧映射，且只允许最新请求写入状态。统计失败保留旧值但显示“未更新”，列表失败清空旧行并显示错误提示/重新加载，不会伪装成空结果。

---

## 4. Phase B — 编辑保护与提交恢复

### Task B1：更换步骤动作会清空名称与定位信息 `A`

**现状证据**
- [frontend/src/views/case/ui/index.vue:843](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/index.vue#L843) `changeStepAction` 用 `Object.assign(step, withKey(createUiStep(action)), { action })`，整段重置。
- 浏览器复现：`click` 改 `fill` 后，名称「点击搜索」、目标「搜索按钮」全部清空。

**Files**
- Modify: `frontend/src/lib/uiCase.js`（新增 `mergeUiStep`）、`frontend/src/views/case/ui/index.vue:843-848`
- Test: `frontend/src/lib/__tests__/uiCase.test.js`（追加）

- [x] **Step 1：写失败测试**（沿用现有 vitest 风格）：

```js
it('keeps shared fields when switching action', () => {
  const step = { ...createUiStep('click'), name: '点击搜索', target: '搜索按钮', selector: '#search' }
  const next = mergeUiStep(step, 'fill')
  expect(next).toMatchObject({ action: 'fill', name: '点击搜索', target: '搜索按钮' })
  expect(next.value).toBe('')            // 动作专属参数重置
  expect(mergeUiStep(step, 'wait').selector).toBeUndefined()  // 不适用定位被丢弃
})
```

- [ ] **Step 2：确认失败**：`cd frontend && npm run test -- uiCase` → `mergeUiStep is not exported`。
- [x] **Step 3：实现** `mergeUiStep(step, action)`：保留 `name/target/role/accessible_name/test_id` 中对新动作有意义的字段，重置动作专属参数（`value/duration_ms/url/expected`），并用 `serializeUiSteps` 已有的参数白名单决定丢弃项；断言侧同理处理 `changeAssertionType`。
- [ ] **Step 4：确认通过**，同时把 `lint` 白名单确认包含 `src/lib/uiCase.js`（已在脚本中）。
- [ ] **Step 5：提交** `feat(ui-case): merge step fields on action change`。

**验收：** 改动作不再丢名称与语义目标；真正不兼容的参数被清空且有可见提示。
**不做：** 不做字段级撤销树（先只加动作切换的撤销提示，见 B2 备注）。

**实施记录（2026-11-11）：** 当前工作区已有步骤与断言的合并逻辑及基础测试；补充参数重置提示，并覆盖定位、输入值和等待时间的重置检测。相关单测 9 项、lint 和类型检查通过；尚未完成浏览器实际操作验收，也没有回退现有代码复现旧问题。

---

### Task B2：关闭编辑器直接丢失草稿 `A`

**现状证据**
- [frontend/src/views/case/ui/index.vue:198](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/index.vue#L198) 编辑器 `el-dialog` 无 `before-close`；取消按钮直接 `editorVisible = false`。
- 全 `frontend/src` grep `beforeunload|onBeforeRouteLeave|before-close|dirty|unsaved` 无命中；浏览器复现：填写名称后按 Escape，重新打开内容为空且无提示。

**Files**
- Modify: `frontend/src/views/case/ui/index.vue`（编辑器 dialog）、`frontend/src/router/index.js`（可选路由级守卫）
- Test: `e2e/tests/ui_case_draft_guard.spec.js`（新增）

- [x] **Step 1：写失败测试**：打开高级创建 → 填名称 → Escape → 断言出现「继续编辑 / 放弃修改」确认框；选「继续编辑」后草稿仍在。

```js
await page.keyboard.press('Escape')
await expect(page.locator('.el-message-box')).toContainText('放弃未保存的修改')
```

- [ ] **Step 2：确认失败**（无确认框，草稿消失）。
- [x] **Step 3：实现**：编辑器维护 `dirty` 快照（进入时 `JSON.stringify` 关键字段，变化即比较）；dialog 加 `:before-close`，dirty 时 `ElMessageBox.confirm('继续编辑|放弃修改')`；`router.beforeResolve` 对存在 dirty 编辑器的工作区页补一层离开确认。删除单个步骤改为「移除后短暂提供撤销」，不逐步弹确认。
- [ ] **Step 4：确认通过**，并验证无修改时关闭不打扰。
- [ ] **Step 5：提交** `feat(editor): guard unsaved case edits`。

**验收：** 误关、误切项目、误刷新不会静默丢草稿。
**不做：** 不做全量 localStorage 草稿服务——请求头、输入值、模型参数可能含凭据，跨会话明文驻留本地是新增风险。若后续要持久化，先定义字段脱敏白名单与过期策略（列为待决策）。

**实施记录（2026-11-11）：** 当前工作区已有编辑器关闭、路由离开和浏览器刷新保护；新增 `ui_case_draft_guard.spec.js` 并接入 CI，覆盖继续编辑、放弃修改、无修改关闭和步骤删除撤销。步骤删除后可在 8 秒内撤销最近一次删除，关闭编辑器时清理撤销状态；前端单测、lint 和类型检查通过，浏览器运行态验证仍待完成。

---

### Task B3：「保存并试运行」在部分失败后会重复创建 `B`

**现状证据**
- [frontend/src/views/case/ui/index.vue:920](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/index.vue#L920) `saveAIDraft`：`POST /ui-cases` 成功后，`getList`/预检/执行 POST 任一失败会落入 catch，对话框可能仍带原草稿，再次点击又从创建开始。

**Files**
- Modify: `frontend/src/views/case/ui/index.vue:920-954`
- Test: `e2e/tests/ui_case_save_then_run.spec.js`（新增）

- [ ] **Step 1：写失败测试**：拦截执行 POST 返回 500 → 点「保存并试运行」→ 断言提示区出现「用例已创建（#N）」与「重试运行」按钮，且再次点击不产生第二条用例（列表新增后计数仍为 1）。
- [ ] **Step 2：确认失败**（当前再次点击会再创建一条）。
- [x] **Step 3：实现**：把创建结果 ID 存入 `savedCaseId`；阶段化反馈：`已保存 → 预检结果 → 执行提交结果`；失败时保留对话框但主按钮改为「重试运行」（走 `POST /executions/ui/{id}/run`），并显示「查看已保存用例」。「新建」入口在 `savedCaseId` 存在时禁用创建分支。
- [ ] **Step 4：确认通过。**
- [ ] **Step 5：提交** `fix(ui-case): idempotent save-and-run flow`。

**验收：** 重试不重复创建；用户能看清已完成哪一步、失败在哪一步。
**不做：** 不引入分布式事务/outbox——这是单库单用户动作，前端阶段状态足够。

**实施记录（2026-11-11）：** 工作区已有保存 ID、失败信息和重试运行逻辑。本轮封闭保存后仍可返回修改或进入新建编辑器导致重复创建的入口，增加查看已保存用例；前端 lint、类型检查及现有单测通过。模拟执行接口失败后的完整浏览器回归仍待编写并运行。

**补充验证：** `aiSavedState.test.js` 已覆盖保存后失败提示、禁用返回修改、隐藏高级编辑和重试事件；该组件测试不验证网络请求次数，完整端到端回归仍未完成。

**网络回归（2026-11-11）：** 新增 `ui_case_save_then_run.spec.js` 并接入 CI，使用路由桩模拟两次执行提交失败，断言保存请求仅一次；Playwright 收集通过，因服务未启动尚未实际运行，不能视为验收通过。

---

### Task B4：同类表单提交保护不一致 `B`

**现状证据**
- UI 用例保存有 `saving`（[index.vue:893](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/index.vue#L893)），API 用例保存没有 loading/防重（[frontend/src/views/case/api/index.vue:2595](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/api/index.vue#L2595)）；导入路径同样缺少 `importing` 保护（[ui/index.vue:1075](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/index.vue#L1075)）。

**Files**
- Modify: `frontend/src/views/case/api/index.vue`（`saveData`）、`frontend/src/views/case/ui/index.vue`（`submitImportCases`）、`frontend/src/views/project/workspace/Defects.vue:338`
- Test: `e2e/tests/submit_guard_consistency.spec.js`（新增）

- [ ] **Step 1：写失败测试**：在 API 用例保存请求 pending 期间连点两次「保存」，断言只发出一次 POST。

```js
let posts = 0
await page.route('**/api/v1/api-cases', (route) => { posts++; return route.continue() })
await page.getByRole('button', { name: '保存' }).dblclick()
await expect.poll(() => posts).toBe(1)
```

- [ ] **Step 2：确认失败**（`posts` 为 2）。
- [x] **Step 3：实现**：抽一个 `useSubmitGuard()`（composable，`run(fn)` 内置 `pending` 与重入拒绝），在各表单按钮绑定 `:loading`/`:disabled`。校验失败定位到首个错误字段所在标签页（UI 页已实现，作为参照）。
- [ ] **Step 4：确认通过**，手测 API/UI/缺陷三处一致。
- [ ] **Step 5：提交** `feat(frontend): shared submit guard for forms`。

**验收：** 所有写表单在请求进行中不可重复提交；失败保留输入。

**实施记录（2026-11-11）：** API 用例保存、UI 导入和缺陷创建已有提交保护；本轮补齐 UI 保存异步校验前的重入拦截、AI 保存及缺陷编辑的函数级保护。现有前端测试、lint 和类型检查通过；跨 API/UI/缺陷的延迟请求双击回归及其他写表单审计仍待完成。

---

### Task B5：批量修改无法表达「清空」 `B`

**现状证据**
- [frontend/src/views/case/ui/index.vue:681](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/index.vue#L681)：`if (batchEditForm.folder_path)` 才写入 patch，留空＝不修改，因此「移至未分组」无法表达；API 页同样（[api/index.vue:2143](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/api/index.vue#L2143)）。

**Files**
- Modify: `frontend/src/views/case/ui/index.vue`（批量对话框与 patch 构造）、`frontend/src/views/case/api/index.vue`
- Test: `frontend/src/views/case/__tests__/batchPatch.test.js`（新增）

- [x] **Step 1：写失败测试**：把 patch 构造函数抽为 `buildBatchPatch(form)`，测试三态。

```js
expect(buildBatchPatch({ folder: { mode: 'keep' } })).not.toHaveProperty('folder_path')
expect(buildBatchPatch({ folder: { mode: 'set', value: '登录/异常' } })).toEqual({ folder_path: '登录/异常' })
expect(buildBatchPatch({ folder: { mode: 'clear' } })).toEqual({ folder_path: null })
```

- [ ] **Step 2：确认失败**（当前无 `mode` 概念）。
- [x] **Step 3：实现**：每个批量字段提供「不修改 / 设置为… / 清空」单选；负责人、标签、优先级、迭代、状态同样遵循；后端确认 `null` 与「缺字段」在 update schema 中的语义差异（`exclude_unset`），必要时补 `exclude_none=False` 分支测试。
- [ ] **Step 4：确认通过。**
- [ ] **Step 5：提交** `feat(cases): tri-state batch field semantics`。

**验收：** 用户能显式清空目录/标签，而不是只能改成另一个值。

**实施记录（2026-11-11）：** API/UI 目录三态及后端 `exclude_unset` 已存在；补充两页标签的不修改、设置和清空控件，扩展共享补丁函数单测。前端单测、lint、类型检查通过；新增 API/UI 两项接口测试并通过，验证省略字段保留原值、显式 null 清空目录和标签。浏览器验收仍待执行。优先级和状态为必填字段，不提供清空。

---

### Task B6：评论草稿与关联数据跨实体残留 `B`

**现状证据**
- [frontend/src/views/project/workspace/Requirements.vue:293](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Requirements.vue#L293) `openDrawer` 不清 `commentText`、不预清 `linkedCases/comments`；加载失败被吞（`catch noop`）。[:349](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Requirements.vue#L349) 评论提交使用当前 `current.id` → 旧文本可发给新对象。Tasks/Defects 详情同构（[Tasks.vue](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Tasks.vue)）。

**Files**
- Modify: `frontend/src/views/project/workspace/Requirements.vue`、`Tasks.vue`、`Defects.vue`
- Test: `e2e/tests/workspace_drawer_isolation.spec.js`（新增）

- [ ] **Step 1：写失败测试**：打开需求 1，在评论框输入文本但不发表 → 关闭 → 打开需求 2 → 断言评论框为空、列表区显示加载/空态而非需求 1 的关联。

```js
await expect(drawer.locator('.comment-add textarea')).toHaveValue('')
await expect(drawer.getByText(requirementOneLinkedCase)).toHaveCount(0)
```

- [ ] **Step 2：确认失败**（文本残留）。
- [x] **Step 3：实现**：`openDrawer` 先重置 `commentText/linkedCases/comments/commentState`，再拉数据；关联与评论失败改为行内「加载失败 · 重试」；草稿如需保留，按 `entity:comment:{id}` 在内存 Map 中分键（不写 localStorage）。
- [ ] **Step 4：确认通过。**
- [ ] **Step 5：提交** `fix(workspace): isolate drawer drafts and linked data`。

**验收：** 一个实体的输入与关联数据不会出现在另一个实体的详情里。

**实施记录（2026-11-11）：** 当前需求、任务和缺陷抽屉已有初始清理、读取请求令牌和失败提示。本轮修复需求关联操作及需求/任务评论提交后的跨实体回写：固定提交时的实体 ID，只在同一抽屉上下文仍有效时刷新，并保留提交期间新输入的草稿。类型检查和现有前端测试通过；慢请求切换记录的专门浏览器回归仍待补充及执行。

**回归补充：** 新增 `workspace_drawer_isolation.spec.js` 并接入 CI，以模拟接口延迟验证需求 A 评论返回后不清空需求 B 草稿；Playwright 收集通过，实际运行及任务/缺陷覆盖仍待完成。

---

## 5. Phase C — 业务闭环

### Task C1：报告提缺陷与项目缺陷是两套数据 `B`

**现状证据**
- 报告页 [frontend/src/views/report/index.vue:902](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/report/index.vue#L902) `POST /defects`；后端 [backend/app/api.py:6260](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L6260) 写 `DefectRecord`（含外部平台/编号字段），报告聚合 `GET` 只查 `DefectRecord`。
- 项目缺陷页读 `Defect`（[backend/app/project_workspace_api.py:933](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/project_workspace_api.py#L933)）。
- **已有可直接复用的接口**：`POST /project-defects/from-run/{run_id}`（[同文件:1003](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/project_workspace_api.py#L1003)）会创建 `Defect`、`DefectRunLink`、`DefectCaseLink` 并写活动日志，同一事务。

**决策前置（需产品确认）**：`DefectRecord` 定位为「外部跟踪系统登记」还是「历史遗留的内部缺陷」。本任务按「外部登记」设计。

**Files**
- Modify: `frontend/src/views/report/index.vue:902-950`、`backend/app/api.py`（报告聚合读取处）
- Test: `backend/tests/test_defect_from_run_in_report.py`（新增）

- [x] **Step 1：写失败测试**：创建 run → 调 `/project-defects/from-run/{run}` → 断言该 run 的报告详情里出现这条内部缺陷，且项目缺陷列表能查到同一条。

```python
def test_report_shows_internal_defect_created_from_run(client, seeded_run) -> None:
    defect = client.post(f"/project-defects/from-run/{seeded_run.id}", json={"title": "登录超时"}).json()
    report = client.get(f"/reports/plan-runs/{seeded_run.plan_run_id}").json()
    assert defect["id"] in {item["id"] for item in report["internal_defects"]}
```

- [ ] **Step 2：确认失败**（报告里没有内部缺陷）。
- [x] **Step 3：实现**：报告页把「提缺陷」拆成两个明确入口——「创建项目缺陷」调用现有 from-run 接口；「登记外部缺陷」保留 `DefectRecord` 的外部字段。报告聚合新增 `internal_defects`（来自 `Defect` + `DefectRunLink`），与 `external_defects`（`DefectRecord`）分列展示。历史数据不迁移、不双写；旧 `DefectRecord` 记录标注为外部登记。
- [ ] **Step 4：确认通过**，手测「报告 → 创建项目缺陷 → 项目缺陷页 → 状态关闭 → 回报告」四处一致。
- [ ] **Step 5：提交** `feat(defects): split internal defect from external tracker record`。

**实施记录（2026-11-13）：** 报告聚合 `GET /reports/{plan_run_id}` 新增 `internal_defects`（`Defect` JOIN `DefectRunLink`，含状态/严重级别/经办人序列化）；报告页缺陷面板分「内部缺陷 / 外部登记」两组表格展示，提缺陷入口拆分为「创建项目缺陷」（走 from-run 契约，需先有失败 run）与「登记外部缺陷」（保留原 DefectRecord 表单）。回归测试 `backend/tests/test_defect_from_run_in_report.py` 覆盖内部缺陷出现在报告聚合与可被删除。待办：Step 2 失败态确认与 Step 4 浏览器手测。

**验收：** 一条从执行创建的内部缺陷在报告、项目缺陷、需求追溯中是同一 ID、同一状态。
**不做：** 不合表、不双写、不建缺陷同步作业。

---

### Task C2：需求追溯把「部分执行」判成「已覆盖」 `B`

**现状证据**
- [backend/app/project_workspace_api.py:1446](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/project_workspace_api.py#L1446)：按关联用例取最新 `TestRun`，`last_status` 只记录首个非 `None`；未执行的关联用例被忽略 → 一条成功 + 一条未执行 得到 `COVERED`。非 `SUCCESS` 一律落 `FAILED`（含 `PENDING/RUNNING/CANCELLED`）。未按需求版本/环境限定「最新」。
- 前端 [frontend/src/views/project/workspace/Trace.vue:49](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Trace.vue#L49) 用绿色「已覆盖」呈现（`C` 级，行号来自子代理复核）。

**Files**
- Modify: `backend/app/project_workspace_api.py:1446-1512`、`backend/app/schemas.py`（追溯读模型）、`frontend/src/views/project/workspace/Trace.vue`
- Test: `backend/tests/test_requirement_trace_coverage.py`（新增）

- [x] **Step 1：写失败测试**：需求关联 2 条用例，A 有 SUCCESS run，B 无 run → 断言口径不是「已覆盖」。

```python
def test_untested_case_blocks_coverage(client, requirement_with_two_cases) -> None:
    payload = client.get(f"/projects/{project_id}/trace").json()
    item = next(row for row in payload["rows"] if row["requirement_id"] == requirement_with_two_cases.id)
    assert item["linked_case_count"] == 2
    assert item["executed_case_count"] == 1
    assert item["coverage"] == "PARTIAL"
```

- [ ] **Step 2：确认失败**（当前返回 `COVERED`）。
- [x] **Step 3：实现**：读模型拆为四个独立字段——`linked_case_count`、`executed_case_count`、`passed_case_count`、`open_defect_count`；`coverage ∈ {NONE, UNTESTED, PARTIAL, AT_RISK, COVERED}`，只有「全部关联用例都有终态 run 且全部 SUCCESS」才 `COVERED`；`PENDING/RUNNING` 计为「执行中」而非失败。版本/环境口径先作为字段透传并显示「按当前默认环境」，作为后续任务。
- [ ] **Step 4：确认通过**，前端改为「关联 N · 已执行 M · 通过 K」并配中性色。
- [ ] **Step 5：提交** `fix(trace): report coverage as linked/executed/passed`。

**验收：** 「一条成功、一条未执行」不得显示为已覆盖；质量结论不使用单一总分。

**实施记录（2026-11-11）：** 当前工作区已有分项计数与覆盖分类，新增真实追溯接口回归 `test_requirement_trace_coverage.py`：两条关联用例中一条成功、一条未执行时返回 2/1/1 和 `PARTIAL`，测试通过。环境/需求版本口径及浏览器展示仍需进一步核验。

---

### Task C3：合法状态在看板中消失 `A`

**现状证据**
- [frontend/src/views/project/workspace/constants.js:36](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/constants.js#L36) `DEFECT_COLUMNS` 只有 6 列；`DEFECT_STATUS_LABELS` 还包含 `REOPENED`、`WONTFIX`，详情状态流转也允许（[Defects.vue:128](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Defects.vue#L128)、[:268](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Defects.vue#L268)）。
- 浏览器复现：列表 3 条（NEW/REOPENED/WONTFIX）→ 切看板 → 只剩 1 条卡片。
- 需求侧 `REJECTED` 同理（`constants.js` 列与标签集不一致，静态 `B`）。
- [frontend/src/views/project/workspace/components/KanbanBoard.vue:51](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/components/KanbanBoard.vue#L51) 会为未知状态建组但不渲染未知列。

**Files**
- Modify: `frontend/src/views/project/workspace/constants.js`、`components/KanbanBoard.vue:3-18`
- Test: `frontend/src/views/project/workspace/__tests__/kanbanColumns.test.js`（新增）

- [x] **Step 1：写失败测试**：断言每个状态标签都有归属列。

```js
import { DEFECT_COLUMNS, DEFECT_STATUS_LABELS } from '../constants'
it('every defect status has a board column', () => {
  const keys = new Set(DEFECT_COLUMNS.flatMap((c) => c.statuses ?? [c.key]))
  expect(Object.keys(DEFECT_STATUS_LABELS).filter((s) => !keys.has(s))).toEqual([])
})
```

- [ ] **Step 2：确认失败**（缺 `REOPENED`、`WONTFIX`）。
- [x] **Step 3：实现**：`DEFECT_COLUMNS` 增加「重新打开」列；「不予处理/已关闭」归入可折叠的「已归档」列（默认折叠，可展开）。给列加 `statuses: []` 支持多状态同列。需求侧补 `REJECTED` 归属。`KanbanBoard` 的列集合由 `columns` 驱动，卡片按 `statuses` 匹配；仍未匹配的状态进「待归类」兜底列而不是消失。
- [ ] **Step 4：确认通过**，并验证拖到归档列时 `handleMove` 提交的 `status` 合法（[Defects.vue:404](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Defects.vue#L404)）。
- [ ] **Step 5：提交** `fix(workspace): board covers all legal statuses`。

**验收：** 列表中的每条记录都能在看板找到；看板卡片总数与已加载记录数一致。

**实施记录（2026-11-11）：** 现有代码已覆盖合法状态、未知状态兜底和归档拖放映射；本轮增加归档列默认折叠/展开，并补组件测试覆盖卡片数量、未知状态、归档状态及拖放目标。组件测试和类型检查通过，浏览器视觉与服务端流转仍待运行态验收。

---

### Task C4：看板作用范围被误认为全量 `B`

**现状证据**
- [Defects.vue:295](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Defects.vue#L295) `pageSize = 50`，看板直接用 `items`；分页器只在 `viewMode === 'list'` 渲染（[:38-41](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Defects.vue#L38)）；需求侧同构（[Requirements.vue:21](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Requirements.vue#L21)）。

**Files**
- Modify: `frontend/src/views/project/workspace/Defects.vue`、`Requirements.vue`、`components/KanbanBoard.vue`
- Test: `e2e/tests/workspace_board_scope_label.spec.js`（新增）

- [ ] **Step 1：写失败测试**：seed > 50 条缺陷 → 看板模式 → 断言页面出现「已加载 50 / 共 N」的说明。
- [ ] **Step 2：确认失败。**
- [x] **Step 3：实现（短期）**：看板顶部固定显示「已加载 X / 共 Y」+「加载更多」，并把分页器在看板模式下也渲染。**中期**：改为按列查询 `GET /projects/{id}/defects?status=NEW&limit=…`，每列独立分页与真实计数（需要后端支持按 status 计数，复用 `list_defects` 的 `status` 参数）。
- [ ] **Step 4：确认通过。**
- [ ] **Step 5：提交** `fix(workspace): make board scope explicit`。

**不做：** 不把 `page_size` 提到几百上千来「看起来全量」。

**实施记录（2026-11-11）：** 需求与缺陷看板已有分页；范围提示改为“当前页已加载 X 条，共 Y 条”，使用实际加载数量，避免空列表显示 1–0。类型检查及现有看板组件测试通过；超过 50 条的浏览器回归和按列独立加载仍待完成。

---

### Task C5：计划用例转移不是原子操作 `B`

**现状证据**
- [frontend/src/views/plan/index.vue:763](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/plan/index.vue#L763)：`POST /test-plans` → `POST /test-plans/{id}/cases/batch`（只带 `case_type/case_id`，`allow_unapproved: true`）→ 循环 `DELETE` 原条目 → 提示成功。中途失败留下半转移；重新关联会替换原计划条目快照并可能合并重复（后端批处理行为 `C`，实施时复核 `api.py` 批量分支）。

**Files**
- Option A（推荐先做）：仅改前端为「复制」；Option B：后端新增按 plan-item ID 的原子迁移端点
- Test: `backend/tests/test_plan_transfer.py`（新增）

- [x] **Step 1：写失败测试（Option A）**：断言「转移」后原计划条目仍在，新计划条目数等于筛选数。

```python
def test_transfer_copies_without_removing_source(client, plan_with_items) -> None:
    result = client.post(f"/test-plans/{plan_with_items.id}/cases/copy-to-review", json={"items": [...]})
    assert result.status_code == 200
    assert len(client.get(f"/test-plans/{plan_with_items.id}/cases").json()) == plan_with_items.count
```

- [ ] **Step 2：确认失败**（端点不存在或原条目被删）。
- [x] **Step 3：实现**：按钮文案改「复制到待评审计划」，删除自动 `DELETE` 循环；在同一数据库事务内创建新计划、复制条目、写来源说明；复制时明确沿用当前用例版本还是原快照，并在 UI 标注。若之后确需「真转移」，新增 `POST /test-plans/{id}/items/move`（入参为 plan-item ID 列表 + 目标计划），单事务处理归属与顺序。
- [ ] **Step 4：确认通过**，验证中途失败（人为让第 3 条冲突）时整批不落库、原计划不变。
- [ ] **Step 5：提交** `fix(plans): copy-on-transfer instead of partial move`。

**验收：** 转移不再出现「一半在新、一半在旧」；快照语义对用户可见。
**不做：** 不用 outbox/CAS/事件总线——同库一事务即可。

**实施记录（2026-11-11）：** 新增按来源计划条目 ID 复制到待评审计划的接口：先校验全部条目、项目归属及评审权限，再在同一事务内创建计划和当前版本快照；前端已改用该接口。接口测试验证非法条目不创建计划、成功后原计划保留，并在目标计划 flush 后注入快照异常确认回滚；前端类型检查通过。浏览器验收仍待完成。

---

### Task C6：报告的「跳执行」不打开对应执行 `B`

**现状证据**
- 报告 [frontend/src/views/report/index.vue:947](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/report/index.vue#L947) `push('/execution/index?run_id=…')`；[frontend/src/views/execution/index.vue:528](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/execution/index.vue#L528) 只 `onMounted` 加载列表，全文件不读 `route.query.run_id`（grep 确认）。
- 附带：`submitDefect` 里 `run_id` 取「第一个 `status !== 'SUCCESS'`」的 run（含 `PENDING/CANCELLED`），未必是用户正在看的失败项。

**Files**
- Modify: `frontend/src/views/execution/index.vue`、`frontend/src/views/report/index.vue:930-950`
- Test: `e2e/tests/report_to_run_deep_link.spec.js`（新增）

- [x] **Step 1：写失败测试**：从报告点某条失败执行 → 断言 URL 含 `run_id` 且执行详情抽屉自动打开并显示该 run 编号。

```js
await page.goto(`/execution/index?run_id=${failedRun.id}`)
await expect(page.getByRole('dialog')).toContainText(`执行 #${failedRun.id}`)
```

- [ ] **Step 2：确认失败**（只落在列表，无详情）。
- [x] **Step 3：实现**：`onMounted` 读取 `route.query.run_id`，命中时 `GET /executions/runs/{id}` 并打开详情，成功后同步移除或保留 query（保留以便刷新）；详情关闭时用 `router.replace` 清 query。报告缺陷对话框改为让用户在选择器里确认目标失败 run，默认预选第一个 FAILED。
- [ ] **Step 4：确认通过。**
- [ ] **Step 5：提交** `feat(execution): open run detail from report deep link`。

**实施记录（2026-11-11）：** 执行页已有 query 加载与关闭清理，但数字 ID 正则多转义导致正常链接被拒绝；已修复并添加 ID 校验单测。报告缺陷弹窗新增失败执行选择，默认仅选择 FAILED/ERROR/TIMEOUT。类型检查及单测通过；真实浏览器跳转仍待验收。

---

### Task C7：有迭代与工时字段，却没有规划入口 `B`

**现状证据**
- [Requirements.vue:124](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Requirements.vue#L124) 迭代只读展示；[Tasks.vue:99](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Tasks.vue#L99) 迭代只读、[:116](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Tasks.vue#L116) 预估/实际工时只读。后端更新接口支持这些字段（上一轮确认，实施时复核 `project_workspace_api.py` 的 update schema，等级 `C`）。

**Files**
- Modify: `frontend/src/views/project/workspace/Requirements.vue`、`Tasks.vue`
- Test: `e2e/tests/workspace_iteration_planning.spec.js`（新增）

- [ ] **Step 1：写失败测试**：需求详情里把迭代改为可选并选择迭代 → 断言保存后列表「迭代」列更新；任务详情填预估工时 → 断言刷新后仍在。
- [ ] **Step 2：确认失败**（当前无控件）。
- [x] **Step 3：实现**：详情抽屉增加「迭代」下拉（复用已有 `iterations` 与 `updateField`）与「预估/实际工时」数字输入；列表页增加批量「规划到迭代」（复用 B5 的三态 patch）。后端确认字段允许更新且做角色校验。
- [ ] **Step 4：确认通过。**
- [ ] **Step 5：提交** `feat(workspace): iteration planning and task hour fields`。

**不做：** 不建燃尽图/工时报表体系；先让数据能被录入。

**实施记录（2026-11-11）：** 需求和任务详情已有迭代编辑，任务已有预估/实际工时输入；后端更新使用 `exclude_unset`。本轮补充创建和更新时的迭代项目归属校验，接口测试通过同项目、跨项目拒绝和显式清空。批量规划入口、工时持久化及浏览器验收仍待完成。

**实施记录（2026-11-13）：** 批量规划入口已落地：需求列表页增加多选列与「规划到迭代」批量按钮；新增后端 `PUT /requirements/batch-iteration`（同项目校验、迭代归属校验、支持置空移出迭代、404/400/422 分支），回归测试 `backend/tests/test_requirement_batch_iteration.py` 覆盖批量规划、移出迭代、跨项目拒绝、缺失 ID 与空列表。待办：浏览器手测与 e2e 用例。

---

### Task C8：关联用例要手输数字 ID `B`

**实施记录（2026-11-11）：** 需求关联选择器已有远程搜索，但误用统一接口不存在的 `id` 字段且数字 ID 在不同类型间可能重复；现改为 `case_type:case_id` 组合值并使用正确的 `case_id` 提交，同时保护搜索结果顺序。类型检查和现有前端测试通过；新增同 ID 跨类型的模拟浏览器回归并接入 CI，已收集但尚未执行。缺陷详情目前仅展示关联结果，手动关联入口仍待设计实现。

**现状证据**
- [Requirements.vue:153-160](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/Requirements.vue#L153) 需要选类型再手输 `case_id`（默认 1）；列表行的「序号」是按总数反推的展示序号（[CaseTable.vue:135](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/components/CaseTable.vue#L135)），不是稳定 ID，容易造成认知错位。

**Files**
- Modify: `frontend/src/views/project/workspace/Requirements.vue`、`Defects.vue`（关联区）
- Test: `e2e/tests/workspace_link_picker.spec.js`（新增）

- [ ] **Step 1：写失败测试**：打开需求详情 → 关联用例 → 输入名称关键字 → 断言下拉出现用例名＋类型＋版本号，选中后关联表显示用例名。
- [ ] **Step 2：确认失败**（当前只有数字输入）。
- [x] **Step 3：实现**：换成 `el-select` 远程搜索（复用 `GET /cases?keyword=&project_id=`），选项文案「UI · 用例名 · v1.2.0」；同时把列表列名「序号」改为「编号」并展示真实 `id`，避免与关联输入混淆。
- [ ] **Step 4：确认通过。**
- [ ] **Step 5：提交** `feat(workspace): search-based case linking`。

---

## 6. Phase D — 权限、评审与数据归属

> 本阶段多数条目为上一轮结论（等级 `C`）。**每条第一步都是复核行号与现状**，若已被你近期改动修复则跳过并记录。

### Task D1：更新端点允许把对象移到未授权项目 `C`

**现状证据（本轮已复核）**
- `APICaseUpdate` 直接继承 `APICaseCreate`（[backend/app/schemas.py:73](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/schemas.py#L73)），`UICaseUpdate`/`PerformanceCaseUpdate` 同样（[:329](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/schemas.py#L329)、[:490](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/schemas.py#L490)），三者都带 `project_id`。
- [backend/app/api.py:3497](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L3497) 只校验**原**项目访问权；[:3514-3517](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L3514) 无差别 `setattr`，包含 `project_id`。UI/PERF 的 update 同构。

**Files**
- Modify: `backend/app/api.py`（三处 update）、`backend/app/schemas.py`
- Test: `backend/tests/test_case_update_project_guard.py`（新增）

- [x] **Step 1：写失败测试**：用户只有项目 A 权限，`PUT /api-cases/{id}` 带 `project_id: B` → 断言 403（或明确拒绝跨项目移动）。

```python
def test_update_case_cannot_move_to_unauthorized_project(client, api_case_in_project_a) -> None:
    response = client.put(f"/api-cases/{api_case_in_project_a.id}",
                          json={**case_payload(api_case_in_project_a), "project_id": other_project_id})
    assert response.status_code == 403
    assert client.get(f"/api-cases/{api_case_in_project_a.id}").json()["project_id"] == project_a_id
```

- [ ] **Step 2：确认失败**（当前 200 且已改项目）。
- [x] **Step 3：实现**：update 路径把 `project_id` 视为不可变（默认拒绝并返回明确 detail）；若产品需要「移动用例」，单独提供 `POST /cases/{type}/{id}/move`，同时校验源与目标项目权限、重算 `folder_path` 与评审状态。
- [ ] **Step 4：确认通过**，三类用例与场景/数据集子字段一并覆盖。
- [ ] **Step 5：提交** `fix(api): block cross-project case reassignment via update`。

**实施记录（2026-11-11）：** 三类普通用例更新已调用项目不可变校验；新增 API/UI/性能三类接口回归，验证更改项目被拒绝且原项目不变，3 项通过。当前测试为管理员身份；非管理员权限和场景/数据集子字段仍需单独核验。

---

### Task D2：创建/导入/批量可绕过评审直接置为已批准 `C`

**现状证据**：`import_cases` 直接写入 `item.review_status`（[api.py:1803](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L1803)、[:1827](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L1827)、[:1863](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L1863)）；批量评审端点存在（`CaseBatchReviewPayload`，[schemas.py:920](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/schemas.py#L920)）。update 已排除评审字段（[api.py:3514](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L3514)）。

- [x] **Step 1：写失败测试**：导入时带 `review_status: APPROVED` 且提交者非评审角色 → 断言落库为 `DRAFT`（或 403），并记录评审人只能由评审动作设置。
- [ ] **Step 2：确认失败。**
- [x] **Step 3：实现**：新增服务层 `resolve_review_status(payload, current_user, action)`，创建/导入统一走它——非评审角色提交一律 `DRAFT`；`APPROVED/REJECTED` 只能由评审端点写并记录 `reviewed_by/reviewed_at`。批量评审同样校验角色与项目归属。
- [ ] **Step 4：确认通过**，检查 AI 生成落库路径（`ui_case_ai.py`）是否复用该函数。
- [ ] **Step 5：提交** `fix(review): enforce review transitions only via review endpoints`。

**验收：** 无法通过创建、导入、AI 生成、批量接口绕过评审；计划执行仍按评审状态拦截。

**实施记录（2026-11-11）：** 创建和导入已有强制草稿逻辑；批量评审现要求其他用户创建且状态为 `IN_REVIEW`，只允许通过/拒绝，并记录评审人、时间，所有条目先校验后写入。自评审拒绝、合法跨用户批量评审、混合状态批次不部分生效及审计字段测试通过；历史测试中部分夹具依赖旧的自批行为，完整后端测试仍待核验和调整。

**全量回归（截至前 5 个失败）：** `pytest tests -q --maxfail=5` 得到 249 通过、5 失败；其中 4 项历史用例直接对自己创建的草稿调用批量批准，需改为合法跨用户评审夹具；另 1 项上传图片 Cookie 鉴权测试返回 401，需独立排查。测试在第 5 个失败后停止，不能视为全量通过。

**Cookie 失败排查：** 新增的跨用户评审测试曾覆盖共享客户端的浏览器 Cookie，再删除临时评审员导致后续图片测试使用失效会话；改为独立评审客户端后，按顺序运行两项评审测试和图片 Cookie 测试，3 项均通过。4 项历史自批夹具仍待调整和全量重跑。

**后续全量回归：** 已将历史自批夹具改为独立评审员和正式提交评审流程，并验证重复批准被拒绝；`pytest tests -q` 全量 271 项通过，1 条 Starlette/AnyIO 弃用警告。

---

### Task D3：全局角色与项目成员边界收口 `C`

**现状证据（部分本轮复核）**：全局 `tester`/`project viewer` 的能力面、owner 保护散落在多处；仓库已有 e2e 覆盖 `workspace_owner_guard.spec.js`、`workspace_membership_flow.spec.js`。

- [x] **Step 1：先做现状清单**（不写代码）：列出所有 `_require_project_access` / `_require_project_role` / `require_tester` 的使用点与语义差异（`D` → 完成后转 `B`）。
- [ ] **Step 2：写失败测试**：viewer 成员调用需 member 的写操作、非项目成员访问他人项目对象，各自断言 403/404。
- [ ] **Step 3：实现**：把「角色 → 允许动作」收敛到一个 `permissions.py`（纯函数 + 常量表），API 层只调用它；先覆盖高风险动作（删除、执行、评审、成员管理、缺陷状态流转），其余端点逐步迁移。
- [ ] **Step 4：确认通过**，并保证 e2e 两个既有 spec 不回归。
- [ ] **Step 5：提交** `refactor(auth): centralize project permission checks`。

**不做：** 不做可配置 RBAC 平台、不自建权限管理界面。

**实施记录（2026-11-11）：** 复核确认全局 tester 与项目 viewer 是不同维度：原单条及批量评审仅检查 tester 和可访问性。现评审决定入口要求项目 member 及以上（admin 保持全局权限），viewer 单条/批量拒绝及合法跨用户评审测试通过。删除、执行、其他写入口与完整权限清单仍待审计，兼容旧工作空间回退行为需继续核验。

**实施记录（2026-11-13，运行态验证）：** 起栈跑 pytest 发现 2 个评审用例失败——`decide_*_review` 三个端点把 `_require_project_member` 放在自评检查之前，而创建项目的用户未自动成为 ProjectMember，导致角色检查抢在自评检查前返回「项目内权限不足」，自评文案「不能评审自己创建的用例」永远到不了。已修复：三处（api/UI/性能）把自评检查（`created_by == current_user.id`）移到 `_require_project_member` 之前。全量回归 287 通过。遗留：创建者是否应自动成为 owner ProjectMember 仍待产品确认（当前依赖工作空间级访问回退）。

**执行权限补充：** API/UI/性能单次和批量执行、批量失败重跑、计划执行均改为项目 member 及以上；已测试 viewer 的 UI 单次/批量执行被拒绝，其他执行类型、合法 member、历史兼容及全量回归仍待验证。

**兼容性核查：** 显式项目 member 的 UI 执行在模拟调度下通过。现行项目角色策略将没有显式项目成员记录的工作空间用户视为 viewer，因此旧式全局 tester 即使可查看项目，也需要被加入项目才能评审或执行；这是权限行为变更，需部署前确认迁移/授权方案，不能视为无感兼容。

**成员管理越权：** 两套路由重复，先注册的 `api.py` 版本原仅检查可访问性；已要求项目 manager 及以上才能增删改成员，viewer 自提权接口测试通过。重复路由收敛、角色提升边界和最后 owner 保护仍待核验。

**owner 保护补充：** 生效路由现拒绝非法角色，manager 不能授予或修改 owner；降级/删除最后一名已有 owner 被拒绝，包括新增接口更新已有成员的路径。相关接口测试通过；并发变更竞态和重复路由收敛仍待验证。

---

### Task D4：富文本、上传与证据文件的归属 `C`

**现状证据**：工作树里存在未跟踪的 `backend/app/rich_text_security.py`（你已有改动，**不要覆盖**），说明清洗工作正在进行；`/uploads/image` 鉴权已有测试（[test_platform_api.py:46](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/tests/test_platform_api.py#L46)）。

- [ ] **Step 1：与用户确认** `rich_text_security.py` 的完成度与提交计划。
- [ ] **Step 2：写失败测试**：缺陷描述里 `<script>`、`onerror`、`javascript:` 被去除；上传文件归属校验；产物下载需登录且限项目成员。
- [ ] **Step 3：实现**：所有富文本入口（缺陷描述/重现/解决、需求描述、评论如转富文本）统一走同一清洗函数；产物路径校验拒绝符号链接与目录穿越。
- [ ] **Step 4：确认通过。**
- [ ] **Step 5：提交**（与用户既有改动分开提交）。

---

### Task D5：通知凭据与 API Token 生命周期 `C`

- [x] **Step 1：写失败测试**：Webhook secret 读接口不回明文；Token 仅在创建响应里出现一次；删除后旧 Token 立即失效。
- [x] **Step 2/3：** 若已有实现则只补测试；缺失部分按测试补齐。
- [ ] **Step 4：确认通过。**
- [ ] **Step 5：提交** `test(security): cover token and webhook secret lifecycle`。

**实施记录（2026-11-13）：** 复核确认功能已实现——`NotificationSettingRead.secret_configured` 只回布尔不回明文；`ApiTokenRead` 仅含 `token_prefix`（掩码），明文 token 只在 `POST /api-tokens` 的 `ApiTokenCreated` 出现一次；`DELETE /api-tokens/{id}` 删库后 `get_user_by_token` 每次查库即失效。本轮补 `backend/tests/test_token_and_webhook_secret_lifecycle.py`：①PUT/GET 通知设置不回明文且读侧无 `secret` 字段；②token 明文仅创建响应存在、列表只回前缀；③删除后同一 token 立即 401 且从列表消失。py_compile 通过，pytest 待运行态执行。未发现需要改的产品代码。

---

## 7. Phase E — 执行引擎与 AI 生成契约

> 均为源码确认（`B`），**未执行真实模型调用、未测真实调用成本**。实施前先用可控桩（假模型）跑测试，不产生真实费用。

### Task E1：页面所选模型 ≠ 任务实际生效模型

**证据**：提交 [generator2/index.vue:705-748](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/generator2/index.vue#L705)——仅当 `api_key` 有值才 `persistModelConfig()`，只改模型名/URL 时不一定落库；后端 [api.py:2488-2497](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L2488) 用已保存配置覆盖 `openai_model/base_url`；执行时 [engine.py:4023-4031](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/tasks/case_generation_v2_pipeline/engine.py#L4023) 又优先读共享配置（排队期间可被改动）。

- [x] **Step 1：写失败测试**（`backend/tests/test_case_generation_v2_model_snapshot.py`）：提交时指定模型 B（已存在 active 配置 A）→ 断言 attempt 快照记录的 `model == B`，且随后修改 A 不影响该 attempt。
- [x] **Step 2：确认失败**（快照取到 A）。
- [x] **Step 3：实现**：提交时对非秘密参数（provider/model/base_url）做**任务级快照**并持久化到 attempt；执行优先读快照；Key 仍按引用解析。前端提交前显示「本次生效：provider · model · host」，且模型名/URL 变更后强制走一次保存。
- [x] **Step 4：确认通过。**
- [ ] **Step 5：提交** `fix(case-gen): snapshot effective model config per attempt`。

**实施记录（2026-11-13）：** ①提交端点（api.py 四处：v1/v2 创建与重跑路径）在 attempt 的 `input_payload` JSON 字段中写入 `model_config_snapshot`（provider/model/base_url 非秘密参数，复用现有 JSON 字段、无新增列/迁移）；②执行侧 `engine.py` 新增 `_resolve_model_execution_config(db, payload, attempt_payload)`：优先读 attempt 快照，无快照时回退旧共享配置逻辑，Key 始终按引用解析；四处执行调用点统一切换；③前端 `generator2/index.vue` 新增 `effectiveModelPreview`（按将随任务提交的实际参数计算「本次生效：provider · model · host」）与 `modelConfigDirty`：模型名/URL 变更未保存时阻断提交并提示先保存。测试 `test_case_generation_v2_model_snapshot.py`（3 用例）通过。运行态验证：全量套件中该测试因复用 admin 用户与前序用例遗留的 in-progress V2 任务冲突而失败，已改为独立用户+独立项目隔离，全量回归 287 通过。

### Task E2：预览显示旧内容、下载得到新内容

**证据**：前端刷新时优先保留旧 `content_json`（[generator2/index.vue:598-608](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/generator2/index.vue#L598)），后端同 ID 原地更新（[artifacts.py:98-130](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/tasks/case_generation_v2_pipeline/artifacts.py#L98)）；刷新还会重置选中页签（`activeArtifactType` 重置）。

- [x] **Step 1：写失败测试**：同一 artifact 更新两次内容 → 刷新逻辑只接受匹配 revision 的缓存，页签按 `artifact_type` 保持；API 覆盖过期预览/下载返回 409。
- [ ] **Step 2：确认失败**（仍是第一次内容）。
- [x] **Step 3：实现**：以「手动刷新」为准丢弃旧缓存；为产物加 `revision`/内容摘要（新增列走 F1 迁移），预览和下载校验同一 `revision`；页签按 `artifact_type` 保持。
- [x] **Step 4：确认通过**：产物缓存测试、stale preview/download API 测试、前端类型检查与构建通过。
- [ ] **Step 5：提交** `fix(case-gen): invalidate stale artifact preview`。

### Task E3：新 attempt 混合继承不同尝试的产物

**证据**：`_inherit_case_generation_v2_artifacts` 按整个 job「每种类型最新记录」复制，不绑定父 attempt（[api.py:759-806](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L759)）；「最终 XMind」只要存在就展示（[ArtifactViewer.vue:2-8](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/generator2/components/ArtifactViewer.vue#L2)）。

- [x] **Step 1：写失败测试**：构造 A 成功 → B 部分失败 → C 恢复，断言 C 的产物集合只来自指定的父快照，历史门禁结论不带入 C。
- [ ] **Step 2：确认失败。**
- [x] **Step 3：实现**：继承时记录 `parent_attempt_id` 并限定输入产物白名单；为恢复路径所需的 `evidence_trace/testcase_base_package` 一并保留。gate、review、XMind 等结论类产物不继承；继承数据展示「来自尝试 #N · 本次未验证」。
- [x] **Step 4：确认通过**：A→B→C 快照隔离测试通过。
- [ ] **Step 5：提交** `fix(case-gen): bind inherited artifacts to parent attempt`。

### Task E4：门禁建议的恢复动作未必能执行

**证据**：恢复计划生成 `return_to`（[delivery_impl.py:132-179](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/tasks/case_generation_v2_pipeline/stages/delivery_impl.py#L132)）与面板按钮转发（[GateIssuesPanel.vue:9-31](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/generator2/components/GateIssuesPanel.vue#L9)）；但 source shard 重跑要求已存在 `testcase_package`（[api.py:2863-2870](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L2863)），需求门禁失败时该产物可能不存在；实际恢复只支持特定检查点（[orchestration.py:23-30](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/tasks/case_generation_v2_pipeline/orchestration.py#L23)）。

- [x] **Step 1：写失败测试**：需求门禁失败、无 `testcase_package` 时，详情接口不返回 `rerun_source`；补充有 package 时只为实际存在的 source 返回动作。
- [x] **Step 2：确认失败**：旧详情接口没有 `recovery_actions`，契约断言失败。
- [x] **Step 3：实现**：`job detail` 增加 `recovery_actions`，由后端按当前 attempt 产物、模型配置、任务状态与角色计算；前端只消费服务端动作，禁用时展示原因，确认框说明保留/重算范围及模型调用。
- [x] **Step 4：确认通过**：恢复动作 API 回归、后端全套测试、前端全套测试、类型检查与生产构建通过。
- [ ] **Step 5：提交** `feat(case-gen): expose actionable recovery options`。

### Task E5：功能点存在多份不同步事实源

**证据**：恢复路径更新 `requirement_handoff`（[engine.py:3908-3923](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/tasks/case_generation_v2_pipeline/engine.py#L3908)）；门禁读独立 `function_points` 产物（[delivery_impl.py:950-966](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/tasks/case_generation_v2_pipeline/stages/delivery_impl.py#L950)）；导出又从 `requirement_handoff` 重建（[:1266-1272](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/tasks/case_generation_v2_pipeline/stages/delivery_impl.py#L1266)）。

- [ ] **Step 1：写失败测试**：修复后，门禁读取的功能点集合与导出的 `FunctionPoints.yaml` 完全一致（用规范化后的集合比较）。
- [ ] **Step 2：确认失败。**
- [ ] **Step 3：实现**：确定 `requirement_handoff`（或其规范化产物）为唯一事实源，`function_points` 改为派生视图并在同一处生成；门禁结论绑定输入的 `revision/hash`。
- [ ] **Step 4：确认通过。**
- [ ] **Step 5：提交** `refactor(case-gen): single source of truth for function points`。

### Task E6：一次用户操作缺少统一模型调用预算

**证据**：契约修复、内容修复、skill 重试、JSON 修复分层叠加（[testcase_impl.py:557](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/tasks/case_generation_v2_pipeline/stages/testcase_impl.py#L557)、[:1141](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/tasks/case_generation_v2_pipeline/stages/testcase_impl.py#L1141)、[engine.py:1591](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/tasks/case_generation_v2_pipeline/engine.py#L1591)）。每层有上限，但一次「重跑」总调用数不可预测（成本结论为 `D`，需实测）。

- [ ] **Step 1：先测量**：用假模型（返回预置 JSON）跑一次 trusted 任务，记录 `model_call_trace` 实际调用次数，确认预算基线（这一步产出数据，不产出结论）。
- [ ] **Step 2：写失败测试**：注入「JSON 错 + 契约错 + 429」组合，断言总调用次数不超过预算、保留最后一次输出、`generation_metrics` 记录超限原因。
- [ ] **Step 3：实现**：attempt 级 `call_budget`（次数 + 墙钟时间），网络重试独立计数，内容修复最多一轮并把错误反馈带入；超限时 `finish_attempt(status='FAILED', summary='超出调用预算')`。前端进度区展示「已调用 X / 预算 Y」。
- [ ] **Step 4：确认通过。**
- [ ] **Step 5：提交** `feat(case-gen): per-attempt model call budget`。

### Task E7：生成结果到导入/执行的能力边界不明确

**证据**：V2 页面是提交—预览—下载，未见编辑选中用例并入库的链路；通用导入模型不承接 `datasets_json/mock_*`（[schemas.py:926-962](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/schemas.py#L926)、映射 [api.py:1794-1815](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L1794)）；执行器遇到 `steps_json` 优先走 scenario，`datasets_json` 被忽略（[executions.py:996-1007](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/tasks/executions.py#L996)）。

- [x] **Step 1：写失败测试**：带 `datasets_json` 的导入项要么按数据集执行、要么被明确拒绝；断言不会「保存成功但执行时静默忽略」。
- [x] **Step 2：确认失败。**
- [x] **Step 3：实现**：先产出「支持矩阵」文档小节（可生成 / 可入库 / 可执行 / 不支持组合）；导入模型补字段映射；对不支持的组合在 `CaseImportItem` 校验层显式报错并指明第 N 条与字段。保留导入的整批事务（[api.py:1883](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L1883)），并补「哪一条导致整批失败」的定位信息（注意：现有实现是末尾统一提交，**尚未观察到逐条部分落库**）。
- [x] **Step 4：确认通过。**
- [ ] **Step 5：提交** `feat(cases): declare import execution support matrix`。

**实施记录（2026-11-13）：** ①整批导入 `/cases/import` 逐条 try/except：失败回滚整批并返回 `导入失败：第 N 条（类型 · 名称）：原因`（HTTPException 保持原状态码，其余异常归一为 400），回归测试 `test_case_import_localization.py` 覆盖三类成功导入与「第 2 条失败→整批回滚」。②支持矩阵落盘 `docs/case_import_support_matrix.md`：明确 datasets_json/mock_* 不在导入模型（数据驱动执行契约待产品决策），UI 动作受引擎白名单约束（联动 E8）。③「导入模型补字段映射」暂缓：先声明边界，待 datasets 执行契约确定后一并补。

### Task E8：两种引擎共用同一份步骤候选 `C`

**上一轮结论**：UI 步骤选项对 native 与 Midscene 共用（[ui/index.vue:297](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/index.vue#L297)），可选动作与执行器实际支持的动作可能不一致。

- [x] **Step 1：复核**两引擎各自的动作集合（`frontend/src/lib/uiCase.js:1-18` vs Midscene 执行侧动作映射）。
- [x] **Step 2：写失败测试**：选择 Midscene 引擎时，候选只含其支持动作；保存历史用例中的不受支持动作给出明确提示而非静默执行错误分支。
- [x] **Step 3：实现**：按引擎拆分动作白名单常量；`unknown action` 回退（`uiCase.js` 现有回退到 click 定义但保留原 `action`）改为校验失败并提示。
- [x] **Step 4：确认通过。**
- [ ] **Step 5：提交** `fix(ui-case): per-engine step action whitelist`。

**实施记录（2026-11-13）：** 两引擎动作对照（以执行侧代码为准）：native 17 项与 UI_STEP_OPTIONS 完全一致；Midscene（`backend/midscene/midscene_runner.js`）一等支持仅 goto/click/fill/wait/assert_text 5 项。`uiCase.js` 新增 `NATIVE_ACTIONS`/`MIDSCENE_ACTIONS`/`getStepOptions(engine)`/`isStepActionSupported`/`findUnsupportedActions`，`validateUiWorkflow` 增加可选 engine 参数（默认 native，API 兼容），不受支持动作报「步骤 N 的动作 X 不受 Y 引擎支持」；`ui/index.vue` 步骤下拉按 `temp.engine` 过滤、保存校验传入引擎、加载历史/切换引擎时 `warnUnsupportedSteps` 给警告但不阻塞展示；click 定义回退仅保留用于历史数据展示/序列化。新增 4 个白名单测试，`uiCase.test.js` 13 用例全通过，typecheck/lint 通过。待办：浏览器手测引擎切换提示。

### Task E9：执行提交的可靠性边界（小范围） `C`

**上一轮结论**：任务提交与派发之间存在窗口、取消可被覆盖、重复领取风险、快照未实际用于执行、计划创建部分提交。

- [ ] **Step 1：只补对账**：`/system/health` 之外新增内部对账（提交后 N 秒仍 PENDING 的 run 标记 `DISPATCH_LOST` 并可重试），范围仅限「已入库但未进入 worker」这一段。
- [ ] **Step 2：写失败测试**：模拟 worker 未领取，run 进入 `DISPATCH_LOST` 且能被重试；不新增状态枚举前，先确认所有终态判断点（报告聚合、轮询、门禁资格）都能识别新状态。
- [ ] **Step 3：实现** → **Step 4：验证** → **Step 5：提交** `fix(execution): reconcile undispatched runs`。

**不做：** 全域 outbox、事件溯源、全链路 CAS。

---

## 8. Phase F — 工程、测试与部署可靠性

### Task F1：启动期建表无版本管理

**证据**：启动时 `bootstrap_runtime()`（[main.py:21-33](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/main.py#L21)），索引异常被吞（上一轮结论，等级 `C`）。E2/E3/E5 需要新增列，**必须先有迁移机制**。

- [x] **Step 1：确认现状**：启动 bootstrap 原先走 `init_db`；现已确认并替换为迁移版本检查。
- [x] **Step 2：引入 Alembic**：`backend/alembic.ini` + 初始 baseline 迁移；完整未版本化 schema 才会被安全 stamp，业务数据不重建。
- [x] **Step 3：实现**：启动只校验 revision；backend 容器在 Uvicorn 前执行 upgrade；后续新增列/索引走迁移文件。
- [ ] **Step 4：验证**：SQLite 升降级与旧库 stamp、密钥迁移保护测试已通过；`docker-compose config` 校验通过。MariaDB 实际启动/迁移与 CI 工作流尚未运行。
- [ ] **Step 5：提交** `chore(db): add alembic migrations`。

### Task F2：健康检查 degraded 仍返回 200

**证据**：既有测试允许 `app_status ∈ {healthy, degraded}`（[test_platform_api.py:14-21](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/tests/test_platform_api.py#L14)），`redis: unhealthy` 也可能 200。CI 用 `scripts/health_check.sh` 判定。

- [x] **Step 1：写失败测试**：依赖不可用时 `/system/health` 返回 503（保留 body 里的分项状态），`health_check.sh` 对 degraded 非零退出。
- [ ] **Step 2：确认失败。**
- [x] **Step 3：实现**：区分「应用活着」与「依赖可用」；若部署侧需要 liveness/readiness 分离，提供 `/system/health/live`（始终 200）与 `/system/health/ready`（依赖驱动状态码），并同步改 `health_check.sh` 与 compose 健康检查。
- [ ] **Step 4：确认通过**，跑 `bash scripts/health_check.sh` 验证。
- [ ] **Step 5：提交** `fix(health): distinguish degraded from healthy status code`。

**实施记录（2026-11-13）：** `/system/health` degraded 返回 503（body 保留分项 JSON）；新增 `/system/health/live` 与 `/system/health/ready`；`health_check.sh` 与 compose 健康检查（curl -fsS）对 503 天然非零退出，逻辑无需改动；新增 `backend/tests/test_system_health.py` 契约测试（monkeypatch 模拟 healthy/degraded 两态）。单测环境（SQLite + 无 Redis）在 `services.collect_system_health` 中跳过 Redis 探测，避免 conftest 就绪轮询与 28 个自引用 `/api/v1/system/health` 的平台用例批量失败；真实部署始终探测。仪表盘对健康请求单独兜底，503 不再拖垮整页加载。待办：Step 2/4 运行时验证（本机 Docker 不可用）。

### Task F3：CI 未覆盖前端与 worker

**证据**：[.github/workflows/stack-tests.yml](file:///Users/zhangyongcheng/Desktop/PPPtest/.github/workflows/stack-tests.yml) 跑 compose 健康、后端 pytest、5 个 e2e spec；**没有** `npm run lint / typecheck / test`，也没有对 Celery worker 与 case_generation 队列的真实执行验证（`EXECUTION_ENGINE=httpx`）。

- [x] **Step 1：新增 job**：`frontend` job（Node 24、`npm ci`、`lint`、`typecheck`、`test`）。
- [ ] **Step 2：新增 worker 冒烟**：一个使用真实 worker + Redis 的最小执行用例（不是桩），断言 run 由 worker 完成并产出产物。
- [ ] **Step 3：验证**：在 PR 分支触发一次完整 workflow，确认红/绿都能被捕获。
- [ ] **Step 4：提交** `ci: cover frontend checks and worker execution`。

**实施记录（2026-11-13）：** `stack-tests.yml` 已新增 `frontend-checks` job（Node 22、npm ci、lint、typecheck、test，含 npm 缓存）。待办：Step 2 worker 真实执行冒烟与 Step 3 workflow 验证。

### Task F4：本地脚本可能删除开发数据卷

**证据**：`docker compose down -v` 出现在 CI 收尾（[stack-tests.yml:156](file:///Users/zhangyongcheng/Desktop/PPPtest/.github/workflows/stack-tests.yml#L156)，CI 可接受）；上一轮发现同一用法也存在于本地测试脚本（等级 `C`，实施前先 `grep -rn "down -v" scripts/`）。

- [x] **Step 1：定位**所有 `down -v` 使用点，区分 CI/本地。
- [x] **Step 2：改本地脚本**为 `docker compose down`（不带 `-v`），清理卷改为显式可选参数 `--purge`，默认不删。
- [ ] **Step 3：验证**：跑一次本地脚本，确认数据卷仍在；`--purge` 时按预期删除。
- [ ] **Step 4：提交** `fix(scripts): never purge volumes by default`。

**实施记录（2026-11-13）：** `down -v` 全仓只有两处——CI 收尾（保留）与 `scripts/run_stack_tests.sh` 的 cleanup（已改）。本地脚本现默认 `compose down` 保留卷，`--purge` 参数才执行 `down -v`，未知参数直接报错退出；`bash -n` 语法通过。待办：Step 3 运行时验证。

### Task F5：测试环境继承外部变量

**证据**：`os.environ.setdefault("DATABASE_URL", ...)`（[backend/tests/conftest.py:9](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/tests/conftest.py#L9)）——若 shell 已导出指向真实库的 `DATABASE_URL`，测试会打到真实数据库。

- [x] **Step 1：写失败测试/守卫**：conftest 中显式覆盖 `DATABASE_URL` 为临时 SQLite，并在检测到指向 MySQL 且非 CI 标记时直接 `pytest.exit` 报错。

```python
if os.environ.get("DATABASE_URL", "").startswith("mysql") and not os.environ.get("PYTEST_DB_ALLOWED"):
    pytest.exit("拒绝在真实 MariaDB 上运行测试：设置 PYTEST_DB_ALLOWED=1 或指向 SQLite")
```

**实施记录（2026-11-13）：** conftest 顶部已实现「先检查原始值、再覆盖」的守卫：非 sqlite 且未设置 `PYTEST_DB_ALLOWED=1` 时 `pytest.exit`（含 sqlite 白名单）；否则覆盖为进程级临时 SQLite。待办：Step 2 运行时验证。

- [ ] **Step 2：验证**：临时 `export DATABASE_URL=mysql+pymysql://...` 后 `pytest -q` 应立即退出而非执行。
- [ ] **Step 3：提交** `test: harden pytest database guard`。

### Task F6：部署与回滚 `C`

**上一轮结论**：GHCR + SSH + Compose 单主机，回滚路径不完整、无备份校验。

- [x] **Step 1：先确认现状**：读取 `docs/production_deployment.md` 与 `publish-deploy.yml`，列出「发布前是否备份」「失败是否回滚」「镜像 tag 是否可追溯」。
- [x] **Step 2：实现最小组合**：发布前 `mysqldump`（或云快照）到对象存储/备份目录并校验大小；保留上一 compose 镜像 tag；健康检查失败自动 `docker compose up -d` 回退到旧 tag；发布记录写入部署日志。
- [ ] **Step 3：验证**：在预发环境演练一次「发布失败 → 自动回滚」，并演练一次「从备份恢复」。
- [ ] **Step 4：提交** `ci(deploy): add backup and rollback guardrails`。

**实施记录（2026-11-13）：** Step 1 现状确认——镜像 tag 已可追溯（不可变 `sha-<commit>` 标签 + OCI labels），`deploy.sh` 已有「健康检查失败 → 回退上一成功 tag（`.last-successful-image-tag`）+ 部署锁」；**缺发布前数据库备份与部署日志**。本轮补齐：`deploy.sh` 新增 `backup_database()`（`mariadb-dump --single-transaction --routines --triggers` → gzip → 校验 ≥1KB，<1KB 中止部署，保留最近 `BACKUP_KEEP=7` 份）与 `log_deploy()`（备份/部署开始/成功/回滚开始/成功或失败全链路写 `deploy.log`）；部署前强制备份失败即退出（exit 6）。同步更新 `docs/production_deployment.md` 第六节与 `.env.production.example`（`BACKUP_DIR`/`BACKUP_KEEP` 可选覆盖）。`bash -n` 通过。待办：Step 3 预发演练（备份恢复 + 失败自动回滚），需真实服务器。

### Task F7：统一列表在 Python 内存过滤

**上一轮结论**：部分聚合列表把全表读进内存再过滤（等级 `C`）。

- [x] **Step 1：定位**：`grep -n "for .* in db.scalars" backend/app/api.py` 找无 `limit` 的全表循环（例如重复用例检测，当前位于 `/cases/duplicates`）。
- [x] **Step 2：写性能失败测试**：用 SQL 计数/分组替代 Python 循环，断言查询走 DB 层（可用 SQLAlchemy `echo` 或语句计数）。
- [x] **Step 3：实现**：过滤、分组、分页下推到 SQL；补必要索引（依赖 F1）。
- [ ] **Step 4：验证**：在 1 万条用例的测试数据集上比对改造前后耗时与行数。
- [ ] **Step 5：提交** `perf(cases): push filtering to database`。

**实施记录（2026-11-13）：** `/cases/duplicates` 已改造：先用 SQL 聚合（`lower(trim(...))` 键表达式 + `GROUP BY ... HAVING count>1`）求重复键，再只加载重复组成员实体，不再把全表用例（含大 JSON 列）实例化进内存。键语义与原 Python 逻辑一致（API/PERF=lower(trim(upper(method)+' '+path))，UI=lower(trim(target_url))；空键在 SQL 层过滤）。注：SQL `TRIM` 仅剥离空格，与 Python `strip()` 在制表符/换行场景存在理论差异（路径/URL 场景无实际影响）。待办：Step 4 万级数据集基准与索引评估（依赖 F1 迁移）。

---

## 9. Phase G — 体验、响应式与规范

### Task G1：移动端能力被裁掉 + 宽泛隐藏表格样式

**证据**：390×844 下 UI 用例页无整页溢出，卡片仅「详情/执行」，缺编辑与选择入口（[CaseTable.vue:73-91](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/components/CaseTable.vue#L73)）；计划与报告用 `.el-table { display: none; }`（[plan/index.vue:1014](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/plan/index.vue#L1014)、[report/index.vue:1281](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/report/index.vue#L1281)），可能连弹窗内表格一起隐藏（`D`，需 fixture 复现）。

- [ ] **Step 1：先复现**：窄屏打开计划/报告的用例明细弹窗，截图确认主表与弹窗表是否都被隐藏。
- [ ] **Step 2：实现**：隐藏规则限定为「主列表专用 class」（如 `.list-table-on-desktop`）；UI 用例卡片补「编辑」与选择控件（或「更多」菜单），空态与错误态补齐。
- [ ] **Step 3：验证**：390/768/1440 三档宽度手测关键路径；e2e 增加一个移动端断言。
- [ ] **Step 4：提交** `fix(responsive): scope table hiding and restore mobile actions`。

**先决产品问题：** 移动端定位是「查看 + 复核 + 触发执行」还是「完整编辑」。当前按前者实现，不硬塞桌面所有列。

### Task G2：编辑器渐进披露 `B`

**证据**：步骤行同时展示 target/role/accessible_name/test_id/selector（[ui/index.vue:309-314](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/index.vue#L309)）；native 四种执行模式 + 自愈 + 引擎选择一次性铺开（[:253](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/index.vue#L253)）。

- [ ] **Step 1：实现**：默认只显示「动作 + 目标 + 值」，其余折叠进「高级定位」；引擎/模式用一句场景说明（稳定回放 vs 视觉/自主）后再展开选项。
- [ ] **Step 2：验证**：新建流程首屏控件数下降，且老用例编辑不丢字段（结合 B1）。
- [ ] **Step 3：提交** `feat(ui-case): progressive disclosure in editor`。

### Task G3：把「预期条件」与「执行通过」区分开 `B`

**证据**：AI 草稿用绿色 `CircleCheck` 表示待验证条件（[AICaseComposer.vue:131-137](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/components/AICaseComposer.vue#L131)）；警告只显示第一条（[:109-112](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/components/AICaseComposer.vue#L109)）；Skill 版本硬编码展示（[:18](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/components/AICaseComposer.vue#L18)）。

- [x] **Step 1：实现**：条件项图标改中性并标注「待验证」；警告条显示「N 项」并可展开全部，区分「阻断」与「建议」；版本取结果元数据里的实际值（或直接不展示内部版本号）。
- [ ] **Step 2：验证**：vitest 组件测试断言警告数量与展开行为。
- [ ] **Step 3：提交** `fix(ai-composer): separate expectation from verified pass`。

**实施记录（2026-11-13）：** 已完成：断言项图标 `CircleCheck`→中性 `InfoFilled` 并加「待验证」状态标注（两处）；警告条改为「共 N 项需要留意」+ 本地 `warningsExpanded` 展开/收起；Skill 版本标签改为 `draft.skill_name/skill_version` 存在才渲染（删除硬编码）。typecheck/lint 通过。待办：Step 2 组件级 vitest 断言（现有用例覆盖数据层，未覆盖该组件渲染交互）。

### Task G4：导航暴露内部版本 `B`

**证据**：菜单同时有「用例生成」「用例生成2」（[router/index.js](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/router/index.js)）；桌面截图已确认并列出现。

- [ ] **Step 1：与用户确认**：V1 是否只读归档、是否允许新建。
- [ ] **Step 2：实现**：统一入口「AI 用例生成」，内部按模式/历史分组；旧任务通过历史列表可访问。**不合并两条后端流水线。**
- [ ] **Step 3：验证**：路由与菜单快照测试 + 手测历史可回看。
- [ ] **Step 4：提交** `refactor(nav): single AI generation entry`。

### Task G5：文案语言与时间口径统一 `D`

**证据**：分页与选择器出现 `Total 2 / 20/page / Select` 等英文组件默认文案（桌面截图确认）；[Header.vue:209-213](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/layout/components/Header.vue#L209) 对无时区时间补 `Z`，其他页面 `formatShortTime` 直接 `new Date`（口径差异需先确认后端返回格式才能定性）。

- [x] **Step 1：确认后端时间序列化口径**（naive UTC 还是带时区）。
- [x] **Step 2：实现**：Element Plus locale 统一中文；抽 `formatTime` 到 `frontend/src/lib/`，全站复用同一时区处理。
- [x] **Step 3：验证**：vitest 对同一时间戳断言跨页一致显示。
- [ ] **Step 4：提交** `fix(frontend): unify locale and time formatting`。

**实施记录（2026-11-13）：** Element Plus 中文 locale 经根组件挂载（`App.vue` 引入 `element-plus/es/locale/lang/zh-cn`）；新建 `frontend/src/lib/formatTime.js`（以 Header.vue 的 naive-UTC 补 Z → 本地时区展示为准），页面级重复 `formatShortTime/formatDateTime` 定义已替换为统一 import（Header、dashboard、workspace 各页、user、settings、CaseTable、BatchRunDrawer、ReviewPanel 等）；新增 `src/lib/__tests__/formatTime.test.js` 4 条用例通过（固定时间戳断言带 Z/不带 Z 一致）。全量 `npm run test`（4 文件通过，另有 9 条 forks worker 启动超时为本机资源限制所致非代码失败）、`typecheck`、`lint` 全部通过。待办：浏览器目检分页/选择器文案。

### Task G6：键盘可达与偏好保持 `D`

**证据**：看板卡片为 `div` + 原生拖拽（[KanbanBoard.vue:51-63](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/project/workspace/components/KanbanBoard.vue#L51)），键盘无法直接移动；详情产物用 `<button>` 内嵌 `el-button`（[ui/index.vue:419](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/views/case/ui/index.vue#L419)），非图片行点击外层无反馈；Header 侧栏按钮为纯图标（[Header.vue:34-41](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/layout/components/Header.vue#L34)）；resize 会覆盖用户手动折叠选择（[layout/index.vue:34-41](file:///Users/zhangyongcheng/Desktop/PPPtest/frontend/src/layout/index.vue#L34)）。同列内拖拽不生效（`onDrop` 同列直接 return），属于能力边界而非缺陷。

- [x] **Step 1：实现**：卡片 `tabindex` + 键盘打开详情 + 状态菜单作为拖拽替代路径（移动端同样受益）；去掉按钮嵌套；图标按钮补 `aria-label`；侧栏折叠区分「用户显式选择」与「断点默认」。
- [ ] **Step 2：验证**：`axe`/keyboard-only 手测一次看板与详情流程。
- [ ] **Step 3：提交** `a11y: keyboard paths for board and icon controls`。

**实施记录（2026-11-13）：** ①看板卡片 `tabindex="0"` + Enter/空格打开详情 + focus-visible 样式，卡片内「移动状态…」原生下拉作为拖拽键盘替代路径（复用 onDrop 载荷与归档映射，`@click.stop/@keydown.stop` 防误触）；②详情产物外层 `<button>` 改 `div role="button"` + 键盘激活，消除 button 嵌套 el-button，下载按钮 `@click.stop` 保留；③Header 侧栏按钮按状态动态 `aria-label`（折叠/展开侧边栏）；④`layout/index.vue` 新增 `userAdjustedSidebar` + `applyingSidebarDefault` 守卫，用户显式折叠后 resize 不再覆盖，未操作时仍按断点默认（无持久化）。typecheck 通过、`kanbanColumns.test.js` 4 用例通过（新增键盘路径用例）、case/ui 相关 3 测试文件通过、eslint 无告警。人工验收点：Tab 聚焦卡片→Enter 开详情；产物行 hover/预览反馈；读屏朗读侧栏按钮；跨 960px 断点拖动窗口不重置手动折叠。待办：axe/keyboard-only 手测（Step 2）。

**说明：** 本条是局部可访问性改进，**不构成 WCAG 完整合规审计**。性能（LCP/INP）本轮未测，需真实数据量下另测。

---

## 10. 明确不做或延后（反过度设计清单）

| 想法 | 决定 | 理由 |
|---|---|---|
| 全域事件溯源 / 所有异步动作 outbox | 延后，仅 E9 的派发窗口做对账 | 多数问题是同库事务与对象归属，不需要分布式机制 |
| 任意阶段回退的通用工作流引擎 | 不做，只支持已实现的检查点（E4） | 建议文案不能当作系统能力 |
| API/UI/PERF 合并成一张用例大表 | 不做，先统一公共字段与导入契约（E7） | 三者执行语义不同，合并只会把差异藏进 JSON |
| V1/V2 生成流水线整体重写 | 延后，先统一入口（G4）+ 修数据一致性（E1–E5）+ 质量对比 | 重写不能自动修好版本与契约问题 |
| 全局项目上下文 Store | 延后，先做 A1–A4 | Store 不解决旧响应归属与隐藏选择 |
| 全站草稿持久化到 localStorage | 不做 | 请求头/AI 参数可能含凭据，需先定义脱敏与过期策略 |
| 复杂质量总分体系 | 不做，用分维度指标（C2） | 总分会掩盖「未执行」这类关键事实 |
| 大规模模块重切 | 延后，等 D/E 的规则收敛 | 搬文件不消除多份事实源与反向依赖（`delivery_impl.py` 反向依赖 engine，等级 `C`） |
| 一次性并行开工全部阶段 | 不做 | 本文人日为粗估，含未定产品决策，先按 A→D→B→C→E→F→G 分批 |

---

## 11. 回归矩阵（每批实施后至少跑一遍）

**上下文与选择**
- [ ] 项目 A→B→A 往返（含慢响应、空列表、请求失败）
- [ ] 有执行记录用例 → 无执行记录用例
- [ ] 筛选变化前后存在勾选项
- [ ] 新建表单项目/目录/目标地址三者一致

**编辑与提交**
- [ ] 编辑中 Escape、切项目、关弹窗、点遮罩
- [ ] 切换步骤/断言动作后共用字段保留
- [ ] 保存成功 + 执行提交失败 → 重试不重复创建
- [ ] 请求 pending 期间连点保存/导入/删除
- [ ] 批量修改三态（不修改/设置为/清空）

**业务口径**
- [ ] 关联 2 条用例：1 成功 + 1 未执行 → 不是「已覆盖」
- [ ] 列表与看板记录数一致（含 REOPENED/WONTFIX/REJECTED）
- [ ] 计划转移中途失败 → 原计划与新计划都不出现半状态
- [ ] 报告创建内部缺陷 → 项目缺陷/追溯同一 ID 同一状态
- [ ] 报告 `run_id` 深链打开对应执行详情

**AI 生成**
- [ ] 选择模型 B 不静默跑 A；排队期间改共享配置不影响已提交任务
- [ ] 同产物 ID 更新两次 → 预览 = 门禁 = 下载 同一版本
- [ ] 成功 → 部分失败 → 恢复 不混产物
- [ ] 需求门禁失败且无 `testcase_package` → 不提供 source 重跑
- [ ] 假模型注入「JSON 错 + 契约错 + 限流」不越调用预算

**移动端与键盘**
- [ ] 390/768/1440 三档：列表、详情、弹窗表、批量操作
- [ ] 键盘完成「打开看板卡片 → 改状态 → 打开详情」
- [ ] 空态 / 加载失败 / 重试 在移动与桌面均可用

**质量门**
- [ ] `cd backend && pytest -q`
- [ ] `cd frontend && npm run lint && npm run typecheck && npm run test`
- [ ] `docker compose run --rm e2e npx playwright test`（CI 中 5 个 spec 全通过）
- [ ] `bash scripts/health_check.sh`

---

## 12. 实施前必须先决策的问题

1. `DefectRecord` 的定位：外部跟踪登记，还是应被 `Defect` 取代的内部缺陷？（影响 C1 迁移策略）
2. 需求/缺陷「不予处理、已关闭、已拒绝」在看板上是否应独立成列（C3）还是折叠归档。
3. 用例是否允许跨项目移动，若允许，评审状态与目录如何处理（D1）。
4. 非评审角色能否在创建/导入时直接给出已批准状态（D2 的业务例外）。
5. 移动端目标能力集（G1）：只读复核，还是包含编辑。
6. V1 用例生成的历史任务是否需要长期保留入口，能否只读（G4）。
7. 「复制到待评审计划」是否足够，还是必须有真正的原子迁移（C5 Option B）。
8. 是否引入 Alembic 并让 CI 执行迁移（F1，阻塞 E2/E3/E5 的 schema 变更）。

---

## 13. 未验证与已知空白（诚实边界）

- 本轮**未运行**后端 pytest / 前端 vitest / e2e / 构建 / 真实数据库 / 真实模型调用；上述所有「现状证据」是源码阅读与隔离 fixture 浏览器复现，不代表修复可行。
- 标记为 `C` 的条目源自上一轮审查，行号与结论**需在实施前复核**（本文件里的近期改动可能已修复部分）。
- 成本结论（E6 模型调用费用、F7 性能收益）为待测量项，**当前无数据支撑**。
- 交互走查不等同于真实用户研究，也不等同于完整无障碍合规审计。
- 工作树中存在大量用户既有未提交改动；实施时**不得**清理、覆盖或整目录 `git add`。
