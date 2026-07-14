const { test, expect } = require('@playwright/test')

const ADMIN_USER = process.env.E2E_ADMIN_USER || 'admin'
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'admin123'

async function login(page) {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill(ADMIN_USER)
  await page.getByPlaceholder('请输入密码').fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/dashboard/, { timeout: 10000 })
}

async function authHeaders(page) {
  const token = await page.evaluate(() => localStorage.getItem('tp_token'))
  expect(token).toBeTruthy()
  return { Authorization: `Bearer ${token}` }
}

test('UI 用例可结构化创建、预检、执行并查看证据', async ({ page }) => {
  test.setTimeout(120000)
  const caseName = `UI闭环_${Date.now()}`
  const importedCaseName = `UI导入_${Date.now()}`

  await login(page)
  await page.goto('/case/ui')
  await expect(page.locator('.page-title')).toHaveText('UI 用例')
  await expect(page.getByText('用例总数', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '新增 UI 用例' }).click()
  const editor = page.locator('.el-dialog').filter({ hasText: '新增 UI 用例' }).last()
  await expect(editor).toBeVisible()
  await editor.getByLabel('用例名称').fill(caseName)
  await editor.getByLabel('目录/分组').fill('E2E/浏览器巡检')
  await editor.getByLabel('目标地址').fill('http://frontend:3000/login')

  await editor.getByRole('tab', { name: /操作步骤/ }).click()
  await editor.getByRole('button', { name: '添加步骤' }).click()
  const step = editor.locator('.builder-row').last()
  await step.locator('.builder-action').click()
  await page.getByRole('option', { name: '等待文本' }).click()
  await step.getByPlaceholder('步骤名称（可选）').fill('等待登录页渲染')
  await step.getByPlaceholder('限定选择器（可选）').fill('body')
  await step.getByPlaceholder('文本').fill('登录')

  await editor.getByRole('tab', { name: /断言/ }).click()
  await editor.getByLabel('最终文本断言').fill('登录')
  await editor.getByRole('button', { name: '添加断言' }).click()
  const assertion = editor.locator('.assertion-row').last()
  await assertion.getByPlaceholder('断言名称（可选）').fill('登录按钮可见')
  await assertion.getByPlaceholder('限定选择器（可选）').fill('button')
  await assertion.getByPlaceholder('期望文本').fill('登录')

  await editor.getByRole('button', { name: '保存用例' }).click()
  await expect(page.getByText('UI 用例已创建').first()).toBeVisible()
  await expect(editor).toBeHidden()

  await page.getByPlaceholder('搜索名称、分组、地址或标签').fill(caseName)
  const caseRow = page.getByRole('row').filter({ hasText: caseName }).last()
  await expect(caseRow).toBeVisible()
  await page.screenshot({ path: '/tmp/ui-case-desktop.png', fullPage: true })

  await caseRow.getByRole('button', { name: '编辑 UI 用例' }).click()
  const editDialog = page.locator('.el-dialog').filter({ hasText: '编辑 UI 用例' }).last()
  await expect(editDialog).toBeVisible()
  await editDialog.getByLabel('目录/分组').fill('E2E/浏览器巡检/已复核')
  await editDialog.locator('.el-form-item').filter({ hasText: '评审状态' }).locator('.el-select').click()
  await page.getByRole('option', { name: '已通过' }).click()
  await editDialog.getByRole('button', { name: '保存用例' }).click()
  await expect(page.getByText('UI 用例已更新').first()).toBeVisible()
  await expect(editDialog).toBeHidden()
  await expect(caseRow).toContainText('v1.0.1')

  const headers = await authHeaders(page)
  const caseResponse = await page.request.get('/api/v1/ui-cases', { headers })
  expect(caseResponse.ok()).toBeTruthy()
  const createdCase = (await caseResponse.json()).find((item) => item.name === caseName)
  expect(createdCase).toBeTruthy()
  expect(createdCase.folder_path).toBe('E2E/浏览器巡检/已复核')
  expect(createdCase.review_status).toBe('APPROVED')
  expect(createdCase.version_no).toBe('1.0.1')
  expect(createdCase.steps_json).toEqual([
    { action: 'wait_for_text', name: '等待登录页渲染', selector: 'body', value: '登录' }
  ])
  expect(createdCase.assertions_json).toEqual([
    { type: 'text_visible', name: '登录按钮可见', selector: 'button', value: '登录' }
  ])

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出当前结果' }).click()
  const download = await downloadPromise
  const stream = await download.createReadStream()
  let exportText = ''
  for await (const chunk of stream) exportText += chunk.toString()
  const exported = JSON.parse(exportText)
  expect(exported.count).toBe(1)
  expect(exported.items[0].name).toBe(caseName)
  expect(exported.items[0].steps_json).toEqual(createdCase.steps_json)
  expect(exported.items[0].assertions_json).toEqual(createdCase.assertions_json)

  await page.getByRole('button', { name: '导入 UI 用例' }).click()
  const importDialog = page.locator('.el-dialog').filter({ hasText: '导入 UI 用例' }).last()
  await importDialog.locator('textarea').fill(JSON.stringify({
    items: [{
      case_type: 'UI', project_id: createdCase.project_id, name: importedCaseName,
      folder_path: 'E2E/导入验证', target_url: 'http://frontend:3000/login', priority: 'P2',
      status: 'ACTIVE', review_status: 'DRAFT', version_no: '1.0.0', tags_json: ['e2e-import'],
      steps_json: [{ action: 'wait_for_text', selector: 'body', value: '登录' }],
      assertions_json: [{ type: 'text_visible', selector: 'button', value: '登录' }], expect_text: '登录'
    }]
  }))
  await importDialog.getByRole('button', { name: '导入', exact: true }).click()
  await expect(page.getByText('UI 用例导入成功').first()).toBeVisible()
  await page.getByPlaceholder('搜索名称、分组、地址或标签').fill(importedCaseName)
  const importedRow = page.getByRole('row').filter({ hasText: importedCaseName }).last()
  await expect(importedRow).toBeVisible()
  await importedRow.getByRole('button', { name: '删除 UI 用例' }).click()
  const confirmDialog = page.locator('.el-message-box').last()
  await confirmDialog.getByRole('button', { name: '删除', exact: true }).click()
  await expect(page.getByText('UI 用例已删除').first()).toBeVisible()
  await expect(importedRow).toBeHidden()
  await page.getByPlaceholder('搜索名称、分组、地址或标签').fill(caseName)

  await caseRow.getByRole('button', { name: caseName }).click()
  const drawer = page.locator('.el-drawer').last()
  await expect(drawer).toBeVisible()
  await expect(drawer.getByText('等待登录页渲染')).toBeVisible()
  await expect(drawer.getByText('登录按钮可见')).toBeVisible()
  await expect(drawer.getByText('1 步', { exact: true })).toBeVisible()
  await expect(drawer.getByText('2 项', { exact: true })).toBeVisible()

  await drawer.getByRole('tab', { name: /执行记录/ }).click()
  await drawer.getByRole('button', { name: '立即执行' }).click()
  const runDialog = page.locator('.el-dialog').filter({ hasText: '执行 UI 用例' }).last()
  await runDialog.getByRole('button', { name: '执行前校验' }).click()
  await expect(page.getByText('执行预检通过').first()).toBeVisible()
  await expect(runDialog.locator('.precheck-panel')).toContainText('未发现缺失变量')
  await expect(runDialog.locator('.precheck-panel')).not.toHaveClass(/is-invalid/)
  await runDialog.getByRole('button', { name: '开始执行' }).click()

  let completedRun
  for (let attempt = 0; attempt < 75; attempt += 1) {
    const response = await page.request.get(`/api/v1/executions/runs?case_type=UI&case_id=${createdCase.id}&limit=10`, { headers })
    expect(response.ok()).toBeTruthy()
    const [run] = await response.json()
    if (run && !['PENDING', 'RUNNING'].includes(run.status)) {
      completedRun = run
      break
    }
    await page.waitForTimeout(1000)
  }

  expect(completedRun).toBeTruthy()
  expect(completedRun.status).toBe('SUCCESS')

  const detailResponse = await page.request.get(`/api/v1/executions/runs/${completedRun.id}`, { headers })
  const stepResponse = await page.request.get(`/api/v1/executions/runs/${completedRun.id}/steps`, { headers })
  const artifactResponse = await page.request.get(`/api/v1/executions/runs/${completedRun.id}/artifacts`, { headers })
  expect(detailResponse.ok()).toBeTruthy()
  expect(stepResponse.ok()).toBeTruthy()
  expect(artifactResponse.ok()).toBeTruthy()
  expect((await stepResponse.json()).length).toBeGreaterThanOrEqual(4)
  const artifacts = (await artifactResponse.json()).artifacts
  expect(artifacts.some((item) => item.name === 'ui-success.png')).toBeTruthy()
  expect(artifacts.some((item) => item.name === 'ui-trace.zip')).toBeTruthy()

  await expect(drawer.getByText('成功', { exact: true }).last()).toBeVisible({ timeout: 10000 })
  await expect(drawer.getByText('步骤结果', { exact: true })).toBeVisible()
  await expect(drawer.getByText('执行产物', { exact: true })).toBeVisible()
  await expect(drawer.getByText('ui-success.png', { exact: true })).toBeVisible()
  await expect(drawer.locator('.artifact-preview img')).toBeVisible()
  await page.screenshot({ path: '/tmp/ui-case-detail.png', fullPage: true })
})

test('UI 用例列表在移动端保持可操作', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await login(page)
  await page.goto('/case/ui')
  await expect(page.locator('.page-title')).toHaveText('UI 用例')
  await expect(page.locator('.mobile-cards')).toBeVisible()
  await expect(page.locator('.case-table')).toBeHidden()
  await expect(page.getByRole('button', { name: '新增 UI 用例' })).toBeVisible()
  await page.screenshot({ path: '/tmp/ui-case-mobile.png', fullPage: true })
})
