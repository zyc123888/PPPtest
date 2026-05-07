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

test('最后一个 Owner 不可降级且不可移除', async ({ page }) => {
  const suffix = Date.now()
  const workspaceName = `OwnerGuard_${suffix}`

  await login(page)

  await page.goto('/workspace/index')
  await page.getByRole('button', { name: '新增空间' }).click()
  const workspaceDialog = page.locator('.el-dialog').filter({ hasText: '新增工作空间' }).last()
  await workspaceDialog.getByPlaceholder('例如：核心业务').fill(workspaceName)
  await workspaceDialog.getByPlaceholder('可选').fill('owner guard e2e flow')
  await workspaceDialog.getByRole('button', { name: '确认' }).click()
  await expect(page.getByText('创建成功').first()).toBeVisible()

  await page.getByPlaceholder('空间名称/说明').fill(workspaceName)
  await page.getByRole('button', { name: '查询' }).click()
  const workspaceRow = page.getByRole('row').filter({ hasText: workspaceName }).last()
  await workspaceRow.getByRole('button', { name: '成员管理' }).click()

  const memberDialog = page.locator('.el-dialog').filter({ hasText: `成员管理 · ${workspaceName}` }).last()
  await expect(memberDialog).toBeVisible()

  const adminRow = memberDialog.getByRole('row').filter({ hasText: ADMIN_USER }).last()
  await expect(adminRow).toContainText('Owner')
  await expect(adminRow.getByRole('button', { name: '移除' })).toBeDisabled()

  await adminRow.locator('.el-select').click()
  await page.getByRole('option', { name: 'Member' }).click()

  await expect(page.getByText('工作空间至少需要保留一个 Owner').first()).toBeVisible()
  await expect(memberDialog.getByRole('row').filter({ hasText: ADMIN_USER }).last()).toContainText('Owner')
})
