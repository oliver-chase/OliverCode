"""Test the story format checker against saved bodies. No network and no gh.
Run: python3 -m unittest discover -p "test_*.py"   (from this folder)
"""
import re
import subprocess
import sys
import unittest
from pathlib import Path

import check_story_format as sf

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "references" / "story-template.md"


def body(name):
    return (HERE / "fixtures" / name).read_text(encoding="utf-8")


def parts(name, kind=None):
    return [p for p, _ in sf.check_body(body(name), kind)]


def parts_of(text, **flags):
    return [p for p, _ in sf.check_body(text, **flags)]


def with_blocker(text):
    return text.replace("Priority:", "Blocked by: none.\nPriority:", 1)


def with_fit(text):
    return text.replace("finds none.", "finds none. Second opinion agreed.\n\nFit: extends the backup job.", 1)


def sized(size, text=None):
    return (text or body("story-good.body")).replace("Size: S.", f"Size: {size}.")


class StorySize(unittest.TestCase):
    """#1437: filing refuses a story the drain cannot build or rarely lands."""

    def test_an_l_or_xl_story_is_refused_and_names_the_split(self):
        for size in ("L", "XL"):
            [(part, fix)] = sf.check_body(sized(size))
            self.assertEqual(f"Size {size} is too large for a Story", part)
            self.assertEqual("a Story is S or M at most, and the work becomes an Epic over S and M stories split by file group", fix)
            done = subprocess.run([sys.executable, str(HERE / "check_story_format.py"), "--offline"],
                                  input=with_fit(with_blocker(sized(size))), capture_output=True, text=True)
            self.assertEqual(1, done.returncode)
            self.assertIn(fix, done.stdout)

    def test_the_fields_line_wins_over_fields_a_scenario_quotes(self):
        quoting = body("story-good.body").replace("Given the nightly backup job ran and exited with an error",
                                                  "Given a body with `Size: L. Work type: Epic.`")
        self.assertEqual([], sf.check_body(quoting))
        self.assertEqual("Story", sf.kind_of(quoting))
        self.assertEqual(["Size L is too large for a Story"], parts_of(sized("L", quoting.replace("`Size: L.", "`Size: S."))))

    def test_an_epic_keeps_any_size(self):
        for size in ("L", "XL"):
            self.assertEqual([], sf.check_body(body("epic-good.body").replace("Size: M.", f"Size: {size}."), fit=True))

    def test_xs_s_and_m_stories_pass(self):
        for size in ("XS", "S", "M"):
            self.assertEqual([], sf.check_body(sized(size)))

    def test_a_missing_fit_line_or_second_opinion_result_is_named(self):
        good = with_fit(body("story-good.body"))
        self.assertEqual([], parts_of(good, fit=True))
        self.assertEqual(["Fit line"], parts_of(good.replace("Fit:", "Notes:"), fit=True))
        self.assertEqual(["Fit line"], parts_of(good.replace("Fit: extends the backup job.", "Fit:\n\nMore."), fit=True))
        self.assertEqual(["Second-opinion result"], parts_of(good.replace("opinion agreed", "opinion pending"), fit=True))
        for result in ("opinion differed and the owner picked one script", "opinion skipped: a one-line change"):
            self.assertEqual([], parts_of(good.replace("opinion agreed", result), fit=True))

    def test_more_than_five_files_is_refused(self):
        five = body("story-good.body").replace("Files area: skills/backlog/scripts/check_story_format.py",
                                               "Files area: a.py, b.py, c.py, d.py, e.py")
        self.assertEqual([], sf.check_body(five))
        [(part, fix)] = sf.check_body(five.replace("e.py", "e.py, f.py"))
        self.assertEqual("Files area names 6 files", part)
        self.assertEqual("split it into stories of five files or fewer, one fix each", fix)

    def test_only_paths_are_counted_as_files(self):
        def area(text, extra=""):
            return sf.check_body(body("story-good.body").replace(
                "Files area: skills/backlog/scripts/check_story_format.py", extra + "Files area: " + text))
        for five in ("a.py, b.py, c.py, d.py and e.py", "a.py (new), b.py, c.py, d.py, `e.py` (a new file).",
                     "a.py, b.py, c.py, Makefile and LICENSE", "a.py, b.py, c.py, d.py, and the new e.py"):
            self.assertEqual([], area(five), five)
        for six in ("a.py, b.py, c.py, d.py, e.py, Makefile", "a.py, b.py, c.py, d.py, Makefile and LICENSE",
                    "a.py b.py c.py d.py e.py f.py"):
            self.assertEqual(["Files area names 6 files"], [p for p, _ in area(six)], six)
        removes = "Removes tests: tests/test_a.py::test_x\n"
        self.assertEqual([], area("tests/test_a.py and tests/test_b.py (new)", removes))
        [(part, _)] = area("tests/test_a.py and Makefile", removes)
        self.assertEqual("Removes tests: story also changes Makefile", part)

    def test_a_line_count_target_in_a_scenario_is_refused_and_a_quoted_one_is_not(self):
        def given(text):
            return sf.check_body(body("story-good.body").replace("Then no message is sent", text))
        for target in ("Then it works in about 2,500 lines", "Then the module is under 300 lines", "Then it is 90 lines or fewer"):
            [(part, fix)] = given(target)
            self.assertTrue(part.startswith("Line target"), part)
            self.assertEqual("state the behavior to keep, one module per story, with no line target", fix)
        for allowed in ('Then it refuses "under 300 lines"', "Then it prints the last 40 lines", "Then a change of 20 changed lines or fewer passes"):
            self.assertEqual([], given(allowed))

    def test_an_m_story_that_shrinks_or_removes_code_is_refused(self):
        good = body("story-good.body")
        for title in ("Remove the dead helpers", "Cut the unused commands", "The scripts shrink", "Merge two modules", "Consolidate duplicate code"):
            [(_, fix)] = sf.check_body(sized("M"), title=title)
            self.assertEqual("file one S story per module", fix)
            self.assertEqual([], sf.check_body(good, title=title))
        asked = sized("M").replace("a failed nightly backup to message me the same day", "the backup scripts consolidated")
        self.assertEqual(["Size M for a story that shrinks or removes code"], parts_of(asked))
        for title in ("Unused and disabled features are removed", "Tests: wording-only tests are cut to their protection"):
            self.assertEqual(["Size M for a story that shrinks or removes code"], parts_of(sized("M"), title=title))
        merging = asked.replace("the backup scripts consolidated", "the backup job to merge its duplicate helpers")
        self.assertEqual(["Size M for a story that shrinks or removes code"], parts_of(merging))

    def test_every_form_of_a_shrink_is_refused(self):
        refused = ["Size M for a story that shrinks or removes code"]
        for ask in ("the dead code to be removed", "the drain module to shrink", "OliverCode to remove the unused commands",
                    "the runner to consolidate the duplicate helpers into one", "the unused scripts to be fully removed from the repo",
                    "the drain module should shrink"):
            asked = sized("M").replace("a failed nightly backup to message me the same day", ask)
            self.assertEqual(refused, parts_of(asked), ask)
        for title in ("Removing the dead helpers", "Cutting the unused commands", "Shrinking the drain module",
                      "Merging the duplicate helpers", "Consolidating the test helpers", "Removal of dead code",
                      "Drain: removing the unused functions"):
            self.assertEqual(refused, parts_of(sized("M"), title=title), title)

    def test_an_m_story_that_only_mentions_a_removal_passes(self):
        for title in ("The drain removes a worktree before its hooks run", "A merged story is closed the same day",
                      "Remove the stale lock before the hooks run", "The landing refuses a removed test"):
            self.assertEqual([], sf.check_body(sized("M"), title=title))
        for ask in ("the drain to run a worktree's hooks before it removes the worktree",
                    "the drain to remove a worktree only after its hooks run",
                    "the drain to remove the test worktrees", "the script to merge into main"):
            self.assertEqual([], sf.check_body(sized("M").replace("a failed nightly backup to message me the same day", ask)))
        outcome = sized("M").replace("so that", "so that dead code is removed and")
        self.assertEqual([], sf.check_body(outcome))

    def test_the_command_reads_the_title(self):
        done = subprocess.run([sys.executable, str(HERE / "check_story_format.py"), "--offline", "--title", "Remove the dead code"],
                              input=with_fit(with_blocker(sized("M"))), capture_output=True, text=True)
        self.assertEqual(1, done.returncode)
        self.assertIn("file one S story per module", done.stdout)

    def test_a_story_that_removes_tests_changes_only_tests(self):
        line = "Removes tests: tests/test_a.py::test_x\nFiles area: tests/test_a.py, skills/x/scripts/test_b.py"
        alone = body("story-good.body").replace("Files area: skills/backlog/scripts/check_story_format.py", line)
        self.assertEqual([], sf.check_body(alone))
        [(part, fix)] = sf.check_body(alone.replace("test_b.py", "test_b.py, scripts/lib/a.py"))
        self.assertIn("scripts/lib/a.py", part)
        self.assertIn("remove the tests in their own story", fix)

    def test_a_removes_tests_entry_without_a_file_is_refused_with_the_form(self):
        alone = body("story-good.body").replace("Files area: skills/backlog/scripts/check_story_format.py",
                                                "Removes tests: test_a_thing\nFiles area: tests/test_x.py")
        [(part, fix)] = sf.check_body(alone)
        self.assertEqual('Removes tests entry "test_a_thing" has no file', part)
        self.assertEqual("write it as FILE.py::test_a_thing, or FILE.py::Class::test_a_thing", fix)

    def test_entries_in_the_land_gates_form_pass_the_removes_check(self):
        line = "Removes tests: tests/test_x.py::Thing::test_a, tests/test_x.py::test_b\nFiles area: tests/test_x.py"
        alone = body("story-good.body").replace("Files area: skills/backlog/scripts/check_story_format.py", line)
        self.assertEqual([], sf.check_body(alone))

    def test_the_removes_check_splits_entries_as_the_land_gate_does(self):
        from lib import intake
        self.assertIs(sf.intake, intake)
        line = "**Removes tests:** `tests/test_x.py::test_a`, bare_name, (tests/test_x.py::test_b)\nFiles area: tests/test_x.py"
        alone = body("story-good.body").replace("Files area: skills/backlog/scripts/check_story_format.py", line)
        self.assertEqual(["bare_name"], [p.split('"')[1] for p, _ in sf.check_body(alone) if p.startswith("Removes tests entry")])

    def test_the_template_story_passes_every_check_the_command_runs(self):
        example = re.findall(r"````markdown\n(.*?)````", TEMPLATE.read_text(encoding="utf-8"), re.S)[0]
        self.assertEqual([], sf.check_body(example, blocker=True, line_numbers=True, files=True, fit=True))


class StoryFormat(unittest.TestCase):
    def test_a_files_area_that_names_a_folder_is_rejected_and_a_file_is_not(self):
        """#1077: a folder in the Files area holds every other story back, so filing names it; a file with no extension passes."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts" / "lib").mkdir(parents=True)
            (root / "scripts" / "olivercode").write_text("#!/bin/sh\n")
            base = re.findall(r"````markdown\n(.*?)````", TEMPLATE.read_text(encoding="utf-8"), re.S)[0]
            base = re.sub(r"\n*Files area:.*\n", "\n", base)
            folder = base + "\nFiles area: scripts/lib, scripts/olivercode\n"
            slash = base + "\nFiles area: docs/\n"
            files = base + "\nFiles area: scripts/olivercode, scripts/lib/intake.py\n"
            self.assertIn("Files area names the folder scripts/lib", [p for p, _ in sf.check_body(folder, root=root)])
            self.assertIn("Files area names the folder docs/", [p for p, _ in sf.check_body(slash, root=root)])
            self.assertEqual([], sf.check_body(files, root=root))

    def test_the_template_examples_pass(self):
        examples = re.findall(r"````markdown\n(.*?)````", TEMPLATE.read_text(encoding="utf-8"), re.S)
        self.assertTrue(examples)
        for example in examples:
            self.assertEqual([], sf.check_body(example, blocker=True, line_numbers=True))
        skill = (HERE.parent / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotRegex(skill, r"(?i)pull request|\bweekly\b|ask where a config|Which dimension should I check")

    def test_a_story_without_gherkin_is_rejected_with_a_fix(self):
        problems = sf.check_body(body("story-no-gherkin.body"))
        self.assertEqual(["Gherkin Feature"], [p for p, _ in problems])
        self.assertIn("Feature:", problems[0][1])

    def test_angle_brackets_inside_backticks_are_not_a_placeholder(self):
        good = body("story-good.body") + "\nRun `size.sh <target>` before and after.\n"
        self.assertEqual([], [p for p, _ in sf.check_body(good) if "placeholder" in p])

    def test_a_story_without_an_existing_coverage_line_is_rejected_with_a_fix(self):
        text = body("story-good.body").replace("Existing coverage checked:", "Searched:")
        problems = sf.check_body(text)
        self.assertEqual(["Existing coverage checked line"], [p for p, _ in problems])
        self.assertIn("Existing coverage checked:", problems[0][1])

    def test_a_story_that_names_its_search_passes_that_part(self):
        self.assertEqual([], parts("story-good.body"))

    def test_an_epic_and_an_old_story_scan_need_no_coverage_line(self):
        self.assertNotIn("Existing coverage checked line", parts("epic-good.body"))
        text = body("story-good.body").replace("Existing coverage checked:", "Searched:")
        self.assertEqual([], sf.check_body(text, coverage=False))

    def test_a_story_without_an_epic_link_is_rejected(self):
        self.assertEqual(["Epic link"], parts("story-no-epic.body"))

    def test_an_epic_needs_no_epic_link(self):
        self.assertNotIn("Epic link", parts("epic-good.body"))

    def test_a_missing_story_sentence_is_rejected(self):
        self.assertEqual(["User story sentence"], parts("story-no-sentence.body"))

    def test_invalid_priority_and_size_are_rejected(self):
        found = parts("story-bad-values.body")
        self.assertEqual(2, len(found))
        self.assertTrue(found[0].startswith("Priority") and found[1].startswith("Size"))

    def test_a_scenario_missing_then_is_rejected(self):
        self.assertIn("lacks Then", parts("story-incomplete-scenario.body")[0])

    def test_steps_out_of_order_are_rejected(self):
        swapped = body("story-good.body").replace("Given the nightly backup job ran and exited with an error",
                                                 "When X").replace("When the job finishes", "Given Y", 1)
        self.assertTrue(any("out of order" in p for p, _ in sf.check_body(swapped)))

    def test_work_type_must_match_the_kind(self):
        self.assertTrue(any("checked as a story" in p for p in parts("epic-good.body", "story")))

    def test_an_unfilled_placeholder_is_rejected(self):
        found = [p for p, _ in sf.check_body(body("story-good.body") + "\nSee <the plan>")]
        self.assertTrue(any("placeholder" in p for p in found))

    def test_a_story_with_no_blocker_line_fails_and_prints_the_fix(self):
        """A story is one session of work: it names what must land first, or says none."""
        self.assertEqual(["Blocked by line"], [p for p, _ in sf.check_body(body("story-good.body"), blocker=True)])
        self.assertIn("Blocked by: none.", sf.check_body(body("story-good.body"), blocker=True)[0][1])
        completed = subprocess.run([sys.executable, str(HERE / "check_story_format.py"),
                                    str(HERE / "fixtures" / "story-good.body"), "--offline"],
                                   capture_output=True, text=True)
        self.assertEqual(1, completed.returncode)
        self.assertIn("MISSING Blocked by line. Fix:", completed.stdout)

    def test_a_blocker_naming_a_story_or_none_passes(self):
        good = with_blocker(body("story-good.body"))
        self.assertEqual([], sf.check_body(good.replace("Blocked by: none.", "Blocked by: #1067"), blocker=True))
        self.assertEqual([], sf.check_body(good.replace("Blocked by: none.", "Blocked by: o/r#1067"), blocker=True))

    def test_a_body_that_names_a_line_number_is_flagged(self):
        flagged = body("story-good.body") + "\nThe call at scripts/hooks/status_hint.py:84 files the story.\n"
        self.assertTrue(any(p.startswith("Line number") for p in parts_of(flagged, line_numbers=True)))
        prose = body("story-good.body") + "\nSee line 84 of the hook.\n"
        self.assertTrue(any(p.startswith("Line number") for p in parts_of(prose, line_numbers=True)))

    def test_the_library_default_leaves_line_numbers_unchecked_for_intake_scans(self):
        """Intake's scan of older stories and the generated bodies use the library default, so an old body naming a line is not queued."""
        old = body("story-good.body") + "\nSee line 84 of the hook.\n"
        self.assertEqual([], [p for p, _ in sf.check_body(old) if p.startswith("Line number")])

    def test_a_line_number_inside_a_pasted_code_block_is_not_flagged(self):
        pasted = body("story-good.body") + "\nPasted error:\n\n```\nFile \"x.py\", line 84, in run\n```\n"
        self.assertEqual([], [p for p in parts_of(pasted, line_numbers=True) if p.startswith("Line number")])

    def test_the_closed_search_for_rejected_ideas_is_in_the_skill(self):
        skill = (HERE.parent / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('is:closed reason:\\"not planned\\"', skill)
        self.assertRegex(skill, r"(?i)file nothing until the owner decides")

    def test_a_story_without_a_files_area_is_rejected_and_an_epic_needs_none(self):
        """#1274: dispatch needs the files a story changes, so the check names the missing line; an epic changes no files."""
        text = re.sub(r"^Files area:.*\n", "", body("story-good.body"), flags=re.M)
        self.assertEqual([], parts_of(text))
        self.assertEqual(["Files area"], parts_of(text, files=True))
        self.assertEqual([], parts_of(body("epic-good.body"), files=True))

    def test_an_open_story_on_the_same_file_is_listed_by_number_and_title(self):
        """#1274: the new story is listed with the open story that names scripts/lib/cmd_status.py, and the fix offers both ways out."""
        text = body("story-good.body").replace("skills/backlog/scripts/check_story_format.py", "scripts/lib/cmd_status.py")
        stories = {412: {"title": "Show the status of a run", "body": "Files area: scripts/lib/cmd_status.py, docs/a.md"}}
        [(part, fix)] = sf.overlap_problems(text, stories)
        self.assertEqual('Open story #412 "Show the status of a run" touches the same files', part)
        self.assertIn("add the new scenarios to #412", fix)
        self.assertIn("Existing coverage checked:", fix)

    def test_naming_the_overlapping_story_in_existing_coverage_passes_that_overlap(self):
        text = body("story-good.body").replace(
            "Existing coverage checked: a search of the repo for this behavior finds none.",
            "Existing coverage checked: #412 shows the status; this adds the exit code, so it is separate.").replace(
            "Files area: skills/backlog/scripts/check_story_format.py", "Files area: scripts/lib/cmd_status.py")
        stories = {412: {"title": "Show the status", "body": "Files area: scripts/lib/cmd_status.py"}}
        self.assertEqual([], sf.overlap_problems(text, stories))

    def test_a_folder_holding_a_file_overlaps_and_an_unrelated_file_does_not(self):
        text = "Files area: scripts/lib/cmd_status.py\n"
        self.assertEqual(1, len(sf.overlap_problems(text, {5: {"title": "Folder", "body": "Files area: scripts/lib/"}})))
        self.assertEqual([], sf.overlap_problems(text, {6: {"title": "Other", "body": "Files area: scripts/lib/cmd_groom.py"}}))
        self.assertEqual([], sf.overlap_problems(text, {7: {"title": "Word", "body": "Files area: new, cmd"}}))

    def test_open_stories_reads_each_issue_through_intake_and_refuses_a_failed_read(self):
        from unittest import mock
        from lib import backlog_setup, intake
        issues = {7: {"number": 7, "title": "Word", "body": "Files area: a.py", "labels": []},
                  9: {"number": 9, "title": "Other", "body": "", "labels": []}}
        with mock.patch.object(backlog_setup, "origin_owner_name", return_value=("acme", "widget")), \
                mock.patch.object(intake, "open_stories", return_value=issues) as read:
            self.assertEqual({7: "Word", 9: "Other"}, {n: o["title"] for n, o in sf.open_stories(".").items()})
            read.assert_called_once_with("acme/widget")
        with mock.patch.object(backlog_setup, "origin_owner_name", return_value=("acme", "widget")), \
                mock.patch.object(intake, "open_stories", side_effect=RuntimeError("GitHub is held")):
            with self.assertRaises(RuntimeError):
                sf.open_stories(".")

    def test_an_unreadable_issue_list_is_a_problem_and_the_offline_flag_skips_it(self):
        import contextlib
        import io
        from unittest import mock
        path = str(HERE / "fixtures" / "story-good.body")
        with mock.patch.object(sf, "open_stories", side_effect=RuntimeError("no network")) as read:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(1, sf.main([path]))
            self.assertIn("MISSING Overlap check.", out.getvalue())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                sf.main([path, "--offline"])
            self.assertEqual(1, read.call_count)
            self.assertNotIn("Overlap check", out.getvalue())

    def test_the_command_reads_stdin_and_sets_the_exit_status(self):
        script = str(HERE / "check_story_format.py")
        good = subprocess.run([sys.executable, script, "--offline"], input=with_fit(with_blocker(body("story-good.body"))),
                              capture_output=True, text=True)
        bad = subprocess.run([sys.executable, script, str(HERE / "fixtures" / "story-no-gherkin.body"), "--offline"],
                             capture_output=True, text=True)
        self.assertEqual(0, good.returncode)
        self.assertEqual(1, bad.returncode)
        self.assertIn("MISSING Gherkin Feature. Fix:", bad.stdout)
