"""Tests for .githooks/pre-commit — the only mechanically-enforced layer.

Each gate gets a case that MUST block and a case that MUST pass. The hook reads
staged files from git, so every test copies a template repo that already holds the hook,
stages a fixture, and runs the hook against it. Each class builds its template once.
Nothing touches this checkout.

Gates that consult the machine run against stand-ins: the workflow-auth gate and the
skill-citation check get a stub `gh` on PATH. Every `exit 1` in a gate has a test that fails when it
becomes `true`.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import ISOLATION, REPO_ROOT, git, git_env, scratch_repo

HOOK = REPO_ROOT / ".githooks" / "pre-commit"
TEMPLATE_HOOK = REPO_ROOT / "core" / "templates" / "project" / "pre-commit"
_SAVED_GIT_ENV = {}


def setUpModule():
    # `git rebase -x` and `git bisect run` export GIT_DIR, which would aim every scratch-repo
    # git call (config, add, commit) at the real checkout. Drop them for the whole module.
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        _SAVED_GIT_ENV[key] = os.environ.pop(key)
    os.environ.update(ISOLATION)


def tearDownModule():
    os.environ.update(_SAVED_GIT_ENV)


class GateHarness(unittest.TestCase):
    """Builds a scratch git repo with the hook installed."""

    HOOK_SOURCE = HOOK
    HOOK_FILE = None  # a subclass names the hook to run, relative to the repo root

    @classmethod
    def setUpClass(cls):
        if cls.HOOK_FILE:
            cls.HOOK_SOURCE = REPO_ROOT / cls.HOOK_FILE
        cls._template_dir = Path(tempfile.mkdtemp(prefix="olivercode-gates-template-"))
        template = scratch_repo(cls._template_dir / "repo")
        hooks = template / ".githooks"
        hooks.mkdir()
        shutil.copy2(cls.HOOK_SOURCE, hooks / "pre-commit")
        (hooks / "pre-commit").chmod(0o755)
        cls._template = template

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._template_dir, ignore_errors=True)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-gates-"))
        shutil.rmtree(self.tmp)
        shutil.copytree(self._template, self.tmp, symlinks=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stage(self, relpath, content):
        path = self.tmp / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        git(self.tmp, "add", relpath)

    def write(self, relpath, content):
        path = self.tmp / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def stub_gh(self, script):
        """A `gh` that runs `script` (bash, args in "$@") ahead of any real one on PATH."""
        gh = self.write("stub-bin/gh", "#!/usr/bin/env bash\n" + script)
        gh.chmod(0o755)
        return {"PATH": f"{gh.parent}{os.pathsep}{os.environ['PATH']}"}

    def run_hook(self, **env_overrides):
        # validate.sh --tree exports OLIVERCODE_SCAN_TREE, and a test must check staged
        # files only.
        env = {k: v for k, v in os.environ.items() if not k.startswith("OLIVERCODE_")}
        env.update(env_overrides)
        return subprocess.run(
            ["bash", str(self.tmp / ".githooks" / "pre-commit")],
            cwd=self.tmp,
            capture_output=True,
            text=True,
            env=env,
        )

    def assertBlocked(self, gate_hint="", **env):
        result = self.run_hook(**env)
        self.assertNotEqual(
            result.returncode, 0, f"hook should have blocked ({gate_hint}); output:\n{result.stdout}"
        )
        return result

    def assertAllowed(self, **env):
        result = self.run_hook(**env)
        self.assertEqual(
            result.returncode, 0, f"hook should have passed; output:\n{result.stdout}{result.stderr}"
        )
        return result


class TestPrivateRepoLocalGate(GateHarness):
    """The private variant runs a repo's own .githooks/pre-commit.local after its gates."""

    def setUp(self):
        super().setUp()
        shutil.copy2(REPO_ROOT / "core/templates/project/pre-commit-private",
                     self.tmp / ".githooks" / "pre-commit")

    def local_gate(self, code):
        local = self.write(".githooks/pre-commit.local", f"#!/usr/bin/env bash\nexit {code}\n")
        local.chmod(0o755)
        self.stage("notes.txt", "Plain notes.\n")

    def test_a_failing_local_gate_blocks(self):
        self.local_gate(1)
        self.assertNotIn("All gates passed", self.assertBlocked("repo-local").stdout)

    def test_a_passing_local_gate_passes(self):
        self.local_gate(0)
        self.assertIn("All gates passed", self.assertAllowed().stdout)


class TestTreeScan(GateHarness):
    """A secret already committed passes a normal run, because nothing is staged, and fails a tree scan."""

    def setUp(self):
        super().setUp()
        self.stage("config.py", 'KEY = "sk-' + "d" * 32 + '"\n')
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "x")

    def test_a_normal_run_sees_nothing_staged(self):
        self.assertEqual(0, self.run_hook().returncode)

    def test_a_tree_scan_finds_the_committed_secret(self):
        result = subprocess.run(
            ["bash", str(self.tmp / ".githooks" / "pre-commit")],
            cwd=self.tmp, capture_output=True, text=True,
            env={**os.environ, "OLIVERCODE_SCAN_TREE": "1"},
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("secret pattern", result.stdout)


class TestLinkedWorktree(unittest.TestCase):
    """A commit from a linked worktree runs every gate. Git sets GIT_DIR for a hook there,
    and `git -C .githooks rev-parse --show-toplevel` then answers with the .githooks folder,
    so the secret scan read no file at all."""

    @classmethod
    def setUpClass(cls):
        """One main repo and one linked worktree for the class; each test resets the worktree."""
        cls.tmp = Path(tempfile.mkdtemp(prefix="olivercode-worktree-"))
        cls.main = cls.tmp / "main"
        cls.wt = cls.tmp / "wt"
        scratch_repo(cls.main)
        cls.git("-C", str(cls.main), "config", "core.hooksPath", ".githooks")
        (cls.main / ".githooks").mkdir()
        shutil.copy2(HOOK, cls.main / ".githooks" / "pre-commit")
        (cls.main / ".githooks" / "pre-commit").chmod(0o755)
        cls.git("-C", str(cls.main), "add", "-A")
        cls.git("-C", str(cls.main), "commit", "-q", "--no-verify", "-m", "base")
        cls.git("-C", str(cls.main), "worktree", "add", "-q", str(cls.wt))
        cls.base = cls.git("-C", str(cls.main), "rev-parse", "HEAD").stdout.strip()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.git("-C", str(self.wt), "reset", "-q", "--hard", self.base)
        self.git("-C", str(self.wt), "clean", "-fdq")

    @classmethod
    def git(cls, *args, **kw):
        return subprocess.run(["git", *args], check=kw.pop("check", True),
                              capture_output=True, text=True, env=git_env(), **kw)

    @staticmethod
    def write(path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def commit_in_worktree(self, rel, body):
        self.write(self.wt / rel, body)
        self.git("-C", str(self.wt), "add", rel)
        return self.git("-C", str(self.wt), "commit", "-m", "change", check=False)

    def test_a_secret_blocks(self):
        result = self.commit_in_worktree("config.py", 'KEY = "sk-' + "e" * 32 + '"\n')
        out = result.stdout + result.stderr
        self.assertNotEqual(0, result.returncode, out)
        self.assertIn("secret pattern", out)


if __name__ == "__main__":
    unittest.main()


class TestPublicRepoLocalAndPii(GateHarness):
    def test_the_public_variant_runs_the_repo_local_gate(self):
        local = self.write(".githooks/pre-commit.local", "#!/usr/bin/env bash\nexit 1\n")
        local.chmod(0o755)
        self.stage("notes.txt", "Plain notes.\n")
        self.assertBlocked("repo-local")

    def test_a_file_listed_in_the_pii_exempt_file_passes_and_others_still_block(self):
        self.stage("docs/PII-GATE.json", '{"exempt": ["fixtures/*"], "reasons": {"fixtures/*": "sample data"}}\n')
        self.stage("fixtures/home.py", 'P = "/Users/' + 'sample/work"\n')
        self.assertAllowed()
        self.stage("other.py", 'P = "/Users/' + 'sample/work"\n')
        self.assertBlocked("pii")

    def test_a_home_path_with_digits_or_dots_is_pii(self):
        self.stage("a.py", 'P = "/Users/' + 'jane.doe2/work"\n')
        self.assertBlocked("pii")

    def test_the_hook_files_are_not_scanned_for_pii(self):
        self.stage(".githooks/pre-commit", "# an address such as git@github.com is explained here\n")
        self.assertAllowed()
