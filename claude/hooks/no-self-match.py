#!/usr/bin/env python3
"""PreToolUse(Bash): refuse `pgrep -f`/`pkill -f` whose pattern can match its own command line.

A `-f` pattern is matched against full command lines, including the shell that runs it, so a wait
loop on `pgrep -f 'bin/check'` sees itself forever (43 instances in M125's friction count). A
bracket expression (`[b]in/check`) cannot match its own literal text, so it passes, but a `pgrep -f`
used as a WAIT (in an until/while condition) is refused even with a bracket: it matches any other process
whose argv holds the text (another seat's launch prompt, for one), so the wait never ends.
"""
import json, re, shlex, sys

def offending(cmd):
    """Return (pattern, is_wait) for the first refused pgrep/pkill -f, or (None, False)."""
    in_cond = False  # inside an until/while condition, up to its `do`
    for seg in re.split(r'(?:&&|\|\||[;|&\n]|\$\(|`)', cmd):
        try:
            toks = shlex.split(seg, posix=True)
        except ValueError:
            toks = seg.split()
        if toks[:1] in (["while"], ["until"]):
            in_cond = True
        elif toks[:1] in (["do"], ["then"]):
            in_cond = False
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
            if has_f and pattern:
                if in_cond and (t == "pgrep" or t.endswith("/pgrep")):
                    return pattern, True
                if not re.search(r"\[[^\]]+\]", pattern):
                    return pattern, False
    return None, False

try:
    cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "")
except Exception:
    sys.exit(0)
p, wait = offending(cmd or "")
if wait:
    reason = (f"a pgrep -f wait ({p!r}) in an until/while condition matches any process whose argv holds that text, "
              "other Claude seats' launch prompts included, so it never ends; wait on a PID instead: "
              "tail --pid=N -f /dev/null, or kill -0 N in the loop, or the tool's own blocking wait")
elif p:
    reason = (f"a pgrep/pkill -f pattern ({p!r}) matches its own command line; use a bracket trick "
              "([b]in/check), wait on a PID (tail --pid=N -f /dev/null, kill -0), or the tool's own blocking wait")
if p:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))
sys.exit(0)
