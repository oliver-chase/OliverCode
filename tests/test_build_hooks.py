"""Tests for scripts/build-hooks.py: the committed hooks match the build, and a hand edit fails."""

import contextlib
import importlib.util
import io
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_hooks", REPO_ROOT / "scripts" / "build-hooks.py")
bh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bh)


class TestBuildHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-hooks-"))
        shutil.copytree(REPO_ROOT / "core" / "hooks", self.tmp / "core" / "hooks")
        for rel in (*bh.VARIANTS, *bh.PRE_PUSH_TARGETS):
            (self.tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / rel, self.tmp / rel)
        self.saved = (bh.OC_ROOT, bh.GATES_DIR, bh.HEADER, bh.SECRET_PATTERNS, bh.PRE_PUSH)
        hooks = self.tmp / "core" / "hooks"
        bh.OC_ROOT = self.tmp
        bh.GATES_DIR = hooks / "gates"
        bh.HEADER = hooks / "header.sh"
        bh.SECRET_PATTERNS = hooks / "secret-patterns.sh"
        bh.PRE_PUSH = hooks / "pre-push.sh"

    def tearDown(self):
        bh.OC_ROOT, bh.GATES_DIR, bh.HEADER, bh.SECRET_PATTERNS, bh.PRE_PUSH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, *argv):
        with unittest.mock.patch("sys.argv", ["build-hooks.py", *argv]), \
                contextlib.redirect_stdout(io.StringIO()):
            return bh.main()

    def test_committed_hooks_match_the_build(self):
        self.assertEqual(self.check("--check"), 0)

    def test_a_hand_edit_to_a_built_hook_fails(self):
        hook = self.tmp / "core" / "templates" / "project" / "pre-commit-private"
        hook.write_text(hook.read_text() + "echo hand edit\n")
        self.assertEqual(self.check("--check"), 1)

    def test_a_hand_edit_to_the_built_pre_push_fails(self):
        hook = self.tmp / ".githooks" / "pre-push"
        hook.write_text(hook.read_text() + "echo hand edit\n")
        self.assertEqual(self.check("--check"), 1)

    def test_a_secret_pattern_edit_reaches_the_commit_gate_and_the_push_hook(self):
        patterns = bh.SECRET_PATTERNS
        patterns.write_text(patterns.read_text().replace("SECRET_PATTERNS=(", "SECRET_PATTERNS=(\n  'newtok_[0-9]{8}'", 1))
        self.assertEqual(self.check(), 0)
        for rel in (".githooks/pre-commit", ".githooks/pre-push", "core/templates/project/pre-push"):
            self.assertIn("newtok_", (self.tmp / rel).read_text(), rel)

    def test_a_gate_edit_reaches_every_variant_that_runs_it(self):
        gate = bh.GATES_DIR / "secrets.sh"
        gate.write_text(gate.read_text() + "# shared fix\n")
        self.assertEqual(self.check("--check"), 1)
        self.assertEqual(self.check(), 0)
        for rel in bh.VARIANTS:
            self.assertIn("# shared fix", (self.tmp / rel).read_text())

    def test_banners_count_only_numbered_gates(self):
        text = bh.build(bh.VARIANTS["core/templates/project/pre-commit-private"])
        self.assertIn("Gate 4/4: Writing clarity", text)
        self.assertIn("# ─── Repo-local gates ", text)


if __name__ == "__main__":
    unittest.main()
