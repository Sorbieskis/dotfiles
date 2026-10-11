export type Ctx = { tokens: number | null; window: number | null; percent: number | null }

declare module 'claude-code' {
  interface PluginState {
    'context-band': { ctx: Ctx | null }
  }
}
