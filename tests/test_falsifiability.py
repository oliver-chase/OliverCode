"""Tests for the unfalsifiable-check detector.

The detector exists because a run of defects in this repo shared one shape: a check that
could not fail. These tests replay two of the real ones, so the detector itself
cannot rot into the thing it was built to catch.
"""

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "fc", REPO_ROOT / "scripts" / "lib" / "falsifiability_check.py"
)
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)


class _Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-falsify-"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, body):
        (self.tmp / name).write_text(body, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.tmp), "add", name], check=True)


class TestDeadCounter(_Scratch):
    def test_counter_compared_but_never_incremented_is_caught(self):
        """The real CRITICAL_ISSUES bug: exit 2 was unreachable."""
        self.write("c.sh", 'CRITICAL=0\nif [ "$CRITICAL" -gt 0 ]; then\n  exit 2\nfi\nexit 0\n')
        found = fc.check_dead_counters(self.tmp)
        self.assertTrue(found, "a never-incremented counter must be caught")
        self.assertIn("CRITICAL", found[0])

    def test_incremented_counter_is_fine(self):
        self.write("c.sh", 'N=0\nN=$((N + 1))\nif [ "$N" -gt 0 ]; then\n  exit 1\nfi\n')
        self.assertEqual(fc.check_dead_counters(self.tmp), [])


class TestScriptCanFail(_Scratch):
    def test_reports_failure_but_cannot_exit_nonzero_is_caught(self):
        """The real post-commit bug: printed FAIL, always exit 0."""
        self.write("v.sh", 'echo "--- check ---"\nif [ ! -f x ]; then\n  echo "  [FAIL] missing"\nfi\nexit 0\n')
        found = fc.check_scripts_can_fail(self.tmp)
        self.assertTrue(found, "a script that cannot act on its own findings must be caught")
        self.assertIn("no nonzero exit", found[0])

    def test_script_that_can_fail_is_fine(self):
        self.write("v.sh", 'if [ ! -f x ]; then\n  echo "  [FAIL] missing"\n  exit 1\nfi\n')
        self.assertEqual(fc.check_scripts_can_fail(self.tmp), [])

    def test_failure_words_in_comments_do_not_trigger(self):
        """A script may discuss failure without implementing it."""
        self.write("v.sh", '# This does not BLOCK anything; FAIL handling lives elsewhere.\necho ok\n')
        self.assertEqual(fc.check_scripts_can_fail(self.tmp), [])


class TestCheckAll(_Scratch):
    def test_runs_both_detectors(self):
        self.write("c.sh", 'CRITICAL=0\nif [ "$CRITICAL" -gt 0 ]; then\n  exit 2\nfi\nexit 0\n')
        self.write("v.sh", 'if [ ! -f x ]; then\n  echo "  [FAIL] missing"\nfi\nexit 0\n')
        found = " ".join(fc.check_all(self.tmp))
        self.assertIn("CRITICAL", found)
        self.assertIn("no nonzero exit", found)

    def test_this_repo_has_no_unfalsifiable_checks(self):
        self.assertEqual(fc.check_all(REPO_ROOT), [])


if __name__ == "__main__":
    unittest.main()
