import { expect, test } from 'claude-code/testing'

const stub = (result: unknown) => (on: any) => on('tool.call', () => ({ result }))

test('redacts an env-style secret and an API key in a string result', async ($, on) => {
  stub('JWT_SECRET=hunter2hunter2\nkey sk-ant-api03-abcdefghijklmnopqrstuvwxyz\nPORT=8081')(on)
  on('ui.log', () => ({ value: undefined }))
  const out: any = await $.tool.call({ tool: 'Read', file_path: '.env' })
  expect(out.result).toContain('JWT_SECRET=[REDACTED]')
  expect(out.result).toContain('[REDACTED anthropic key]')
  expect(out.result).toContain('PORT=8081')
})

test('walks nested results and leaves clean ones alone', async ($, on) => {
  stub({ stdout: 'ghp_' + 'a'.repeat(36), nested: ['fine', { t: 'AKIAABCDEFGHIJKLMNOP' }] })(on)
  on('ui.log', () => ({ value: undefined }))
  const out: any = await $.tool.call({ tool: 'Bash', command: 'env' })
  expect(out.result.stdout).toBe('[REDACTED github token]')
  expect(out.result.nested[0]).toBe('fine')
  expect(out.result.nested[1].t).toBe('[REDACTED aws key id]')
})

test('a result with no secrets passes through unchanged', async ($, on) => {
  stub('cargo build ok')(on)
  const out: any = await $.tool.call({ tool: 'Bash', command: 'cargo build' })
  expect(out.result).toBe('cargo build ok')
})
