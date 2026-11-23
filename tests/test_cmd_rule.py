"""A rules file the check cannot read is unknown and never a pass (#1048)."""

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


class TestUnreadableRules(unittest.TestCase):
    def test_a_malformed_rules_file_is_unknown_and_exits_non_zero(self):
        repo = temp_dir(self)
        (repo / "owner-rules.json").write_text("{not json")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(1, cmd_rule.command_rule(["check", "--repo", str(repo)]))
        self.assertIn("Unknown", out.getvalue())
        self.assertIn("owner-rules.json", out.getvalue())
        (repo / "owner-rules.json").write_text('{"id": "x"}')
        self.assertEqual(1, run(cmd_rule.command_rule, ["check", "--repo", str(repo)]))

    def test_add_never_overwrites_a_malformed_rules_file(self):
        repo = temp_dir(self)
        (repo / "owner-rules.json").write_text("{not json")
        self.assertEqual(1, run(cmd_rule.command_rule, ["add", "--repo", str(repo), "--id", "x", "--text", "t", "--paths", "*", "--forbid", "a"]))
        self.assertEqual("{not json", (repo / "owner-rules.json").read_text())


if __name__ == "__main__":
    unittest.main()
