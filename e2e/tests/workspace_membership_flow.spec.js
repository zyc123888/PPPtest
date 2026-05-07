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

test('成员管理联动流程可运行', async ({ page }) => {
  const suffix = Date.now()
  const workspaceName = `MemberSpace_${suffix}`
  const username = `member_user_${suffix}`
  const displayName = `成员用户${suffix}`
  const password = 'member123'

  await login(page)

  await page.goto('/workspace/index')
  await page.getByRole('button', { name: '新增空间' }).click()
  const workspaceDialog = page.locator('.el-dialog').filter({ hasText: '新增工作空间' }).last()
  await expect(workspaceDialog).toBeVisible()
  await workspaceDialog.getByPlaceholder('例如：核心业务').fill(workspaceName)
  await workspaceDialog.getByPlaceholder('可选').fill('workspace membership e2e flow')
  await workspaceDialog.getByRole('button', { name: '确认' }).click()
  await expect(page.getByText('创建成功').first()).toBeVisible()

  await page.goto('/user/index')
  await page.getByRole('button', { name: '新增用户' }).click()
  const userDialog = page.locator('.el-dialog').filter({ hasText: '新增用户' }).last()
  await expect(userDialog).toBeVisible()
  await userDialog.getByPlaceholder('例如：tester1').fill(username)
  await userDialog.getByPlaceholder('可选').fill(displayName)
  await userDialog.locator('.el-select').first().click()
  await page.getByRole('option', { name: '测试工程师' }).click()
  await userDialog.getByPlaceholder('至少6位').fill(password)
  await userDialog.getByRole('button', { name: '确认' }).click()
  await expect(page.getByText('创建成功').first()).toBeVisible()

  const userRow = page.getByRole('row').filter({ hasText: username }).last()
  await expect(userRow).toContainText('默认空间')

  await page.goto('/workspace/index')
  await page.getByPlaceholder('空间名称/说明').fill(workspaceName)
  await page.getByRole('button', { name: '查询' }).click()
  const workspaceRow = page.getByRole('row').filter({ hasText: workspaceName }).last()
  await expect(workspaceRow).toBeVisible()
  await workspaceRow.getByRole('button', { name: '成员管理' }).click()

  const memberDialog = page.locator('.el-dialog').filter({ hasText: `成员管理 · ${workspaceName}` }).last()
  await expect(memberDialog).toBeVisible()
  await memberDialog.locator('.el-select').first().click()
  await page.getByRole('option', { name: new RegExp(username) }).click()
  await memberDialog.getByRole('button', { name: '添加成员' }).click()
  await expect(page.getByText('成员已添加').first()).toBeVisible()

  const memberRow = memberDialog.getByRole('row').filter({ hasText: username }).last()
  await expect(memberRow).toContainText('Member')
  await memberDialog.getByRole('button', { name: '关闭' }).click()

  await page.goto('/user/index')
  const targetUserRow = page.getByRole('row').filter({ hasText: username }).last()
  await expect(targetUserRow).toContainText(workspaceName)
  await targetUserRow.getByText(workspaceName).click()

  await expect(page).toHaveURL(new RegExp(`/workspace/index\\?workspace_id=\\d+`))
  const jumpedWorkspaceRow = page.getByRole('row').filter({ hasText: workspaceName }).last()
  await expect(jumpedWorkspaceRow).toBeVisible()
  await jumpedWorkspaceRow.getByRole('button', { name: '成员管理' }).click()

  const roleDialog = page.locator('.el-dialog').filter({ hasText: `成员管理 · ${workspaceName}` }).last()
  const roleRow = roleDialog.getByRole('row').filter({ hasText: username }).last()
  await roleRow.locator('.el-select').click()
  await page.getByRole('option', { name: 'Owner' }).click()
  await expect(page.getByText('成员角色已更新').first()).toBeVisible()
  await expect(roleDialog.getByRole('row').filter({ hasText: username }).last()).toContainText('Owner')
  await roleDialog.getByRole('button', { name: '关闭' }).click()

  await page.goto('/user/index')
  const updatedUserRow = page.getByRole('row').filter({ hasText: username }).last()
  await expect(updatedUserRow).toContainText(`${workspaceName} · owner`)
})
