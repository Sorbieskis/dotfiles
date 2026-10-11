#!/usr/bin/env python3
"""PreToolUse(Agent): deny a subagent spawn that names no `model`.

An unnamed spawn inherits the parent's model (Opus at xhigh here), which is how cheap work
ran at the dearest rate. `subagent_type: "fork"` is exempt: a fork always inherits and its
`model` is ignored. Fails open on unparseable input.
"""
import json, sys

try:
    ev = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if not isinstance(ev, dict) or not isinstance(ev.get("tool_input") or {}, dict):
    sys.exit(0)
if ev.get("tool_name") not in ("Agent", "Task"):
    sys.exit(0)
ti = ev.get("tool_input") or {}
if ti.get("subagent_type") == "fork" or ti.get("model"):
    sys.exit(0)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
    "permissionDecisionReason": "Agent spawn without `model`: it would inherit this session's model. Re-issue the same call "
    "with an explicit model: \"sonnet\" (typing, scoped builds, chore review), \"opus\" (design-heavy work, milestone review) "
    "or \"haiku\" (lookups, mechanical edits). Exempt: subagent_type \"fork\"."}}))
sys.exit(0)
