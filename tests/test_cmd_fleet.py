"""`conform --fix` reports a skip when a fix commits nothing, never a fix (#1048)."""

import os
import unittest
from unittest import mock

from _support import REPO_ROOT, git, git_env, load_script, quiet, scratch_repo, temp_dir

load_script("scripts/olivercode", "olivercode_launcher")
from lib import cmd_fleet, conform  # noqa: E402  (load_script put scripts/ on the path)


class TestFixReport(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-fixreport-")
        env = mock.patch.dict(os.environ, {**git_env(), "OLIVERCODE_HOME": str(self.tmp / "home")}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.repo = scratch_repo(self.tmp / "a")
        (self.repo / "README").write_text("hello\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "--no-verify", "-m", "First commit")

    def fix(self):
        entry = ("a", self.repo, False, "")
        rows, settings = conform.check_fleet([entry], oc_root=REPO_ROOT, offline=True)
        with mock.patch.object(cmd_fleet._repo_state, "archived", return_value=None):
            return quiet(cmd_fleet._fix_fleet, REPO_ROOT, [entry], rows, settings, True, False, "acme/widgets#7")

    def test_a_fix_that_commits_nothing_is_a_skip_not_a_fix(self):
        with mock.patch.object(cmd_fleet, "commit_after", return_value="nothing to commit"):
            _, out = self.fix()
        self.assertIn("[SKIP] a: nothing to commit", out)
        self.assertNotIn("[FIX] a:", out)

    def test_a_fix_that_commits_is_a_fix(self):
        with mock.patch.object(cmd_fleet, "commit_after", return_value="committed abc1234"):
            _, out = self.fix()
        self.assertIn("[FIX] a: committed abc1234", out)

    def test_an_owner_step_whose_check_now_passes_leaves_the_queue_and_a_failing_one_stays(self):
        """#1205: the check runs again after --fix, and a step whose requirement passes is closed."""
        from lib import cmd_owner
        cmd_owner.add("conform", "a: hooks needs the owner", command="fix", error="stopped")
        cmd_owner.add("conform", "a: ignore needs the owner", command="fix", error="tracked")
        again = [[conform.Row("hooks", "pass"), conform.Row("ignore", "fail", "tracked", "fix")]]
        entry = ("a", self.repo, False, "")
        with mock.patch.object(cmd_fleet._conform, "check_fleet", return_value=(again, None)), mock.patch.object(cmd_fleet._repo_state, "archived", return_value=None):
            quiet(cmd_fleet._fix_fleet, REPO_ROOT, [entry], [[]], None, True, False, "acme/widgets#7")
        self.assertEqual(["a: ignore needs the owner"], [i["step"] for i in cmd_owner.items() if i["status"] == "open"])


if __name__ == "__main__":
    unittest.main()
