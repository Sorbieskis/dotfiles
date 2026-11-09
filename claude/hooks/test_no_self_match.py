#!/usr/bin/env python3
"""Tests for no-self-match.py. Stdlib only: python3 -I test_no_self_match.py"""
import json
import os
import subprocess
import sys
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-self-match.py")


def bash(command):
    p = subprocess.run([sys.executable, "-I", HOOK], input=json.dumps({"tool_name": "Bash",
                       "tool_input": {"command": command}}), capture_output=True, text=True)
    return p.returncode, p.stdout


class NoSelfMatch(unittest.TestCase):
    def assertDenied(self, command):
        rc, out = bash(command)
        self.assertEqual(rc, 0)
        self.assertTrue(out, f"hook passed (no verdict) on: {command}")
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def assertPassed(self, command):
        rc, out = bash(command)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_incident_wait_loop_denied(self):
        self.assertDenied('until ! pgrep -f "[b]in/check"; do sleep 5; done')

    def test_while_wait_loop_denied(self):
        self.assertDenied("while pgrep -f '[x]yz' >/dev/null; do sleep 1; done")

    def test_wait_loop_full_flag_denied(self):
        self.assertDenied('until ! pgrep --full "[b]in/check"; do sleep 5; done')

    def test_loop_body_bracket_pgrep_passes(self):
        self.assertPassed("while read l; do pgrep -f '[x]yz'; done")

    def test_one_shot_bracket_pgrep_passes(self):
        self.assertPassed("pgrep -f '[b]in/check'")

    def test_self_match_pgrep_denied(self):
        self.assertDenied("pgrep -f bin/check")


if __name__ == "__main__":
    unittest.main()
