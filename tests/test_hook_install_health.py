"""Tests for _hook_problems() in scripts/olivercode.

This guards a fail-OPEN. When core.hooksPath is unset, points at a missing directory,
holds no pre-commit file, or holds a non-executable one, git runs no hooks and says
nothing: a commit containing secrets goes straight through. `olivercode health` is
the fleet-wide detector, so it must not report OK in any of those states.

An earlier version returned "no divergence" for a missing directory, which the caller
printed as [OK] -- the detector itself failed open. Each case below is that bug's
regression test.
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


class TestHookProblems(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-hookhealth-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _install(self, template="pre-commit", executable=True):
        hooks = self.tmp / ".githooks"
        hooks.mkdir(parents=True, exist_ok=True)
        live = hooks / "pre-commit"
        shutil.copy2(TEMPLATES / template, live)
        mode = live.stat().st_mode
        if executable:
            live.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        else:
            live.chmod(mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        shutil.copy2(TEMPLATES / launcher.STE_JOIN_WRAPPER, hooks / launcher.STE_JOIN_WRAPPER)
        return hooks

    def test_missing_directory_is_reported(self):
        problems = launcher._hook_problems(self.tmp / "nope", TEMPLATES)
        self.assertTrue(problems, "a missing hooks directory must not report clean")
        self.assertIn("does not exist", problems[0])

    def test_empty_directory_is_reported(self):
        hooks = self.tmp / ".githooks"
        hooks.mkdir()
        problems = launcher._hook_problems(hooks, TEMPLATES)
        self.assertTrue(problems, "a hooks directory with no pre-commit must not report clean")
        self.assertIn("no pre-commit", problems[0])

    def test_non_executable_hook_is_reported(self):
        hooks = self._install(executable=False)
        problems = launcher._hook_problems(hooks, TEMPLATES)
        self.assertTrue(problems, "a non-executable hook must not report clean")
        self.assertIn("not executable", problems[0])

    def test_diverged_hook_is_reported(self):
        hooks = self._install()
        (hooks / "pre-commit").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        (hooks / "pre-commit").chmod(0o755)
        problems = launcher._hook_problems(hooks, TEMPLATES)
        self.assertTrue(problems, "a hook diverging from the template must not report clean")
        self.assertIn("diverges", problems[0])

    def test_public_template_installed_correctly_is_clean(self):
        hooks = self._install("pre-commit")
        self.assertEqual(launcher._hook_problems(hooks, TEMPLATES), [])

    def test_private_variant_deployed_as_pre_commit_is_clean(self):
        """A private repo runs the private variant under the filename `pre-commit`."""
        hooks = self._install("pre-commit-private")
        self.assertEqual(launcher._hook_problems(hooks, TEMPLATES), [])

    def test_missing_ste_join_wrapper_is_reported(self):
        """The clarity gate blocks without it (STE-JOIN-1), so health must say so."""
        hooks = self._install()
        (hooks / launcher.STE_JOIN_WRAPPER).unlink()
        problems = launcher._hook_problems(hooks, TEMPLATES)
        self.assertTrue(any(launcher.STE_JOIN_WRAPPER in p for p in problems), problems)

    def test_hook_without_clarity_gate_does_not_need_wrapper(self):
        """A declared variant hook that never lints must not fail health for the wrapper."""
        hooks = self._install()
        (hooks / "pre-commit").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        (hooks / "pre-commit").chmod(0o755)
        (hooks / launcher.STE_JOIN_WRAPPER).unlink()
        problems = launcher._hook_problems(hooks, TEMPLATES)
        self.assertFalse(any(launcher.STE_JOIN_WRAPPER in p for p in problems), problems)

    def test_diverged_ste_join_wrapper_is_reported(self):
        hooks = self._install()
        (hooks / launcher.STE_JOIN_WRAPPER).write_text("print('stale')\n", encoding="utf-8")
        problems = launcher._hook_problems(hooks, TEMPLATES)
        self.assertTrue(any("diverges" in p for p in problems), problems)

    def test_install_hook_pair_output_is_clean_for_both_variants(self):
        """What sync-hooks writes must pass health, wrapper included."""
        import subprocess
        for private in (True, False):
            repo = self.tmp / f"repo-{private}"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            launcher._install_hook_pair(repo, TEMPLATES, private_repo=private)
            self.assertEqual(launcher._hook_problems(repo / ".githooks", TEMPLATES), [])


class TestInstallHookPair(unittest.TestCase):
    """What sync-hooks deploys to each repo. Health accepts either pre-commit variant, so
    these check the exact files: the wrong variant in a repo still looks healthy."""

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
