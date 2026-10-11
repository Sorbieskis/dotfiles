// Context band: the session's own context size against the loop's hand-off
// thresholds (kernel "Token economy", memory orchestrator-self-handoff), so
// "clear at round boundaries" has a mechanism. Thresholds are loop policy, not
// engine facts: change them here only with the kernel.
//
// Trap: `tokens`/`percent` are absent before the first response and after
// /compact until the next call. Absent means "no reading", never 0: draw no
// band rather than a false "0k".
import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Ctx } from '../types'

const RESUME = 150_000
const HANDOFF = 190_000
const HARD_STOP = 300_000

const ctxAtom = atom({ plugin: 'context-band', key: 'ctx' } as const, null)

const k = (n: number) => `${Math.round(n / 1000)}k`

export const register: Register = on => {
  on('session.measure', async ($, e, next) => {
    const c = e.context
    const tokens = typeof c.tokens === 'number' ? c.tokens : null
    const ctx: Ctx = {
      tokens,
      window: typeof c.window === 'number' ? c.window : null,
      percent: typeof c.percent === 'number' ? c.percent : null,
    }
    await update($, ctxAtom, () => ctx)
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const ctx = await read($, ctxAtom)
    if (e.props.hasSurvey || ctx === null || ctx.tokens === null) return next(e)

    const { Box, Text } = $.ui.resolve(e)
    const t = ctx.tokens
    const pct = ctx.percent !== null ? ` (${ctx.percent}%)` : ''
    const base = `context ${k(t)}${ctx.window ? ` / ${k(ctx.window)}` : ''}${pct}`

    if (t >= HARD_STOP) {
      return <Box><Text bold inverse color="red"> {base} · HARD STOP over {k(HARD_STOP)}: /clear now </Text></Box>
    }
    if (t >= HANDOFF) {
      return <Box><Text bold inverse color="red"> {base} · HAND OFF: past {k(HANDOFF)} </Text></Box>
    }
    if (t >= RESUME) {
      return <Box><Text color="yellow">{base} · past {k(RESUME)} resume ceiling, hand off by {k(HANDOFF)}</Text></Box>
    }
    return <Box><Text dimColor>{base}</Text></Box>
  })
}
