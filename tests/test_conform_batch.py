"""Conform batches its git and GitHub calls (#775) and `conform --fix` repairs each repo in one commit (#778)."""

import json
import os
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from _support import REPO_ROOT, git, git_env, load_script, quiet, scratch_repo, temp_dir

load_script("scripts/olivercode", "olivercode_launcher")
from lib import cmd_fleet, conform, gitfiles  # noqa: E402  (load_script put scripts/ on the path)


def _repo(tmp, name, slug=("acme", "widgets")):
    repo = scratch_repo(tmp / name)
    (repo / "docs").mkdir()
    (repo / "docs" / "backlog-config.json").write_text(json.dumps({"repoOwner": slug[0], "repoName": slug[1]}))
    (repo / "README").write_text("hello\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "--no-verify", "-m", "First commit")
    return repo


class TestBatchedReads(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-batch-")

    def test_one_graphql_request_answers_every_repo(self):
        calls = []

        def runner(argv, **_):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout=json.dumps({"data": {
                "r0": {"deleteBranchOnMerge": True, "description": "a", "repositoryTopics": {"totalCount": 1}, "viewerCanAdminister": True},
                "r1": {"deleteBranchOnMerge": False, "description": "", "repositoryTopics": {"totalCount": 0}, "viewerCanAdminister": False}}}))
        found = conform.fleet_settings([("acme", "b"), ("acme", "a")], runner)
        self.assertEqual(1, len(calls))
        self.assertTrue(found["acme/a"]["deleteBranchOnMerge"])
        a, b = _repo(self.tmp, "a", ("acme", "a")), _repo(self.tmp, "b", ("acme", "b"))
        self.assertEqual("pass", conform.delete_on_merge(a, offline=False, settings=found).status)
        self.assertEqual("fail", conform.delete_on_merge(b, offline=False, settings=found).status)
        self.assertEqual("pass", conform.docs(a, offline=False, settings=found).status)
        self.assertEqual("fail", conform.docs(b, offline=False, settings=found).status)

    def test_an_unreachable_github_returns_none_so_checks_fall_back(self):
        self.assertIsNone(conform.fleet_settings([("acme", "a")], lambda *a, **k: SimpleNamespace(returncode=1, stdout="")))

    def test_branches_calls_ls_remote_once(self):
        repo = _repo(self.tmp, "a")
        listing = "ref: refs/heads/main\tHEAD\nabc\tHEAD\nabc\trefs/heads/main\n"
        seen = []

        def fake(repo_path, *args):
            seen.append(args)
            return SimpleNamespace(returncode=0, stdout=listing if args[0] == "ls-remote" else "")
        with mock.patch.object(conform, "_git", fake):
            row = conform.branches(repo, offline=False)
        self.assertEqual("pass", row.status)
        self.assertEqual(1, sum(a[0] == "ls-remote" for a in seen))

    def test_check_fleet_returns_rows_in_repo_order(self):
        repos = [(n, _repo(self.tmp, n), False, "") for n in ("b", "a", "c")]
        rows, _ = conform.check_fleet(repos, oc_root=REPO_ROOT, offline=True)
        self.assertEqual(3, len(rows))
        self.assertTrue(all(r[0].requirement == "layout" for r in rows))


class TestCommitHelper(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-commit-")
        env = mock.patch.dict(os.environ, git_env(), clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.repo = _repo(self.tmp, "a")

    def test_every_change_lands_in_one_commit(self):
        def change():
            (self.repo / "one.txt").write_text("1\n")
            (self.repo / "two.txt").write_text("2\n")
        result = gitfiles.commit_after(self.repo, change, "Subject (#775)", "Body.")
        self.assertTrue(result.startswith("committed"), result)
        self.assertEqual(2, len(git(self.repo, "log", "--format=%H").stdout.split()))
        self.assertEqual(["one.txt", "two.txt"], sorted(git(self.repo, "show", "--name-only", "--format=", "HEAD").stdout.split()))

    def test_local_changes_in_a_touched_file_skip_the_repo_and_others_stay_out(self):
        (self.repo / "README").write_text("edited\n")
        ran = []
        result = gitfiles.commit_after(self.repo, lambda: ran.append(1), "S", "B", touches=("README",))
        self.assertIn("already had uncommitted changes", result)
        self.assertEqual([], ran)
        (self.repo / "other.txt").write_text("x\n")
        gitfiles.commit_after(self.repo, lambda: (self.repo / "new.txt").write_text("n\n"), "S", "B", touches=("new.txt",))
        self.assertEqual(["new.txt"], git(self.repo, "show", "--name-only", "--format=", "HEAD").stdout.split())

    def test_nothing_changed_makes_no_commit(self):
        self.assertEqual("nothing to commit", gitfiles.commit_after(self.repo, lambda: None, "S", "B"))


class TestConformFix(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-fix-")
        env = mock.patch.dict(os.environ, {**git_env(), "OLIVERCODE_HOME": str(self.tmp / "home")}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def fix(self, repo):
        entry = ("a", repo, False, "")
        rows, settings = conform.check_fleet([entry], oc_root=REPO_ROOT, offline=True)
        with mock.patch.object(cmd_fleet._repo_state, "archived", return_value=None), \
                mock.patch.object(cmd_fleet._features, "enable", return_value=[]):
            return quiet(cmd_fleet._fix_fleet, REPO_ROOT, [entry], rows, settings, True, False, "acme/widgets#7")

    def test_a_dead_selftest_is_removed_in_one_commit_and_owner_steps_are_queued(self):
        repo = _repo(self.tmp, "a")
        (repo / ".githooks").mkdir()
        (repo / conform.DEAD_SELFTEST).write_text("x\n")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "--no-verify", "-m", "Add selftest")
        left, out = self.fix(repo)
        self.assertIn("[FIX] a: committed", out)
        self.assertFalse((repo / conform.DEAD_SELFTEST).exists())
        self.assertIn("[OWNER] a:", out)
        self.assertNotIn("dead-selftest", out.split("Checking again")[1].replace("[OK] dead-selftest", ""))
        self.assertEqual(left, int(out.rsplit("After --fix: ", 1)[1].split()[0]))

    def test_a_repo_with_a_local_edit_in_a_touched_file_is_skipped(self):
        repo = _repo(self.tmp, "a")
        (repo / ".githooks").mkdir()
        (repo / conform.DEAD_SELFTEST).write_text("x\n")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "--no-verify", "-m", "Add selftest")
        (repo / conform.DEAD_SELFTEST).write_text("edited\n")
        _, out = self.fix(repo)
        self.assertIn("[SKIP] a: not committed", out)
        self.assertTrue((repo / conform.DEAD_SELFTEST).exists())

    def test_fix_kinds(self):
        self.assertEqual("local", conform.fix_kind(conform.Row("hooks", "fail", fix="olivercode sync-hooks")))
        self.assertEqual("github", conform.fix_kind(conform.Row("delete-on-merge", "fail")))
        self.assertEqual("owner", conform.fix_kind(conform.Row("docs", "fail")))



if __name__ == "__main__":
    unittest.main()
