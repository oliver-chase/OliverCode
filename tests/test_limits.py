"""The size ceiling only warns: the count prints against one number and the exit code is always 0 (#879, #882)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, git_env, quiet, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_limits, context_budget, limits  # noqa: E402


def write(root, rel, lines):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"line {i}\n" for i in range(lines)), encoding="utf-8")


def commit(root, message):
    git(root, "add", "-A")
    subprocess.run(["git", "-C", str(root), "commit", "-qm", message], env=git_env(), check=True, capture_output=True)


class Repo(unittest.TestCase):
    """A repo of 120 counted lines with the ceiling at 120."""

    @classmethod
    def setUpClass(cls):
        """One repo per class; each test copies it."""
        cls._template = scratch_repo(Path(tempfile.mkdtemp(prefix="olivercode-limits-template-")).resolve() / "r", branch="main")
        cls.addClassCleanup(shutil.rmtree, cls._template.parent, ignore_errors=True)
        write(cls._template, "README.md", 20)
        write(cls._template, "docs/GUIDE.md", 100)
        (cls._template / limits.LIMITS_FILE).write_text(json.dumps({"limit": 120}) + "\n", encoding="utf-8")
        commit(cls._template, "Start (#1)")

    def setUp(self):
        self.root = temp_dir(self) / "r"
        shutil.copytree(self._template, self.root, symlinks=True)

    def run_cmd(self, *argv):
        return quiet(cmd_limits.command_limits, list(argv) + ["--root", str(self.root)])


class TestWarning(Repo):
    def test_a_count_at_the_ceiling_prints_both_numbers_and_exits_0(self):
        code, out = self.run_cmd("check")
        self.assertEqual(0, code)
        self.assertIn("120 tracked lines against a ceiling of 120", out)
        self.assertNotIn("warning", out)

    def test_a_large_growth_diff_warns_and_still_exits_0(self):
        write(self.root, "scripts/lib/big.py", 400)
        commit(self.root, "Grow a lot (#2)")
        code, out = self.run_cmd("check")
        self.assertEqual(0, code)
        self.assertIn("520 tracked lines against a ceiling of 120", out)
        self.assertIn("400 over. This is a warning and blocks nothing", out)

    def test_a_missing_or_broken_ceiling_file_still_exits_0(self):
        (self.root / limits.LIMITS_FILE).write_text("not json", encoding="utf-8")
        commit(self.root, "Break the file (#2)")
        code, out = self.run_cmd("check")
        self.assertEqual(0, code)
        self.assertIn("no readable ceiling", out)

    def test_tests_the_limits_file_and_the_changelog_do_not_count(self):
        write(self.root, "tests/test_big.py", 300)
        write(self.root, "CHANGELOG.md", 300)
        commit(self.root, "Evidence (#2)")
        self.assertIn("120 tracked lines", self.run_cmd("check")[1])

    def test_the_file_holds_the_ceilings_and_no_raise_history(self):
        data = json.loads((REPO_ROOT / limits.LIMITS_FILE).read_text(encoding="utf-8"))
        self.assertEqual({"_comment", "limit", "stateEntries", "stateBytes", "stateLogBytes"}, set(data))

    def test_bad_arguments_print_the_usage(self):
        for argv in (["nope"], [], ["check", "--root"], ["record", "--story", "3"]):
            self.assertEqual(1, quiet(cmd_limits.command_limits, argv)[0], argv)


class TestContextRatchet(unittest.TestCase):
    def setUp(self):
        self.home, self.claude = temp_dir(self), temp_dir(self)
        for target in (mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)}), mock.patch.object(context_budget, "claude_dir", lambda: self.claude)):
            target.start()
            self.addCleanup(target.stop)
        (self.claude / "CLAUDE.md").write_text("word " * 100)

    def test_the_first_reading_is_recorded_and_passes(self):
        ok, text = context_budget.report()
        self.assertTrue(ok)
        self.assertEqual(100, context_budget.landed())
        self.assertIn("100 words, within the recorded 100", text)

    def test_growth_past_the_landed_total_fails_and_a_trim_is_never_required(self):
        context_budget.report()
        (self.claude / "CLAUDE.md").write_text("word " * 120)
        ok, text = context_budget.report()
        self.assertFalse(ok)
        self.assertIn("a session loads 120 words, 20 past the recorded 100", text)
        (self.claude / "CLAUDE.md").write_text("word " * 100)
        self.assertTrue(context_budget.report()[0])

    def test_a_lower_reading_lowers_the_landed_total(self):
        context_budget.report()
        (self.claude / "CLAUDE.md").write_text("word " * 80)
        self.assertTrue(context_budget.report()[0])
        self.assertEqual(80, context_budget.landed())


if __name__ == "__main__":
    unittest.main()
