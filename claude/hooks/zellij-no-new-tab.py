#!/usr/bin/env python3
"""PreToolUse(Bash): refuse commands that add a tab to a running zellij session.

On zellij 0.45.1, `zellij -s <s> action new-tab` on a session with no client attached leaves a broken tab,
and the next client attach panics the server ("failed to attach client N to tab with index M"), killing
every pane in it. It took down `osnova` on 2026-10-14 and 2026-10-15 (an orchestrator launching its
successor at night); reproduced in a throwaway session 2026-10-15. Agents run unattended, so "only when
someone is attached" cannot be guaranteed: the safe path is a new detached session via `zj-spawn`.
"""
import json, re, shlex, sys

WRAPPERS = {"timeout", "env", "sudo", "command", "exec", "nohup", "setsid", "time"}
FLAG_VALUE = {"-u", "--unset", "-s", "--signal", "-k", "--kill-after", "-C", "--chdir", "-g"}  # wrapper flags taking a value

def attached(args):
    """True when the target session (-s/--session, else $ZELLIJ_SESSION_NAME) lists at least one client."""
    import os, subprocess
    s = next((args[j + 1] for j, a in enumerate(args[:-1]) if a in ("-s", "--session")),
             os.environ.get("ZELLIJ_SESSION_NAME"))
    if not s:
        return False
    try:
        out = subprocess.run(["zellij", "-s", s, "action", "list-clients"], capture_output=True, text=True,
                             timeout=5).stdout
    except Exception:
        return False
    return any(l.split()[:1] and l.split()[0].isdigit() for l in out.splitlines()[1:])

def offending(cmd):
    for seg in re.split(r'(?:&&|\|\||[;|&\n]|\$\()', cmd):  # not backticks: markdown is full of them
        try:
            toks = shlex.split(seg, posix=True)
        except ValueError:
            toks = seg.split()
        # only zellij in command position (after wrappers like timeout/env), so text that merely mentions
        # new-tab (heredocs, grep patterns, docs) passes
        i = 0
        while i < len(toks) and (toks[i] in WRAPPERS or "=" in toks[i] or toks[i].startswith("-")
                                 or (i and toks[i - 1] in FLAG_VALUE)
                                 or (i and toks[i - 1] == "timeout" and toks[i][:1].isdigit())):
            i += 1
        if i < len(toks) and (toks[i] == "zellij" or toks[i].endswith("/zellij")):
            args = toks[i + 1:]
            if "new-tab" in args:
                # safe while a client is attached (the panic needs a tab made with none): the founder wants
                # successor orchestrators in an `osnova` tab (2026-10-15), so allow it then
                if not attached(args):
                    return "zellij action new-tab (no client attached to that session)"
                continue
            # with no client attached there is no focused tab: go-to-tab-name and a plain write-chars report
            # success and deliver nothing (tested 2026-10-15), so an unattended hand-off silently never starts
            if "write-chars" in args and not ({"-p", "--pane-id"} & set(args)) and not attached(args):
                return "zellij action write-chars without --pane-id (no client attached: it silently goes nowhere)"
            if "go-to-tab-name" in args and ("-c" in args or "--create" in args):
                return "zellij action go-to-tab-name --create"
            # `zellij -s <live session> --layout x` (without attach -b) adds the layout's tabs to it
            if ({"-s", "--session"} & set(args)) and ({"-l", "--layout", "-n", "--new-session-with-layout"} & set(args)) \
                    and "attach" not in args:
                return "zellij --session <s> --layout (adds tabs to a live session)"
    return None

try:
    cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "")
except Exception:
    sys.exit(0)
p = offending(cmd or "")
if p:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": f"{p} is blocked. Adding a tab to a running zellij session while no client is "
        "attached makes the next attach panic the whole server, killing every Claude in it (osnova crashed this way "
        "2026-10-14 and 2026-10-15); new-tab IS allowed while a client is attached to that session. With no client, "
        "go-to-tab-name and a plain write-chars do nothing. Unattended: reuse an EXISTING idle tab by pane id: "
        "`zellij -s <s> action list-panes -t -c` to find its terminal_N, then `zellij -s <s> action write-chars "
        "-p terminal_N '<command>'` (then a newline the same way). Or, as a last resort, "
        "open it in its own detached session: "
        "`zj-spawn <new-session-name> <cwd> <command...>` (e.g. zj-spawn orch-23 ~/dev/osnova-product fish "
        "~/lab/2026-10-m128-run/launch23.fish). `zellij run`, `close-tab-by-id` and `write-chars` to an existing pane are fine."}}))
sys.exit(0)
