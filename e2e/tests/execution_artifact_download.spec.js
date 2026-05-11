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

async function triggerApiRun(page) {
  const token = await page.evaluate(() => localStorage.getItem('tp_token'))
  const headers = { Authorization: `Bearer ${token}` }
  const cases = await page.request.get('/api/v1/api-cases', { headers })
  expect(cases.ok()).toBeTruthy()
  const casePayload = await cases.json()
  const healthCase = casePayload.find((item) => item.name === '示例健康检查接口')
  expect(healthCase).toBeTruthy()

  const run = await page.request.post(`/api/v1/executions/api/${healthCase.id}/run`, { headers })
  expect(run.ok()).toBeTruthy()
  const runPayload = await run.json()

  for (let attempt = 0; attempt < 20; attempt += 1) {
    const detail = await page.request.get(`/api/v1/executions/runs/${runPayload.id}`, { headers })
    expect(detail.ok()).toBeTruthy()
    const detailPayload = await detail.json()
    if (detailPayload.status === 'SUCCESS') return detailPayload
    await page.waitForTimeout(500)
  }

  throw new Error(`执行记录 ${runPayload.id} 未在预期时间内成功`)
}

test('执行中心可下载执行产物', async ({ page }) => {
  await login(page)
  const run = await triggerApiRun(page)

  await page.goto('/execution/index')
  await page.getByPlaceholder('用例名称/摘要').fill(run.case_name)
  await page.getByRole('button', { name: '查询' }).click()

  const runRow = page.getByRole('row').filter({ hasText: String(run.id) }).filter({ hasText: run.case_name }).first()
  await expect(runRow).toBeVisible({ timeout: 10000 })
  await runRow.getByRole('button', { name: '产物' }).click()

  const artifactDialog = page.locator('.el-dialog').filter({ hasText: '执行产物' }).last()
  await expect(artifactDialog).toBeVisible()
  await expect(artifactDialog.getByText('request.json', { exact: true })).toBeVisible()

  const token = await page.evaluate(() => localStorage.getItem('tp_token'))
  const artifactsResponse = await page.request.get(`/api/v1/executions/runs/${run.id}/artifacts`, {
    headers: { Authorization: `Bearer ${token}` }
  })
  expect(artifactsResponse.ok()).toBeTruthy()
  const artifactsPayload = await artifactsResponse.json()
  const artifactIndex = artifactsPayload.artifacts.findIndex((item) => item.name === 'request.json')
  expect(artifactIndex).toBeGreaterThanOrEqual(0)

  const response = await page.request.get(`/api/v1/executions/runs/${run.id}/artifacts/${artifactIndex}/download`, {
    headers: { Authorization: `Bearer ${token}` }
  })
  expect(response.ok()).toBeTruthy()
  expect(response.headers()['content-disposition']).toContain('request.json')
  const payload = await response.json()
  expect(payload).toHaveProperty('url')
})
