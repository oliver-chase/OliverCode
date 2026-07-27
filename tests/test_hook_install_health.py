"""Tests for _hook_problems() in scripts/olivercode.

This guards a fail-OPEN. When core.hooksPath is unset, points at a missing directory,
holds no pre-commit file, or holds a non-executable one, git runs no hooks and says
nothing: a commit containing secrets goes straight through. `olivercode health` is
the only thing that detects it, so health must not report OK in any of those states.

An earlier version returned "no divergence" for a missing directory, which the caller
printed as [OK] -- the detector itself failed open. Each case below is that bug's
regression test.
"""

import importlib.util
import os
import shutil
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
        """The vault runs the 2-gate variant under the filename `pre-commit`."""
        hooks = self._install("pre-commit-private")
        self.assertEqual(launcher._hook_problems(hooks, TEMPLATES), [])


if __name__ == "__main__":
    unittest.main()
