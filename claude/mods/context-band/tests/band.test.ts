import { expect, test } from 'claude-code/testing'

const PROPS = { hasSurvey: false, isWorking: false, maxRows: 10, width: 100 } as any

function bottoms(on: any) {
  on('session.measure', (_$: any, e: any) => ({ changed: e.changed }))
  on('ui.render', ($: any, e: any) => (globalThis as any).h($.ui.resolve(e).Text, null, 'engine band'))
}

async function draw($: any, on: any, context: any): Promise<string | null> {
  await $.session.measure({ context, rateLimits: [], changed: ['context'] })
  const ui = await $.ui.mount({ plugin: 'context-band', surface: 'terminal', component: 'AbovePrompt', props: PROPS })
  const hit = await ui.find({ type: 'Text', text: /context|HAND|HARD/ })
  await ui.unmount()
  return hit ? (hit.text as string) : null
}

for (const [name, context, want] of [
  ['under 150k', { tokens: 120000, window: 1000000, percent: 12 }, /^context 120k \/ 1000k \(12%\)$/],
  ['at 150k', { tokens: 150000, window: 1000000, percent: 15 }, /resume ceiling/],
  ['just under 190k', { tokens: 189999, window: 1000000, percent: 19 }, /resume ceiling/],
  ['at 190k', { tokens: 190000, window: 1000000, percent: 19 }, /HAND OFF/],
  ['over 300k', { tokens: 310000, window: 1000000, percent: 31 }, /HARD STOP/],
] as const) {
  test(`band: ${name}`, async ($, on) => {
    bottoms(on)
    expect(await draw($, on, context)).toMatch(want)
  })
}

test('null readings (early session, after /compact) draw nothing', async ($, on) => {
  bottoms(on)
  expect(await draw($, on, { window: 200000 })).toBeNull()
  expect(await draw($, on, { tokens: null, window: null, percent: null })).toBeNull()
})
