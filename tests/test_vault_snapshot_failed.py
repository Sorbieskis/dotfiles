"""Hermetic tests for the vault-snapshot failure notice (bin/vault-snapshot-failed and its OnFailure= wiring).

A stub `curl` on PATH records its arguments; no real ntfy is contacted.

Run: python3 -m unittest discover -s tests
"""

import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
NOTIFIER = os.path.join(ROOT, "bin", "vault-snapshot-failed")
SNAPSHOT_UNIT = os.path.join(ROOT, "systemd", "user", "vault-snapshot.service")
TOPIC = "test-topic-123"
MESSAGE = "vault-snapshot failed: the claude.ai door serves the last snapshot; see journalctl --user -u vault-snapshot"


class VaultSnapshotFailedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.curl_log = os.path.join(self.root, "curl.log")
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "curl"), "w") as f:
            f.write(f'#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a" >> "{self.curl_log}"; done\n')
        os.chmod(os.path.join(self.bin, "curl"), 0o755)
        self.topic_file = os.path.join(self.root, "ntfy-topic")

    def tearDown(self):
        self._tmp.cleanup()

    def run_notifier(self):
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], NTFY_TOPIC_FILE=self.topic_file)
        return subprocess.run(["bash", NOTIFIER], env=env, capture_output=True, text=True, timeout=30)

    def test_sends_the_fixed_message_to_the_topic(self):
        with open(self.topic_file, "w") as f:
            f.write(TOPIC + "\n")
        p = self.run_notifier()
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(self.curl_log) as f:
            args = f.read().splitlines()
        self.assertIn(f"https://ntfy.sh/{TOPIC}", args)
        self.assertIn(MESSAGE, args)
        self.assertIn("Title: vault snapshot", args)

    def test_missing_topic_file_sends_nothing_and_exits_zero(self):
        p = self.run_notifier()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(os.path.exists(self.curl_log))

    def test_service_names_the_failure_unit_in_onfailure(self):
        with open(SNAPSHOT_UNIT) as f:
            lines = [ln.strip() for ln in f]
        self.assertIn("OnFailure=vault-snapshot-failed.service", lines)


if __name__ == "__main__":
    unittest.main()
