"""Tests for .githooks/pre-commit — the only mechanically-enforced layer.

Each gate gets a case that MUST block and a case that MUST pass. The hook reads
staged files from git, so every test builds a throwaway repo, copies the hook in,
stages a fixture, and runs the hook against it. Nothing touches this checkout.

Gates 5 (workflow push auth) and 7 (planning-doc governance) are environment- and
presence-dependent: 5 consults the machine's live `gh` credential, 7 only fires when
the target repo ships the checker. Both are asserted at the level that is actually
deterministic here -- that a commit with no workflow files and no checker is not
blocked by them.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".githooks" / "pre-commit"


class GateHarness(unittest.TestCase):
    """Builds a scratch git repo with the hook installed."""

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
        shutil.copy2(HOOK, hooks / "pre-commit")
        (hooks / "pre-commit").chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stage(self, relpath, content):
        path = self.tmp / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.tmp), "add", relpath], check=True)

    def run_hook(self):
        return subprocess.run(
            ["bash", str(self.tmp / ".githooks" / "pre-commit")],
            cwd=self.tmp,
            capture_output=True,
            text=True,
        )

    def assertBlocked(self, gate_hint=""):
        result = self.run_hook()
        self.assertNotEqual(
            result.returncode, 0, f"hook should have blocked ({gate_hint}); output:\n{result.stdout}"
        )
        return result

    def assertAllowed(self):
        result = self.run_hook()
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


class TestGates5And7NonFiring(GateHarness):
    def test_no_workflow_files_and_no_checker_still_passes(self):
        """Gate 5 needs staged workflow YAML; gate 7 needs the checker present."""
        self.stage("src/app.py", "print('hello')\n")
        result = self.assertAllowed()
        self.assertIn("Planning doc governance... skipped", result.stdout)


class TestCleanCommitPasses(GateHarness):
    def test_ordinary_change_passes_every_gate(self):
        self.stage("src/module.py", "def add(a, b):\n    return a + b\n")
        self.stage("docs/module.md", "# Module\n\nAdds two numbers.\n")
        result = self.assertAllowed()
        self.assertIn("All gates passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
