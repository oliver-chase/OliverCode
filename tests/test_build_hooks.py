"""Tests for scripts/build-hooks.py: a hand edit to a built hook fails. validate.sh runs the check on the committed hooks."""

import contextlib
import io
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from _support import REPO_ROOT, load_script

bh = load_script("scripts/build-hooks.py", "build_hooks")


class TestBuildHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-hooks-"))
        shutil.copytree(REPO_ROOT / "core" / "hooks", self.tmp / "core" / "hooks")
        for rel in (*bh.VARIANTS, *bh.PRE_PUSH_TARGETS, *bh.COMMIT_MSG_TARGETS):
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

    def test_a_hand_edit_to_any_built_hook_fails(self):
        for rel in ("core/templates/project/pre-commit-private", "core/templates/project/pre-push", "core/templates/project/commit-msg"):
            with self.subTest(rel):
                hook = self.tmp / rel
                original = hook.read_text()
                hook.write_text(original + "echo hand edit\n")
                self.assertEqual(self.check("--check"), 1)
                hook.write_text(original)

    def test_a_secret_pattern_edit_reaches_the_commit_gate_and_the_push_hook(self):
        patterns = bh.SECRET_PATTERNS
        patterns.write_text(patterns.read_text().replace("SECRET_PATTERNS=(", "SECRET_PATTERNS=(\n  'newtok_[0-9]{8}'", 1))
        self.assertEqual(self.check(), 0)
        for rel in ("core/templates/project/pre-commit", "core/templates/project/pre-push"):
            self.assertIn("newtok_", (self.tmp / rel).read_text(), rel)

    def test_a_gate_edit_reaches_every_variant_that_runs_it(self):
        gate = bh.GATES_DIR / "secrets.sh"
        gate.write_text(gate.read_text() + "# shared fix\n")
        self.assertEqual(self.check("--check"), 1)
        self.assertEqual(self.check(), 0)
        for rel in bh.VARIANTS:
            self.assertIn("# shared fix", (self.tmp / rel).read_text())


class TestAdoptedRepoHooksCarryNoOliverCodeText(unittest.TestCase):
    """An adopted repo does not hold OliverCode's docs or generator, so its hooks must not point at them."""

    def test_the_template_hooks_name_no_oliver_code_path_or_doc(self):
        targets = [r for r in (*bh.VARIANTS, *bh.PRE_PUSH_TARGETS, *bh.COMMIT_MSG_TARGETS) if r.startswith("core/templates/")]
        self.assertTrue(targets)
        for rel in targets:
            text = (REPO_ROOT / rel).read_text()
            for word in ("OliverCode", "DECISIONS.md", "RULES.md", "build-hooks.py"):
                self.assertNotIn(word, text, f"{rel} mentions {word}")

    def test_oliver_codes_own_hooks_are_links_to_the_templates(self):
        for name in ("pre-commit", "commit-msg", "pre-push"):
            link = REPO_ROOT / ".githooks" / name
            self.assertTrue(link.is_symlink(), name)
            self.assertEqual(link.resolve(), (REPO_ROOT / "core" / "templates" / "project" / name).resolve(), name)

if __name__ == "__main__":
    unittest.main()
