#!/usr/bin/env python3
"""PreToolUse (all tools): a SUBAGENT past its context limit commits, reports and stops.

Main-session calls (no agent_id) are allowed silently: the context-band mod covers them.
A subagent's context is its own transcript's last assistant usage (input + cache read +
cache create). Over the soft limit only the allowlist below runs; at the hard limit every
tool is denied. Any error or unreadable input allows the call (fail open).
Recipe and evidence: ~/lab/2026-10-loop-mods/part3-context-hook-probe.md.
"""
import json
import os
import re
import sys

# Thresholds, in tokens. "haiku_soft" applies to Haiku-class subagents; "soft" to the rest.
LIMITS = {"haiku_soft": 100_000, "soft": 190_000, "hard": 300_000}

# Allowed over the soft limit: git housekeeping (every segment of a chained command must match),
# and Write/Edit to a report, handoff or notes path.
ALLOW_BASH = re.compile(r"^git\s+(add|commit|status|diff|log|push)(\s|$)")
ALLOW_WRITE_PATH = re.compile(r"report|handoff|notes", re.I)

SOFT_REASON = ("Context {n} k exceeds the limit {m} k for this seat: commit what you have, "
               "write your report, and STOP. Do not start new work.")
HARD_REASON = ("Context {n} k exceeds the hard limit {m} k for this seat: every tool is denied. "
               "Reply now with your report as your final message; do not retry.")

TAIL_SIZES = (1 << 18, 1 << 20, 1 << 22, 1 << 24)  # the subagent file opens with ~150 KB of attachments


def context_tokens(path):
    """Context of the transcript at path, or None if unknown (missing, just compacted, no usage)."""
    try:
        size = os.path.getsize(path)
        f = open(path, "rb")
    except OSError:
        return None
    with f:
        for tail in TAIL_SIZES:
            f.seek(max(0, size - tail))
            for ln in reversed(f.read().splitlines()):
                if b'"compact_boundary"' in ln:
                    return None  # compacted after the last assistant line: its usage is stale
                if b'"type":"assistant"' not in ln:
                    continue
                try:
                    u = json.loads(ln)["message"]["usage"]
                except Exception:
                    continue  # partial first line, or no usage
                return sum(int(u.get(k) or 0) for k in
                           ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            if tail >= size:
                return None
    return None


def is_haiku(meta_path, agent_type):
    names = [str(agent_type or "")]
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        names += [str(meta.get("model") or ""), str(meta.get("agentType") or "")]
    except Exception:
        pass
    return any("haiku" in s.lower() for s in names)


def allowed_over_soft(ev):
    tool = ev.get("tool_name")
    ti = ev.get("tool_input") or {}
    if tool == "Bash":
        segments = [s.strip() for s in re.split(r"&&|\|\||[;|\n]", str(ti.get("command", "")))]
        return all(s and ALLOW_BASH.match(s) for s in segments)
    if tool in ("Write", "Edit"):
        return bool(ALLOW_WRITE_PATH.search(str(ti.get("file_path", ""))))
    return False


def deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def decide(ev):
    aid = ev.get("agent_id")
    if not aid:
        return None  # main session: the context-band mod covers it
    tp = ev.get("transcript_path")
    if not isinstance(tp, str) or not tp.endswith(".jsonl"):
        return None
    base = tp[:-len(".jsonl")] + "/subagents/agent-%s" % aid
    ctx = context_tokens(base + ".jsonl")
    if ctx is None:
        return None
    if ctx >= LIMITS["hard"]:
        return deny(HARD_REASON.format(n=ctx // 1000, m=LIMITS["hard"] // 1000))
    haiku = is_haiku(base + ".meta.json", ev.get("agent_type"))
    soft = LIMITS["haiku_soft"] if haiku else LIMITS["soft"]
    if ctx < soft or allowed_over_soft(ev):
        return None
    return deny(SOFT_REASON.format(n=ctx // 1000, m=soft // 1000))


def main():
    try:
        ev = json.load(sys.stdin)
        if not isinstance(ev, dict):
            return
        out = decide(ev)
    except Exception:
        return  # malformed input or any error: allow
    if out:
        print(json.dumps(out))


if __name__ == "__main__":
    main()
    sys.exit(0)
