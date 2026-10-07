#!/usr/bin/env python3
"""PreToolUse(Bash): refuse `pgrep -f`/`pkill -f` whose pattern can match its own command line.

A `-f` pattern is matched against full command lines, including the shell that runs it, so a wait
loop on `pgrep -f 'bin/check'` sees itself forever (43 instances in M125's friction count). A
bracket expression (`[b]in/check`) cannot match its own literal text, so it passes.
"""
import json, re, shlex, sys

def offending(cmd):
    for seg in re.split(r'(?:&&|\|\||[;|&\n]|\$\(|`)', cmd):
        try:
            toks = shlex.split(seg, posix=True)
        except ValueError:
            toks = seg.split()
        for i, t in enumerate(toks):
            if t not in ("pgrep", "pkill") and not t.endswith(("/pgrep", "/pkill")):
                continue
            args, has_f, pattern, skip = toks[i + 1:], False, None, False
            for a in args:
                if skip:
                    skip = False
                    continue
                if a.startswith("--"):
                    has_f |= a == "--full"
                    continue
                if a.startswith("-") and len(a) > 1:
                    has_f |= "f" in a[1:]
                    if a[1:] in ("u", "U", "g", "G", "P", "s", "t", "F", "n"):  # flags taking a value
                        skip = True
                    continue
                pattern = a
                break
            if has_f and pattern and not re.search(r"\[[^\]]+\]", pattern):
                return pattern
    return None

try:
    cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "")
except Exception:
    sys.exit(0)
p = offending(cmd or "")
if p:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": f"a pgrep/pkill -f pattern ({p!r}) matches its own command line; use a bracket trick "
        "([b]in/check), wait on a PID (tail --pid=N -f /dev/null, kill -0), or the tool's own blocking wait"}}))
sys.exit(0)
