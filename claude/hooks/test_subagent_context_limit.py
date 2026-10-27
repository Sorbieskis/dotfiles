#!/usr/bin/env python3
"""Tests for subagent-context-limit.py. Stdlib only: python3 test_subagent_context_limit.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "subagent-context-limit.py")

SOFT = "Context {n} k exceeds the limit {m} k for this seat: commit what you have, write your report, and STOP. Do not start new work."
HARD = "Context {n} k exceeds the hard limit {m} k for this seat: every tool is denied. Reply now with your report as your final message; do not retry."


STATE = {"dir": None}


def run(stdin, enforce=True):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_SUBAGENT_LIMIT_ENFORCE"}
    env["SUBAGENT_CTX_STATE_DIR"] = STATE["dir"]
    if enforce:
        env["CLAUDE_SUBAGENT_LIMIT_ENFORCE"] = "1"
    p = subprocess.run([sys.executable, "-I", HOOK], input=stdin, capture_output=True, text=True, env=env)
    return p.returncode, p.stdout, p.stderr


def dump(obj):
    return json.dumps(obj, separators=(",", ":"))  # Claude Code writes compact JSON; the hook matches it


def assistant(usage):
    return dump({"type": "assistant", "message": {"usage": {
        "input_tokens": 1000, "cache_read_input_tokens": usage - 1000, "cache_creation_input_tokens": 0}}})


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ctxlimit-")
        STATE["dir"] = os.path.join(self.root, "state")
        self.main = os.path.join(self.root, "sess.jsonl")
        self.subdir = os.path.join(self.root, "sess", "subagents")
        os.makedirs(self.subdir)
        open(self.main, "w").write(assistant(400_000) + "\n")  # main session file: huge, must be ignored

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def sub(self, aid, usage, boundary_after=False, model=None, agent_type="general-purpose", desc=None):
        lines = [dump({"type": "attachment", "pad": "x" * 150_000}), assistant(usage)]
        if boundary_after:
            lines.append(dump({"type": "system", "subtype": "compact_boundary"}))
        open(os.path.join(self.subdir, "agent-%s.jsonl" % aid), "w").write("\n".join(lines) + "\n")
        if model:
            json.dump({"agentType": agent_type, "model": model, "description": desc or ""},
                      open(os.path.join(self.subdir, "agent-%s.meta.json" % aid), "w"))

    def event(self, tool="Bash", aid="A1", agent_type="general-purpose", **ti):
        ev = {"session_id": "sess", "transcript_path": self.main, "tool_name": tool, "tool_input": ti,
              "cwd": "/repo"}
        if aid is not None:
            ev["agent_id"] = aid
            ev["agent_type"] = agent_type
        return json.dumps(ev)

    def assertAllowed(self, stdin):
        rc, out, _ = run(stdin)
        self.assertEqual((rc, out), (0, ""))

    def assertDenied(self, stdin, reason):
        rc, out, _ = run(stdin)
        self.assertEqual(rc, 0)
        d = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(d["permissionDecision"], "deny")
        self.assertEqual(d["permissionDecisionReason"], reason)


class SubagentContextLimit(Fixture):
    def test_under_threshold_allows(self):
        self.sub("A1", 150_000)
        self.assertAllowed(self.event("Bash", command="ls"))

    def test_haiku_is_not_stopped_at_100k_but_shares_the_190k_line(self):
        self.sub("A1", 120_000, model="claude-haiku-5-5")
        self.assertAllowed(self.event("Bash", command="ls"))
        self.sub("A2", 200_000, model="claude-haiku-5-5")
        self.assertDenied(self.event("Bash", aid="A2", command="ls"), SOFT.format(n=200, m=190))

    def test_haiku_by_agent_type_not_stopped_at_120k(self):
        self.sub("A3", 120_000)
        self.assertAllowed(self.event("Bash", aid="A3", agent_type="haiku-scout", command="ls"))

    def test_enforcement_is_inert_without_the_env_var(self):
        self.sub("A1", 200_000)
        self.sub("A2", 310_000)
        for aid in ("A1", "A2"):
            rc, out, _ = run(self.event("Bash", aid=aid, command="ls"), enforce=False)
            self.assertEqual((rc, out), (0, ""))
        self.assertDenied(self.event("Bash", command="ls"), SOFT.format(n=200, m=190))  # control: on = denies

    def test_soft_limit_allowlist(self):
        self.sub("A1", 200_000)
        self.assertAllowed(self.event("Bash", command="git add x && git commit -m m"))
        self.assertAllowed(self.event("Bash", command="git status"))
        self.assertDenied(self.event("Bash", command="rm -rf x && git commit -m m"), SOFT.format(n=200, m=190))
        self.assertDenied(self.event("Bash", command="ls"), SOFT.format(n=200, m=190))
        self.assertAllowed(self.event("Write", file_path="/tmp/x/report.md", content="r"))
        self.assertAllowed(self.event("Edit", file_path="/repo/HANDOFF.md"))
        self.assertDenied(self.event("Write", file_path="/repo/src/a.rs", content="x"), SOFT.format(n=200, m=190))

    def test_hard_limit_denies_all_but_git_save(self):
        self.sub("A1", 310_000)
        self.assertAllowed(self.event("Bash", command="git add -A && git commit -m m"))
        self.assertDenied(self.event("Bash", command="git push"), HARD.format(n=310, m=300))
        self.assertDenied(self.event("Bash", command="ls"), HARD.format(n=310, m=300))
        self.assertDenied(self.event("Bash", command="git commit -m m >x"), HARD.format(n=310, m=300))
        self.assertDenied(self.event("Write", file_path="/tmp/x/report.md", content="r"),
                          HARD.format(n=310, m=300))

    SOFT200 = SOFT.format(n=200, m=190)

    def bash(self, cmd, ok):
        self.sub("A1", 200_000)
        ev = self.event("Bash", command=cmd)
        if ok:
            self.assertAllowed(ev)
        else:
            self.assertDenied(ev, self.SOFT200)

    def test_quoted_and_cd_commits_allowed(self):
        for c in ("cd d && git commit -m x", "git -C d commit -m x", "git commit -m 'a; b && c | d'",
                  'git commit -m "fix: a || b"', "git commit -m x\n",
                  "git commit -m \"$(cat <<'EOF'\nmsg; rm -rf / $(x)\nEOF\n)\"",
                  "git add a\ngit commit -m x"):
            with self.subTest(c=c):
                self.bash(c, True)

    def test_bash_bypasses_denied(self):
        for c in ("git status & rm -rf x", "git status & git log", "git commit -m x $(rm x)", "git commit -m \"$(rm x)\"",
                  "git commit -m `rm x`", "git status > /etc/passwd", "git log >> f", "git status < f",
                  "git log --output=/tmp/x", "git diff --output /tmp/x", "git push --force", "git push -f",
                  "git push --force-with-lease", "git push --delete origin b", "git push origin +main",
                  "git -c core.pager=x log", "git --exec-path=/x status", "git status <(ls)",
                  "git status; (rm x)", "git commit -m \"$(cat <<EOF\nx\nEOF\n)\"",
                  "git status && rm x", "cd a b && git status"):
            with self.subTest(c=c):
                self.bash(c, False)

    def test_push_abbreviations_and_unknown_options_denied(self):
        for c in ("git push --forc origin b", "git push --del origin b", "git push --mir", "git push --f",
                  "git push -fu origin b", "git push -- +main", "git push origin :b", "git push --prune",
                  "git push --force-if-includes", "git push --no-verify origin main",
                  "git push -o ci.skip origin b"):
            with self.subTest(c=c):
                self.bash(c, False)

    def test_push_allowlist_allowed(self):
        for c in ("git push -u origin main", "git push --set-upstream origin b", "git push --tags",
                  "git push --follow-tags -q", "git push --dry-run origin main", "git push -n origin HEAD:refs/heads/x"):
            with self.subTest(c=c):
                self.bash(c, True)

    def test_commit_allowlist(self):
        for c in ("git commit --amend --no-edit", "git commit -s -m x", "git commit -a -m x",
                  "git commit --allow-empty -m x", "git commit -F msg.txt", "git commit -- a.rs"):
            with self.subTest(c=c):
                self.bash(c, True)
        for c in ("git commit --fixup=abc", "git commit --allow-empty-message -m x", "git commit --cleanup=strip -m x",
                  "git commit --am -m x"):
            with self.subTest(c=c):
                self.bash(c, False)

    def test_ansi_c_and_locale_quotes_denied(self):
        for c in ("git status $'x\ngit push --force'", "git commit -m $'a\nrm x'", "git log $\"x\"",
                  "git status a$'b'", "git status $'\\n' rm"):
            with self.subTest(c=c):
                self.bash(c, False)

    def test_dollar_quote_inside_double_quotes_allowed(self):
        self.bash('git commit -m "cost $\'5\' and $\\"x\\""', True)

    def test_write_path_must_be_report_under_root(self):
        self.sub("A1", 200_000)
        for p, ok in (("/repo/report.md", True), ("/repo/docs/HANDOFF-m5.md", True), ("/repo/notes_x.md", True),
                      ("/etc/cron.d/notes", False), ("/repo/src/report.rs", False), ("/repo/../etc/report.md", False),
                      ("/home/dima/lab/2026-10-x/report.md", True), ("/var/www/report.md", False),
                      ("report.md", True)):
            with self.subTest(p=p):
                ev = self.event("Write", file_path=os.path.expanduser(p), content="r")
                self.assertAllowed(ev) if ok else self.assertDenied(ev, self.SOFT200)

    def test_no_agent_id_allows_main_session(self):
        # Main transcript and a file where a missing guard would read (agent-None) both carry 400k.
        self.sub("None", 400_000)
        self.assertAllowed(self.event("Bash", aid=None, command="ls"))

    def test_missing_file_allows(self):
        self.assertAllowed(self.event("Bash", aid="NOPE", command="ls"))

    def test_compact_boundary_after_allows(self):
        self.sub("A1", 250_000, boundary_after=True)
        self.assertAllowed(self.event("Bash", command="ls"))
        self.sub("A2", 250_000)  # control: same usage without the boundary is denied
        self.assertDenied(self.event("Bash", aid="A2", command="ls"), SOFT.format(n=250, m=190))

    def test_garbage_stdin_exits_zero(self):
        for raw in ("not json{", "[]", "", '{"tool_input": "x", "agent_id": "A1", "transcript_path": 3}'):
            self.assertAllowed(raw)


class SpawnerNotice(Fixture):
    def main_call(self):
        return run(self.event("Bash", aid=None, command="ls"), enforce=False)

    def notice_lines(self, out):
        if not out:
            return []
        d = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(d["hookEventName"], "PreToolUse")
        return d["additionalContext"].split("\n")

    def test_crossing_notifies_once_then_silent(self):
        self.sub("A1", 104_000, model="claude-haiku-5-5", desc="build the thing")
        rc, out, _ = run(self.event("Bash", command="ls"), enforce=False)  # the subagent's own call
        self.assertEqual((rc, out), (0, ""))  # a subagent is told nothing
        rc, out, _ = self.main_call()
        self.assertEqual(self.notice_lines(out),
                         ['subagent "build the thing" (claude-haiku-5-5) is at ~104k context (crossed 90k)'])
        self.assertEqual(self.main_call()[1], "")  # never repeated
        run(self.event("Bash", command="ls"), enforce=False)  # the subagent calls again at the same size
        self.assertEqual(self.main_call()[1], "")

    def test_second_line_is_a_second_notice(self):
        self.sub("A1", 104_000, model="haiku", desc="d")
        run(self.event("Bash", command="ls"), enforce=False)
        self.main_call()
        self.sub("A1", 195_000, model="haiku", desc="d")
        run(self.event("Bash", command="ls"), enforce=False)
        lines = self.notice_lines(self.main_call()[1])
        self.assertEqual(len(lines), 1)
        self.assertIn("crossed 190k", lines[0])

    def test_haiku_first_line_is_90k(self):
        self.sub("A1", 89_000, model="haiku")
        run(self.event("Bash", command="ls"), enforce=False)
        self.assertEqual(self.main_call()[1], "")
        self.sub("A1", 91_000, model="haiku")
        run(self.event("Bash", command="ls"), enforce=False)
        self.assertIn("crossed 90k", self.main_call()[1])

    def test_non_haiku_first_line_is_150k(self):
        self.sub("A1", 120_000, model="inherit")
        run(self.event("Bash", command="ls"), enforce=False)
        self.assertEqual(self.main_call()[1], "")
        self.sub("A1", 155_000, model="inherit")
        run(self.event("Bash", command="ls"), enforce=False)
        self.assertIn("crossed 150k", self.main_call()[1])

    def test_main_call_with_nothing_pending_is_silent(self):
        self.assertEqual(self.main_call()[1:], ("", ""))
        self.sub("A1", 50_000, model="haiku")
        run(self.event("Bash", command="ls"), enforce=False)
        self.assertEqual(self.main_call()[1], "")

    def test_notice_goes_to_the_spawning_session_only(self):
        self.sub("A1", 104_000, model="haiku")
        run(self.event("Bash", command="ls"), enforce=False)
        other = json.loads(self.event("Bash", aid=None, command="ls"))
        other["session_id"] = "other"
        self.assertEqual(run(json.dumps(other), enforce=False)[1], "")
        self.assertIn("crossed 90k", self.main_call()[1])

    def test_finished_agent_is_cleaned_up(self):
        self.sub("A1", 104_000, model="haiku")
        run(self.event("Bash", command="ls"), enforce=False)
        stop = json.dumps({"hook_event_name": "SubagentStop", "session_id": "sess", "agent_id": "A1"})
        run(stop, enforce=False)  # stops with its notice undelivered: kept, flagged finished
        self.assertIn("crossed 90k", self.main_call()[1])
        self.assertEqual(os.listdir(STATE["dir"]) and [n for n in os.listdir(STATE["dir"]) if n.endswith(".json")], [])
        self.assertEqual(self.main_call()[1], "")

    def state_agents(self):
        return sorted(json.load(open(os.path.join(STATE["dir"], "sess.json")))["agents"])

    def test_finished_agent_with_nothing_pending_is_retired_from_state(self):
        self.sub("A1", 104_000, model="haiku")
        self.sub("A2", 104_000, model="haiku")
        run(self.event("Bash", aid="A1", command="ls"), enforce=False)
        self.main_call()  # delivers A1's notice: nothing pending
        run(self.event("Bash", aid="A2", command="ls"), enforce=False)  # keeps the state file alive
        self.assertEqual(self.state_agents(), ["A1", "A2"])
        run(json.dumps({"hook_event_name": "SubagentStop", "session_id": "sess", "agent_id": "A1"}), enforce=False)
        self.assertEqual(self.state_agents(), ["A2"])

    def test_main_call_with_nothing_pending_does_not_rewrite_state(self):
        self.sub("A1", 104_000, model="haiku")
        run(self.event("Bash", command="ls"), enforce=False)
        self.main_call()
        f = os.path.join(STATE["dir"], "sess.json")
        os.utime(f, (1, 1))
        self.main_call()
        self.assertEqual(os.path.getmtime(f), 1)

    def test_state_dir_is_private(self):
        self.sub("A1", 104_000, model="haiku")
        run(self.event("Bash", command="ls"), enforce=False)
        self.assertEqual(os.stat(STATE["dir"]).st_mode & 0o777, 0o700)

    def test_stale_sweep_removes_the_lock_with_its_state(self):
        os.makedirs(STATE["dir"])
        for n in ("old.json", "old.json.lock"):
            f = os.path.join(STATE["dir"], n)
            open(f, "w").write("{}")
            os.utime(f, (1, 1))
        run(json.dumps({"hook_event_name": "SubagentStop", "session_id": "sess", "agent_id": "A9"}), enforce=False)
        self.assertEqual(os.listdir(STATE["dir"]), [])

    def test_two_subagents_crossing_together_both_notify(self):
        self.sub("A1", 104_000, model="haiku", desc="one")
        self.sub("A2", 106_000, model="haiku", desc="two")
        ps = [subprocess.Popen([sys.executable, "-I", HOOK], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, env={**os.environ, "SUBAGENT_CTX_STATE_DIR": STATE["dir"]})
              for _ in range(2)]
        for p, a in zip(ps, ("A1", "A2")):
            p.stdin.write(self.event("Bash", aid=a, command="ls")); p.stdin.close()
        for p in ps:
            p.wait(); p.stdout.close()
        text = "\n".join(self.notice_lines(self.main_call()[1]))
        self.assertIn('"one"', text)
        self.assertIn('"two"', text)

    def test_disable_file_turns_it_off(self):
        self.sub("A1", 104_000, model="haiku")
        os.makedirs(STATE["dir"], exist_ok=True)
        open(os.path.join(STATE["dir"], "DISABLE"), "w").close()
        run(self.event("Bash", command="ls"), enforce=False)
        self.assertEqual(self.main_call()[1], "")


if __name__ == "__main__":
    unittest.main()
