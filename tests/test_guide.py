"""`olivercode guide` and the README command list both come from, or are checked against, the launcher's own command table."""

import contextlib
import io
import re
import unittest

from _support import REPO_ROOT, load_script

launcher = load_script("scripts/olivercode", "olivercode_launcher_guide")
from lib import cli, cmd_guide  # noqa: E402


def _names():
    return [re.match(r"olivercode (\S+)", c).group(1) for c, _ in cli.COMMANDS]


class TestGuide(unittest.TestCase):
    def _guide(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cmd_guide.command_guide(REPO_ROOT)
        return code, out.getvalue()

    def test_prints_every_command_and_every_skill_with_its_phrases(self):
        code, text = self._guide()
        self.assertEqual(code, 0)
        for cmd, _ in cli.COMMANDS:
            self.assertIn(cmd, text)
        rows = cmd_guide.skill_triggers(REPO_ROOT)
        self.assertGreaterEqual(len(rows), 6)
        for name, phrases in rows:
            self.assertIn(name, text)
            self.assertTrue(phrases)
            self.assertIn(phrases, text)

    def test_help_points_to_the_guide(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.print_usage()
        self.assertEqual(out.getvalue().rstrip().splitlines()[-1], "New here? Run: olivercode guide")

    def test_the_launcher_runs_guide_and_rejects_extra_arguments(self):
        import sys
        from unittest import mock
        with mock.patch.object(sys, "argv", ["olivercode", "guide"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(), 0)
        with mock.patch.object(sys, "argv", ["olivercode", "guide", "x"]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                launcher.main()


class TestReadmeListsEveryCommand(unittest.TestCase):
    def test_readme_and_setup_name_every_command_and_no_other(self):
        names = set(_names())
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        listed = set(re.findall(r"^\| `olivercode (\S+)` \|", readme, re.M))
        self.assertEqual(listed, names)
        setup = (REPO_ROOT / "docs" / "SETUP.md").read_text(encoding="utf-8")
        for n in names:
            self.assertRegex(setup, rf"(?m)^- `{re.escape(n)}[ `]", f"docs/SETUP.md has no bullet for {n}")

    def test_readme_skill_table_names_every_skill(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for name, _ in cmd_guide.skill_triggers(REPO_ROOT):
            self.assertIn(f"| `{name}` |", readme)


if __name__ == "__main__":
    unittest.main()
