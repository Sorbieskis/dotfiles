"""Hermetic tests for bin/vault-backup.sh.

Each test builds a bare `origin`, a vault clone on `main` and stubs for gitleaks, ntfy and the
doc lint in a temp dir, then runs the real script and checks the outcome in git itself
(origin's main sha, the commit's content), not in the script's output.

Run: python3 -m unittest discover -s tests
"""

import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "vault-backup.sh")

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, env={**os.environ, **GIT_ENV}).stdout.strip()


def write_exec(path, body):
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, 0o755)
    return path


class VaultBackupTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.origin = os.path.join(self.root, "origin.git")
        self.vault = os.path.join(self.root, "vault")
        self.ntfy_log = os.path.join(self.root, "ntfy.log")
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)

        # bare origin with one seed commit on main
        git(self.root, "init", "-q", "--bare", "-b", "main", self.origin)
        seed = os.path.join(self.root, "seed")
        git(self.root, "init", "-q", "-b", "main", seed)
        with open(os.path.join(seed, "README.md"), "w") as f:
            f.write("seed\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "seed")
        git(seed, "remote", "add", "origin", self.origin)
        git(seed, "push", "-q", "origin", "main")

        # vault clone on main, tracking origin/main
        git(self.root, "clone", "-q", "-b", "main", self.origin, self.vault)

        # stubs: gitleaks (rc per test), empty config, ntfy recorder, lint (set per test)
        self.gitleaks = write_exec(os.path.join(self.root, "gitleaks"), "cat >/dev/null; exit 0")
        self.config = os.path.join(self.root, "gitleaks.toml")
        with open(self.config, "w") as f:
            f.write("")
        self.ntfy = write_exec(os.path.join(self.root, "ntfy"),
                               f'printf "%s\\n" "$1" >> "{self.ntfy_log}"')
        self.lint = write_exec(os.path.join(self.root, "lint-ok"), "exit 0")

    def tearDown(self):
        self._tmp.cleanup()

    # helpers -------------------------------------------------------------

    def set_gitleaks_rc(self, rc):
        write_exec(self.gitleaks, f"cat >/dev/null; exit {rc}")  # real gitleaks reads stdin too

    def dirty_vault(self, name="note.md"):
        with open(os.path.join(self.vault, name), "w") as f:
            f.write("content " + name + "\n")

    def origin_main(self):
        return git(self.origin, "rev-parse", "main")

    def run_backup(self, lint=None, timeout=60, **extra):
        env = {
            "PATH": os.environ["PATH"],
            "HOME": self.home,
            **GIT_ENV,
            "VAULT_DIR": self.vault,
            "GITLEAKS_BIN": self.gitleaks,
            "GITLEAKS_CONFIG": self.config,
            "NTFY_CMD": self.ntfy,
        }
        if lint is not None:  # None leaves it unset: the script uses the vault's pre-commit hook
            env["VAULT_LINT_CMD"] = lint
        env.update(extra)
        start = time.monotonic()
        proc = subprocess.run(["bash", SCRIPT], env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=timeout)
        self.elapsed = time.monotonic() - start
        self.out = proc.stdout + proc.stderr
        return proc

    def ntfy_messages(self):
        if not os.path.exists(self.ntfy_log):
            return []
        with open(self.ntfy_log) as f:
            return f.read().splitlines()

    def assert_backup_pushed(self, proc, before):
        self.assertEqual(proc.returncode, 0, self.out)
        after = self.origin_main()
        self.assertNotEqual(after, before, "origin main did not move: push did not happen")
        self.assertEqual(git(self.vault, "rev-parse", "HEAD"), after)
        self.assertIn("backup: vault snapshot", git(self.origin, "log", "-1", "--format=%s", "main"))
        self.assertEqual(self.ntfy_messages(), [])

    def assert_backup_held(self, proc, before):
        self.assertEqual(proc.returncode, 1, self.out)
        self.assertEqual(self.origin_main(), before, "push leaked past the held gate")
        self.assertTrue(any("push held" in m for m in self.ntfy_messages()),
                        self.ntfy_messages())

    # lint advisory: commit, push, exit 0 ----------------------------------

    def test_a_lint_exit_1_commits_pushes_and_logs(self):
        lint = write_exec(os.path.join(self.root, "lint-fail"),
                          'echo "lint: broken link"; exit 1')
        self.dirty_vault()
        before = self.origin_main()
        proc = self.run_backup(lint=lint)
        self.assert_backup_pushed(proc, before)
        self.assertIn("lint: broken link", self.out)
        self.assertIn("vault-backup: doc lint advisory: exit 1 (not holding the backup)", self.out)

    def test_g_lint_ignoring_term_is_killed_after_the_grace_and_the_backup_pushes(self):
        # --kill-after: a plain `sleep 30` dies on TERM, a lint that traps TERM only dies on KILL
        lint = write_exec(os.path.join(self.root, "lint-term-deaf"), "trap '' TERM; sleep 12 & wait")
        self.dirty_vault()
        before = self.origin_main()
        proc = self.run_backup(lint=lint, VAULT_LINT_TIMEOUT="1")
        self.assert_backup_pushed(proc, before)
        self.assertLess(self.elapsed, 10, self.elapsed)
        self.assertIn("doc lint advisory: exit 137", self.out)

    def test_h_lint_that_resets_the_index_cannot_change_the_snapshot(self):
        lint = write_exec(os.path.join(self.root, "lint-resets"), "git reset -q; exit 0")
        self.dirty_vault("kept.md")
        before = self.origin_main()
        proc = self.run_backup(lint=lint)
        self.assert_backup_pushed(proc, before)
        self.assertIn("kept.md", git(self.origin, "show", "--name-only", "--format=", "main"))

    def test_b_lint_missing_or_127_commits_pushes_and_logs(self):
        self.dirty_vault()
        before = self.origin_main()
        proc = self.run_backup(lint=os.path.join(self.root, "no-such-lint"))
        self.assert_backup_pushed(proc, before)
        self.assertIn("vault-backup: doc lint advisory: exit 127 (not holding the backup)",
                      self.out)

    def test_c_lint_hang_is_killed_and_backup_still_pushes(self):
        hang = write_exec(os.path.join(self.root, "lint-hang"), "sleep 30")
        self.dirty_vault()
        before = self.origin_main()
        proc = self.run_backup(lint=hang, VAULT_LINT_TIMEOUT="1")
        self.assertLess(self.elapsed, 10, f"lint hang held the script for {self.elapsed:.1f}s")
        self.assert_backup_pushed(proc, before)
        self.assertIn("vault-backup: doc lint advisory: exit 124 (not holding the backup)",
                      self.out)

    def test_d_real_precommit_hook_failing_does_not_block_commit(self):
        # the vault's own pre-commit hook, exit 1: git commit would refuse without --no-verify
        hook = os.path.join(self.vault, ".git", "hooks", "pre-commit")
        write_exec(hook, 'echo "hook: refused"; exit 1')
        self.dirty_vault()
        before = self.origin_main()
        proc = self.run_backup()  # no VAULT_LINT_CMD: default = $VAULT_DIR/.git/hooks/pre-commit
        self.assert_backup_pushed(proc, before)
        self.assertIn("hook: refused", self.out)
        self.assertIn("doc lint advisory: exit 1", self.out)

    # gitleaks: still holds the push, independent of the lint ---------------

    def test_e_gitleaks_hit_holds_push_with_lint_fine(self):
        self.set_gitleaks_rc(1)
        self.dirty_vault()
        before = self.origin_main()
        proc = self.run_backup(lint=self.lint)
        self.assert_backup_held(proc, before)

    def test_f_gitleaks_hit_and_lint_failing_still_holds_push(self):
        self.set_gitleaks_rc(1)
        lint = write_exec(os.path.join(self.root, "lint-fail"), "exit 1")
        self.dirty_vault()
        before = self.origin_main()
        proc = self.run_backup(lint=lint)
        self.assert_backup_held(proc, before)
        self.assertIn("doc lint advisory: exit 1", self.out)


if __name__ == "__main__":
    unittest.main()
