#!/usr/bin/env node

const fs = require('fs')
const path = require('path')
const { chromium } = require('playwright')
const { PlaywrightAgent, overrideAIConfig } = require('@midscene/web/playwright')

function readJob(jobPath) {
  return JSON.parse(fs.readFileSync(jobPath, 'utf-8'))
}

function writeResult(runDir, result) {
  const outPath = path.join(runDir, 'midscene-result.json')
  fs.writeFileSync(outPath, JSON.stringify(result, null, 2), 'utf-8')
  return outPath
}

function urlOrigin(value) {
  const parsed = new URL(String(value || ''))
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error(`Midscene 仅允许 HTTP 或 HTTPS 导航：${value}`)
  }
  return parsed.origin.toLowerCase()
}

function buildAllowedOrigins(job) {
  const values = Array.isArray(job.allowedOrigins) ? job.allowedOrigins : []
  return new Set([job.targetUrl, ...values].filter(Boolean).map(urlOrigin))
}

function assertAllowedNavigation(value, allowedOrigins) {
  if (value === 'about:blank') return
  const origin = urlOrigin(value)
  if (!allowedOrigins.has(origin)) {
    const error = new Error(`导航地址不在允许域名内：${value}`)
    error.code = 'NAVIGATION_BLOCKED'
    throw error
  }
}

function createNavigationGuard(allowedOrigins) {
  let blockedError = null
  return {
    async route(route) {
      const request = route.request()
      if (request.isNavigationRequest() && request.resourceType() === 'document') {
        try {
          assertAllowedNavigation(request.url(), allowedOrigins)
        } catch (error) {
          blockedError = error
          await route.abort('blockedbyclient')
          return
        }
      }
      await route.continue()
    },
    assertClean() {
      if (blockedError) throw blockedError
    },
    assertCurrent(value) {
      assertAllowedNavigation(value, allowedOrigins)
      this.assertClean()
    },
  }
}

function describeStep(step) {
  const name = (step.name || '').trim()
  const value = step.value == null ? '' : String(step.value)
  const selector = (step.selector || '').trim()
  const hint = name || selector || value || step.action
  switch (step.action) {
    case 'click':
      return name ? `点击「${name}」` : `点击 ${hint}`
    case 'input':
    case 'fill':
      return name ? `在「${name}」输入框填写：${value}` : `在 ${selector || hint} 填写：${value}`
    case 'select':
      return name ? `在「${name}」选择：${value}` : `选择：${value}`
    case 'hover':
      return name ? `将鼠标悬停在「${name}」` : `悬停 ${hint}`
    case 'wait':
      return name || `等待页面出现：${value || hint}`
    case 'assert_text':
    case 'assert':
      return value || name || hint
    default:
      return name || hint
  }
}

function prohibitedActions(job) {
  const values = job.prohibitedActions || job.prohibited_actions_json
  return Array.isArray(values) ? values.map((item) => String(item || '').trim()).filter(Boolean) : []
}

function assertStepAllowed(step, job) {
  const instruction = `${step.name || ''} ${step.selector || ''} ${step.value || ''}`.toLowerCase()
  const blocked = prohibitedActions(job).find((action) => instruction.includes(action.toLowerCase()))
  if (blocked) {
    const error = new Error(`步骤命中禁止动作：${blocked}`)
    error.code = 'PROHIBITED_ACTION'
    throw error
  }
}

function assertionInstruction(assertion) {
  const value = assertion.value ?? assertion.expected ?? ''
  const target = assertion.target || assertion.description || assertion.selector || ''
  switch (assertion.type) {
    case 'text_present':
    case 'text_visible':
      return `页面应显示文本：${value}`
    case 'text_hidden':
      return `页面不应显示文本：${value}`
    case 'selector_visible':
      return `页面应显示：${target}`
    case 'selector_hidden':
      return `页面不应显示：${target}`
    case 'visual':
      return String(value)
    default:
      return `${assertion.name || assertion.type || '断言'}：${value || target}`
  }
}

async function runAssertion(agent, page, assertion, index, navigationGuard) {
  const started = Date.now()
  const record = {
    index,
    action: 'assert',
    name: assertion.name || `附加断言 ${index}`,
    status: 'SUCCESS',
    detail: '',
    error: null,
    durationMs: 0,
  }
  try {
    const value = String(assertion.value ?? assertion.expected ?? '')
    if (assertion.type === 'url_contains') {
      if (!page.url().includes(value)) throw new Error(`当前地址不包含：${value}`)
      record.detail = `URL 包含：${value}`
    } else if (assertion.type === 'title_contains') {
      const title = await page.title()
      if (!title.includes(value)) throw new Error(`页面标题不包含：${value}`)
      record.detail = `标题包含：${value}`
    } else if (assertion.selector && assertion.type === 'selector_visible') {
      if (!(await page.locator(assertion.selector).first().isVisible())) throw new Error(`元素不可见：${assertion.selector}`)
      record.detail = `元素可见：${assertion.selector}`
    } else if (assertion.selector && assertion.type === 'selector_hidden') {
      if (await page.locator(assertion.selector).first().isVisible()) throw new Error(`元素仍可见：${assertion.selector}`)
      record.detail = `元素已隐藏：${assertion.selector}`
    } else {
      const instruction = assertionInstruction(assertion)
      await agent.aiAssert(instruction)
      record.detail = instruction
    }
    navigationGuard.assertCurrent(page.url())
  } catch (error) {
    record.status = 'FAILED'
    record.error = (error && error.message) || String(error)
    record.detail = record.error
    record.durationMs = Date.now() - started
    throw Object.assign(new Error(record.error), { assertionFailed: true, assertionRecord: record })
  }
  record.durationMs = Date.now() - started
  return record
}

async function runStep(agent, page, step, index, job, navigationGuard) {
  const started = Date.now()
  const action = step.action
  const record = {
    index: index + 1,
    action,
    name: step.name || describeStep(step),
    status: 'SUCCESS',
    detail: '',
    error: null,
    durationMs: 0,
  }
  try {
    assertStepAllowed(step, job)
    if (action === 'goto') {
      const dest = new URL(String(step.value || job.targetUrl), job.targetUrl).toString()
      assertAllowedNavigation(dest, buildAllowedOrigins(job))
      await page.goto(dest, { waitUntil: 'networkidle', timeout: Math.min(job.timeoutMs || 30000, 30000) })
      record.detail = `已打开 ${dest}`
    } else if (action === 'click') {
      await agent.aiTap(describeStep(step))
      record.detail = `点击：${describeStep(step)}`
    } else if (action === 'input' || action === 'fill') {
      await agent.aiInput(String(step.value ?? ''), step.name || step.selector || describeStep(step))
      record.detail = `输入：${step.value ?? ''}`
    } else if (action === 'wait') {
      await agent.aiWaitFor(describeStep(step))
      record.detail = `等待：${describeStep(step)}`
    } else if (action === 'assert_text' || action === 'assert') {
      const assertion = describeStep(step)
      await agent.aiAssert(assertion)
      record.detail = `断言：${assertion}`
    } else {
      await agent.ai(describeStep(step))
      record.detail = `AI 执行：${describeStep(step)}`
    }
    navigationGuard.assertCurrent(page.url())
  } catch (error) {
    try {
      navigationGuard.assertClean()
    } catch (blockedError) {
      error = blockedError
    }
    record.status = 'FAILED'
    record.error = (error && error.message) || String(error)
    record.detail = record.error
    record.durationMs = Date.now() - started
    throw Object.assign(new Error(record.error), { stepRecord: record })
  }
  record.durationMs = Date.now() - started
  return record
}

async function main() {
  const jobPath = process.argv[2]
  if (!jobPath) {
    console.error('usage: node midscene_runner.js <job.json>')
    process.exitCode = 2
    return
  }
  const job = readJob(jobPath)
  const runDir = job.runDir || process.env.MIDSCENE_RUN_DIR || process.cwd()
  const allowedOrigins = buildAllowedOrigins(job)
  const navigationGuard = createNavigationGuard(allowedOrigins)
  const result = {
    status: 'ERROR',
    summary: '',
    finalUrl: null,
    reportPath: null,
    steps: [],
    error: null,
  }

  overrideAIConfig({
    MIDSCENE_MODEL_NAME: process.env.MIDSCENE_MODEL_NAME,
    MIDSCENE_MODEL_BASE_URL: process.env.MIDSCENE_MODEL_BASE_URL,
    MIDSCENE_MODEL_API_KEY: process.env.MIDSCENE_MODEL_API_KEY,
  })

  let browser
  let agent
  try {
    browser = await chromium.launch({ headless: true })
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    await context.route('**/*', (route) => navigationGuard.route(route))
    const page = await context.newPage()
    agent = new PlaywrightAgent(page, { reportFileName: job.reportFileName || 'midscene-run' })

    const steps = Array.isArray(job.steps) ? job.steps.slice() : []
    if (!steps.length || steps[0].action !== 'goto') {
      steps.unshift({ action: 'goto', value: job.targetUrl, name: '打开目标页面' })
    }
    for (let i = 0; i < steps.length; i++) {
      result.steps.push(await runStep(agent, page, steps[i], i, job, navigationGuard))
    }

    if (job.expectText && job.expectText.trim()) {
      const started = Date.now()
      const assertion = `页面应当包含或体现：${job.expectText.trim()}`
      try {
        await agent.aiAssert(assertion)
        navigationGuard.assertCurrent(page.url())
        result.steps.push({
          index: result.steps.length + 1,
          action: 'assert_text',
          name: '最终文本断言',
          status: 'SUCCESS',
          detail: assertion,
          error: null,
          durationMs: Date.now() - started,
        })
      } catch (error) {
        const message = (error && error.message) || String(error)
        result.steps.push({
          index: result.steps.length + 1,
          action: 'assert_text',
          name: '最终文本断言',
          status: 'FAILED',
          detail: message,
          error: message,
          durationMs: Date.now() - started,
        })
        throw Object.assign(new Error(message), { assertionFailed: true })
      }
    }

    const assertions = job.assertions || job.assertionsJson || job.assertions_json
    if (Array.isArray(assertions)) {
      for (const assertion of assertions) {
        if (!assertion || typeof assertion !== 'object') continue
        result.steps.push(
          await runAssertion(agent, page, assertion, result.steps.length + 1, navigationGuard)
        )
      }
    }

    navigationGuard.assertCurrent(page.url())
    result.finalUrl = page.url()
    result.status = 'SUCCESS'
    result.summary = `Midscene 执行成功，共 ${result.steps.length} 个步骤`
  } catch (error) {
    if (error && error.assertionFailed) {
      if (error.assertionRecord) result.steps.push(error.assertionRecord)
      result.status = 'FAILED'
      result.error = error.message
      result.summary = `Midscene 断言未通过：${error.message}`
    } else if (error && error.stepRecord) {
      const record = error.stepRecord
      if (!result.steps.find((step) => step.index === record.index)) result.steps.push(record)
      result.status = 'FAILED'
      result.error = error.message
      result.summary = `Midscene 步骤失败：${error.message}`
    } else {
      result.status = 'ERROR'
      result.error = (error && error.message) || String(error)
      result.summary = `Midscene 执行异常：${result.error}`
    }
  } finally {
    try {
      if (agent && typeof agent.writeOutActionDumps === 'function') agent.writeOutActionDumps()
    } catch (_) {}
    try {
      const reportDir = path.join(process.env.MIDSCENE_RUN_DIR || runDir, 'report')
      if (fs.existsSync(reportDir)) {
        const htmls = fs
          .readdirSync(reportDir)
          .filter((file) => file.endsWith('.html'))
          .map((file) => ({ file, time: fs.statSync(path.join(reportDir, file)).mtimeMs }))
          .sort((left, right) => right.time - left.time)
        if (htmls.length) result.reportPath = path.join(reportDir, htmls[0].file)
      }
    } catch (_) {}
    try {
      if (agent && typeof agent.destroy === 'function') await agent.destroy()
    } catch (_) {}
    try {
      if (browser) await browser.close()
    } catch (_) {}
  }

  const outPath = writeResult(runDir, result)
  console.log(`[midscene] result -> ${outPath} status=${result.status}`)
}

if (require.main === module) {
  main().catch((error) => {
    console.error('[midscene] fatal:', (error && error.stack) || error)
    process.exitCode = 1
  })
}

module.exports = {
  assertAllowedNavigation,
  assertStepAllowed,
  assertionInstruction,
  buildAllowedOrigins,
  createNavigationGuard,
  main,
  urlOrigin,
}
