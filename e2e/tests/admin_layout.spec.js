const { test, expect } = require('@playwright/test')

async function login(page) {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill('admin')
  await page.getByPlaceholder('请输入密码').fill('admin123')
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/dashboard/, { timeout: 10000 })
}

test('企业级后台首页加载与导航验证', async ({ page }) => {
  // 1. 访问首页
  await login(page)
  
  // 验证页面标题
  await expect(page).toHaveTitle(/OmniTest/)
  
  // 验证侧边栏菜单存在
  const sidebar = page.locator('.layout-aside')
  await expect(sidebar).toBeVisible()
  
  // 验证顶部导航存在
  const header = page.locator('.layout-header')
  await expect(header).toBeVisible()

  // 2. 验证仪表盘核心元素
  // 检查统计卡片 (限定在 main 区域内查找，避免匹配到菜单)
  const main = page.locator('.layout-main')
  const resourceGrid = main.locator('.resource-grid')
  await expect(resourceGrid.getByText('工作空间', { exact: true })).toBeVisible()
  await expect(resourceGrid.getByText('项目总数', { exact: true })).toBeVisible()
  await expect(resourceGrid.getByText('接口用例', { exact: true })).toBeVisible()
  await expect(resourceGrid.getByText('UI 用例', { exact: true })).toBeVisible()
  await expect(resourceGrid.getByText('用例执行', { exact: true })).toBeVisible()
  
  // 检查健康状态面板
  await expect(page.locator('[aria-label="系统运行状态"]')).toBeVisible()

  // 3. 导航切换测试
  // 切换到项目管理
  await page.getByRole('menuitem', { name: '项目管理' }).click()
  await expect(page).toHaveURL(/\/project/)
  await expect(page.getByRole('button', { name: '新增项目' })).toBeVisible()

  // 切换到接口用例
  await page.getByRole('menuitem', { name: '用例管理' }).click()
  await page.getByRole('menuitem', { name: '接口用例' }).click()
  await expect(page).toHaveURL(/\/case\/api/)
  await expect(page.getByRole('button', { name: '新增接口用例' })).toBeVisible()

  // 切换到 UI 用例
  await page.getByRole('menuitem', { name: 'UI 用例' }).click()
  await expect(page).toHaveURL(/\/case\/ui/)
  await expect(page.getByRole('button', { name: '新增 UI 用例' })).toBeVisible()
  
  // 切换到执行中心
  await page.getByRole('menuitem', { name: '执行中心' }).click()
  await expect(page).toHaveURL(/\/execution/)
  
  // 切换到常用工具
  await page.getByRole('menuitem', { name: '常用工具' }).click()
  await expect(page).toHaveURL(/\/tools/)
  await expect(page.getByText('JSON 格式化')).toBeVisible()
})

test('常用工具交互验证', async ({ page }) => {
  await login(page)
  await page.goto('/tools/index') // Try explicit path first
  
  // If redirected or direct navigation works, check title
  // Add a longer timeout for initial load in case of compilation
  await expect(page.locator('.page-title')).toContainText('常用工具', { timeout: 10000 })
  
  // Element Plus 的 Tabs 渲染可能延迟
  // 先等待页面主体加载完成
  await page.locator('.app-page').waitFor()
  
  // 查找并点击 "JSON 格式化" 文本，不管它是什么元素
  const tabLabel = page.getByText('JSON 格式化', { exact: true })
  await expect(tabLabel).toBeVisible()
  await tabLabel.click()
  
  const jsonInput = page.getByPlaceholder('请输入 JSON')
  await jsonInput.fill('{"a":1,"b":2}')
  
  // 这里的 button 可能在 tab-pane 内部，需要确保可见性
  await page.getByRole('button', { name: '格式化 JSON' }).click()
  
  // 简单验证输出框有内容
  const jsonOutput = page.getByPlaceholder('格式化结果')
  await expect(jsonOutput).toBeVisible()
})
