"""Tests for scripts/build-hooks.py: every hook is built from core/hooks/, and a hand edit does not survive a build."""

import contextlib
import io
import shutil
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so `-m unittest tests.test_build_hooks` finds _support
from _support import REPO_ROOT, load_script, temp_dir  # noqa: E402

bh = load_script("scripts/build-hooks.py", "build_hooks")
BUILT = (*bh.VARIANTS, *bh.PRE_PUSH_TARGETS, *bh.COMMIT_MSG_TARGETS)


class TestBuildHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-hooks-")
        hooks = self.tmp / "core" / "hooks"
        shutil.copytree(REPO_ROOT / "core" / "hooks", hooks)
        (self.tmp / "core" / "templates" / "project").mkdir(parents=True)
        self.enterContext(unittest.mock.patch.multiple(
            bh, OC_ROOT=self.tmp, GATES_DIR=hooks / "gates", HEADER=hooks / "header.sh",
            SECRET_PATTERNS=hooks / "secret-patterns.sh", PRE_PUSH=hooks / "pre-push.sh"))

    def build(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return bh.main()

    def test_a_build_writes_every_hook_and_replaces_a_hand_edit(self):
        self.assertEqual(self.build(), 0)
        for rel in BUILT:
            with self.subTest(rel):
                hook = self.tmp / rel
                built = hook.read_text()
                self.assertTrue(hook.stat().st_mode & 0o111)
                hook.write_text(built + "echo hand edit\n")
                self.build()
                self.assertEqual(hook.read_text(), built)

    def test_an_unchanged_hook_is_not_rewritten(self):
        self.build()
        before = {rel: (self.tmp / rel).stat().st_ino for rel in BUILT}
        self.build()
        self.assertEqual(before, {rel: (self.tmp / rel).stat().st_ino for rel in BUILT})

    def test_a_secret_pattern_edit_reaches_the_commit_gate_and_the_push_hook(self):
        patterns = bh.SECRET_PATTERNS
        patterns.write_text(patterns.read_text().replace("SECRET_PATTERNS=(", "SECRET_PATTERNS=(\n  'newtok_[0-9]{8}'", 1))
        self.assertEqual(self.build(), 0)
        for rel in ("core/templates/project/pre-commit", "core/templates/project/pre-push"):
            self.assertIn("newtok_", (self.tmp / rel).read_text(), rel)

    def test_a_gate_edit_reaches_every_variant_that_runs_it(self):
        gate = bh.GATES_DIR / "secrets.sh"
        gate.write_text(gate.read_text() + "# shared fix\n")
        self.assertEqual(self.build(), 0)
        for rel in bh.VARIANTS:
            self.assertIn("# shared fix", (self.tmp / rel).read_text())

    def test_the_built_hooks_are_untracked(self):
        ran = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", *BUILT], capture_output=True, text=True)
        if ran.returncode != 0:
            self.skipTest("this copy of the repo is not a git checkout, so tracked files cannot be listed")
        self.assertEqual(ran.stdout, "")


class TestAdoptedRepoHooksCarryNoOliverCodeText(unittest.TestCase):
    """An adopted repo does not hold OliverCode's docs or generator, so its hooks must not point at them."""

    def test_the_template_hooks_name_no_oliver_code_path_or_doc(self):
        targets = [r for r in BUILT if r.startswith("core/templates/")]
        self.assertTrue(targets)
        for rel in targets:
            text = (REPO_ROOT / rel).read_text()
            for word in ("OliverCode", "RULES.md", "build-hooks.py"):
                self.assertNotIn(word, text, f"{rel} mentions {word}")

    def test_oliver_codes_own_hooks_are_links_to_the_templates(self):
        for name in ("pre-commit", "commit-msg", "pre-push"):
            link = REPO_ROOT / ".githooks" / name
            self.assertTrue(link.is_symlink(), name)
            self.assertEqual(link.resolve(), (REPO_ROOT / "core" / "templates" / "project" / name).resolve(), name)


class TestSharedFunctionsDoNotDrift(unittest.TestCase):
    """secret_filter, and SECRET_PATTERNS live once in core/hooks/ (#606), so every built hook holds that text verbatim."""

    def test_each_built_hook_holds_the_shared_source_it_is_built_from(self):
        shared = {"secret-patterns.sh": (*bh.VARIANTS, *bh.PRE_PUSH_TARGETS)}
        for name, hooks in shared.items():
            text = (REPO_ROOT / "core" / "hooks" / name).read_text()
            for rel in hooks:
                with self.subTest(f"{name} in {rel}"):
                    self.assertIn(text, (REPO_ROOT / rel).read_text())
