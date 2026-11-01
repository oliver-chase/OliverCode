"""Tests for .githooks/pre-commit — the only mechanically-enforced layer.

Each gate gets a case that MUST block and a case that MUST pass. The hook reads
staged files from git, so every test builds a throwaway repo, copies the hook in,
stages a fixture, and runs the hook against it. Nothing touches this checkout.

Gates that consult the machine run against stand-ins: gate 5 and gate 9's citation
check get a stub `gh` on PATH, and gates 6 and 7 their checkers copied or stubbed into the
scratch repo. Every
`exit 1` in a gate has a test that fails when it becomes `true`.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".githooks" / "pre-commit"
TEMPLATE_HOOK = REPO_ROOT / "core" / "templates" / "project" / "pre-commit"
_SAVED_GIT_ENV = {}


def setUpModule():
    # `git rebase -x` and `git bisect run` export GIT_DIR, which would aim every scratch-repo
    # git call (config, add, commit) at the real checkout. Drop them for the whole module.
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        _SAVED_GIT_ENV[key] = os.environ.pop(key)


def tearDownModule():
    os.environ.update(_SAVED_GIT_ENV)


class GateHarness(unittest.TestCase):
    """Builds a scratch git repo with the hook installed."""

    HOOK_SOURCE = HOOK

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-gates-"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(
            ["git", "-C", str(self.tmp), "config", "user.email", "test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.tmp), "config", "user.name", "Gate Test"], check=True
        )
        hooks = self.tmp / ".githooks"
        hooks.mkdir()
        shutil.copy2(self.HOOK_SOURCE, hooks / "pre-commit")
        (hooks / "pre-commit").chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stage(self, relpath, content):
        path = self.tmp / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.tmp), "add", relpath], check=True)

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


class TestGate1Secrets(GateHarness):
    def test_openai_style_key_blocks(self):
        self.stage("config.py", 'KEY = "sk-' + "a" * 32 + '"\n')
        self.assertBlocked("gate 1")

    def test_github_pat_blocks(self):
        self.stage("deploy.sh", "TOKEN=ghp_" + "b" * 36 + "\n")
        self.assertBlocked("gate 1")

    def test_private_key_header_blocks(self):
        self.stage("id.txt", "-----BEGIN RSA PRIVATE KEY-----\n")
        self.assertBlocked("gate 1")

    def test_a_secret_in_a_large_file_blocks(self):
        # A pipeline that exits early fails open on big files under pipefail.
        self.stage("big.py", ('KEY = "sk-' + "d" * 32 + '"\n') * 2000)
        self.assertBlocked("gate 1")

    def test_env_example_is_exempt(self):
        # Placeholder-only tracked env templates must not trip the scan.
        self.stage(".env.example", 'API_KEY="sk-' + "c" * 32 + '"\n')
        self.assertAllowed()

    def test_ordinary_prose_passes(self):
        self.stage("notes.md", "This file mentions a token conceptually.\n")
        self.assertAllowed()


class TestGate2Emoji(GateHarness):
    def test_emoji_blocks(self):
        self.stage("readme.md", "Status: done \U0001F600\n")
        result = self.assertBlocked("gate 2")
        self.assertIn("emojis or icons", result.stdout)

    def test_plain_text_passes(self):
        self.stage("readme.md", "Status: done.\n")
        self.assertAllowed()

    def test_box_drawing_is_allowed(self):
        # The QA scripts use box-drawing characters in their banners; those are not
        # in the blocked ranges and must stay usable.
        self.stage("banner.sh", "echo \"" + "╔" + "═" * 5 + "╗\"\n")
        self.assertAllowed()

    def test_missing_perl_blocks_before_any_later_gate(self):
        # Without perl the scan finds nothing, so the gate must stop the commit itself.
        # PATH keeps every other tool, so only the guard can make this run fail.
        bin_dir = self.tmp / "no-perl-bin"
        bin_dir.mkdir()
        for entry in os.environ["PATH"].split(os.pathsep):
            if not os.path.isdir(entry):
                continue
            for name in os.listdir(entry):
                target = Path(entry) / name
                if name.startswith("perl") or (bin_dir / name).exists():
                    continue
                if os.access(target, os.X_OK) and not target.is_dir():
                    (bin_dir / name).symlink_to(target)
        self.stage("readme.md", "Status: done.\n")
        result = self.assertBlocked("gate 2", PATH=str(bin_dir))
        self.assertIn("perl not found", result.stdout)
        self.assertNotIn("Gate 3/", result.stdout)


class TestGate3PII(GateHarness):
    def test_macos_home_path_blocks(self):
        self.stage("run.sh", "cd /Users/someone/projects\n")
        self.assertBlocked("gate 3")

    def test_linux_home_path_blocks(self):
        self.stage("run.sh", "cd /home/someone/projects\n")
        self.assertBlocked("gate 3")

    def test_email_blocks(self):
        self.stage("run.sh", "NOTIFY=person@example.com\n")
        self.assertBlocked("gate 3")

    def test_markdown_is_exempt(self):
        # Docs legitimately quote host paths as examples; .md is skipped by design.
        self.stage("doc.md", "Example path: /Users/someone/projects\n")
        self.assertAllowed()

    def test_placeholder_path_passes(self):
        self.stage("run.sh", "cd <vault-root>/projects\n")
        self.assertAllowed()


class TestGate6ContractIntegrity(GateHarness):
    """Guards the container-path class. A `_Management/` pattern was removed after it
    was found to have zero hits across all six repos and no trace in git history."""

    def test_workspace_path_blocks(self):
        self.stage("tool.sh", "cd /workspace/project\n")
        self.assertBlocked("gate 6")

    def test_markdown_is_exempt(self):
        self.stage("doc.md", "Never hardcode /workspace/ in code.\n")
        self.assertAllowed()

    def test_tests_dir_is_exempt(self):
        """A test proving the gate blocks a path must be able to contain that path."""
        self.stage("tests/t.py", 'p = "/workspace/x"\n')
        self.assertAllowed()


class TestGate4DeletedRepos(GateHarness):
    """Patterns come from the gitignored .private-patterns, since the tracked list is empty."""

    def setUp(self):
        super().setUp()
        self.write(".private-patterns", "# retired repos\nretired-project\n")

    def test_a_reference_to_a_deleted_repo_blocks(self):
        self.stage("src/app.py", "URL = 'github.com/me/retired-project'\n")
        result = self.assertBlocked("gate 4")
        self.assertIn("references deleted path: retired-project", result.stdout)

    def test_a_file_without_the_name_passes(self):
        self.stage("src/app.py", "URL = 'github.com/me/live-project'\n")
        self.assertIn("Gate 4 passed.", self.assertAllowed().stdout)


class TestGate5WorkflowAuth(GateHarness):
    SCOPES = 'case "$1 $2" in "auth status") exit 0 ;; "api user") echo "x-oauth-scopes: {}" ;; esac\n'

    def setUp(self):
        super().setUp()
        self.stage(".github/workflows/ci.yml", "on: push\n")

    def test_a_credential_without_workflow_scope_blocks(self):
        result = self.assertBlocked("gate 5", **self.stub_gh(self.SCOPES.format("repo, gist")))
        self.assertIn("no workflow-scoped credential", result.stdout)

    def test_no_signed_in_gh_blocks(self):
        result = self.assertBlocked("gate 5", **self.stub_gh("exit 1\n"))
        self.assertIn("no workflow-scoped credential", result.stdout)

    def test_a_credential_with_workflow_scope_passes(self):
        result = self.assertAllowed(**self.stub_gh(self.SCOPES.format("repo, workflow")))
        self.assertIn("gh credential has workflow scope", result.stdout)
        self.assertIn("Gate 5 passed.", result.stdout)


class TestGate6PlanningDocs(GateHarness):
    """Planning doc governance ships in the template hook, not OliverCode's own."""

    HOOK_SOURCE = TEMPLATE_HOOK

    def test_no_checker_skips(self):
        self.stage("src/app.py", "print('hello')\n")
        self.assertIn("Planning doc governance... skipped", self.assertAllowed().stdout)

    def test_a_failing_checker_blocks(self):
        self.write("scripts/check-planning-doc-governance.py", "raise SystemExit(1)\n")
        self.stage("src/app.py", "print('hello')\n")
        self.assertIn("BLOCKED: Planning doc governance failed.", self.assertBlocked("gate 6").stdout)

    def test_a_passing_checker_passes(self):
        self.write("scripts/check-planning-doc-governance.py", "raise SystemExit(0)\n")
        self.stage("src/app.py", "print('hello')\n")
        self.assertIn("Gate 6 passed.", self.assertAllowed().stdout)


@unittest.skipUnless(shutil.which("node"), "gate 7 needs node")
class TestGate7BacklogHygiene(GateHarness):
    def setUp(self):
        super().setUp()
        self.write("core/templates/project/scripts/check-backlog-hygiene.mjs",
                   (REPO_ROOT / "core/templates/project/scripts/check-backlog-hygiene.mjs")
                   .read_text(encoding="utf-8"))

    def test_a_done_heading_blocks(self):
        self.stage("docs/BACKLOG.md", "# Backlog\n\n## Search rewrite DONE\n\n- item\n")
        self.assertIn("BLOCKED: Backlog hygiene failed.", self.assertBlocked("gate 7").stdout)

    def test_an_open_backlog_passes(self):
        self.stage("docs/BACKLOG.md", "# Backlog\n\n## Not done yet\n\n- item\n")
        self.assertIn("Gate 7 passed.", self.assertAllowed().stdout)


class TestGate8ArchivedContent(GateHarness):
    def test_an_archive_directory_blocks(self):
        self.stage("docs/Archive/plan.md", "Old plan.\n")
        self.assertIn("names an archive", self.assertBlocked("gate 8").stdout)

    def test_a_superseded_copy_name_blocks(self):
        self.stage("docs/plan-old.md", "Old plan.\n")
        self.assertIn("named as a superseded copy", self.assertBlocked("gate 8").stdout)

    def test_prose_about_legacy_systems_passes(self):
        self.stage("docs/Legacy Modernization.md", "How we replace legacy systems.\n")
        self.assertIn("Gate 8 passed.", self.assertAllowed().stdout)


class TestGate9SkillCitations(GateHarness):
    """Offline: a stub `gh` that knows issues 1 and 2."""

    GH = 'case "$1 $2" in "auth status") exit 0 ;; "issue list") printf "1\\n2\\n" ;; esac\n'

    def setUp(self):
        super().setUp()
        self.env = {**self.stub_gh(self.GH)}

    def test_a_citation_to_no_real_issue_blocks(self):
        self.stage("skills/x/SKILL.md", "Fixes the parser, see #99.\n")
        result = self.assertBlocked("gate 9", **self.env)
        self.assertIn("#99 is cited in a staged skill file but resolves to no real issue", result.stdout)

    def test_a_citation_to_a_real_issue_passes(self):
        self.stage("skills/x/SKILL.md", "Fixes the parser, see #2.\n")
        self.assertIn("Gate 9 passed.", self.assertAllowed(**self.env).stdout)


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


class TestCleanCommitPasses(GateHarness):
    def test_ordinary_change_passes_every_gate(self):
        self.stage("src/module.py", "def add(a, b):\n    return a + b\n")
        self.stage("docs/module.md", "# Module\n\nAdds two numbers.\n")
        result = self.assertAllowed()
        self.assertIn("All gates passed", result.stdout)



class TestTreeScan(GateHarness):
    """A secret already committed passes a normal run, because nothing is staged, and fails a tree scan."""

    def setUp(self):
        super().setUp()
        self.stage("config.py", 'KEY = "sk-' + "d" * 32 + '"\n')
        subprocess.run(["git", "-C", str(self.tmp), "commit", "-q", "--no-verify", "-m", "x"], check=True)

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


def git_env():
    """The environment for a real `git commit` in a scratch repo. A suite that itself runs
    inside a hook inherits GIT_DIR and GIT_INDEX_FILE, which would aim git at this checkout."""
    return {k: v for k, v in os.environ.items()
            if not k.startswith("GIT_") and k != "OLIVERCODE_SCAN_TREE"}


@unittest.skipUnless(shutil.which("node"), "gate 7 needs node")
class TestLinkedWorktree(unittest.TestCase):
    """A commit from a linked worktree runs every gate. Git sets GIT_DIR for a hook there,
    and `git -C .githooks rev-parse --show-toplevel` then answers with the .githooks folder,
    so gate 7 reported its checker missing and skipped, and the secret scan
    read no file at all."""

    CHECKERS = {
        "core/templates/project/scripts/check-backlog-hygiene.mjs":
            "console.log('backlog checker ran');\n",
    }

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-worktree-"))
        self.main = self.tmp / "main"
        self.wt = self.tmp / "wt"
        self.git("init", "-q", str(self.main))
        self.git("-C", str(self.main), "config", "user.email", "test@example.invalid")
        self.git("-C", str(self.main), "config", "user.name", "Gate Test")
        self.git("-C", str(self.main), "config", "core.hooksPath", ".githooks")
        (self.main / ".githooks").mkdir()
        shutil.copy2(HOOK, self.main / ".githooks" / "pre-commit")
        (self.main / ".githooks" / "pre-commit").chmod(0o755)
        for rel, body in self.CHECKERS.items():
            self.write(self.main / rel, body)
        self.git("-C", str(self.main), "add", "-A")
        self.git("-C", str(self.main), "commit", "-q", "--no-verify", "-m", "base")
        self.git("-C", str(self.main), "worktree", "add", "-q", str(self.wt))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args, **kw):
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

    def test_gate_7_runs(self):
        result = self.commit_in_worktree("src/app.py", "print('hello')\n")
        out = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, out)
        self.assertIn("backlog checker ran", out)
        self.assertIn("Gate 7 passed.", out)

    def test_a_failing_checker_blocks(self):
        self.write(self.wt / "core/templates/project/scripts/check-backlog-hygiene.mjs",
                   "process.exit(1);\n")
        result = self.commit_in_worktree("src/app.py", "print('hello')\n")
        out = result.stdout + result.stderr
        self.assertNotEqual(0, result.returncode, out)
        self.assertIn("BLOCKED: Backlog hygiene failed.", out)

    def test_a_secret_blocks(self):
        result = self.commit_in_worktree("config.py", 'KEY = "sk-' + "e" * 32 + '"\n')
        out = result.stdout + result.stderr
        self.assertNotEqual(0, result.returncode, out)
        self.assertIn("secret pattern", out)


if __name__ == "__main__":
    unittest.main()
