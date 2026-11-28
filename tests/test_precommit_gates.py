"""Tests for .githooks/pre-commit — the only mechanically-enforced layer.

Each gate gets a case that MUST block and a case that MUST pass. The hook reads
staged files from git, so every test copies a template repo that already holds the hook,
stages a fixture, and runs the hook against it. Each class builds its template once.
Nothing touches this checkout.

Every `exit 1` in a gate has a test that fails when it becomes `true`.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import ISOLATION, REPO_ROOT, git, git_env, scratch_repo

HOOK = REPO_ROOT / ".githooks" / "pre-commit"
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

    def path_without(self, *names):
        """A PATH that holds every tool the real PATH does, minus the commands named, so only a gate's own guard can fail the run."""
        bin_dir = self.tmp / ("without-" + "-".join(names))
        bin_dir.mkdir()
        for entry in os.environ["PATH"].split(os.pathsep):
            if not os.path.isdir(entry):
                continue
            for name in os.listdir(entry):
                target = Path(entry) / name
                if name in names or name.startswith(tuple(f"{n}3" for n in names)) or (bin_dir / name).exists():
                    continue
                if os.access(target, os.X_OK) and not target.is_dir():
                    (bin_dir / name).symlink_to(target)
        return str(bin_dir)

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

    def each_verdict(self, rows):
        """Run each (written, committed, staged, exit code, words) row in a fresh copy of the template.

        A written file sits in the worktree unstaged, and a written script is executable."""
        for written, committed, staged, code, words in rows:
            with self.subTest(staged=sorted(staged)):
                self.tearDown()
                self.setUp()
                for rel, body in written.items():
                    self.write(rel, body).chmod(0o755)
                for rel, body in committed.items():
                    self.stage(rel, body)
                if committed:
                    git(self.tmp, "commit", "-q", "--no-verify", "-m", "config")
                for rel, body in staged.items():
                    self.stage(rel, body)
                out = (self.assertAllowed() if code == 0 else self.assertBlocked(str(sorted(staged)))).stdout
                for word in words:
                    self.assertIn(word, out)


LOCAL_FAIL = {".githooks/pre-commit.local": "#!/usr/bin/env bash\nexit 1\n"}
NOTES = {"notes.txt": "Plain notes.\n"}
SUITE = '{"checks": [{"name": "doc rule", "files": ["docs/*.md", "research/*.md"], "command": "bash %s"}]}\n'
PII_EXEMPT = {"docs/PII-GATE.json": '{"exempt": ["fixtures/*"], "reasons": {"fixtures/*": "sample data"}}\n'}
HOME_PATH = 'P = "/Users/' + 'sample/work"\n'
# (written, committed, staged, exit code, words): the public hook's repo-local, suite-check and PII gates.
PUBLIC = [
    (LOCAL_FAIL, {}, NOTES, 1, []),
    ({"check.sh": "#!/usr/bin/env bash\ngrep -q TODO \"$@\" && exit 1; exit 0\n"}, {},
     {"docs/SUITE-CHECKS.json": SUITE % "check.sh", "research/notes.md": "TODO fill this in\n"}, 1, ["suite check doc rule failed"]),
    ({"check.sh": "#!/usr/bin/env bash\nexit 1\n"}, {}, {"docs/SUITE-CHECKS.json": SUITE % "check.sh", **NOTES}, 0, []),
    ({"ok.sh": "#!/usr/bin/env bash\nexit 0\n"}, {}, {"docs/SUITE-CHECKS.json": SUITE % "ok.sh", "docs/clean.md": "Clean text.\n"}, 0, ["Suite checks"]),
    ({}, {}, {"docs/SUITE-CHECKS.json": "{not json"}, 1, []),
    # A committed PII exemption covers its files only, and the commit that adds one does not use it.
    ({}, PII_EXEMPT, {"fixtures/home.py": HOME_PATH}, 0, []),
    ({}, PII_EXEMPT, {"other.py": HOME_PATH}, 1, []),
    ({}, {}, {**PII_EXEMPT, "fixtures/home.py": HOME_PATH}, 1, []),
    ({}, {}, {"a.py": 'P = "/Users/' + 'jane.doe2/work"\n'}, 1, []),
    ({}, {}, {"a.py": 'HOME_DIR = "/Users/' + 'jane"\n'}, 1, []),
    ({}, {}, {"docs/mockup-notes.md": "Reach me at jane" + "@example.org\n"}, 1, []),
    ({}, {}, {".githooks/pre-commit": "# an address such as git@github.com is explained here\n"}, 0, []),
]


class TestPublicHook(GateHarness):
    def test_each_gate_input_gets_its_verdict(self):
        self.each_verdict(PUBLIC)

    def test_a_renamed_file_is_scanned(self):
        self.stage("notes.txt", "a plain line of notes that is long enough to be renamed as one file\n")
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "notes")
        git(self.tmp, "mv", "notes.txt", "moved.txt")
        with open(self.tmp / "moved.txt", "a", encoding="utf-8") as f:
            f.write("TOKEN=ghp_" + "b" * 36 + "\n")
        git(self.tmp, "add", "moved.txt")
        self.assertBlocked("secret")


class TestPrivateRepoLocalGate(GateHarness):
    """The private variant runs a repo's own .githooks/pre-commit.local after its gates."""

    HOOK_FILE = "core/templates/project/pre-commit-private"

    def test_the_local_gate_decides_the_verdict(self):
        self.each_verdict([(LOCAL_FAIL, {}, NOTES, 1, []),
                           ({".githooks/pre-commit.local": "#!/usr/bin/env bash\nexit 0\n"}, {}, NOTES, 0, ["All gates passed"])])


class TestTreeScan(GateHarness):
    """A secret already committed passes a normal run, because nothing is staged, and fails a tree scan."""

    def test_only_a_tree_scan_finds_the_committed_secret(self):
        self.stage("config.py", 'KEY = "sk-' + "d" * 32 + '"\n')
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "x")
        self.assertEqual(0, self.run_hook().returncode)
        result = self.run_hook(OLIVERCODE_SCAN_TREE="1")
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
