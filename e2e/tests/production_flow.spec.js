const { test, expect } = require('@playwright/test')

test('生产级完整流程可运行', async ({ page }) => {
  const now = Date.now()
  const projectName = `ProdProject_${now}`
  const envName = `ProdEnv_${now}`
  const apiCaseName = `ProdApiCase_${now}`
  const planName = `ProdPlan_${now}`

  await page.goto('/login')
  await page.getByPlaceholder('请输入密码').fill('admin123')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/dashboard/)

  await page.getByRole('menuitem', { name: '项目管理' }).click()
  await page.getByRole('button', { name: '新增项目' }).click()
  await page.getByPlaceholder('例如：订单中心').fill(projectName)
  await page.getByPlaceholder('http://backend:8000').fill('http://127.0.0.1:8000')
  await page.getByPlaceholder('可选').fill('生产流验证项目')
  await page.getByRole('button', { name: '确认' }).click()
  await page.keyboard.press('Escape')

  await page.getByRole('menuitem', { name: '环境管理' }).click()
  await page.getByRole('button', { name: '新增环境' }).click()
  await page.getByPlaceholder('例如：测试环境').fill(envName)
  await page.getByPlaceholder('http://backend:8000').fill('http://127.0.0.1:8000')
  await page.getByRole('button', { name: '确认' }).click()
  await page.keyboard.press('Escape')

  await page.getByRole('menuitem', { name: '用例管理' }).click()
  await page.getByRole('menuitem', { name: '接口用例' }).click()
  await page.getByRole('button', { name: '新增接口用例' }).click()
  await page.getByPlaceholder('请输入用例名称').fill(apiCaseName)
  await page.getByPlaceholder('/api/v1/...').fill('/api/v1/system/health')
  await page.getByRole('button', { name: '确认' }).click()
  await page.keyboard.press('Escape')

  await page.getByRole('menuitem', { name: '测试计划' }).click()
  await page.getByRole('button', { name: '新增计划' }).click()
  await page.getByPlaceholder('例如：核心回归').fill(planName)
  await page.getByRole('button', { name: '确认' }).click()
  await page.getByPlaceholder('计划名称/说明').fill(planName)
  await page.getByRole('button', { name: '查询' }).click()
  await expect(page.getByText(planName)).toBeVisible({ timeout: 10000 })

  const planRow = page.getByRole('row').filter({ hasText: planName }).first()
  await planRow.getByRole('button', { name: '用例配置' }).click()
  const caseDialog = page.locator('.el-dialog').filter({ hasText: '计划用例配置' }).last()
  await caseDialog.locator('.el-select').nth(1).click()
  await page.getByRole('option', { name: apiCaseName }).click()
  await caseDialog.getByRole('button', { name: '加入计划' }).click()
  await expect(caseDialog.getByText(apiCaseName)).toBeVisible({ timeout: 10000 })
  await page.keyboard.press('Escape')

  const planRowAfterConfig = page.getByRole('row').filter({ hasText: planName }).first()
  await planRowAfterConfig.getByRole('button', { name: '执行计划' }).click()
  await page.getByRole('button', { name: '确认执行' }).click()

  await page.getByRole('menuitem', { name: '报告中心' }).click()
  await expect(page.getByText(planName)).toBeVisible({ timeout: 15000 })

  const reportRow = page.getByRole('row').filter({ hasText: planName }).first()
  await reportRow.getByRole('button', { name: '详情' }).click()
  await expect(page.getByText(apiCaseName)).toBeVisible()
  await page.keyboard.press('Escape')

  await reportRow.getByRole('button', { name: 'JSON' }).click()
  await reportRow.getByRole('button', { name: 'JUnit' }).click()
})
