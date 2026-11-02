"""Tests for repo_gates.hook_problems() and _install_hook_pair() in scripts/olivercode.

When core.hooksPath is unset or points elsewhere, or the hook is missing, not executable or
the wrong variant, git runs weaker gates or none and says nothing. `olivercode conform` is the
fleet-wide detector, so it must not report OK in any of those states.
"""

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, load_script, scratch_repo

TEMPLATES = REPO_ROOT / "core" / "templates" / "project"
launcher = load_script("scripts/olivercode", "olivercode_launcher")
from lib import cmd_fleet  # noqa: E402  (load_script put scripts/ on the path)
repo_gates = load_script("scripts/lib/repo_gates.py")


class TestHookProblems(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="olivercode-hookhealth-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        scratch_repo(self.repo)
        self.hooks = self.repo / ".githooks"

    def install(self, private=False):
        cmd_fleet._install_hook_pair(self.repo, TEMPLATES, private_repo=private)

    def problems(self, private=False):
        return repo_gates.hook_problems(self.repo, TEMPLATES, private)

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

    def test_a_stale_pre_push_is_reported(self):
        self.install()
        (self.hooks / "pre-push").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        self.assertIn("pre-push diverges", "; ".join(self.problems()))

    def test_a_missing_commit_msg_is_reported(self):
        self.install()
        (self.hooks / "commit-msg").unlink()
        self.assertIn("no commit-msg", "; ".join(self.problems()))

    def test_a_stale_commit_msg_is_reported(self):
        self.install()
        (self.hooks / "commit-msg").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        self.assertIn("commit-msg diverges", "; ".join(self.problems()))

class TestInstallHookPair(unittest.TestCase):
    """What sync-hooks deploys to each repo, file by file."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="olivercode-hookpair-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
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

    def test_both_variants_get_an_executable_pre_push(self):
        for private in (True, False):
            with self.subTest(private=private):
                shutil.rmtree(self.repo / ".githooks", ignore_errors=True)
                cmd_fleet._install_hook_pair(self.repo, TEMPLATES, private_repo=private)
                self.assertEqual(self.hook("pre-push"), (TEMPLATES / "pre-push").read_bytes())
                self.assertTrue(os.access(self.repo / ".githooks" / "pre-push", os.X_OK))

    def test_both_variants_get_an_executable_commit_msg(self):
        for private in (True, False):
            with self.subTest(private=private):
                shutil.rmtree(self.repo / ".githooks", ignore_errors=True)
                cmd_fleet._install_hook_pair(self.repo, TEMPLATES, private_repo=private)
                self.assertEqual(self.hook("commit-msg"), (TEMPLATES / "commit-msg").read_bytes())
                self.assertTrue(os.access(self.repo / ".githooks" / "commit-msg", os.X_OK))

    def test_gate_problem_names_an_unset_hooks_path_and_clears_after_install(self):
        self.assertIn("core.hooksPath is unset", repo_gates.gate_problem(self.repo))
        cmd_fleet._install_hook_pair(self.repo, TEMPLATES, private_repo=False)
        self.assertEqual("", repo_gates.gate_problem(self.repo))

if __name__ == "__main__":
    unittest.main()
