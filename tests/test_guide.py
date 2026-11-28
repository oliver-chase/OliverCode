"""`olivercode guide` prints the approved copy from the archive, with the commands today's launcher has (#1333)."""

import contextlib
import io
import re
import unittest
from _support import REPO_ROOT, load_script, quiet

launcher = load_script("scripts/olivercode", "olivercode_launcher_guide")
from lib import cli, cmd_guide, cmd_install  # noqa: E402

# The fleet commands #1286 removes. The guide names none of them.
FLEET = ("discover", "policy")
# The headings the approved copy prints, in order.
HEADINGS = ("How work runs", "How the work is split", "Getting started", "How it works", "An example", "Using it well",
            "What to use when", "Commands", "Your projects, your rules")


def _names():
    return [re.match(r"olivercode (\S+)", c).group(1) for c, _ in cli.COMMANDS]


class TestGuide(unittest.TestCase):
    def _guide(self):
        return quiet(cmd_guide.command_guide, REPO_ROOT)

    def test_prints_every_command_and_every_skill_with_its_phrases(self):
        code, text = self._guide()
        self.assertEqual(code, 0)
        for name in set(_names()) - set(FLEET):
            self.assertIn(name, text)
        _, skills = quiet(cmd_guide.command_guide, REPO_ROOT, "skills")
        rows = cmd_guide.skill_triggers(REPO_ROOT)
        self.assertGreaterEqual(len(rows), 6)
        for name, phrases in rows:
            self.assertIn(name, skills)
            self.assertTrue(phrases)
            self.assertIn(phrases, skills)
            self.assertRegex(phrases, r"(?i)\b(trigger|use when)", name)

    def test_the_guide_prints_every_how_work_runs_sentence_and_habit(self):
        _, text = self._guide()
        for line in [*cmd_guide.HOW_WORK_RUNS, *cmd_guide.USING_IT_WELL]:
            self.assertIn(line, text)

    def test_the_launcher_runs_guide_and_rejects_extra_arguments(self):
        import sys
        from unittest import mock
        with mock.patch.object(sys, "argv", ["olivercode", "guide"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(), 0)
        with mock.patch.object(sys, "argv", ["olivercode", "guide", "x", "y"]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                launcher.main()


class TestApprovedCopy(unittest.TestCase):
    def test_the_headings_print_in_the_archived_order(self):
        _, text = quiet(cmd_guide.command_guide, REPO_ROOT)
        positions = [text.index(f"\n{heading}\n") for heading in HEADINGS]
        self.assertEqual(positions, sorted(positions))

    def test_every_command_the_guide_names_exists_in_the_launcher(self):
        _, text = quiet(cmd_guide.command_guide, REPO_ROOT)
        named = set(re.findall(r"olivercode ([a-z][a-z-]*)", text))
        self.assertTrue(named)
        self.assertEqual(set(), named - set(_names()))

    def test_the_guide_names_no_fleet_command(self):
        _, text = quiet(cmd_guide.command_guide, REPO_ROOT)
        for name in FLEET:
            self.assertNotRegex(text, rf"\b{name}\b", name)
        for gone in ("status publish", "candidates", "olivercode story", "status page", "guide city"):  # retired commands and topics the guide must not name
            self.assertNotIn(gone, text)


class TestCommandsByJob(unittest.TestCase):
    def test_the_command_sets_cover_every_launcher_command_except_the_fleet_ones(self):
        # A subcommand line such as `board groom` is listed under its launcher name, `board`.
        listed = [c for _, cmds in cmd_guide.COMMAND_SETS for c in cmds.split(" · ")]
        self.assertEqual(len(listed), len(set(listed)), "a command line appears twice")
        self.assertEqual({c.split()[0] for c in listed}, set(_names()) - set(FLEET))

    def test_the_commands_print_under_their_job_titles(self):
        _, text = quiet(cmd_guide.command_guide, REPO_ROOT)
        for title, cmds in cmd_guide.COMMAND_SETS:
            self.assertIn(f"  {title}\n    {cmds}\n", text)

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


class TestTopics(unittest.TestCase):
    def test_the_design_topic_names_the_design_file_and_the_relink_command(self):
        _, out = quiet(cmd_guide.command_guide, REPO_ROOT, "design")
        line = next(l for l in out.splitlines() if "designFile" in l)
        self.assertIn("olivercode install", line)
        self.assertIn("~/.claude/DESIGN.md", line)


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

    def test_the_steps_teach_watch_first_then_status_and_say_both_cost_no_model_turn(self):
        steps = cmd_guide.status_steps(REPO_ROOT)
        watch = next(i for i, s in enumerate(steps) if "olivercode watch REPO" in s)
        status = next(i for i, s in enumerate(steps) if "olivercode status`" in s)
        self.assertLess(watch, status)
        self.assertEqual(0, watch)
        self.assertIn("Watch and status cost no model turn", steps[-1])

    def test_install_says_once_that_no_figure_is_billed_and_watch_names_what_it_prints(self):
        closing = cmd_install.closing_lines(REPO_ROOT)
        billing = "Builds run on the signed-in Claude subscription, and watch and status show tokens with an API-price equivalent that is not billed."
        self.assertEqual(1, closing.count(billing))
        self.assertIn("with its time, tokens and API-price equivalent.", cmd_guide.status_steps(REPO_ROOT)[0])

    def test_install_closes_with_the_same_steps_and_the_adoption_pointer(self):
        closing = cmd_install.closing_lines(REPO_ROOT)
        for step in cmd_guide.status_steps(REPO_ROOT):
            self.assertIn(step, closing)
        self.assertIn("olivercode-adoption", closing)
        self.assertNotIn("Run `olivercode guide` to see how work runs.", closing)

    def test_the_introduction_and_the_guide_say_the_thread_steers_a_run_and_status_is_free(self):
        line = "The thread that started a run is the one to steer it."
        free = "`olivercode status` answers status from any thread or terminal at no token cost."
        self.assertIn(line, cmd_install.INTRODUCTION.replace("\n  ", " "))
        self.assertIn(free, cmd_install.INTRODUCTION.replace("\n  ", " "))
        _, text = quiet(cmd_guide.command_guide, REPO_ROOT)
        self.assertIn(line, text)
        self.assertIn(free, text)


class TestRetiredCity(unittest.TestCase):
    """#1561: the guide has no City topic, and `guide city` is an unknown name."""

    def test_guide_city_exits_one(self):
        code, _ = quiet(cmd_guide.command_guide, REPO_ROOT, "city")
        self.assertEqual(1, code)


class TestLauncherSetupDoc(unittest.TestCase):
    def test_every_setup_launcher_bullet_names_a_real_command(self):
        setup = (REPO_ROOT / "docs" / "SETUP.md").read_text(encoding="utf-8")
        section = setup.split("## Launcher commands", 1)[1].split("\n## ", 1)[0]
        bullets = re.findall(r"(?m)^- `([a-z-]+)", section)
        self.assertTrue(bullets)
        for name in bullets:
            self.assertIn(name, _names(), f"docs/SETUP.md describes {name}, which olivercode --help does not list")


class TestBareUsage(unittest.TestCase):
    """Bare `olivercode` prints each command's first sentence; the guide keeps the rest (#1544)."""

    def test_every_row_stops_at_its_first_sentence(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.print_usage()
        rows = [line for line in out.getvalue().splitlines() if line.startswith("  ")]
        self.assertEqual(len(rows), len(cli.COMMANDS))
        for row in rows:
            self.assertNotRegex(row, r"\. [A-Z]", row)

    def test_the_guide_keeps_the_full_description(self):
        promote = next(desc for cmd, desc in cli.COMMANDS if cmd == "olivercode promote")
        self.assertGreater(promote.count(". "), 0)
        self.assertEqual(cli.first_sentence(promote), promote.split(". ")[0] + ".")
        self.assertIn(promote, cmd_guide.explain(REPO_ROOT, "promote")[0])
