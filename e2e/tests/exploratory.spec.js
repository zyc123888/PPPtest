const { test, expect } = require('@playwright/test')

async function login(page) {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill('admin')
  await page.getByPlaceholder('请输入密码').fill('admin123')
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/dashboard/, { timeout: 10000 })
}

test.describe('自动化测试平台 - 探索式测试', () => {
  
  test.beforeEach(async ({ page }) => {
    await login(page)
    // 确保页面加载完成
    await expect(page.locator('.layout-aside')).toBeVisible()
  })

  test('功能与边界测试：项目管理', async ({ page }) => {
    // 导航
    await page.getByRole('menuitem', { name: '项目管理' }).click()
    await expect(page).toHaveURL(/\/project\/index/)

    // 1. 正常流程：创建项目
    await page.getByRole('button', { name: '新增项目' }).click()
    const dialog = page.locator('.el-dialog').filter({ hasText: '新增项目' })
    await expect(dialog).toBeVisible()
    
    const testProjectName = `TestProject_${Date.now()}`
    await dialog.locator('input[placeholder="例如：订单中心"]').fill(testProjectName)
    await dialog.locator('input[placeholder="http://backend:8000"]').fill('http://127.0.0.1:8000')
    await dialog.locator('textarea').fill('自动化测试创建的项目')
    await dialog.getByRole('button', { name: '确认' }).click()
    
    // 验证创建成功
    await expect(page.getByText('创建成功').first()).toBeVisible()
    await page.getByPlaceholder('项目名称/说明').fill(testProjectName)
    await page.getByRole('button', { name: '查询' }).click()
    const projectRow = page.getByRole('row', { name: new RegExp(testProjectName) })
    await expect(projectRow).toBeVisible({ timeout: 10000 })

    // 2. 边界流程：空值校验
    await page.getByRole('button', { name: '新增项目' }).click()
    await dialog.locator('input[placeholder="例如：订单中心"]').fill('') // 清空
    await dialog.locator('input[placeholder="http://backend:8000"]').fill('')
    await dialog.getByRole('button', { name: '确认' }).click()
    
    // 验证错误提示 (Element Plus form validation)
    await expect(page.getByText('项目名称必填')).toBeVisible()
    await expect(page.getByText('基础地址必填')).toBeVisible()
    await dialog.getByRole('button', { name: '取消' }).click()
  })

  test('功能与边界测试：接口用例', async ({ page }) => {
    await page.getByRole('menuitem', { name: '用例管理' }).click()
    await page.getByRole('menuitem', { name: '接口用例' }).click()

    // 1. 异常流程：JSON 格式校验
    await page.getByRole('button', { name: '新增接口用例' }).click()
    const dialog = page.locator('.el-dialog').filter({ hasText: '新增接口用例' })
    
    await dialog.locator('input[placeholder="请输入用例名称"]').fill('Bad JSON Case')
    await dialog.locator('input[placeholder="/api/v1/..."]').fill('/test')
    await dialog.locator('.el-select').first().click()
    await page.getByRole('option').first().click()
    
    // 输入非法 JSON
    await dialog.locator('textarea').first().fill('{ "bad": json }') // 正常
    await dialog.locator('textarea').nth(1).fill('{ bad: json }') // 非法
    
    await dialog.getByRole('button', { name: '确认' }).click()
    // 验证是否拦截
    await expect(page.getByText('JSON 格式错误').first()).toBeVisible()
    
    // 2. 正常流程：创建并执行
    await dialog.locator('textarea').first().fill('{ \"accept\": \"application/json\" }') // 修复 headers
    await dialog.locator('textarea').nth(1).fill('{}') // 修复 body
    await dialog.getByRole('button', { name: '确认' }).click()
    await expect(page.getByText('创建成功')).toBeVisible()
    
    // 执行 (Mock 接口调用或真实调用)
    // 找到刚才创建的行，点击执行
    const row = page.getByRole('row', { name: /Bad JSON Case/ }).first()
    await row.getByRole('button', { name: '立即执行' }).first().click()
    await expect(page.getByText('任务已投递')).toBeVisible()
  })

  test('UI/UX 细节检查：常用工具', async ({ page }) => {
    await page.goto('/tools/index')
    
    // 1. 检查 Tab 切换
    await expect(page.locator('.page-title')).toContainText('常用工具')
    
    // 2. Base64 编解码体验
    await page.getByText('Base64 编解码').click()
    const input = page.locator('textarea[placeholder="请输入内容"]')
    await input.fill('Hello World')
    await page.getByRole('button', { name: '编码' }).click()
    const output = page.locator('textarea[placeholder="结果"]')
    await expect(output).toHaveValue('SGVsbG8gV29ybGQ=')
    
    // 3. 解码
    await input.fill('SGVsbG8gV29ybGQ=')
    await page.getByRole('button', { name: '解码' }).click()
    await expect(output).toHaveValue('Hello World')
  })

  test('系统健壮性：不存在的路由', async ({ page }) => {
    await page.goto('/not-exists-page')
    // 应该重定向回 Dashboard 或显示 404
    // 根据 router 配置：redirect: '/dashboard'
    await expect(page).toHaveURL(/\/dashboard/)
  })
})
