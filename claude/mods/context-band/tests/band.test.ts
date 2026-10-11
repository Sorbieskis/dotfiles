import { expect, test } from 'claude-code/testing'

const PROPS = { hasSurvey: false, isWorking: false, maxRows: 10, width: 100 } as any

function bottoms(on: any) {
  on('session.measure', (_$: any, e: any) => ({ changed: e.changed }))
  on('ui.render', ($: any, e: any) => (globalThis as any).h($.ui.resolve(e).Text, null, 'engine band'))
}

async function drawHit($: any, context: any): Promise<any | null> {
  await $.session.measure({ context, rateLimits: [], changed: ['context'] })
  const ui = await $.ui.mount({ plugin: 'context-band', surface: 'terminal', component: 'AbovePrompt', props: PROPS })
  const hit = await ui.find({ type: 'Text', text: /context|HAND|HARD/ })
  await ui.unmount()
  return hit ?? null
}

async function draw($: any, on: any, context: any): Promise<string | null> {
  const hit = await drawHit($, context)
  return hit ? (hit.text as string) : null
}

// Styling is part of the contract: past 190k the band must be bold red inverse, 150k-189k yellow,
// below that dim. Exact thresholds are tested on both sides (>= comparisons).
const RED = { bold: true, inverse: true, color: 'red' }
const YELLOW = { color: 'yellow' }
const DIM = { dimColor: true }
const W = 1000000

for (const [name, tokens, want, props] of [
  ['under 150k', 120000, /^context 120k \/ 1000k \(12%\)$/, DIM],
  ['149999 is still dim', 149999, /^context 150k \/ 1000k/, DIM],
  ['at 150k', 150000, /resume ceiling/, YELLOW],
  ['just under 190k', 189999, /resume ceiling/, YELLOW],
  ['at 190k', 190000, /HAND OFF/, RED],
  ['299999 is HAND OFF, not HARD STOP', 299999, /HAND OFF/, RED],
  ['exactly 300k', 300000, /HARD STOP/, RED],
  ['over 300k', 310000, /HARD STOP/, RED],
] as const) {
  test(`band: ${name}`, async ($, on) => {
    bottoms(on)
    const hit = await drawHit($, { tokens, window: W, percent: Math.floor(tokens / 10000) })
    expect(hit.text).toMatch(want)
    expect(hit.props).toEqual(props)
  })
}

test('null readings (early session, after /compact) draw nothing', async ($, on) => {
  bottoms(on)
  expect(await draw($, on, { window: 200000 })).toBeNull()
  expect(await draw($, on, { tokens: null, window: null, percent: null })).toBeNull()
})
