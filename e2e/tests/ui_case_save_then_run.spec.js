const { test, expect } = require('@playwright/test')

test('AI 用例保存后重试运行不重复创建', async ({ page }) => {
  let creates = 0
  let runs = 0
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill(process.env.E2E_ADMIN_USER || 'admin')
  await page.getByPlaceholder('请输入密码').fill(process.env.E2E_ADMIN_PASSWORD || '')
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/dashboard/)

  await page.route('**/api/v1/ui-cases/ai/generate', async (route) => {
    const request = route.request().postDataJSON()
    await route.fulfill({ json: { draft: {
      project_id: request.project_id, name: '重试验证用例', target_url: request.target_url,
      expect_text: 'ready', steps_json: [], assertions_json: [], generation_mode: 'ai_skill'
    }, warnings: [] } })
  })
  await page.route('**/api/v1/ui-cases', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    creates += 1
    await route.fulfill({ status: 201, json: { id: 987654 } })
  })
  await page.route('**/api/v1/executions/ui/987654/precheck', (route) => route.fulfill({ json: { is_valid: true } }))
  await page.route('**/api/v1/executions/ui/987654/run', async (route) => {
    runs += 1
    await route.fulfill({ status: 500, json: { detail: '模拟执行失败' } })
  })

  await page.goto('/case/ui')
  await page.getByRole('button', { name: 'AI 创建' }).click()
  const dialog = page.locator('.el-dialog:visible').filter({ hasText: 'AI 创建 UI 用例' })
  await dialog.getByPlaceholder('https://example.com').fill('http://example.test')
  await dialog.locator('textarea').first().fill('打开页面并验证内容出现')
  await dialog.getByRole('button', { name: '生成测试步骤' }).click()
  await dialog.getByRole('button', { name: '保存并试运行' }).click()
  await expect(dialog).toContainText('用例已创建（#987654）')
  await expect(dialog).toContainText('试运行未提交')
  await dialog.getByRole('button', { name: '重试运行' }).click()
  await expect.poll(() => runs).toBe(2)
  expect(creates).toBe(1)
})
