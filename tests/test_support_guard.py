"""The suite starts with guards for gh, claude and osascript ahead on PATH (#1271)."""

import subprocess
import unittest

import _support


class TestExternalToolGuard(unittest.TestCase):
    def test_gh_without_a_fake_exits_with_the_guard_status(self):
        result = subprocess.run(["gh", "api", "rate_limit"], capture_output=True, text=True)
        self.assertEqual(_support.GUARD_STATUS, result.returncode)
        self.assertIn("unexpected call to gh api rate_limit", result.stderr)

    def test_claude_and_osascript_are_guarded_too(self):
        for tool in ("claude", "osascript"):
            result = subprocess.run([tool, "-e", "x"], capture_output=True, text=True)
            self.assertEqual(_support.GUARD_STATUS, result.returncode, tool)
            self.assertIn(f"unexpected call to {tool}", result.stderr)


if __name__ == "__main__":
    unittest.main()
