"""The explicit quick validation entry point requires changed paths and preserves the full default suite."""

import os
import subprocess
import unittest

from _support import REPO_ROOT

VALIDATE = REPO_ROOT / "scripts" / "validate.sh"


def run_validate(*args):
    env = dict(os.environ, VALIDATE_QUEUE_SLOT="none")
    return subprocess.run(["bash", str(VALIDATE), *args], capture_output=True, text=True, env=env)


class TestQuickValidation(unittest.TestCase):
    def test_help_explains_quick_and_full_validation(self):
        done = run_validate("--help")
        self.assertEqual(0, done.returncode)
        self.assertIn("--quick FILE...", done.stdout)
        self.assertIn("full pre-merge check", done.stdout)
        self.assertIn("run the full suite before merge or landing", done.stdout)

    def test_quick_requires_at_least_one_changed_path(self):
        done = run_validate("--quick")
        self.assertEqual(2, done.returncode)
        self.assertIn("Pass at least one changed path", done.stderr)
        self.assertNotIn("=== validate:", done.stdout)

    def test_default_mode_remains_full_validation(self):
        source = VALIDATE.read_text(encoding="utf-8")
        self.assertIn("all|--tree)", source)
        self.assertIn("run_gates", source)


if __name__ == "__main__":
    unittest.main()
