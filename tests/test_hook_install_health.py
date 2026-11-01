"""Tests for _hook_problems() and _install_hook_pair() in scripts/olivercode.

When core.hooksPath is unset or points elsewhere, or the hook is missing, not executable or
the wrong variant, git runs weaker gates or none and says nothing. `olivercode health` is the
fleet-wide detector, so it must not report OK in any of those states.
"""

import importlib.util
import os
import shutil
import subprocess
import stat
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = REPO_ROOT / "core" / "templates" / "project"


def _load_launcher():
    loader = SourceFileLoader("olivercode_launcher", str(REPO_ROOT / "scripts" / "olivercode"))
    spec = importlib.util.spec_from_loader("olivercode_launcher", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


launcher = _load_launcher()


GIT_ENV = {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], env=GIT_ENV, check=True,
                          capture_output=True, text=True)


class TestHookProblems(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="olivercode-hookhealth-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        git(self.repo, "init", "-q")
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

    def test_missing_ste_join_wrapper_is_reported(self):
        """The clarity gate blocks without it (STE-JOIN-1), so health must say so."""
        self.install()
        (self.hooks / launcher.STE_JOIN_WRAPPER).unlink()
        self.assertTrue(any(launcher.STE_JOIN_WRAPPER in p for p in self.problems()))

    def test_hook_without_clarity_gate_does_not_need_wrapper(self):
        """A declared variant hook that never lints must not fail health for the wrapper."""
        self.install()
        (self.hooks / "pre-commit").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        (self.hooks / launcher.STE_JOIN_WRAPPER).unlink()
        self.assertFalse(any(launcher.STE_JOIN_WRAPPER in p for p in self.problems()))

    def test_install_hook_pair_output_is_clean_for_both_variants(self):
        """What sync-hooks writes must pass health, for the variant it wrote."""
        for private in (True, False):
            with self.subTest(private=private):
                shutil.rmtree(self.hooks, ignore_errors=True)
                self.install(private)
                self.assertEqual(self.problems(private), [])


class TestInstallHookPair(unittest.TestCase):
    """What sync-hooks deploys to each repo, file by file."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="olivercode-hookpair-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

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

    def test_git_is_pointed_at_the_installed_hooks(self):
        launcher._install_hook_pair(self.repo, TEMPLATES, private_repo=False)
        got = subprocess.run(["git", "-C", str(self.repo), "config", "--get", "core.hooksPath"],
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual(got, ".githooks")


if __name__ == "__main__":
    unittest.main()
