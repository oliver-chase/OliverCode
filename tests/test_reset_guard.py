"""Tests for scripts/hooks/reset_guard.py: a hard reset is refused in a main checkout or a dirty tree and allowed in a clean worktree."""

import sys
import unittest

from _support import REPO_ROOT, git, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import reset_guard  # noqa: E402


class TestResetGuard(unittest.TestCase):
    def setUp(self):
        base = temp_dir(self)
        self.main = scratch_repo(base / "main")
        (self.main / "f").write_text("a\n", encoding="utf-8")
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "first")
        self.wt = base / "wt"
        git(self.main, "worktree", "add", "-q", "-b", "story/1", str(self.wt))

    def test_main_checkout_is_refused_even_when_clean(self):
        self.assertIn("main checkout", reset_guard.reason("git reset --hard origin/main", self.main))

    def test_clean_worktree_is_allowed(self):
        self.assertEqual("", reset_guard.reason("git reset --hard origin/main", self.wt))

    def test_dirty_worktree_is_refused_and_names_the_safe_route(self):
        (self.wt / "f").write_text("b\n", encoding="utf-8")
        why = reset_guard.reason("git reset --hard", self.wt)
        self.assertIn("uncommitted changes", why)
        self.assertIn("git checkout -- FILE", why)

    def test_each_refusal_is_one_line_under_200_characters_and_names_the_rules_doc(self):
        base = temp_dir(self)
        long = scratch_repo(base / ("a-checkout-with-a-long-name-" + "x" * 20))  # 48 characters, longer than most repo names
        (long / "f").write_text("a\n", encoding="utf-8")
        git(long, "add", "-A")
        git(long, "commit", "-q", "-m", "first")
        wt = base / "long-wt"
        git(long, "worktree", "add", "-q", "-b", "story/2", str(wt))
        (wt / "f").write_text("b\n", encoding="utf-8")
        for why in (reset_guard.reason("git reset --hard origin/main", long), reset_guard.reason("git reset --hard", wt)):
            self.assertLessEqual(len(why), 200, why)
            self.assertNotIn("\n", why)
            self.assertIn("docs/RULES.md", why)

    def test_git_dash_c_and_chained_commands_are_read(self):
        (self.wt / "f").write_text("b\n", encoding="utf-8")
        self.assertIn("uncommitted", reset_guard.reason(f"git -C {self.wt} reset --hard", self.main.parent))
        self.assertIn("uncommitted", reset_guard.reason("echo x && git reset --hard HEAD", self.wt))

    def test_other_resets_and_other_commands_are_allowed(self):
        (self.wt / "f").write_text("b\n", encoding="utf-8")
        for command in ("git reset --soft HEAD~1", "git reset HEAD f", "echo git reset --hard", "git status"):
            self.assertEqual("", reset_guard.reason(command, self.wt), command)
        self.assertEqual("", reset_guard.reason("git reset --soft HEAD~1", self.main))

    def test_a_folder_outside_git_is_allowed(self):
        self.assertEqual("", reset_guard.reason("git reset --hard", temp_dir(self)))


if __name__ == "__main__":
    unittest.main()
