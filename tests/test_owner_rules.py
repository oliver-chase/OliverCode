"""An owner rule is a check in the repo it governs, and a batch stops after one sample until the owner approves it (#628)."""

import contextlib
import io
import sys
import unittest

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_rule  # noqa: E402


def run(fn, argv):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(argv)


class TestOwnerRules(unittest.TestCase):
    def test_a_rule_fails_the_file_that_breaks_it_and_passes_once_fixed(self):
        repo = temp_dir(self)
        (repo / "posts.md").write_text("reuse after 14 days")
        self.assertEqual(0, run(cmd_rule.command_rule, ["add", "--repo", str(repo), "--id", "reuse", "--text", "no 14-day reuse", "--paths", "*.md", "--forbid", "14 days"]))
        self.assertEqual(1, run(cmd_rule.command_rule, ["check", "--repo", str(repo)]))
        (repo / "posts.md").write_text("reuse after 50 posts")
        self.assertEqual(0, run(cmd_rule.command_rule, ["check", "--repo", str(repo)]))

    def test_a_bad_pattern_is_refused_and_writes_nothing(self):
        repo = temp_dir(self)
        self.assertEqual(1, run(cmd_rule.command_rule, ["add", "--repo", str(repo), "--id", "x", "--text", "t", "--paths", "*", "--forbid", "("]))
        self.assertFalse((repo / "owner-rules.json").exists())
