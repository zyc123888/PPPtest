// 独立的 Midscene AI 用例配置，与现有 playwright.config.js 隔离，
// 这样普通 e2e 套件不受影响。运行：npm run test:ai
const path = require('path')
require('dotenv').config({ path: path.resolve(__dirname, '.env') })

const { defineConfig } = require('@playwright/test')

module.exports = defineConfig({
  testDir: './tests-ai',
  timeout: 120 * 1000, // AI 单步需要调用大模型，超时给宽一些
  reporter: [
    ['list'],
    ['@midscene/web/playwright-reporter', { type: 'merged' }], // 生成可视化 AI 执行报告
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
    headless: true,
    viewport: { width: 1440, height: 900 }, // 视觉模型定位在该分辨率下更稳
    acceptDownloads: true,
  },
})
