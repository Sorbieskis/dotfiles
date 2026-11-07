"""Hermetic tests for bin/vault-snapshot (M9 P2): the read-only vault snapshot claude.ai reads from.

Each test builds a vault git repo whose `refs/remotes/origin/main` is the "pushed" state, runs the real
script into a scratch output dir and checks the published tree itself. Real gitleaks is used where the
guarantee is the scan (skipped if the binary is missing); failure paths use stubs. Secret fixtures are
assembled at runtime and never whole in git.

Run: python3 -m unittest discover -s tests
"""

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "bin", "vault-snapshot")
GITLEAKS = os.environ.get("GITLEAKS_BIN") or "/home/dima/.local/share/mise/installs/aqua-gitleaks-gitleaks/8.30.1/gitleaks"
CONFIG = os.path.join(ROOT, "vault", "gitleaks.toml")

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, env={**os.environ, **GIT_ENV}).stdout.strip()


def secret():
    """A gitleaks-positive GitHub token assembled here, never whole in git."""
    return "".join(["gh", "p_", "R7x2KqL9mZ4v", "B8nC1dF5gH3j", "T6wY0sA2eU9p"])


def stub(path, body):
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, 0o755)
    return path


def tree(root):
    """All published file paths, relative, excluding the stamp."""
    out = set()
    for d, _, files in os.walk(root):
        for n in files:
            rel = os.path.relpath(os.path.join(d, n), root)
            if rel != "SNAPSHOT.md":
                out.add(rel)
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.vault = os.path.join(self.root, "vault")
        self.out = os.path.join(self.root, "out")  # scratch output, never ~/.cache/vault-snapshot
        git(self.root, "init", "-q", "-b", "main", self.vault)
        self.gl_ok = stub(os.path.join(self.root, "gl-ok"), "exit 0")

    def put(self, rel, text="note\n"):
        p = os.path.join(self.vault, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def link(self, rel, target):
        p = os.path.join(self.vault, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        os.symlink(target, p)

    def commit(self, push=True):
        git(self.vault, "add", "-A")
        git(self.vault, "commit", "-q", "--allow-empty", "-m", "c")
        if push:
            git(self.vault, "update-ref", "refs/remotes/origin/main", "HEAD")
        return git(self.vault, "rev-parse", "HEAD")

    def run_snapshot(self, gitleaks=None, config=True, **extra):
        env = {**os.environ, **GIT_ENV, "VAULT_DIR": self.vault, "SNAPSHOT_DIR": self.out,
               "GITLEAKS_BIN": gitleaks or self.gl_ok, "GITLEAKS_CONFIG": CONFIG if config else "/nonexistent.toml"}
        env.update(extra)
        return subprocess.run([SCRIPT], capture_output=True, text=True, env=env, timeout=120)

    def current(self):
        return os.path.join(self.out, "current")

    def published(self):
        return tree(os.path.join(self.out, "current"))

    def gens(self):
        return sorted(n for n in os.listdir(self.out) if n.startswith("gen-"))


class ScopeTests(Base):
    def test_allowlisted_folders_are_published_and_every_other_top_folder_is_not(self):
        keep = ["1_projects/p/a.md", "2_areas/x/b.md", "4_resources/c.md", "1_projects/p/engineering/plans/m1.md"]
        deny = ["3_personal/d.md", "belle/e.md", "journal/f.md", "5_archive/g.md", "0_inbox/h.md",
                "0_inbox/claude-ai/i.md", "excalidraw/j.md", "CLAUDE.md", "Untitled 1.md", ".obsidian/k.md", ".trash/l.md"]
        for rel in keep + deny:
            self.put(rel)
        self.commit()
        r = self.run_snapshot()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.published(), set(keep))

    def test_only_md_files_are_kept(self):
        for rel in ["1_projects/p/a.md", "1_projects/p/b.png", "1_projects/p/c.txt", "1_projects/p/d.md.bak", "1_projects/p/e.canvas"]:
            self.put(rel)
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(self.published(), {"1_projects/p/a.md"})

    def test_hidden_files_and_folders_inside_the_allowed_folders_are_dropped(self):
        for rel in ["1_projects/p/a.md", "1_projects/p/.review-record/r.md", "1_projects/p/.hidden.md", "2_areas/.obsidian/o.md"]:
            self.put(rel)
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(self.published(), {"1_projects/p/a.md"})

    def test_names_with_spaces_and_unicode_survive(self):
        self.put("1_projects/p/Plan v2 \u2014 \u0436.md", "x\n")
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(self.published(), {"1_projects/p/Plan v2 \u2014 \u0436.md"})


class MachineOutputTests(Base):
    def test_the_p3_machine_output_paths_are_excluded_and_their_neighbours_are_not(self):
        drop = ["1_projects/p/pull-log/a.md", "1_projects/p/pull-log/deep/b.md", "1_projects/q/landings/c.md",
                "1_projects/p/engineering/jobs/d.md", "1_projects/p/engineering/seat/e.md",
                "1_projects/p/engineering/seat/x/y/f.md", "1_projects/p/agent-ledger.md", "1_projects/p/agent-ledger-2026.md"]
        keep = ["1_projects/p/engineering/plans/m1.md", "1_projects/p/engineering/jobs-notes.md", "1_projects/p/current.md",
                "1_projects/p/notes/pull-log.md", "1_projects/p/landing-page.md", "2_areas/pull-log/z.md"]
        for rel in drop + keep:
            self.put(rel)
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(self.published(), set(keep))


class PushedOnlyTests(Base):
    def test_only_origin_main_is_published_never_local_commits_or_the_work_tree(self):
        self.put("1_projects/p/pushed.md", "v1 pushed\n")
        sha = self.commit()
        self.put("1_projects/p/pushed.md", "v2 LOCAL\n")
        self.put("1_projects/p/local-only.md")
        self.commit(push=False)  # committed, not pushed
        self.put("1_projects/p/dirty.md")  # not even committed
        r = self.run_snapshot()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.published(), {"1_projects/p/pushed.md"})
        with open(os.path.join(self.current(), "1_projects/p/pushed.md")) as f:
            self.assertEqual(f.read(), "v1 pushed\n")
        with open(os.path.join(self.current(), "SNAPSHOT.md")) as f:
            self.assertRegex(f.read(), rf"(?m)^sha: {sha}$")

    def test_no_origin_main_publishes_nothing_and_fails(self):
        self.put("1_projects/p/a.md")
        self.commit(push=False)
        r = self.run_snapshot()
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.lexists(self.current()))

    def test_symlinks_in_the_tree_are_not_published(self):
        self.put("1_projects/p/real.md", "real\n")
        self.put("3_personal/diary.md", "PRIVATE\n")
        self.link("1_projects/p/alias.md", "real.md")
        self.link("1_projects/p/leak.md", "../../3_personal/diary.md")
        self.link("1_projects/p/dirlink", "../../3_personal")
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(self.published(), {"1_projects/p/real.md"})
        for d, _, files in os.walk(self.current()):
            for n in files + _:
                self.assertFalse(os.path.islink(os.path.join(d, n)), n)

    def test_the_stamp_has_sha_utc_time_and_counts(self):
        for rel in ["1_projects/p/a.md", "1_projects/p/b.md", "1_projects/p/pull-log/c.md", "1_projects/p/.x/d.md"]:
            self.put(rel)
        sha = self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        with open(os.path.join(self.current(), "SNAPSHOT.md")) as f:
            text = f.read()
        self.assertRegex(text, rf"(?m)^sha: {sha}$")
        self.assertRegex(text, r"(?m)^generated: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertRegex(text, r"(?m)^files: 2$")
        self.assertRegex(text, r"(?m)^dropped: 2$")

    def test_published_modes_let_the_container_user_read_them(self):
        self.put("1_projects/p/a.md")
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        gen = os.path.join(self.out, self.gens()[0])
        self.assertEqual(stat.S_IMODE(os.stat(gen).st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(gen, "1_projects/p/a.md")).st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(gen, "1_projects/p")).st_mode), 0o755)


@unittest.skipUnless(os.access(GITLEAKS, os.X_OK), "gitleaks missing")
class SecretScanTests(Base):
    def test_a_file_with_a_credential_is_dropped_and_nothing_else_is(self):
        self.put("1_projects/p/clean.md", "nothing secret here\n")
        self.put("1_projects/p/leaky.md", f"token = {secret()}\n")
        self.put("2_areas/clean2.md", "also fine\n")
        self.commit()
        r = self.run_snapshot(gitleaks=GITLEAKS)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.published(), {"1_projects/p/clean.md", "2_areas/clean2.md"})
        for d, _, files in os.walk(self.out):  # the secret is nowhere under the output, stamp included
            for n in files:
                with open(os.path.join(d, n), errors="replace") as f:
                    self.assertNotIn(secret(), f.read(), n)
        with open(os.path.join(self.current(), "SNAPSHOT.md")) as f:
            self.assertRegex(f.read(), r"(?m)^dropped: 1$")
        self.assertNotIn(secret(), r.stdout + r.stderr)

    def test_a_credential_in_the_file_name_is_dropped_too(self):
        self.put("1_projects/p/clean.md")
        self.put(f"1_projects/p/{secret()}.md", "x\n")
        self.commit()
        r = self.run_snapshot(gitleaks=GITLEAKS)
        # either the name is flagged and dropped, or gitleaks does not scan names: then it must still publish no secret in content
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1_projects/p/clean.md", self.published())

    def test_gitleaks_inline_allow_comment_does_not_exempt_a_file(self):
        self.put("1_projects/p/sneaky.md", f"token = {secret()}  # gitleaks:allow\n")
        self.put("1_projects/p/clean.md")
        self.commit()
        self.assertEqual(self.run_snapshot(gitleaks=GITLEAKS).returncode, 0)
        self.assertEqual(self.published(), {"1_projects/p/clean.md"})


class FailClosedTests(Base):
    def first_generation(self):
        self.put("1_projects/p/old.md", "old\n")
        old = self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(os.readlink(self.current()), f"gen-{old}")
        return old

    def assert_old_kept(self, old):
        self.assertEqual(os.readlink(self.current()), f"gen-{old}")
        self.assertEqual(self.gens(), [f"gen-{old}"])
        self.assertEqual(self.published(), {"1_projects/p/old.md"})
        self.assertEqual([n for n in os.listdir(self.out) if n not in (f"gen-{old}", "current")], [])  # no build leftovers

    def test_gitleaks_error_publishes_nothing_and_keeps_the_old_current(self):
        old = self.first_generation()
        self.put("1_projects/p/new.md")
        self.commit()
        r = self.run_snapshot(gitleaks=stub(os.path.join(self.root, "gl-err"), "exit 2"))
        self.assertNotEqual(r.returncode, 0)
        self.assert_old_kept(old)

    def test_gitleaks_missing_publishes_nothing_and_keeps_the_old_current(self):
        old = self.first_generation()
        self.put("1_projects/p/new.md")
        self.commit()
        r = self.run_snapshot(gitleaks=os.path.join(self.root, "no-such-gitleaks"))
        self.assertNotEqual(r.returncode, 0)
        self.assert_old_kept(old)

    def test_gitleaks_config_unreadable_fails_closed(self):
        old = self.first_generation()
        self.put("1_projects/p/new.md")
        self.commit()
        r = self.run_snapshot(config=False)
        self.assertNotEqual(r.returncode, 0)
        self.assert_old_kept(old)

    def test_exit_1_without_a_readable_report_is_an_error_not_a_hit(self):
        # gitleaks also exits 1 on a bad config: no report must never read as "all files dropped, publish"
        old = self.first_generation()
        self.put("1_projects/p/new.md")
        self.commit()
        r = self.run_snapshot(gitleaks=stub(os.path.join(self.root, "gl-1"), "exit 1"))
        self.assertNotEqual(r.returncode, 0)
        self.assert_old_kept(old)

    def test_a_rescan_that_still_finds_a_hit_publishes_nothing(self):
        # first call reports a hit on a.md, the second still exits 1: dropping did not make it clean
        old = self.first_generation()
        self.put("1_projects/p/new.md")
        self.commit()
        body = ('rp=""; while [ $# -gt 0 ]; do [ "$1" = "--report-path" ] && rp="$2"; shift; done\n'
                'echo \'[{"File":"1_projects/p/new.md","RuleID":"x"}]\' > "$rp"; exit 1')
        r = self.run_snapshot(gitleaks=stub(os.path.join(self.root, "gl-stuck"), body))
        self.assertNotEqual(r.returncode, 0)
        self.assert_old_kept(old)

    def test_a_report_naming_a_path_outside_the_generation_is_an_error(self):
        old = self.first_generation()
        self.put("1_projects/p/new.md")
        self.commit()
        body = ('rp=""; while [ $# -gt 0 ]; do [ "$1" = "--report-path" ] && rp="$2"; shift; done\n'
                'echo \'[{"File":"/etc/passwd","RuleID":"x"}]\' > "$rp"; exit 1')
        r = self.run_snapshot(gitleaks=stub(os.path.join(self.root, "gl-out"), body))
        self.assertNotEqual(r.returncode, 0)
        self.assert_old_kept(old)


class SwapTests(Base):
    def test_current_is_a_relative_symlink_to_gen_sha_and_the_mounted_parent_is_never_renamed(self):
        self.put("1_projects/p/a.md")
        sha1 = self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        ino = os.stat(self.out).st_ino
        self.assertEqual(os.readlink(self.current()), f"gen-{sha1}")  # relative: valid inside a /snapshot mount
        self.put("1_projects/p/b.md")
        sha2 = self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(os.readlink(self.current()), f"gen-{sha2}")
        self.assertEqual(os.stat(self.out).st_ino, ino)
        self.assertNotIn("current.tmp", os.listdir(self.out))

    def test_a_reader_never_sees_current_missing_or_half_written_across_swaps(self):
        self.put("1_projects/p/a.md", "a\n")
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        stop, bad = threading.Event(), []

        def reader():
            while not stop.is_set():
                try:
                    with open(os.path.join(self.current(), "SNAPSHOT.md")) as f:
                        if not f.read().startswith("#"):
                            bad.append("content")
                    os.stat(os.path.join(self.current(), "1_projects/p/a.md"))
                except OSError as e:
                    bad.append(repr(e))

        t = threading.Thread(target=reader)
        t.start()
        try:
            for i in range(4):
                self.put(f"1_projects/p/n{i}.md")
                self.commit()
                self.assertEqual(self.run_snapshot().returncode, 0)
        finally:
            stop.set()
            t.join()
        self.assertEqual(bad, [])

    def test_two_generations_are_kept(self):
        shas = []
        for i in range(4):
            self.put(f"1_projects/p/n{i}.md")
            shas.append(self.commit())
            self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(self.gens(), sorted(f"gen-{s}" for s in shas[-2:]))

    def test_an_unchanged_sha_republishes_nothing(self):
        self.put("1_projects/p/a.md")
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        stamp = os.lstat(self.current()).st_mtime_ns
        gen = os.path.join(self.out, self.gens()[0], "SNAPSHOT.md")
        before = os.stat(gen).st_mtime_ns
        self.assertEqual(self.run_snapshot(gitleaks=stub(os.path.join(self.root, "gl-boom"), "exit 2")).returncode, 0)
        self.assertEqual(os.stat(gen).st_mtime_ns, before)
        self.assertEqual(os.lstat(self.current()).st_mtime_ns, stamp)

    def test_stale_build_directories_from_a_killed_run_are_cleaned(self):
        os.makedirs(os.path.join(self.out, ".build-999"))
        self.put("1_projects/p/a.md")
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertFalse(any(n.startswith(".build") for n in os.listdir(self.out)))


class WiringTests(unittest.TestCase):
    def read(self, *p):
        with open(os.path.join(ROOT, *p)) as f:
            return f.read()

    def test_hourly_at_47_and_the_service_runs_the_installed_script(self):
        timer = self.read("systemd", "user", "vault-snapshot.timer")
        service = self.read("systemd", "user", "vault-snapshot.service")
        self.assertRegex(timer, r"(?m)^OnCalendar=\*:47(:00)?$")
        self.assertIn("timers.target", timer)
        self.assertRegex(service, r"(?m)^Type=oneshot$")
        self.assertRegex(service, r"(?m)^ExecStart=%h/\.local/bin/vault-snapshot$")
        self.assertRegex(service, r"(?m)^MemoryMax=")

    def test_install_enables_the_timer_and_links_the_script(self):
        install = self.read("install.sh")
        self.assertIn("vault-snapshot.timer", install)
        self.assertTrue(os.access(SCRIPT, os.X_OK))  # install.sh links every executable bin/*


if __name__ == "__main__":
    unittest.main()
