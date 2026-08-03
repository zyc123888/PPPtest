// Midscene 扩展的 Playwright test 实例。
// 在 AI 用例里从这里 require { test, expect }，即可使用 ai/aiTap/aiInput/aiAssert 等方法。
const path = require('path')
require('dotenv').config({ path: path.resolve(__dirname, '.env') })

const { expect } = require('@playwright/test')
const { test: base } = require('@playwright/test')
const { PlaywrightAiFixture } = require('@midscene/web/playwright')

const test = base.extend(
  PlaywrightAiFixture({
    waitForNetworkIdleTimeout: 2000, // 每步操作后等待网络空闲的超时（ms）
  }),
)

module.exports = { test, expect }
