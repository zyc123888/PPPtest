// Midscene AI 自主执行 UI 用例（PoC）
// 运行前：在 e2e/.env 里填好模型配置（见 .env.example），并确保前端已在 E2E_BASE_URL 运行。
// 运行：npm run test:ai
const { test, expect } = require('../fixture')

// 登录用确定性选择器（已知可用、不消耗大模型 token）
async function login(page) {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill('admin')
  await page.getByPlaceholder('请输入密码').fill('admin123')
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/dashboard/, { timeout: 10000 })
}

// 用例 1：最小连通性冒烟——验证模型接线正确、AI 能"看懂"页面
test('AI 冒烟：登录后能识别并断言首页', async ({ page, aiAssert, aiQuery }) => {
  await login(page)
  await aiAssert('页面顶部显示"自动化测试平台"标题，且处于已登录状态')
  const menus = await aiQuery('string[]，返回左侧导航菜单里所有可见的菜单名称')
  console.log('侧边菜单：', menus)
  expect(Array.isArray(menus) && menus.length > 0).toBeTruthy()
})

// 用例 2：真实业务流——AI 自主进入项目缺陷列表并新建一条缺陷
test('AI 自主执行：进入项目缺陷列表并新建缺陷', async ({ page, ai, aiInput, aiTap, aiAssert, aiWaitFor }) => {
  await login(page)
  const title = `AI缺陷_${Date.now()}`

  // 进入项目管理并打开第一个项目的工作台
  await ai('点击左侧导航中的"项目管理"菜单')
  await aiWaitFor('页面出现项目列表', { timeoutMs: 8000 })
  await ai('打开列表中的第一个项目（点击项目名称或该行的"进入/详情"按钮进入项目工作台）')

  // 切换到缺陷模块
  await ai('在项目工作台内切换到"缺陷"标签或菜单')
  await aiWaitFor('出现缺陷列表以及"新增缺陷"按钮', { timeoutMs: 8000 })

  // 新建缺陷
  await aiTap('"新增缺陷"按钮')
  await aiInput(title, '缺陷标题/名称输入框')
  await ai('在弹窗中点击"创建"或"确认"按钮提交这条缺陷')

  // 断言：新缺陷出现在列表中
  await aiAssert(`缺陷列表中出现标题为「${title}」的缺陷记录`)
})
