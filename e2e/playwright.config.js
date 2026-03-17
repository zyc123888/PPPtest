const { defineConfig } = require('@playwright/test')

module.exports = defineConfig({
  testDir: './tests',
  timeout: 60000,
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
    headless: true
  }
})

