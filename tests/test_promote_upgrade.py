"""Promote rehearses the update a main user runs before it moves main, and tags main's old head first (#1389)."""

import subprocess
import time
import unittest
from pathlib import Path

from _support import git, temp_dir
import test_land
from lib import cmd_land

REPO_ROOT = Path(__file__).resolve().parent.parent
setUpModule = test_land.setUpModule  # unittest runs setUpModule only for the module that defines the class, so this file borrows test_land's template


class TestPromoteUpgrade(test_land.TestPromote):
    """The promote fixture of test_land, with its own tests only."""

    def rehearsal(self, repo, wt, head):
        self.rehearsed.append(head)
        return self.rehearsal_result

    def setUp(self):
        self.rehearsed, self.rehearsal_result = [], (True, "")
        super().setUp()

    def test_a_passing_rehearsal_goes_on_to_validation_and_tags_main_before_moving_it(self):
        old, stg = self.sha("origin/main"), self.sha("origin/staging")
        code, out = self.promote()
        git(self.main, "fetch", "-q", "origin", "--tags")
        self.assertEqual(0, code, out)
        self.assertEqual([stg], self.rehearsed)
        self.assertEqual([True, True, True], self.runs)
        self.assertEqual(old, self.sha("refs/tags/archive/main-" + time.strftime("%Y-%m-%d")))
        self.assertEqual(stg, self.sha("origin/main"))

    def test_a_failing_rehearsal_pushes_nothing_and_prints_the_step_and_its_output(self):
        main = self.sha("origin/main")
        self.rehearsal_result = (False, "Upgrade rehearsal failed at: olivercode update\n'conform' is not a valid command.")
        code, out = self.promote()
        git(self.main, "fetch", "-q", "origin", "--tags")
        self.assertEqual(1, code)
        self.assertIn("failed at: olivercode update", out)
        self.assertIn("'conform' is not a valid command", out)
        self.assertEqual([True, True], self.runs)  # the full validation never ran
        self.assertEqual((main, []), (self.sha("origin/main"), self.labels))
        self.assertEqual("", git(self.main, "tag", "-l", "archive/main-*").stdout)

    def test_the_rehearsal_script_passes_when_main_updates_to_itself(self):
        clone = temp_dir(self) / "clone"
        git(clone.parent, "clone", "-q", str(REPO_ROOT), str(clone))
        git(clone, "update-ref", "refs/remotes/origin/main", "HEAD")
        ran = subprocess.run(["bash", str(REPO_ROOT / "scripts/qa/rehearse-upgrade.sh"), str(clone), "HEAD"], capture_output=True, text=True, timeout=600)
        self.assertEqual(0, ran.returncode, ran.stdout + ran.stderr)
        self.assertIn("Upgrade rehearsal passed", ran.stdout)


for _name in [n for n in dir(test_land.TestPromote) if n.startswith("test_")]:
    setattr(TestPromoteUpgrade, _name, None)  # the inherited promote tests run once, in test_land
if __name__ == "__main__":
    unittest.main()
