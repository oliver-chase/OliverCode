"""Tests for _hook_problems() and _install_hook_pair() in scripts/olivercode.

When core.hooksPath is unset or points elsewhere, or the hook is missing, not executable or
the wrong variant, git runs weaker gates or none and says nothing. `olivercode health` is the
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
repo_gates = load_script("scripts/lib/repo_gates.py")


class TestHookProblems(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="olivercode-hookhealth-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        scratch_repo(self.repo)
        self.hooks = self.repo / ".githooks"

    def install(self, private=False):
        launcher._install_hook_pair(self.repo, TEMPLATES, private_repo=private)

    def problems(self, private=False):
        return launcher._hook_problems(self.repo, TEMPLATES, private)

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

    def test_install_hook_pair_output_is_clean_for_both_variants(self):
        """What sync-hooks writes must pass health, for the variant it wrote."""
        for private in (True, False):
            with self.subTest(private=private):
                shutil.rmtree(self.hooks, ignore_errors=True)
                self.install(private)
                self.assertEqual(self.problems(private), [])


class TestFleetHooks(unittest.TestCase):
    """`health --hooks-only`: the hook state of each fleet and private repo, counted once, offline."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="olivercode-fleethooks-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.public = scratch_repo(self.root / "public")
        self.private = scratch_repo(self.root / "private")
        self.bare = scratch_repo(self.root / "bare")
        launcher._install_hook_pair(self.public, TEMPLATES, private_repo=False)
        launcher._install_hook_pair(self.private, TEMPLATES, private_repo=True)
        profiles = {"public": {}, "private": {}, "bare": {}}
        for name, patcher in (
            ("profiles", mock.patch.object(launcher, "load_repo_profiles", return_value=(profiles, None))),
            ("gap", mock.patch.object(launcher, "registry_gap", return_value=None)),
            ("private", mock.patch.object(launcher, "_private_repos", return_value={"private": self.private})),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            return launcher._check_fleet_hooks(launcher.OC_ROOT, self.root), out.getvalue()

    def test_a_repo_in_the_fleet_and_in_private_repos_is_checked_once_as_private(self):
        (passed, failed, _), out = self.run_check()
        self.assertEqual(1, out.count("private: hooksPath set"))
        self.assertEqual((2, 1), (passed, failed))  # public and private pass, bare fails

    def test_a_repo_with_no_hooks_fails_by_name(self):
        _, out = self.run_check()
        self.assertIn("[FAIL] bare:", out)

    def test_hooks_only_exits_nonzero_for_a_failing_repo_and_checks_nothing_over_the_network(self):
        with mock.patch.object(launcher, "_check_remotes_resolve", side_effect=AssertionError("network")), \
                mock.patch.object(launcher, "_check_github_about", side_effect=AssertionError("network")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, launcher.command_health(self.root, hooks_only=True))
            shutil.rmtree(self.bare)
            self.assertEqual(0, launcher.command_health(self.root, hooks_only=True))


class TestInstallHookPair(unittest.TestCase):
    """What sync-hooks deploys to each repo, file by file."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="olivercode-hookpair-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        scratch_repo(self.repo)

    def hook(self, name):
        return (self.repo / ".githooks" / name).read_bytes()

    def test_a_private_repo_gets_the_private_variant_as_its_live_hook(self):
        launcher._install_hook_pair(self.repo, TEMPLATES, private_repo=True)
        self.assertEqual(self.hook("pre-commit"), (TEMPLATES / "pre-commit-private").read_bytes())
        self.assertFalse((self.repo / ".githooks" / "pre-commit-private").exists())

    def test_a_public_repo_gets_the_public_hook_and_the_private_reference_copy(self):
        launcher._install_hook_pair(self.repo, TEMPLATES, private_repo=False)
        self.assertEqual(self.hook("pre-commit"), (TEMPLATES / "pre-commit").read_bytes())
        self.assertEqual(self.hook("pre-commit-private"), (TEMPLATES / "pre-commit-private").read_bytes())

    def test_both_variants_get_an_executable_pre_push(self):
        for private in (True, False):
            with self.subTest(private=private):
                shutil.rmtree(self.repo / ".githooks", ignore_errors=True)
                launcher._install_hook_pair(self.repo, TEMPLATES, private_repo=private)
                self.assertEqual(self.hook("pre-push"), (TEMPLATES / "pre-push").read_bytes())
                self.assertTrue(os.access(self.repo / ".githooks" / "pre-push", os.X_OK))

    def test_both_variants_get_an_executable_commit_msg(self):
        for private in (True, False):
            with self.subTest(private=private):
                shutil.rmtree(self.repo / ".githooks", ignore_errors=True)
                launcher._install_hook_pair(self.repo, TEMPLATES, private_repo=private)
                self.assertEqual(self.hook("commit-msg"), (TEMPLATES / "commit-msg").read_bytes())
                self.assertTrue(os.access(self.repo / ".githooks" / "commit-msg", os.X_OK))

    def test_gate_problem_names_an_unset_hooks_path_and_clears_after_install(self):
        self.assertIn("core.hooksPath is unset", repo_gates.gate_problem(self.repo))
        launcher._install_hook_pair(self.repo, TEMPLATES, private_repo=False)
        self.assertEqual("", repo_gates.gate_problem(self.repo))

    def test_git_is_pointed_at_the_installed_hooks(self):
        launcher._install_hook_pair(self.repo, TEMPLATES, private_repo=False)
        got = git(self.repo, "config", "--get", "core.hooksPath").stdout.strip()
        self.assertEqual(got, ".githooks")


if __name__ == "__main__":
    unittest.main()
