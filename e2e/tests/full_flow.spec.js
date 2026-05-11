const { test, expect } = require('@playwright/test')

async function login(page) {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill('admin')
  await page.getByPlaceholder('请输入密码').fill('admin123')
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/dashboard/, { timeout: 10000 })
}

test('生产级完整流程：项目-用例-计划-执行-报告', async ({ page }) => {
  const suffix = Date.now()
  const projectName = `ProdProject_${suffix}`
  const apiCaseName = `HealthCase_${suffix}`
  const planName = `Plan_${suffix}`

  await login(page)

  // 项目管理 - 新增项目
  await page.getByRole('menuitem', { name: '项目管理' }).click()
  await page.getByRole('button', { name: '新增项目' }).click()
  const projectDialog = page.locator('.el-dialog').filter({ hasText: '新增项目' })
  await expect(projectDialog).toBeVisible()
  await projectDialog.locator('.el-select').click()
  await page.getByRole('option').first().click()
  await projectDialog.getByPlaceholder('例如：订单中心').fill(projectName)
  await projectDialog.getByPlaceholder('http://backend:8000').fill('http://backend:8000')
  await projectDialog.locator('textarea').fill('production flow project')
  await projectDialog.getByRole('button', { name: '确认' }).click()
  await expect(page.getByText('创建成功').first()).toBeVisible()

  // 接口用例 - 新增 API 用例
  await page.getByRole('menuitem', { name: '用例管理' }).click()
  await page.getByRole('menuitem', { name: '接口用例' }).click()
  await page.getByRole('button', { name: '新增接口用例' }).click()
  const apiDialog = page.locator('.el-dialog').filter({ hasText: '新增接口用例' })
  await apiDialog.locator('.el-select').first().click()
  await page.getByRole('option', { name: projectName }).click()
  await apiDialog.getByPlaceholder('请输入用例名称').fill(apiCaseName)
  await apiDialog.getByPlaceholder('/api/v1/...').fill('/api/v1/system/health')
  await apiDialog.getByRole('spinbutton').fill('200')
  await apiDialog.getByPlaceholder('{"Content-Type": "application/json"}').fill('{"accept":"application/json"}')
  await apiDialog.getByPlaceholder('{}').fill('{}')
  await apiDialog.getByRole('button', { name: '确认' }).click()
  await expect(page.getByText('创建成功').first()).toBeVisible()

  // 测试计划 - 新增计划
  await page.getByRole('menuitem', { name: '测试计划' }).click()
  await page.getByRole('button', { name: '新增计划' }).click()
  const planDialog = page.locator('.el-dialog').filter({ hasText: '新增测试计划' })
  await planDialog.locator('.el-select').click()
  await page.getByRole('option', { name: projectName }).click()
  await planDialog.getByPlaceholder('例如：核心回归').fill(planName)
  await planDialog.locator('textarea').fill('production plan')
  await planDialog.getByRole('button', { name: '确认' }).click()
  await expect(page.getByText('创建成功').first()).toBeVisible()

  // 配置计划用例
  const planRow = page.getByRole('row', { name: new RegExp(planName) })
  await planRow.getByRole('button', { name: '用例配置' }).click()
  const caseDialog = page.locator('.el-dialog').filter({ hasText: '计划用例配置' })
  await caseDialog.locator('.el-select').first().click()
  await page.getByRole('option', { name: 'API' }).click()
  await caseDialog.locator('.el-select').nth(1).click()
  await page.getByRole('option', { name: apiCaseName }).click()
  await caseDialog.getByRole('button', { name: '加入计划' }).click()
  await expect(caseDialog.getByText(apiCaseName)).toBeVisible()
  await page.keyboard.press('Escape')

  // 执行测试计划
  await planRow.getByRole('button', { name: '执行计划' }).click()
  const runDialog = page.locator('.el-dialog').filter({ hasText: '执行测试计划' })
  await runDialog.getByRole('button', { name: '确认执行' }).click()
  await expect(page.getByText('计划已投递')).toBeVisible()

  // 报告中心 - 等待报告生成
  await page.getByRole('menuitem', { name: '报告中心' }).click()
  await page.getByRole('button', { name: '刷新' }).click()
  const reportRow = page.getByRole('row', { name: new RegExp(planName) })
  await expect(reportRow).toBeVisible({ timeout: 20000 })
  await reportRow.getByRole('button', { name: '详情' }).click()
  await expect(page.getByText(apiCaseName)).toBeVisible()
})
