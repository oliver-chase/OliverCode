"""Remote branches (#657): conform fails for an origin branch besides the default, `clean --apply` deletes the merged ones,
and conform flags a repo that keeps merged branches on GitHub. Each test runs against a real bare origin."""

import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, git, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import conform, placement  # noqa: E402


def make_pair(case):
    """A Repos root with a clone `work` whose bare origin holds main. Returns (root, work, origin)."""
    base = temp_dir(case, resolve=True)
    root = base / "Repos"
    root.mkdir()
    origin = scratch_repo(base / "origin.git", bare=True)
    work = scratch_repo(root / "work", branch="main")
    git(work, "remote", "add", "origin", str(origin))
    git(work, "commit", "--allow-empty", "-q", "-m", "init")
    git(work, "push", "-q", "origin", "main")
    git(work, "remote", "set-head", "origin", "main")
    return root, work, origin


def push_branch(work, name, merged):
    """A branch on origin at main's commit (merged), or one commit ahead of it (not merged)."""
    if merged:
        git(work, "push", "-q", "origin", f"main:refs/heads/{name}")
        return
    git(work, "checkout", "-q", "-b", name)
    git(work, "commit", "--allow-empty", "-q", "-m", name)
    git(work, "push", "-q", "origin", name)
    git(work, "checkout", "-q", "main")


def origin_branches(origin):
    return set(git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout.split())


def config(root):
    return placement.Config(root=root, worktrees=root / "_worktrees", archive=root / "_archive", watch=[], allow=[])


class ConformBranches(unittest.TestCase):
    def setUp(self):
        self.root, self.work, self.origin = make_pair(self)
        patch = mock.patch.object(placement, "_open_pr", return_value=False)  # no open pull request, so a merged story/* branch may go (#1045)
        patch.start()
        self.addCleanup(patch.stop)

    def test_origin_with_only_its_default_branch_passes(self):
        self.assertEqual(conform.branches(self.work, offline=False).status, "pass")

    def test_a_merged_remote_branch_fails_and_is_named_safe_to_delete(self):
        push_branch(self.work, "story/done", merged=True)
        row = conform.branches(self.work, offline=False)
        self.assertEqual(row.status, "fail")
        self.assertIn("story/done (merged into main, safe to delete)", row.detail)
        self.assertIn("olivercode clean --apply", row.fix)

    def test_a_merged_branch_clean_keeps_is_not_called_safe_to_delete(self):
        push_branch(self.work, "feature-x", merged=True)
        row = conform.branches(self.work, offline=False)
        self.assertIn("feature-x (merged into main, not a story branch, so clean leaves it)", row.detail)
        self.assertNotIn("safe to delete", row.detail)

    def test_a_merged_story_branch_with_an_open_pull_request_is_not_called_safe_to_delete(self):
        push_branch(self.work, "story/held", merged=True)
        with mock.patch.object(placement, "_open_pr", return_value=True):
            row = conform.branches(self.work, offline=False)
        self.assertIn("story/held (merged into main, kept by clean", row.detail)
        self.assertNotIn("safe to delete", row.detail)

    def test_an_unmerged_remote_branch_fails_and_is_named_with_its_commits(self):
        push_branch(self.work, "story/open", merged=False)
        row = conform.branches(self.work, offline=False)
        self.assertEqual(row.status, "fail")
        self.assertIn("story/open (has commits not on main)", row.detail)

    def test_offline_skips_and_a_repo_with_no_origin_skips(self):
        push_branch(self.work, "story/open", merged=False)
        self.assertEqual(conform.branches(self.work, offline=True).status, "skip")
        local = scratch_repo(self.root / "local", branch="main")
        self.assertEqual(conform.branches(local, offline=False).status, "skip")


class DeleteOnMerge(unittest.TestCase):
    def setUp(self):
        self.root, self.work, _ = make_pair(self)
        (self.work / "docs").mkdir()
        (self.work / "docs" / "backlog-config.json").write_text('{"repoOwner": "acme", "repoName": "widgets"}')

    def answer(self, returncode, stdout):
        return mock.patch("lib.conform.subprocess.run", return_value=mock.Mock(returncode=returncode, stdout=stdout))

    def test_offline_skips_without_asking_github(self):
        with mock.patch("lib.conform.subprocess.run") as run:
            self.assertEqual(conform.delete_on_merge(self.work, offline=True).status, "skip")
        run.assert_not_called()

    def test_a_repo_that_keeps_merged_branches_fails_with_the_gh_fix(self):
        with self.answer(0, "false\n"):
            row = conform.delete_on_merge(self.work, offline=False)
        self.assertEqual(row.status, "fail")
        self.assertIn("gh repo edit acme/widgets --delete-branch-on-merge", row.fix)

    def test_a_repo_that_deletes_merged_branches_passes_and_an_unreachable_github_skips(self):
        with self.answer(0, "true\n"):
            self.assertEqual(conform.delete_on_merge(self.work, offline=False).status, "pass")
        with self.answer(1, ""):
            self.assertEqual(conform.delete_on_merge(self.work, offline=False).status, "skip")


class CleanRemoteBranches(unittest.TestCase):
    def setUp(self):
        self.root, self.work, self.origin = make_pair(self)
        self.cfg = config(self.root)
        patch = mock.patch.object(placement, "_open_pr", return_value=False)  # no open pull request, so a merged story/* branch may go (#1045)
        patch.start()
        self.addCleanup(patch.stop)

    def test_without_apply_a_merged_branch_is_listed_and_kept(self):
        push_branch(self.work, "story/done", merged=True)
        lines = placement.remote_branches(self.cfg, apply=False)
        self.assertTrue(any("origin/story/done" in line and "run with --apply" in line for line in lines))
        self.assertIn("story/done", origin_branches(self.origin))

    def test_apply_deletes_the_merged_branch_and_keeps_unmerged_and_default(self):
        push_branch(self.work, "story/done", merged=True)
        push_branch(self.work, "story/open", merged=False)
        lines = placement.remote_branches(self.cfg, apply=True)
        self.assertTrue(any(line.startswith("REMOVE") and "origin/story/done" in line for line in lines))
        remaining = origin_branches(self.origin)
        self.assertNotIn("story/done", remaining)
        self.assertTrue({"story/open", "main"} <= remaining)

    def test_a_branch_a_worktree_has_checked_out_is_never_deleted(self):
        push_branch(self.work, "story/live", merged=True)
        git(self.work, "worktree", "add", "-q", "-b", "story/live", str(self.root.parent / "wt"), "origin/story/live")
        placement.remote_branches(self.cfg, apply=True)
        self.assertIn("story/live", origin_branches(self.origin))


class CleanRemoteBranchesQAFixes(unittest.TestCase):
    """Cold-QA fixes: a default branch named other than main, a branch that moves on origin mid-run, and a branch already gone."""

    def setUp(self):
        self.root, self.work, self.origin = make_pair(self)
        self.cfg = config(self.root)
        patch = mock.patch.object(placement, "_open_pr", return_value=False)  # no open pull request, so a merged story/* branch may go (#1045)
        patch.start()
        self.addCleanup(patch.stop)

    def make_trunk_default(self):
        git(self.work, "push", "-q", "origin", "main:refs/heads/trunk")
        git(self.origin, "symbolic-ref", "HEAD", "refs/heads/trunk")
        git(self.work, "remote", "set-head", "origin", "trunk")

    def test_a_trunk_default_is_never_listed_for_removal(self):
        self.make_trunk_default()
        push_branch(self.work, "story/done", merged=True)
        lines = placement.remote_branches(self.cfg, apply=False)
        self.assertTrue(any("origin/story/done" in line for line in lines))
        self.assertFalse(any(line.startswith("REMOVE work: origin/trunk") for line in lines))

    def test_apply_deletes_merged_branches_on_a_trunk_default_and_keeps_trunk(self):
        self.make_trunk_default()
        push_branch(self.work, "story/done", merged=True)
        placement.remote_branches(self.cfg, apply=True)
        remaining = origin_branches(self.origin)
        self.assertNotIn("story/done", remaining)
        self.assertIn("trunk", remaining)

    def test_a_branch_that_moved_on_origin_after_the_merge_check_is_kept(self):
        push_branch(self.work, "story/moved", merged=True)
        real_git = placement._git
        raced = []

        def race(repo, *args):
            out = real_git(repo, *args)
            if args[:1] == ("rev-parse",) and not raced:
                # Origin's branch gets a new commit between the merge check and the delete.
                raced.append(True)
                git(self.work, "checkout", "-q", "-B", "tmp", "main")
                git(self.work, "commit", "--allow-empty", "-q", "-m", "moved on origin")
                git(self.work, "push", "-q", "origin", "tmp:refs/heads/story/moved")
                git(self.work, "checkout", "-q", "main")
                git(self.work, "branch", "-q", "-D", "tmp")
            return out

        with mock.patch.object(placement, "_git", side_effect=race):
            lines = placement.remote_branches(self.cfg, apply=True)
        self.assertTrue(raced)
        self.assertTrue(any(line.startswith("FAILED") and "story/moved" in line for line in lines))
        self.assertIn("story/moved", origin_branches(self.origin))

    def test_a_branch_already_deleted_on_origin_is_not_reported_as_removed(self):
        push_branch(self.work, "story/gone", merged=True)
        git(self.origin, "update-ref", "-d", "refs/heads/story/gone")
        lines = placement.remote_branches(self.cfg, apply=True)
        self.assertFalse(any("story/gone" in line for line in lines))
