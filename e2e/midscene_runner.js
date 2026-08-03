#!/usr/bin/env node

const path = require('path')
process.env.NODE_PATH = process.env.NODE_PATH || path.join(__dirname, 'node_modules')
require('module').Module._initPaths()
require('../backend/midscene/midscene_runner.js').main().catch((error) => {
  console.error('[midscene] fatal:', (error && error.stack) || error)
  process.exitCode = 1
})
