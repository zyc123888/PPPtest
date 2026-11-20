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

test('UI 用例新建时项目、目录和目标地址跟随所选项目', async ({ page }) => {
  const suffix = `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
  const projectIds = []
  const caseIds = []
  const projectAName = `UIContextA_${suffix}`
  const projectBName = `UIContextB_${suffix}`
  const folderA = `A_folder_${suffix}`
  const folderB = `B_folder_${suffix}`

  await login(page)

  try {
    const projectA = await apiRequest(page, 'POST', '/projects', {
      name: projectAName,
      base_url: 'http://project-a.local',
      description: 'ui case create context e2e fixture'
    })
    projectIds.push(projectA.id)
    const caseA = await apiRequest(page, 'POST', '/ui-cases', {
      project_id: projectA.id,
      name: `UIFolderA_${suffix}`,
      folder_path: folderA,
      target_url: 'http://project-a.local/login',
      expect_text: 'ready',
      steps_json: []
    })
    caseIds.push(caseA.id)

    const projectB = await apiRequest(page, 'POST', '/projects', {
      name: projectBName,
      base_url: 'http://project-b.local',
      description: 'ui case create context e2e fixture'
    })
    projectIds.push(projectB.id)
    const caseB = await apiRequest(page, 'POST', '/ui-cases', {
      project_id: projectB.id,
      name: `UIFolderB_${suffix}`,
      folder_path: folderB,
      target_url: 'http://project-b.local/login',
      expect_text: 'ready',
      steps_json: []
    })
    caseIds.push(caseB.id)

    await page.goto('/case/ui')
    const projectFilter = page.locator('.filter-bar .el-select').first()
    await projectFilter.click()
    await page.getByRole('option', { name: projectBName, exact: true }).click()
    await expect(page.locator('.case-table').getByRole('row').filter({ hasText: caseB.name })).toBeVisible()

    await page.getByRole('button', { name: '高级创建' }).click()
    const editor = page.locator('.el-dialog:visible').filter({ hasText: '新增 UI 用例' })
    await expect(editor).toBeVisible()
    const projectField = editor.locator('.el-form-item').filter({ hasText: '所属项目' })
    await expect(projectField.locator('.el-select__selection')).toContainText(projectBName)
    const targetField = editor.locator('.el-form-item').filter({ hasText: '目标地址' })
    await expect(targetField.locator('input')).toHaveValue(projectB.base_url)

    const folderField = editor.locator('.el-form-item').filter({ hasText: '目录/分组' })
    await folderField.locator('.el-select').click()
    let folderDropdown = page.locator('.el-select-dropdown:visible').last()
    await expect(folderDropdown.getByText(folderB, { exact: true })).toBeVisible()
    await expect(folderDropdown.getByText(folderA, { exact: true })).toHaveCount(0)
    await page.keyboard.press('Escape')

    const projectAOptions = page.waitForResponse((response) =>
      response.request().method() === 'GET' &&
      response.url().includes(`/ui-cases/folders?project_id=${projectA.id}`)
    )
    await projectField.locator('.el-select').click()
    await page.getByRole('option', { name: projectAName, exact: true }).click()
    await projectAOptions
    await expect(targetField.locator('input')).toHaveValue(projectA.base_url)

    await folderField.locator('.el-select').click()
    folderDropdown = page.locator('.el-select-dropdown:visible').last()
    await expect(folderDropdown.getByText(folderA, { exact: true })).toBeVisible()
    await expect(folderDropdown.getByText(folderB, { exact: true })).toHaveCount(0)

    await editor.getByRole('button', { name: '取消', exact: true }).click()
    await page.getByRole('button', { name: '放弃修改' }).click()
  } finally {
    for (const caseId of caseIds.reverse()) {
      await apiRequest(page, 'DELETE', `/ui-cases/${caseId}`)
    }
    for (const projectId of projectIds.reverse()) {
      await apiRequest(page, 'DELETE', `/projects/${projectId}`)
    }
  }
})
