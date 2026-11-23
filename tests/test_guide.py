"""`olivercode guide` and the README command list both come from, or are checked against, the launcher's own command table."""

import contextlib
import io
import re
import unittest

from _support import REPO_ROOT, load_script, quiet

launcher = load_script("scripts/olivercode", "olivercode_launcher_guide")
from lib import cli, cmd_guide  # noqa: E402


def _names():
    return [re.match(r"olivercode (\S+)", c).group(1) for c, _ in cli.COMMANDS]


class TestGuide(unittest.TestCase):
    def _guide(self):
        return quiet(cmd_guide.command_guide, REPO_ROOT)

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
            # Each skill shows the phrases that load it, as cli.py's guide line promises.
            self.assertRegex(phrases, r"(?i)\b(trigger|use when)", name)

    def test_the_launcher_runs_guide_and_rejects_extra_arguments(self):
        import sys
        from unittest import mock
        with mock.patch.object(sys, "argv", ["olivercode", "guide"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(), 0)
        with mock.patch.object(sys, "argv", ["olivercode", "guide", "x"]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                launcher.main()


class TestHowWorkRunsMatches(unittest.TestCase):
    def test_the_guide_opens_with_how_work_runs_before_the_command_list(self):
        code, text = quiet(cmd_guide.command_guide, REPO_ROOT)
        self.assertEqual(code, 0)
        self.assertTrue(text.startswith("How work runs\n"))
        self.assertLess(text.index(cmd_guide.HOW_WORK_RUNS[-1]), text.index(cli.COMMANDS[0][0]))
        for sentence in cmd_guide.HOW_WORK_RUNS:
            self.assertIn(sentence, text)

    def test_the_readme_section_says_the_same_things_in_the_same_order(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        section = readme.split("## How work runs", 1)[1].split("\n## ", 1)[0]
        positions = [section.index(sentence) for sentence in cmd_guide.HOW_WORK_RUNS]
        self.assertEqual(positions, sorted(positions))


class TestReadmeListsEveryCommand(unittest.TestCase):
    def test_every_setup_launcher_bullet_names_a_real_command(self):
        setup = (REPO_ROOT / "docs" / "SETUP.md").read_text(encoding="utf-8")
        section = setup.split("## Launcher commands", 1)[1].split("\n## ", 1)[0]
        bullets = re.findall(r"(?m)^- `([a-z-]+)", section)
        self.assertTrue(bullets)
        for name in bullets:
            self.assertIn(name, _names(), f"docs/SETUP.md describes {name}, which olivercode --help does not list")
