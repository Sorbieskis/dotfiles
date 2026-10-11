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
import tempfile

# Thresholds, in tokens. "haiku_soft" applies to Haiku-class subagents; "soft" to the rest.
LIMITS = {"haiku_soft": 100_000, "soft": 190_000, "hard": 300_000}

# Allowed over the soft limit: git housekeeping (every segment of a chained command must pass
# parse_bash + git_ok), and Write/Edit to a report/handoff/notes file under a work root.
GIT_SOFT = {"add", "commit", "status", "diff", "log", "push"}
GIT_HARD = {"add", "commit"}  # at the hard tier uncommitted work may still be saved
PUSH_OPTS = {"-u", "--set-upstream", "--tags", "--follow-tags", "-q", "--quiet", "-v", "--verbose",
             "--dry-run", "-n"}
COMMIT_OPTS = {"-m", "-a", "-am", "--amend", "--no-edit", "-s", "-q", "--allow-empty", "-F", "--no-verify"}
REPORT_BASENAME = re.compile(r"^(report|handoff|notes)[A-Za-z0-9_.-]*\.md$", re.I)
HEREDOC = re.compile(r"\$\(\s*cat\s+<<-?\s*(['\"])(\w+)\1[ \t]*\n")


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


def parse_bash(cmd):
    """Split into segments of plain words, or None if anything exotic appears.

    Separators: unquoted && || ; | newline. Denied outright: lone &, unquoted/backtick/$(...)
    substitution (except one quoted $(cat <<'EOF' ... EOF) heredoc), redirections, <( >(, ( ), ${,
    unquoted $'...' and $"...".
    """
    segs, words, cur, have = [], [], [], False

    def end_word():
        nonlocal cur, have
        if have:
            words.append("".join(cur))
        cur, have = [], False

    def end_seg(blank_ok=False):
        nonlocal words
        end_word()
        if words:
            segs.append(words)
        elif not blank_ok:
            raise ValueError("empty segment")
        words = []

    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c in " \t":
            end_word()
        elif c == "\n":
            end_seg(blank_ok=True)
        elif c == "\\":
            if i + 1 >= n:
                return None
            cur.append(cmd[i + 1]); have = True; i += 1
        elif c == "'":
            j = cmd.find("'", i + 1)
            if j < 0:
                return None
            cur.append(cmd[i + 1:j]); have = True; i = j
        elif c == '"':
            have = True
            i += 1
            while True:
                if i >= n:
                    return None
                d = cmd[i]
                if d == '"':
                    break
                if d == "\\" and i + 1 < n:
                    cur.append(cmd[i + 1]); i += 2; continue
                if d == "`":
                    return None
                if d == "$" and i + 1 < n and cmd[i + 1] in "({":
                    m = HEREDOC.match(cmd, i)
                    if not m:
                        return None
                    end = re.compile(r"^%s[ \t]*\n?[ \t]*\)" % re.escape(m.group(2)), re.M).search(cmd, m.end())
                    if not end:
                        return None
                    cur.append("HEREDOC"); i = end.end(); continue
                cur.append(d); i += 1
        elif c == "&":
            if cmd[i:i + 2] != "&&":
                return None
            end_seg(); i += 1
        elif c == "|":
            end_seg()
            if cmd[i:i + 2] == "||":
                i += 1
        elif c == ";":
            end_seg()
        elif c in "`<>()":
            return None
        elif c == "$" and i + 1 < n and cmd[i + 1] in "({'\"":
            return None  # $(...), ${...}, and ANSI-C $'...' / locale $"..." (escapes can embed a newline)
        elif c == "#" and not have:
            return None
        else:
            cur.append(c); have = True
        i += 1
    end_seg(blank_ok=True)
    return segs or None


def git_ok(words, subs):
    i = 1
    while i < len(words) and words[i].startswith("-"):
        if words[i] == "-C" and i + 1 < len(words):
            i += 2
        else:
            return False  # -c, --exec-path, --git-dir, ...
    if i >= len(words) or words[i] not in subs:
        return False
    sub, args = words[i], words[i + 1:]
    if sub == "push":
        # Allowlist, not denylist: git accepts abbreviations (--forc, --del, --mir), so any
        # option outside PUSH_OPTS is denied, and `--` is denied too (a refspec after it would
        # skip the +/: check).
        for a in args:
            if a.startswith("-") and a not in PUSH_OPTS:
                return False
            if a.startswith(("+", ":")):
                return False  # forced / deleting refspec
        return True
    for a in args:
        if a == "--":
            break
        if sub == "commit" and a.startswith("-") and a not in COMMIT_OPTS:
            return False
        if sub in ("log", "diff", "status") and (a.startswith("--output") or a in ("--ext-diff", "--textconv")):
            return False
    return True


def bash_allowed(cmd, subs):
    try:
        segs = parse_bash(str(cmd).rstrip("\n"))
    except ValueError:
        return False
    if not segs:
        return False
    for w in segs:
        if w[0] == "cd":
            if len(w) != 2:
                return False
        elif w[0] != "git" or not git_ok(w, subs):
            return False
    return True


def report_path_ok(path, cwd):
    if not isinstance(path, str) or not path:
        return False
    home = os.path.expanduser("~")
    if not os.path.isabs(path):
        path = os.path.join(cwd or os.getcwd(), path)
    path = os.path.normpath(path)
    if not REPORT_BASENAME.match(os.path.basename(path)):
        return False
    roots = [cwd or os.getcwd(), os.path.join(home, "lab"), os.path.join(home, "drop"), tempfile.gettempdir(), "/tmp"]
    return any(r and path.startswith(os.path.normpath(r).rstrip("/") + "/") for r in roots)


def allowed_over_soft(ev):
    tool = ev.get("tool_name")
    ti = ev.get("tool_input") or {}
    if tool == "Bash":
        return bash_allowed(ti.get("command", ""), GIT_SOFT)
    if tool in ("Write", "Edit"):
        return report_path_ok(ti.get("file_path"), ev.get("cwd"))
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
        ti = ev.get("tool_input") or {}
        if ev.get("tool_name") == "Bash" and bash_allowed(ti.get("command", ""), GIT_HARD):
            return None
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
