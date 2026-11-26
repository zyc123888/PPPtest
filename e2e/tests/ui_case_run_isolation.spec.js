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

test('打开无执行记录的 UI 用例时不显示上一条用例的执行详情', async ({ page }) => {
  const suffix = `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
  const projectIds = []
  const caseIds = []
  const projectName = `RunIsolation_${suffix}`
  const caseAName = `HasRun_${suffix}`
  const caseBName = `NoRun_${suffix}`

  await login(page)

  try {
    const project = await apiRequest(page, 'POST', '/projects', {
      name: projectName,
      base_url: 'http://localhost',
      description: 'ui case run isolation e2e fixture'
    })
    projectIds.push(project.id)

    const createCase = (name) => apiRequest(page, 'POST', '/ui-cases', {
      project_id: project.id,
      name,
      target_url: 'http://localhost',
      expect_text: 'ready',
      steps_json: []
    })
    const caseA = await createCase(caseAName)
    caseIds.push(caseA.id)
    const caseB = await createCase(caseBName)
    caseIds.push(caseB.id)

    const run = {
      id: 987654321,
      project_id: project.id,
      case_type: 'UI',
      case_id: caseA.id,
      case_name: caseAName,
      status: 'SUCCESS',
      summary: 'fixture run for isolation test',
      duration_ms: 250,
      created_at: new Date().toISOString(),
      step_results_json: [],
      artifacts_json: [],
      response_payload: {}
    }

    await page.route('**/api/v1/executions/runs**', async (route) => {
      const url = new URL(route.request().url())
      const pathname = url.pathname

      if (pathname.endsWith('/executions/runs') && url.searchParams.get('case_id') === String(caseA.id)) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([run]) })
      }
      if (pathname.endsWith('/executions/runs') && url.searchParams.get('case_id') === String(caseB.id)) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      }
      if (pathname === `/api/v1/executions/runs/${run.id}`) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(run) })
      }
      if (pathname === `/api/v1/executions/runs/${run.id}/steps`) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      }
      if (pathname === `/api/v1/executions/runs/${run.id}/artifacts`) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ artifacts: [] }) })
      }
      return route.continue()
    })

    await page.goto('/case/ui')
    const projectFilter = page.locator('.filter-bar .el-select').first()
    await projectFilter.hover()
    const clearProjectFilter = projectFilter.locator('.el-select__clear')
    if (await clearProjectFilter.isVisible()) await clearProjectFilter.click()
    const search = page.getByPlaceholder('搜索名称、分组、地址或标签')
    await search.fill(caseAName)
    const caseARow = page.locator('.case-table').getByRole('row').filter({ hasText: caseAName })
    await expect(caseARow).toBeVisible()
    await caseARow.getByRole('button', { name: '查看 UI 用例' }).click()

    const detailDrawer = page.locator('.el-drawer:visible')
    await detailDrawer.getByRole('tab', { name: /执行记录 \(1\)/ }).click()
    await detailDrawer.getByRole('row').filter({ hasText: `#${run.id}` }).click()
    await expect(detailDrawer.locator('.run-detail')).toContainText(`执行 #${run.id}`)

    await detailDrawer.locator('.el-drawer__close-btn').click()
    await expect(page.locator('.el-drawer:visible')).toHaveCount(0)

    await search.fill(caseBName)
    const caseBRow = page.locator('.case-table').getByRole('row').filter({ hasText: caseBName })
    await expect(caseBRow).toBeVisible()
    await caseBRow.getByRole('button', { name: '查看 UI 用例' }).click()

    const secondDrawer = page.locator('.el-drawer:visible')
    await secondDrawer.getByRole('tab', { name: /执行记录 \(0\)/ }).click()
    await expect(secondDrawer.locator('.run-detail')).toHaveCount(0)
    await expect(secondDrawer.getByText(`执行 #${run.id}`, { exact: true })).toHaveCount(0)
  } finally {
    for (const caseId of caseIds.reverse()) {
      await apiRequest(page, 'DELETE', `/ui-cases/${caseId}`)
    }
    for (const projectId of projectIds.reverse()) {
      await apiRequest(page, 'DELETE', `/projects/${projectId}`)
    }
  }
})
