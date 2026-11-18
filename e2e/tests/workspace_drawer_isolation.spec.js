const { test, expect } = require('@playwright/test')

test('需求评论请求返回时不覆盖另一条需求的草稿', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill(process.env.E2E_ADMIN_USER || 'admin')
  await page.getByPlaceholder('请输入密码').fill(process.env.E2E_ADMIN_PASSWORD || '')
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/dashboard/)
  const projectId = await page.evaluate(async () => {
    const response = await fetch('/api/v1/projects', { headers: { Authorization: `Bearer ${localStorage.getItem('tp_token')}` } })
    const projects = await response.json()
    return projects[0]?.id
  })
  expect(projectId).toBeTruthy()
  const firstId = 987601
  const secondId = 987602
  await page.route(`**/api/v1/projects/${projectId}/requirements?*`, (route) => route.fulfill({ json: {
    items: [
      { id: firstId, title: '隔离测试需求 A', status: 'TODO', priority: 'P2' },
      { id: secondId, title: '隔离测试需求 B', status: 'TODO', priority: 'P2' }
    ], total: 2
  } }))
  await page.route('**/api/v1/requirements/98760*/cases', (route) => route.fulfill({ json: [] }))
  let releasePost
  const waitForRelease = new Promise((resolve) => { releasePost = resolve })
  let submitted = false
  await page.route('**/api/v1/requirement/98760*/comments', async (route) => {
    if (route.request().method() === 'POST') {
      submitted = true
      await waitForRelease
      return route.fulfill({ json: { id: 1, content: 'A 的评论' } })
    }
    return route.fulfill({ json: [] })
  })

  await page.goto(`/project/${projectId}/requirements`)
  await page.getByText('隔离测试需求 A', { exact: true }).click()
  let drawer = page.locator('.el-drawer:visible')
  await drawer.getByPlaceholder('写下评论...').fill('A 的评论')
  await drawer.getByRole('button', { name: '发表', exact: true }).click()
  await expect.poll(() => submitted).toBe(true)
  await drawer.locator('.el-drawer__close-btn').click()
  await page.getByText('隔离测试需求 B', { exact: true }).click()
  drawer = page.locator('.el-drawer:visible')
  const comment = drawer.getByPlaceholder('写下评论...')
  await expect(comment).toHaveValue('')
  await comment.fill('B 的未提交草稿')
  const postResponse = page.waitForResponse((response) => response.url().includes(`/requirement/${firstId}/comments`) && response.request().method() === 'POST')
  releasePost()
  await postResponse
  await expect(comment).toHaveValue('B 的未提交草稿')
})
