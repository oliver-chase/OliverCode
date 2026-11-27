"""OliverCode's text never names another repo. The checkouts and config are written into a scratch root, so no real name is needed."""

import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, git, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import repo_name_guard as guard  # noqa: E402

NAMES = ["zz-example-repo"]


class GuardTests(unittest.TestCase):
    def test_a_line_naming_a_registry_repo_is_refused_without_printing_the_name(self):
        reason = guard.refusal("Fix the sync\nSee ZZ-Example-Repo for details\n", NAMES)
        self.assertIn("line 2", reason)
        self.assertIn("another repo", reason)
        self.assertNotIn("zz-example", reason)

    def test_clean_text_and_longer_words_pass(self):
        self.assertEqual(guard.refusal("zz-example-repository is another word", NAMES), "")
        self.assertEqual(guard.refusal("nothing here", NAMES), "")

    def test_a_machine_with_no_other_repo_passes_everything(self):
        self.assertEqual(guard.refusal("zz-example-repo", []), "")

    def test_the_names_come_from_the_checkouts_under_repoRoot_and_privateRepos(self):
        root = temp_dir(self)
        (root / "widget-app" / ".git").mkdir(parents=True)
        config = root / "local.json"
        config.write_text(json.dumps({"repoRoot": str(root), "privateRepos": {"notes-vault": str(root / "notes-vault")}}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(config)}):
            self.assertEqual(guard.hits("a widget-app b\nnotes-vault\nOliverCode", root=root), [(1, "widget-app"), (2, "notes-vault")])

    def test_a_worktree_reads_its_main_checkout(self):
        main = scratch_repo(temp_dir(self) / "main")
        (main / "scripts" / "lib").mkdir(parents=True)
        (main / "scripts" / "lib" / "keep").write_text("", encoding="utf-8")
        git(main, "add", "-A")
        git(main, "commit", "-q", "-m", "init")
        tree = main.parent / "tree"
        git(main, "worktree", "add", "-q", "-b", "side", str(tree))
        self.assertEqual(guard._main_checkout(tree).resolve(), main.resolve())
        self.assertIsNone(guard._main_checkout(main))

    def test_only_olivercode_is_protected(self):
        self.assertTrue(guard.is_olivercode("o/OliverCode"))
        self.assertFalse(guard.is_olivercode("o/zz-example-repo"))

    def test_scan_lists_issues_and_comments_that_name_a_repo_and_skips_pull_requests(self):
        def fetch(path, params):
            if path.endswith("/comments"):
                return [{"issue_url": "https://x/repos/o/r/issues/9", "body": "see zz-example-repo"},
                        {"issue_url": "https://x/repos/o/r/issues/8", "body": "fine"}]
            return [{"number": 3, "title": "t", "body": "uses zz-example-repo"},
                    {"number": 4, "title": "t", "body": "fine"},
                    {"number": 5, "title": "zz-example-repo", "body": "", "pull_request": {}}]
        self.assertEqual(guard.scan_issues("o/r", NAMES, fetch), ([3, 9], ""))
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(guard.main(["--scan-issues", "--repo", "o/r"], out=out, err=err, fetch=fetch, names=NAMES), 1)
        self.assertEqual(out.getvalue().split(), ["3", "9"])

    def test_a_failed_read_exits_two(self):
        err = io.StringIO()
        self.assertEqual(guard.main(["--scan-issues", "--repo", "o/r"], out=io.StringIO(), err=err, fetch=lambda *a: None, names=NAMES), 2)


class CommitMsgHookTests(unittest.TestCase):
    def test_the_hook_blocks_a_message_naming_a_registry_repo_in_an_olivercode_checkout(self):
        repo = scratch_repo(temp_dir(self) / "scratch-checkout")
        (repo / "scripts").mkdir()
        subprocess.run(["cp", "-R", str(REPO_ROOT / "scripts" / "lib"), str(repo / "scripts" / "lib")], check=True)
        root = repo.parent
        (root / "zz-example-repo" / ".git").mkdir(parents=True)
        config = root / "local.json"
        config.write_text(json.dumps({"repoRoot": str(root)}), encoding="utf-8")
        env = {**os.environ, "OLIVERCODE_LOCAL_CONFIG": str(config)}
        hook = REPO_ROOT / "core" / "templates" / "project" / "commit-msg"
        bad, good = repo / "bad.txt", repo / "good.txt"
        bad.write_text("Sync with zz-example-repo (#1)\n", encoding="utf-8")
        good.write_text("Sync with another repo (#1)\n", encoding="utf-8")
        run = lambda f: subprocess.run(["bash", str(hook), str(f)], cwd=repo, capture_output=True, text=True, env=env)
        refused = run(bad)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("another repo", refused.stdout)
        self.assertNotIn("zz-example-repo", refused.stdout + refused.stderr)
        self.assertNotIn("names another repo", run(good).stdout)


if __name__ == "__main__":
    unittest.main()
