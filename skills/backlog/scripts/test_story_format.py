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


class StoryFormat(unittest.TestCase):
    def test_a_files_area_that_names_a_folder_is_rejected_and_a_file_is_not(self):
        """#1077: a folder in the Files area holds every other story back, so filing names it; a file with no extension passes."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts" / "lib").mkdir(parents=True)
            (root / "scripts" / "olivercode").write_text("#!/bin/sh\n")
            base = re.findall(r"````markdown\n(.*?)````", TEMPLATE.read_text(encoding="utf-8"), re.S)[0]
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
        delegating = (HERE.parent / "references" / "delegating-a-backlog.md").read_text(encoding="utf-8")
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

    def test_open_stories_parses_each_issue_gh_prints_and_refuses_a_failed_read(self):
        from unittest import mock
        lines = '{"number": 7, "title": "Word", "body": "Files area: a.py"}\n\n{"number": 9, "title": "Other", "body": ""}\n'
        with mock.patch.object(sf.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, lines, "")):
            self.assertEqual({7: "Word", 9: "Other"}, {n: o["title"] for n, o in sf.open_stories(".").items()})
        with mock.patch.object(sf.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "HTTP 403")):
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
        good = subprocess.run([sys.executable, script, "--offline"], input=with_blocker(body("story-good.body")),
                              capture_output=True, text=True)
        bad = subprocess.run([sys.executable, script, str(HERE / "fixtures" / "story-no-gherkin.body"), "--offline"],
                             capture_output=True, text=True)
        self.assertEqual(0, good.returncode)
        self.assertEqual(1, bad.returncode)
        self.assertIn("MISSING Gherkin Feature. Fix:", bad.stdout)
