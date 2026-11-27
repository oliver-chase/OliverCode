"""Tests for repo_gates.hook_problems() and _install_hook_pair() in scripts/olivercode.

When core.hooksPath is unset or points elsewhere, or the hook is missing, not executable or
the wrong variant, git runs weaker gates or none and says nothing. `olivercode health` is the
detector for OliverCode and each private repo, so it must not report OK in any of those states.
"""

import os
import shutil
import unittest
from unittest import mock

from _support import REPO_ROOT, git, load_script, quiet, scratch_repo, temp_dir

TEMPLATES = REPO_ROOT / "core" / "templates" / "project"
launcher = load_script("scripts/olivercode", "olivercode_launcher")
from lib import cmd_fleet  # noqa: E402  (load_script put scripts/ on the path)
repo_gates = load_script("scripts/lib/repo_gates.py")
from lib import health_checks  # noqa: E402


class TestHookProblems(unittest.TestCase):
    def setUp(self):
        self.repo = temp_dir(self, "olivercode-hookhealth-")
        scratch_repo(self.repo)
        self.hooks = self.repo / ".githooks"

    def install(self, private=False):
        cmd_fleet._install_hook_pair(self.repo, TEMPLATES, private_repo=private)

    def problems(self, private=False):
        return repo_gates.hook_problems(self.repo, TEMPLATES, private)

    def commit_hooks(self):
        self.install()
        git(self.repo, "config", "core.hooksPath", ".githooks")
        git(self.repo, "add", ".githooks")
        git(self.repo, "commit", "-qn", "-m", "hooks")

    def test_a_hand_edited_tracked_hook_is_flagged_dirty(self):
        self.commit_hooks()
        self.assertEqual([], self.problems())
        with open(self.hooks / "pre-push", "a") as f:
            f.write("# hand edit\n")
        self.assertIn("pre-push is tracked but differs from HEAD", " ".join(self.problems()))

    def test_a_committed_hook_that_differs_from_the_template_is_flagged(self):
        self.commit_hooks()
        with open(self.hooks / "pre-push", "a") as f:
            f.write("# drift\n")
        git(self.repo, "commit", "-qan", "-m", "drift")
        self.assertEqual(["pre-push diverges from the pre-push template"], self.problems())

    def test_the_committed_blob_is_what_is_compared(self):
        self.commit_hooks()
        with open(self.hooks / "pre-push", "a") as f:
            f.write("# drift\n")
        git(self.repo, "commit", "-qan", "-m", "drift")
        shutil.copy(TEMPLATES / "pre-push", self.hooks / "pre-push")
        self.assertIn("differs from HEAD", " ".join(self.problems()))

    def test_unset_hooks_path_is_reported(self):
        self.assertIn("unset", self.problems()[0])

    def test_hooks_path_pointed_away_from_githooks_is_reported(self):
        self.install()
        git(self.repo, "config", "core.hooksPath", ".git/hooks")
        self.assertIn("never run", self.problems()[0])

    def test_missing_directory_is_reported(self):
        git(self.repo, "config", "core.hooksPath", ".githooks")
        self.assertIn("does not exist", self.problems()[0])

    def test_empty_directory_is_reported(self):
        git(self.repo, "config", "core.hooksPath", ".githooks")
        self.hooks.mkdir()
        self.assertIn("no pre-commit", self.problems()[0])

    def test_non_executable_hook_is_reported(self):
        self.install()
        (self.hooks / "pre-commit").chmod(0o644)
        self.assertIn("not executable", self.problems()[0])

    def test_diverged_hook_is_reported(self):
        self.install()
        (self.hooks / "pre-commit").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        self.assertTrue(any("pre-commit diverges" in p for p in self.problems()), self.problems())

    def test_a_public_repo_running_the_private_hook_is_reported(self):
        self.install(private=True)
        self.assertTrue(any("pre-commit diverges" in p for p in self.problems(private=False)))

    def test_a_missing_pre_push_is_reported(self):
        self.install()
        (self.hooks / "pre-push").unlink()
        self.assertIn("no pre-push", "; ".join(self.problems()))

    def test_a_stale_commit_msg_is_reported(self):
        self.install()
        (self.hooks / "commit-msg").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        self.assertIn("commit-msg diverges", "; ".join(self.problems()))

class TestInstallHookPair(unittest.TestCase):
    """What sync-hooks deploys to each repo, file by file."""

    def setUp(self):
        self.repo = temp_dir(self, "olivercode-hookpair-")
        scratch_repo(self.repo)

    def hook(self, name):
        return (self.repo / ".githooks" / name).read_bytes()

    def test_a_private_repo_gets_the_private_variant_as_its_live_hook(self):
        cmd_fleet._install_hook_pair(self.repo, TEMPLATES, private_repo=True)
        self.assertEqual(self.hook("pre-commit"), (TEMPLATES / "pre-commit-private").read_bytes())
        self.assertFalse((self.repo / ".githooks" / "pre-commit-private").exists())

    def test_a_public_repo_gets_the_public_hook_and_no_private_copy(self):
        cmd_fleet._install_hook_pair(self.repo, TEMPLATES, private_repo=False)
        self.assertEqual(self.hook("pre-commit"), (TEMPLATES / "pre-commit").read_bytes())
        self.assertFalse((self.repo / ".githooks" / "pre-commit-private").exists())

    def test_a_leftover_private_copy_is_deleted_on_either_variant(self):
        for private in (True, False):
            with self.subTest(private=private):
                (self.repo / ".githooks").mkdir(exist_ok=True)
                (self.repo / ".githooks" / "pre-commit-private").write_text("old\n")
                cmd_fleet._install_hook_pair(self.repo, TEMPLATES, private_repo=private)
                self.assertFalse((self.repo / ".githooks" / "pre-commit-private").exists())

    def test_both_variants_get_an_executable_pre_push_and_commit_msg(self):
        for private in (True, False):
            with self.subTest(private=private):
                shutil.rmtree(self.repo / ".githooks", ignore_errors=True)
                cmd_fleet._install_hook_pair(self.repo, TEMPLATES, private_repo=private)
                for name in ("pre-push", "commit-msg"):
                    self.assertEqual(self.hook(name), (TEMPLATES / name).read_bytes())
                    self.assertTrue(os.access(self.repo / ".githooks" / name, os.X_OK))

    def test_a_dangling_pre_commit_link_counts_as_gates_that_do_not_run(self):
        hooks = self.repo / ".githooks"
        hooks.mkdir(exist_ok=True)
        os.symlink("../missing/pre-commit", hooks / "pre-commit")
        git(self.repo, "config", "core.hooksPath", ".githooks")
        self.assertTrue(repo_gates.has_gates(self.repo))
        self.assertIn("holds no pre-commit file", repo_gates.gate_problem(self.repo))

    def test_gate_problem_names_an_unset_hooks_path_and_clears_after_install(self):
        self.assertIn("core.hooksPath is unset", repo_gates.gate_problem(self.repo))
        cmd_fleet._install_hook_pair(self.repo, TEMPLATES, private_repo=False)
        self.assertEqual("", repo_gates.gate_problem(self.repo))


class TestSessionNotesForStoppedGates(unittest.TestCase):
    """An unset core.hooksPath fails health and a note in the session, so policy cannot turn off silently."""

    def test_unset_hooks_path_fails_health_and_the_session_names_the_fix(self):
        session_check = load_script("scripts/hooks/session_check.py", "session_check_510")
        repo = temp_dir(self, "olivercode-stopped-gates-", resolve=True)
        scratch_repo(repo)
        cmd_fleet._install_hook_pair(repo, TEMPLATES, private_repo=False)
        claude = temp_dir(self, "olivercode-claude-")
        quiet_helpers = {name: mock.patch.object(session_check, name, return_value=[])
                         for name in ("placement_notes", "gh_notes", "checkout_notes")}  # the checkout under test is this worktree, which trails origin/main whenever main moves
        for patcher in quiet_helpers.values():
            patcher.start()
            self.addCleanup(patcher.stop)
        self.assertEqual([], session_check.notes(repo, claude), "gates are on, so nothing to say")
        self.assertEqual("", health_checks.stopped_hook(repo, REPO_ROOT, private=False))

        git(repo, "config", "--unset", "core.hooksPath")
        self.assertNotEqual("", health_checks.stopped_hook(repo, REPO_ROOT, private=False))
        with mock.patch.object(health_checks, "OC_ROOT", REPO_ROOT), \
                mock.patch.object(health_checks, "install_linked", return_value=True):
            result, out = quiet(health_checks._check_stopped_hooks, REPO_ROOT, {"notes": repo})
        self.assertEqual((1, 1), result[:2])
        self.assertIn("[FAIL] notes", out)
        self.assertIn("Fix: olivercode sync-hooks --commit --story N", out)
        with mock.patch.object(health_checks, "install_linked", return_value=False):
            result, out = quiet(health_checks._check_stopped_hooks, REPO_ROOT, {"notes": repo})
        self.assertEqual((0, 0, 1), result)
        self.assertIn("[WARN] install has not linked this checkout", out)
        self.assertNotIn("[FAIL]", out)
        note = " ".join(session_check.notes(repo, claude))
        self.assertIn("core.hooksPath is unset", note)
        self.assertIn("olivercode sync-hooks", note)
