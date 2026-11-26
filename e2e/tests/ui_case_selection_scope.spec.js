const { test, expect } = require('@playwright/test')

const ADMIN_USER = process.env.E2E_ADMIN_USER || 'admin'
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || ''

async function login(page) {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill(ADMIN_USER)
  await page.getByPlaceholder('请输入密码').fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/dashboard/, { timeout: 10000 })
}

async function apiRequest(page, method, path, body) {
  const result = await page.evaluate(async ({ method, path, body }) => {
    const token = localStorage.getItem('tp_token')
    const response = await fetch(`/api/v1${path}`, {
      method,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(body ? { 'Content-Type': 'application/json' } : {})
      },
      ...(body ? { body: JSON.stringify(body) } : {})
    })
    return { status: response.status, text: await response.text() }
  }, { method, path, body })

  if (result.status < 200 || result.status >= 300) {
    throw new Error(`${method} ${path} failed (${result.status}): ${result.text}`)
  }
  return result.text ? JSON.parse(result.text) : null
}

test('UI 用例批量选择显示筛选范围并阻止跨项目操作', async ({ page }) => {
  const suffix = `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
  const projectIds = []
  const caseIds = []
  const projectAName = `SelectionA_${suffix}`
  const projectBName = `SelectionB_${suffix}`
  const casePrefix = `Selection_${suffix}`

  await login(page)

  try {
    const projectA = await apiRequest(page, 'POST', '/projects', {
      name: projectAName,
      base_url: 'http://selection-a.local',
      description: 'ui case selection scope e2e fixture'
    })
    projectIds.push(projectA.id)
    const caseA = await apiRequest(page, 'POST', '/ui-cases', {
      project_id: projectA.id,
      name: `${casePrefix}_A`,
      target_url: 'http://selection-a.local',
      expect_text: 'ready',
      steps_json: []
    })
    caseIds.push(caseA.id)

    const projectB = await apiRequest(page, 'POST', '/projects', {
      name: projectBName,
      base_url: 'http://selection-b.local',
      description: 'ui case selection scope e2e fixture'
    })
    projectIds.push(projectB.id)
    const caseB = await apiRequest(page, 'POST', '/ui-cases', {
      project_id: projectB.id,
      name: `${casePrefix}_B`,
      target_url: 'http://selection-b.local',
      expect_text: 'ready',
      steps_json: []
    })
    caseIds.push(caseB.id)

    await page.goto('/case/ui')
    const projectFilter = page.locator('.filter-bar .el-select').first()
    await projectFilter.hover()
    const clearProjectFilter = projectFilter.locator('.el-select__clear')
    if (await clearProjectFilter.isVisible()) await clearProjectFilter.click()
    const search = page.getByPlaceholder('搜索名称、分组、地址或标签')
    await search.fill(casePrefix)
    const rowA = page.locator('.case-table .el-table__body tr').filter({ hasText: caseA.name })
    const rowB = page.locator('.case-table .el-table__body tr').filter({ hasText: caseB.name })
    await expect(rowA).toBeVisible()
    await expect(rowB).toBeVisible()

    await rowA.locator('.el-checkbox__inner').click()
    await rowB.locator('.el-checkbox__inner').click()
    const batchBar = page.locator('.batch-bar')
    await expect(batchBar.locator('.batch-bar__count')).toContainText('已选 2 条当前页')
    await batchBar.getByRole('button', { name: '批量修改' }).click()
    await expect(page.getByText('批量操作的用例必须属于同一项目，请重新选择')).toBeVisible()
    await expect(page.locator('.el-dialog:visible').filter({ hasText: '批量修改用例' })).toHaveCount(0)

    await batchBar.getByRole('button', { name: '取消选择' }).click()
    await rowA.locator('.el-checkbox__inner').click()
    await expect(batchBar.locator('.batch-bar__count')).toContainText('已选 1 条当前页')

    await search.fill(caseB.name)
    await expect(rowA).toHaveCount(0)
    await expect(rowB).toBeVisible()
    await expect(batchBar.locator('.batch-bar__count')).toContainText('已选 0 条当前页')
    await expect(batchBar.locator('.batch-bar__count')).toContainText('1 条来自其他页或筛选范围')

    const projectFilteredCases = page.waitForResponse((response) => {
      if (response.request().method() !== 'GET') return false
      const url = new URL(response.url())
      return url.pathname.endsWith('/api/v1/ui-cases') && url.searchParams.get('project_id') === String(projectB.id)
    })
    await page.locator('.filter-bar .el-select').first().click()
    await page.getByRole('option', { name: projectBName, exact: true }).click()
    await projectFilteredCases
    await expect(page.locator('.batch-bar')).toHaveCount(0)
    await expect(rowB.locator('.el-checkbox__input.is-checked')).toHaveCount(0)
  } finally {
    for (const caseId of caseIds.reverse()) {
      await apiRequest(page, 'DELETE', `/ui-cases/${caseId}`)
    }
    for (const projectId of projectIds.reverse()) {
      await apiRequest(page, 'DELETE', `/projects/${projectId}`)
    }
  }
})
