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
        for name in _names():
            self.assertIn(name, text)
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
        with mock.patch.object(sys, "argv", ["olivercode", "guide", "x", "y"]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                launcher.main()


class TestHowWorkRunsMatches(unittest.TestCase):
    def test_the_guide_opens_with_how_work_runs_before_the_command_list(self):
        code, text = quiet(cmd_guide.command_guide, REPO_ROOT)
        self.assertEqual(code, 0)
        self.assertTrue(text.startswith("How work runs\n"))
        self.assertLess(text.index(cmd_guide.HOW_WORK_RUNS[-1]), text.index(cmd_guide.GROUPS[0][0]))
        for sentence in cmd_guide.HOW_WORK_RUNS:
            self.assertIn(sentence, text)

    def test_the_readme_section_says_the_same_things_in_the_same_order(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        section = readme.split("## How work runs", 1)[1].split("\n## ", 1)[0]
        positions = [section.index(sentence) for sentence in cmd_guide.HOW_WORK_RUNS]
        self.assertEqual(positions, sorted(positions))


def _readme_rows():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    table = readme.split("| Job | Commands |", 1)[1].split("\n\n", 1)[0]
    return [(m.group(1), re.findall(r"`olivercode ([a-z -]+?)`", m.group(2))) for m in re.finditer(r"(?m)^\| ([^|]+?) \| (.+) \|$", table) if m.group(1) != "---"]


class TestGuideByJob(unittest.TestCase):
    def test_the_groups_match_the_readme_table_and_cover_every_command(self):
        self.assertEqual(_readme_rows(), [(job, [c for c, _ in cmds]) for job, cmds in cmd_guide.GROUPS])
        listed = {c.split()[0] for _, cmds in cmd_guide.GROUPS for c, _ in cmds}
        self.assertEqual(set(_names()), listed)

    def test_the_guide_prints_how_work_runs_then_first_steps_then_the_commands_by_job(self):
        _, text = quiet(cmd_guide.command_guide, REPO_ROOT)
        order = [text.index(t) for t in ("How work runs", "First steps, in order", "Install and update", "Orientation", "Skills:")]
        self.assertEqual(order, sorted(order))
        for _, cmds in cmd_guide.GROUPS:
            for cmd, line in cmds:
                self.assertIn(f"{cmd}", text)
                self.assertIn(line, text)
                self.assertNotIn("\n", line)

    def test_a_name_says_what_a_command_gate_guard_job_or_skill_does_and_where_it_lives(self):
        for name, wants in (("land", ("Command:", "scripts/lib/cmd_land.py")), ("pii", ("Gate: PII", "docs/GATES.md")),
                            ("commit_guard", ("Guard:", "scripts/hooks/commit_guard.py")), ("board-sweep", ("Scheduled job:", "board sync --schedule")),
                            ("audit", ("Skill: audit", "skills/audit/SKILL.md")), ("board groom", ("Command: olivercode board", "cmd_board.py"))):
            code, text = quiet(cmd_guide.command_guide, REPO_ROOT, name)
            self.assertEqual(0, code, name)
            for want in wants:
                self.assertIn(want, text, name)

    def test_an_unknown_name_exits_one_and_points_at_the_guide(self):
        code, text = quiet(cmd_guide.command_guide, REPO_ROOT, "nothing-here")
        self.assertEqual(1, code)
        self.assertIn("olivercode guide", text)


class TestReadmeListsEveryCommand(unittest.TestCase):
    def test_every_setup_launcher_bullet_names_a_real_command(self):
        setup = (REPO_ROOT / "docs" / "SETUP.md").read_text(encoding="utf-8")
        section = setup.split("## Launcher commands", 1)[1].split("\n## ", 1)[0]
        bullets = re.findall(r"(?m)^- `([a-z-]+)", section)
        self.assertTrue(bullets)
        for name in bullets:
            self.assertIn(name, _names(), f"docs/SETUP.md describes {name}, which olivercode --help does not list")


class TestUsingItWell(unittest.TestCase):
    def test_the_guide_lists_each_habit_in_a_section_between_the_first_steps_and_the_commands(self):
        """#991: the guide and the README hold the same six habits, one line each, after the first steps and before the commands."""
        _, text = quiet(cmd_guide.command_guide, REPO_ROOT)
        order = [text.index(t) for t in ("First steps, in order", "Using it well", cmd_guide.USING_IT_WELL[0], "Commands, by the job")]
        self.assertEqual(order, sorted(order))
        for habit in cmd_guide.USING_IT_WELL:
            self.assertIn(habit, text)
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for habit in cmd_guide.USING_IT_WELL:
            self.assertIn(habit.rstrip("."), readme)


class TestStatusSteps(unittest.TestCase):
    """#1059: install, the adoption skill and `olivercode guide status` print one set of steps to follow a run from a terminal."""

    def test_guide_status_prints_the_steps_with_this_checkout_path(self):
        code, text = quiet(cmd_guide.command_guide, REPO_ROOT, "status")
        self.assertEqual(0, code)
        self.assertIn("Command: olivercode status", text)
        for step in cmd_guide.status_steps(REPO_ROOT):
            self.assertIn(step, text)
        self.assertIn(f"olivercode status --root {REPO_ROOT}", text)
        self.assertIn("Terminal", text)
        self.assertIn("no model turn", text)

    def test_install_closes_with_the_same_steps_and_the_adoption_pointer(self):
        from lib import cmd_install
        closing = cmd_install.closing_lines(REPO_ROOT)
        for step in cmd_guide.status_steps(REPO_ROOT):
            self.assertIn(step, closing)
        self.assertIn("olivercode-adoption", closing)
        self.assertNotIn("Run `olivercode guide` to see how work runs.", closing)

    def test_the_introduction_and_the_guide_say_the_thread_steers_a_run_and_status_is_free(self):
        from lib import cmd_install
        line = "The thread that started a run is the one to steer it."
        free = "`olivercode status` answers status from any thread or terminal at no token cost."
        self.assertIn(line, cmd_install.INTRODUCTION.replace("\n  ", " "))
        self.assertIn(free, cmd_install.INTRODUCTION.replace("\n  ", " "))
        _, text = quiet(cmd_guide.command_guide, REPO_ROOT)
        self.assertIn(line, text)
        self.assertIn(free, text)
