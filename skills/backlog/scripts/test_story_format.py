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


class StoryFormat(unittest.TestCase):
    def test_the_template_examples_pass(self):
        examples = re.findall(r"````markdown\n(.*?)````", TEMPLATE.read_text(encoding="utf-8"), re.S)
        self.assertTrue(examples)
        for example in examples:
            self.assertEqual([], sf.check_body(example))
        skill = (HERE.parent / "SKILL.md").read_text(encoding="utf-8")
        delegating = (HERE.parent / "references" / "delegating-a-backlog.md").read_text(encoding="utf-8")
        self.assertNotRegex(skill, r"(?i)pull request|\bweekly\b|ask where a config|Which dimension should I check")
        self.assertNotRegex(delegating, r"(?i)content-flow|ecommerce|pgrep")

    def test_a_story_without_gherkin_is_rejected_with_a_fix(self):
        problems = sf.check_body(body("story-no-gherkin.body"))
        self.assertEqual(["Gherkin Feature"], [p for p, _ in problems])
        self.assertIn("Feature:", problems[0][1])

    def test_angle_brackets_inside_backticks_are_not_a_placeholder(self):
        good = body("story-good.body") + "\nRun `size.sh <target>` before and after.\n"
        self.assertEqual([], [p for p, _ in sf.check_body(good) if "placeholder" in p])

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

    def test_the_command_reads_stdin_and_sets_the_exit_status(self):
        script = str(HERE / "check_story_format.py")
        good = subprocess.run([sys.executable, script], input=body("story-good.body"),
                              capture_output=True, text=True)
        bad = subprocess.run([sys.executable, script, str(HERE / "fixtures" / "story-no-gherkin.body")],
                             capture_output=True, text=True)
        self.assertEqual(0, good.returncode)
        self.assertEqual(1, bad.returncode)
        self.assertIn("MISSING Gherkin Feature. Fix:", bad.stdout)


if __name__ == "__main__":
    unittest.main()
