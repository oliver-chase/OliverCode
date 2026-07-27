"""Tests for the hook-drift detector.

The three pre-commit hooks implement the same gates and nothing compared them. Two
had drifted into carrying BROKEN documentation pointers -- in the message a developer
sees at the moment they are blocked, which is exactly when they go looking for the
standard being cited.
"""

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "hd", REPO_ROOT / "scripts" / "lib" / "hook_drift_check.py"
)
hd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hd)


class TestLiveHooks(unittest.TestCase):
    def test_shipped_hooks_have_no_undeclared_drift(self):
        self.assertEqual(hd.check_all(REPO_ROOT), [])

    def test_every_declared_difference_has_a_reason(self):
        """An undocumented exemption would recreate the blind spot."""
        for gate, reason in hd.DECLARED_DIFFERENCES.items():
            self.assertTrue(reason.strip(), f"{gate} declared with no reason")
            self.assertGreater(len(reason), 40, f"{gate}'s reason is too thin to audit")


class TestDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-drift-"))
        for rel in hd.HOOKS.values():
            dst = self.tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / rel, dst)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_baseline_copy_is_clean(self):
        self.assertEqual(hd.check_all(self.tmp), [])

    def test_a_one_sided_logic_change_is_caught(self):
        """Editing one hook and forgetting the others is the actual failure mode."""
        target = self.tmp / hd.HOOKS["template"]
        target.write_text(
            target.read_text().replace("PII_PATTERNS=(", "PII_PATTERNS=(\n  'zzz-never'", 1)
        )
        found = hd.check_all(self.tmp)
        self.assertTrue(found, "a one-sided gate edit must be caught")
        self.assertIn("PII", found[0])

    def test_a_broken_doc_pointer_is_caught(self):
        """The real bug: one hook citing a path that does not exist."""
        target = self.tmp / hd.HOOKS["olivercode"]
        target.write_text(
            target.read_text().replace(
                "Oliver/Project Repos/OliverCode/core/contracts/NO_ICONS_STANDARD.md",
                "Oliver/OliverCode/core/contracts/NO_ICONS_STANDARD.md",
                1,
            )
        )
        found = hd.check_all(self.tmp)
        self.assertTrue(found, "a divergent doc pointer must be caught")
        self.assertIn("Icons", found[0])


if __name__ == "__main__":
    unittest.main()
