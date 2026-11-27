"""The main checkout of a fleet repo holds only landed work: the guard refuses edits there and health names its drift (#664).

Installed checkout stays level with origin (#785): an ahead checkout names its commits with their authors and the one command that moves them to a branch.
"""

import subprocess
import unittest
from unittest import mock

from _maintain_case import Base
from _support import REPO_ROOT, git, scratch_repo

import sys
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
from lib import main_checkout, placement  # noqa: E402


class TestMainCheckout(Base):
    def repo(self):
        origin = self.root / "origin.git"
        scratch_repo(origin, bare=True, branch="main")
        work = self.root / "work"
        scratch_repo(work, branch="main")
        git(work, "remote", "add", "origin", str(origin))
        (work / "a.txt").write_text("a\n")
        git(work, "add", "."); git(work, "commit", "-q", "-m", "one"); git(work, "push", "-q", "origin", "main")
        git(work, "fetch", "-q", "origin")
        return work

    def test_a_shell_write_in_a_fleet_main_checkout_is_refused_and_quoted_text_is_not(self):
        work = self.repo()
        with mock.patch.object(main_checkout, "fleet_roots", return_value=[work.resolve()]):
            def why(command):
                return main_checkout.reason({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(work)})
            for command in ("sed -i s/a/b/ a.txt", "echo hi > a.txt", "echo hi >> a.txt", "printf x | tee a.txt", "cp /etc/hosts a.txt"):
                self.assertIn("git worktree add", why(command), command)
            for command in ("echo 'sed -i x a.txt' | cat", "ls # > a.txt", "cat a.txt > /dev/null", "echo hi > /dev/stderr"):
                self.assertEqual("", why(command), command)

    def test_an_edit_or_commit_in_a_fleet_main_checkout_is_refused_and_names_the_fix(self):
        work = self.repo()
        with mock.patch.object(main_checkout, "fleet_roots", return_value=[work.resolve()]), mock.patch.object(placement, "load_local", return_value={"repoRoot": str(self.root)}):
            edit = {"tool_name": "Edit", "tool_input": {"file_path": str(work / "a.txt")}, "cwd": str(work)}
            commit = {"tool_name": "Bash", "tool_input": {"command": "git commit -am x"}, "cwd": str(work)}
            for data in (edit, commit):
                why = main_checkout.reason(data)
                self.assertIn(f"git worktree add -b story/N {self.root}/_worktrees/work-N", why)
                self.assertIn("olivercode land", why)
            self.assertEqual("", main_checkout.reason({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(work)}))
        with mock.patch.object(main_checkout, "fleet_roots", return_value=[]):
            self.assertEqual("", main_checkout.reason(edit))

    def test_a_git_ignored_file_under_claude_optimization_is_not_refused(self):
        """#846: the hook handover writes under .claude-optimization/memory/state, which git ignores and which holds no landed work."""
        work = self.repo()
        (work / ".gitignore").write_text(".claude-optimization/memory/\n")
        git(work, "add", "."); git(work, "commit", "-q", "-m", "ignore")
        with mock.patch.object(main_checkout, "fleet_roots", return_value=[work.resolve()]):
            def refused(name):
                return main_checkout.reason({"tool_name": "Write", "tool_input": {"file_path": str(work / name)}, "cwd": str(work)})
            self.assertEqual("", refused(".claude-optimization/memory/state/builder-handover-1.md"))
            self.assertIn("git worktree add", refused(".claude-optimization/tracked.md"))
            self.assertIn("git worktree add", refused("a.txt"))

    def test_a_clean_checkout_reports_no_drift(self):
        self.assertEqual([], main_checkout.drift(self.repo()))

    def test_a_checkout_ahead_of_origin_is_named_with_the_fix(self):
        work = self.repo()
        (work / "a.txt").write_text("b\n")
        git(work, "commit", "-qam", "local")
        line = main_checkout.drift(work)[0]
        self.assertIn("1 commit(s) that origin/main lacks", line)
        self.assertIn(f"{git(work, 'log', '-1', '--format=%an').stdout.strip()}: local", line)  # the commit's author and subject
        self.assertIn("branch olivercode-local && git -C", line)
        self.assertIn("reset --keep origin/main", line)
        self.assertNotIn("olivercode land", line)

    def _origin_moves_on(self, work):
        other = self.root / "other"
        git(self.root, "clone", "-q", str(self.root / "origin.git"), str(other))
        git(other, "config", "user.email", "test@example.invalid")  # a clone has no identity; the CI runner has no global one
        git(other, "config", "user.name", "Test")
        (other / "b.txt").write_text("b\n")
        git(other, "add", "."); git(other, "commit", "-q", "-m", "fix"); git(other, "push", "-q", "origin", "main")
        git(work, "fetch", "-q", "origin")

    def test_a_diverged_checkout_names_that_it_trails_origin_and_the_fix(self):
        work = self.repo()
        (work / "a.txt").write_text("b\n")
        git(work, "commit", "-qam", "local")
        self._origin_moves_on(work)
        line = main_checkout.ahead_refusal(work)
        self.assertIn("trails it by 1", line)
        self.assertIn("reset --keep origin/main", line)

    def test_an_edited_checkout_behind_origin_is_named_and_a_clean_one_is_not(self):
        work = self.repo()
        self._origin_moves_on(work)
        self.assertEqual("", main_checkout.stale_refusal(work))  # clean: the hook fast-forwards it
        (work / "a.txt").write_text("edited\n")
        line = main_checkout.stale_refusal(work)
        self.assertIn("trails origin/main by 1", line)
        self.assertIn("olivercode update", line)
        self.assertEqual([line], main_checkout.drift(work))

    def test_a_checkout_off_main_behind_origin_names_the_checkout_command(self):
        work = self.repo()
        self._origin_moves_on(work)
        git(work, "checkout", "-qb", "side")
        self.assertIn("checkout main", main_checkout.stale_refusal(work))

    def test_a_linked_story_worktree_behind_origin_is_never_named(self):
        work = self.repo()
        self._origin_moves_on(work)
        tree = work.parent / "linked-wt"
        git(work, "worktree", "add", "-q", "-b", "story/7", str(tree), "HEAD")
        (tree / "a.txt").write_text("edited\n")
        self.assertEqual("", main_checkout.stale_refusal(tree))

    def test_a_story_branch_ahead_of_origin_by_design_is_not_named(self):
        work = self.repo()
        git(work, "checkout", "-qb", "story/9")
        (work / "a.txt").write_text("b\n")
        git(work, "commit", "-qam", "story work")
        self.assertEqual([], main_checkout.drift(work))
        self.assertEqual("", main_checkout.ahead_refusal(work))

    def test_a_checkout_level_with_origin_names_no_ahead_commit(self):
        self.assertEqual("", main_checkout.ahead_refusal(self.repo()))

    def test_a_rebase_folder_is_stale_without_a_git_process_and_mid_rebase_with_one(self):
        work = self.repo()
        (work / ".git" / "rebase-merge").mkdir()
        with mock.patch.object(main_checkout.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            self.assertIn("stale rebase-merge folder", " ".join(main_checkout.drift(work)))
        with mock.patch.object(main_checkout.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            self.assertIn("mid-rebase", " ".join(main_checkout.drift(work)))

    def test_conflict_markers_are_named_with_their_file(self):
        work = self.repo()
        (work / "a.txt").write_text("<" * 7 + " HEAD\nx\n" + "=" * 7 + "\ny\n" + ">" * 7 + " b\n")
        found = main_checkout.drift(work)
        self.assertIn("conflict markers in a.txt", found[0])


if __name__ == "__main__":
    unittest.main()
