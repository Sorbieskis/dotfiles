// Rewrites every string in a tool result. Settings hooks (PostToolUse) can't change
// what Claude reads; a mod can, by returning a modified result from tool.call.
//
// Trap: a hook that throws AFTER next() resolves leaves the unredacted result standing
// (docs: "that result stands"). Keep redact() total: no regex that can throw, no I/O.

const PATTERNS = [
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g, '[REDACTED private key]'],
  [/AGE-SECRET-KEY-[A-Z0-9]+/g, '[REDACTED age key]'],
  [/sk-ant-[A-Za-z0-9_-]{20,}/g, '[REDACTED anthropic key]'],
  [/\bsk-[A-Za-z0-9_-]{32,}/g, '[REDACTED api key]'],
  [/\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}/g, '[REDACTED github token]'],
  [/\bgithub_pat_[A-Za-z0-9_]{50,}/g, '[REDACTED github token]'],
  [/\bAKIA[0-9A-Z]{16}\b/g, '[REDACTED aws key id]'],
  [/\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g, '[REDACTED jwt]'],
  [/(Authorization:\s*Bearer\s+)[A-Za-z0-9._~+\/=-]{16,}/gi, '$1[REDACTED]'],
  // .env / fish `set -x` style: NAME containing a secret word, value kept out
  [/\b([A-Z][A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|PRIVATE_?KEY)[A-Z0-9_]*)(\s*[=\s]\s*)(?:"[^"\n]{4,}"|'[^'\n]{4,}'|[^\s"'#]{4,})/g, '$1$2[REDACTED]'],
]

function redactString(text) {
  let out = text
  for (const [pattern, replacement] of PATTERNS) out = out.replace(pattern, replacement)
  return out
}

// Counts replacements so the transcript can say that something was hidden.
function redact(value, tally) {
  if (typeof value === 'string') {
    const out = redactString(value)
    if (out !== value) tally.n += 1
    return out
  }
  if (Array.isArray(value)) return value.map((v) => redact(v, tally))
  if (value !== null && typeof value === 'object') {
    const copy = {}
    for (const key of Object.keys(value)) copy[key] = redact(value[key], tally)
    return copy
  }
  return value
}

export function register(on) {
  // No matcher: Read, Bash, Grep, MCP results all pass through here.
  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    // A refused call has nothing of ours to hide, and its text is the hook's own.
    if (result === undefined || result === null || result.deny) return result
    const tally = { n: 0 }
    const clean = redact(result, tally)
    if (tally.n > 0) $.ui.log('redacted ' + tally.n + ' secret(s) from ' + e.tool + ' output')
    return clean
  })
}
