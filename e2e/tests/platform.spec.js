const { test, expect } = require('@playwright/test')

async function login(page) {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill('admin')
  await page.getByPlaceholder('请输入密码').fill('admin123')
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/dashboard/, { timeout: 10000 })
}

test('平台首页可以加载并使用工具面板', async ({ page }) => {
  await login(page)
  await expect(page.getByTestId('app-title')).toContainText('自动化测试平台')
  await expect(page.getByText('前端在线')).toBeVisible()

  await page.getByTestId('tab-tools').click()
  await page.getByTestId('json-input').fill('{"name":"平台","status":"正常"}')
  await page.getByTestId('json-format-btn').click()

  await expect(page.getByTestId('json-output')).toHaveValue(/"status": "正常"/)
})
