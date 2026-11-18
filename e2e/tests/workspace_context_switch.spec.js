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

test('工作区切换项目后列表更新且不串数据', async ({ page }) => {
  const suffix = `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
  const projectIds = []
  const defectIds = []
  const projectAName = `ContextA_${suffix}`
  const projectBName = `ContextB_${suffix}`
  const defectATitle = `ContextA_defect_${suffix}`
  const defectBTitle = `ContextB_defect_${suffix}`

  await login(page)

  try {
    const projectA = await apiRequest(page, 'POST', '/projects', {
      name: projectAName,
      base_url: 'http://localhost',
      description: 'workspace context switch e2e fixture'
    })
    projectIds.push(projectA.id)
    const defectA = await apiRequest(page, 'POST', `/projects/${projectA.id}/defects`, {
      title: defectATitle,
      description: 'temporary e2e fixture',
      severity: 'MAJOR',
      priority: 'P2'
    })
    defectIds.push(defectA.id)

    const projectB = await apiRequest(page, 'POST', '/projects', {
      name: projectBName,
      base_url: 'http://localhost',
      description: 'workspace context switch e2e fixture'
    })
    projectIds.push(projectB.id)
    const defectB = await apiRequest(page, 'POST', `/projects/${projectB.id}/defects`, {
      title: defectBTitle,
      description: 'temporary e2e fixture',
      severity: 'MAJOR',
      priority: 'P2'
    })
    defectIds.push(defectB.id)

    const defectListRequests = new Map()
    page.on('request', (request) => {
      const match = request.url().match(/\/api\/v1\/projects\/(\d+)\/defects(?:\?|$)/)
      if (request.method() === 'GET' && match) {
        const projectId = Number(match[1])
        defectListRequests.set(projectId, (defectListRequests.get(projectId) || 0) + 1)
      }
    })

    await page.goto(`/project/${projectA.id}/defects`)
    await expect(page.getByText(defectATitle, { exact: true })).toBeVisible()
    await expect.poll(() => defectListRequests.get(projectA.id)).toBe(1)

    const projectBDefectsResponse = page.waitForResponse((response) =>
      response.request().method() === 'GET' &&
      response.url().includes(`/projects/${projectB.id}/defects`)
    )
    await page.locator('.ws-switcher').click()
    await page.getByRole('option', { name: projectBName, exact: true }).click()
    await projectBDefectsResponse

    await expect(page).toHaveURL(new RegExp(`/project/${projectB.id}/defects$`))
    await expect(page.getByText(defectBTitle, { exact: true })).toBeVisible()
    await expect(page.getByText(defectATitle, { exact: true })).toHaveCount(0)
    await expect.poll(() => defectListRequests.get(projectB.id)).toBe(1)

    const returnToProjectAResponse = page.waitForResponse((response) =>
      response.request().method() === 'GET' &&
      response.url().includes(`/projects/${projectA.id}/defects`)
    )
    await page.locator('.ws-switcher').click()
    await page.getByRole('option', { name: projectAName, exact: true }).click()
    await returnToProjectAResponse
    await expect(page).toHaveURL(new RegExp(`/project/${projectA.id}/defects$`))
    await expect(page.getByText(defectATitle, { exact: true })).toBeVisible()
    await expect(page.getByText(defectBTitle, { exact: true })).toHaveCount(0)
    await expect.poll(() => defectListRequests.get(projectA.id)).toBe(2)

    await page.locator('.ws-tab').filter({ hasText: '需求' }).click()
    await expect(page).toHaveURL(new RegExp(`/project/${projectA.id}/requirements$`))
    expect(defectListRequests.get(projectA.id)).toBe(2)

    const returnToDefectsResponse = page.waitForResponse((response) =>
      response.request().method() === 'GET' &&
      response.url().includes(`/projects/${projectA.id}/defects`)
    )
    await page.locator('.ws-tab').filter({ hasText: '缺陷' }).click()
    await returnToDefectsResponse
    await expect(page.getByText(defectATitle, { exact: true })).toBeVisible()
    await expect.poll(() => defectListRequests.get(projectA.id)).toBe(3)
  } finally {
    for (const defectId of defectIds.reverse()) {
      await apiRequest(page, 'DELETE', `/project-defects/${defectId}`)
    }
    for (const projectId of projectIds.reverse()) {
      await apiRequest(page, 'DELETE', `/projects/${projectId}`)
    }
  }
})
