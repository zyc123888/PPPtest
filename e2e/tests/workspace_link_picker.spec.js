const { test, expect } = require('@playwright/test')

test('需求关联选择器按类型区分相同编号', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill(process.env.E2E_ADMIN_USER || 'admin')
  await page.getByPlaceholder('请输入密码').fill(process.env.E2E_ADMIN_PASSWORD || '')
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/dashboard/)
  const projectId = await page.evaluate(async () => {
    const response = await fetch('/api/v1/projects', { headers: { Authorization: `Bearer ${localStorage.getItem('tp_token')}` } })
    return (await response.json())[0]?.id
  })
  expect(projectId).toBeTruthy()
  await page.route(`**/api/v1/projects/${projectId}/requirements?*`, (route) => route.fulfill({ json: {
    items: [{ id: 987611, title: '关联选择器测试需求', status: 'PENDING', priority: 'P2' }], total: 1
  } }))
  await page.route('**/api/v1/requirement/987611/comments', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/requirements/987611/cases', async (route) => {
    if (route.request().method() === 'POST') return route.fulfill({ json: { id: 1 } })
    return route.fulfill({ json: [] })
  })
  await page.route('**/api/v1/cases?*', (route) => route.fulfill({ json: [
    { case_type: 'API', case_id: 7, name: '同号接口用例', version_no: '1.0.0' },
    { case_type: 'UI', case_id: 7, name: '同号界面用例', version_no: '1.0.0' }
  ] }))
  await page.goto(`/project/${projectId}/requirements`)
  await page.getByText('关联选择器测试需求', { exact: true }).click()
  const drawer = page.locator('.el-drawer:visible')
  await drawer.getByPlaceholder('搜索当前项目用例').fill('同号')
  await page.getByRole('option', { name: /UI · 同号界面用例/ }).click()
  const request = page.waitForRequest((item) => item.url().includes('/requirements/987611/cases') && item.method() === 'POST')
  await drawer.getByRole('button', { name: '关联', exact: true }).click()
  expect((await request).postDataJSON()).toEqual({ case_type: 'UI', case_id: 7 })
})
