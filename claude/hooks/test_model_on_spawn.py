#!/usr/bin/env python3
"""Tests for model-on-spawn.py. Stdlib only: python3 -I test_model_on_spawn.py"""
import json
import os
import subprocess
import sys
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model-on-spawn.py")


def run(stdin):
    p = subprocess.run([sys.executable, "-I", HOOK], input=stdin, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def spawn(tool="Agent", **ti):
    return run(json.dumps({"tool_name": tool, "tool_input": ti}))


class ModelOnSpawn(unittest.TestCase):
    def assertAllowed(self, r):
        self.assertEqual(r[0], 0)
        self.assertEqual(r[1], "")

    def assertDenied(self, r):
        self.assertEqual(r[0], 0)
        out = json.loads(r[1])["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        for m in ("sonnet", "opus", "haiku"):
            self.assertIn(m, out["permissionDecisionReason"])

    def test_no_model_denied(self):
        self.assertDenied(spawn(prompt="x"))

    def test_task_alias_denied(self):
        self.assertDenied(spawn(tool="Task", prompt="x"))

    def test_model_allowed(self):
        self.assertAllowed(spawn(model="sonnet", prompt="x"))

    def test_fork_exempt(self):
        self.assertAllowed(spawn(subagent_type="fork", prompt="x"))

    def test_non_agent_tool_allowed(self):
        self.assertAllowed(run(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})))

    def test_empty_and_null_model_denied(self):
        self.assertDenied(spawn(model="", prompt="x"))
        self.assertDenied(spawn(model=None, prompt="x"))

    def test_missing_tool_input_denied(self):
        self.assertDenied(run(json.dumps({"tool_name": "Agent"})))

    def test_malformed_stdin_exits_0(self):
        self.assertAllowed(run("not json {"))
        self.assertAllowed(run(""))

    def test_non_dict_stdin_exits_0_silently(self):
        for raw in ("[]", "null", '"x"', "3"):
            self.assertAllowed(run(raw))
        r = run(json.dumps({"tool_name": "Agent", "tool_input": "str"}))
        self.assertAllowed(r)
        self.assertEqual(r[2], "")


if __name__ == "__main__":
    unittest.main()
