const test = require('node:test')
const assert = require('node:assert/strict')

const {
  assertAllowedNavigation,
  assertStepAllowed,
  assertionInstruction,
  buildAllowedOrigins,
  createNavigationGuard,
  urlOrigin,
} = require('./midscene_runner')

test('blocks explicit steps that contain a prohibited action', () => {
  assert.throws(
    () => assertStepAllowed(
      { action: 'click', name: '删除当前项目' },
      { prohibitedActions: ['删除', '支付'] }
    ),
    /步骤命中禁止动作：删除/
  )
  assert.doesNotThrow(() => assertStepAllowed(
    { action: 'click', name: '查看项目' },
    { prohibited_actions_json: ['删除'] }
  ))
})

test('converts structured assertions into explicit AI instructions', () => {
  assert.equal(
    assertionInstruction({ type: 'text_visible', value: '保存成功' }),
    '页面应显示文本：保存成功'
  )
  assert.equal(
    assertionInstruction({ type: 'selector_hidden', target: '加载动画' }),
    '页面不应显示：加载动画'
  )
})

test('normalizes HTTP origins and rejects non-HTTP URLs', () => {
  assert.equal(urlOrigin('HTTPS://Example.COM:443/path'), 'https://example.com')
  assert.throws(() => urlOrigin('file:///etc/passwd'), /仅允许 HTTP 或 HTTPS/)
})

test('builds the allowlist from the target and configured origins', () => {
  const origins = buildAllowedOrigins({
    targetUrl: 'https://app.example.com/start',
    allowedOrigins: ['https://static.example.com/help'],
  })
  assert.deepEqual([...origins].sort(), ['https://app.example.com', 'https://static.example.com'])
  assert.doesNotThrow(() => assertAllowedNavigation('https://app.example.com/next', origins))
  assert.throws(
    () => assertAllowedNavigation('https://evil.example.net/collect', origins),
    /导航地址不在允许域名内/
  )
})

test('aborts a disallowed document request before navigation', async () => {
  const guard = createNavigationGuard(new Set(['https://app.example.com']))
  let aborted = false
  let continued = false
  await guard.route({
    request: () => ({
      isNavigationRequest: () => true,
      resourceType: () => 'document',
      url: () => 'https://evil.example.net/collect',
    }),
    abort: async () => {
      aborted = true
    },
    continue: async () => {
      continued = true
    },
  })
  assert.equal(aborted, true)
  assert.equal(continued, false)
  assert.throws(() => guard.assertClean(), /导航地址不在允许域名内/)
})

test('allows subresources without widening top-level navigation origins', async () => {
  const guard = createNavigationGuard(new Set(['https://app.example.com']))
  let continued = false
  await guard.route({
    request: () => ({
      isNavigationRequest: () => false,
      resourceType: () => 'script',
      url: () => 'https://cdn.example.net/app.js',
    }),
    abort: async () => assert.fail('subresource should not be aborted'),
    continue: async () => {
      continued = true
    },
  })
  assert.equal(continued, true)
  assert.doesNotThrow(() => guard.assertClean())
})
