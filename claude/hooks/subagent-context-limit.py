#!/usr/bin/env python3
"""PreToolUse (all tools) + SubagentStop: watch every subagent's context; optionally stop it.

Two jobs, both keyed on a subagent's context = its own transcript's last assistant usage
(input + cache read + cache create).
1. NOTICE (always on): when a subagent first crosses a line (Haiku-class 100k and 190k, every
   other model 150k and 190k) the crossing is recorded per spawning session in
   ~/.cache/subagent-ctx/<session_id>.json; the next tool call of the SPAWNING session (no agent_id)
   gets one additionalContext line per crossing, information only. SubagentStop retires the
   agent's entry once its notices are delivered. `touch ~/.cache/subagent-ctx/DISABLE` turns the
   whole hook off.
2. ENFORCEMENT (off unless CLAUDE_SUBAGENT_LIMIT_ENFORCE=1): over the soft limit (190k, every
   model; 100k is a target, never a stop: founder 2026-10-12) only the allowlist below runs; at the
   hard limit (300k) every tool is denied.
Any error or unreadable input allows the call (fail open).
Recipe and evidence: ~/lab/2026-10-loop-mods/part3-context-hook-probe.md, part5-spawner-notice-probe.md.
"""
import fcntl
import json
import os
import re
import sys
import tempfile

# Enforcement thresholds, in tokens (only with CLAUDE_SUBAGENT_LIMIT_ENFORCE=1).
LIMITS = {"soft": 190_000, "hard": 300_000}
# Notice lines, in tokens: informational only, per model class.
NOTICE_LINES = {"haiku": (100_000, 190_000), "other": (150_000, 190_000)}
ENFORCE_ENV = "CLAUDE_SUBAGENT_LIMIT_ENFORCE"
STALE_SECS = 3 * 24 * 3600  # state files of dead sessions

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


def agent_meta(meta_path):
    """(description, model) from the subagent's .meta.json; empty strings if unreadable."""
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        return str(meta.get("description") or ""), str(meta.get("model") or meta.get("agentType") or "")
    except Exception:
        return "", ""


def is_haiku(model, agent_type):
    return "haiku" in ("%s %s" % (model, agent_type or "")).lower()


def state_dir():
    return os.environ.get("SUBAGENT_CTX_STATE_DIR") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "subagent-ctx")


def state_path(session_id):
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", session_id):
        return None
    return os.path.join(state_dir(), session_id + ".json")


class Locked:
    """Read-modify-write of one session's state under flock (parallel subagents race)."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        self.lock = open(self.path + ".lock", "w")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        try:
            with open(self.path, encoding="utf-8") as f:
                self.state = json.load(f)
            if not isinstance(self.state.get("agents"), dict):
                self.state = {"agents": {}}
        except Exception:
            self.state = {"agents": {}}
        self.orig = json.dumps(self.state)
        return self.state

    def __exit__(self, et, ev, tb):
        try:
            if et is None and json.dumps(self.state) != self.orig:  # unchanged: no rewrite
                if self.state["agents"]:
                    tmp = self.path + ".tmp%d" % os.getpid()
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(self.state, f)
                    os.replace(tmp, self.path)
                elif os.path.exists(self.path):
                    os.unlink(self.path)
        finally:
            self.lock.close()
        return False


def label(desc, aid):
    return (" ".join(desc.split())[:60] or aid)


def record_crossings(ev, aid, ctx, base):
    """Subagent call: note each newly crossed notice line as pending for the spawner."""
    desc, model = agent_meta(base + ".meta.json")
    kind = "haiku" if is_haiku(model, ev.get("agent_type")) else "other"
    crossed = [l for l in NOTICE_LINES[kind] if ctx >= l]
    sp = state_path(ev.get("session_id"))
    if not crossed or not sp:
        return
    with Locked(sp) as st:
        a = st["agents"].setdefault(aid, {"notified": [], "pending": []})
        new = [l for l in crossed if l not in a["notified"]]
        for l in new:
            a["notified"].append(l)
            a["pending"].append("subagent \"%s\" (%s) is at ~%dk context (crossed %dk)"
                                % (label(desc, aid), model or ev.get("agent_type") or "?", ctx // 1000, l // 1000))


def pending_notices(ev):
    """Spawning-session call: deliver and clear pending lines; drop finished agents."""
    sp = state_path(ev.get("session_id"))
    if not sp or not os.path.exists(sp):
        return None
    lines = []
    with Locked(sp) as st:
        for aid in list(st["agents"]):
            a = st["agents"][aid]
            lines += a.get("pending") or []
            a["pending"] = []
            if a.get("finished"):
                del st["agents"][aid]
    if not lines:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "\n".join(lines)}}


def finish(ev):
    """SubagentStop: retire the agent once nothing is pending; sweep dead sessions' files."""
    sp = state_path(ev.get("session_id"))
    aid = ev.get("agent_id")
    if sp and aid and os.path.exists(sp):
        with Locked(sp) as st:
            a = st["agents"].get(aid)
            if a is not None:
                if a.get("pending"):
                    a["finished"] = True
                else:
                    del st["agents"][aid]
    try:
        import time
        d = state_dir()
        for n in os.listdir(d):
            fp = os.path.join(d, n)
            if time.time() - os.path.getmtime(fp) > STALE_SECS and n != "DISABLE":
                os.unlink(fp)
                if n.endswith(".json"):
                    try:
                        os.unlink(fp + ".lock")
                    except OSError:
                        pass
    except OSError:
        pass


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
        return pending_notices(ev)  # main session: the context-band mod covers its own size
    tp = ev.get("transcript_path")
    if not isinstance(tp, str) or not tp.endswith(".jsonl"):
        return None
    base = tp[:-len(".jsonl")] + "/subagents/agent-%s" % aid
    ctx = context_tokens(base + ".jsonl")
    if ctx is None:
        return None
    record_crossings(ev, aid, ctx, base)
    if os.environ.get(ENFORCE_ENV) != "1":
        return None
    if ctx >= LIMITS["hard"]:
        ti = ev.get("tool_input") or {}
        if ev.get("tool_name") == "Bash" and bash_allowed(ti.get("command", ""), GIT_HARD):
            return None
        return deny(HARD_REASON.format(n=ctx // 1000, m=LIMITS["hard"] // 1000))
    if ctx < LIMITS["soft"] or allowed_over_soft(ev):
        return None
    return deny(SOFT_REASON.format(n=ctx // 1000, m=LIMITS["soft"] // 1000))


def main():
    try:
        if os.path.exists(os.path.join(state_dir(), "DISABLE")):
            return
        ev = json.load(sys.stdin)
        if not isinstance(ev, dict):
            return
        if ev.get("hook_event_name") == "SubagentStop":
            finish(ev)
            return
        out = decide(ev)
    except Exception:
        return  # malformed input or any error: allow
    if out:
        print(json.dumps(out))


if __name__ == "__main__":
    main()
    sys.exit(0)
