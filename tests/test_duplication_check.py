"""Tests for the cross-doc duplication check. GATE-DUPLICATION-1 in docs/DECISIONS.md.

A genuine cross-file duplicate is caught, a declared marker suppresses it, and a short overlap under the window is not noise.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from _support import git, load_script, scratch_repo, temp_dir

dc = load_script("scripts/lib/duplication_check.py", "dc")

# A real 15-word passage, long enough to clear WINDOW on its own.
LONG_PASSAGE = (
    "hook enforcement fails open if core hookspath is unset points at a missing "
    "directory or the hook is not executable and prints nothing"
)
MARKER = "hook enforcement fails open if core hookspath is unset"
TWICE = {"a.md": f"# A\n\n{LONG_PASSAGE}\n", "b.md": f"# B\n\n{LONG_PASSAGE}\n"}  # the same passage in two files


class TestDuplicationCheck(unittest.TestCase):
    def repo(self, files: dict[str, str]) -> Path:
        """A throwaway git repo with the given markdown files staged."""
        tmp = temp_dir(self, "olivercode-dup-")
        for rel, content in files.items():
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp / rel).write_text(content, encoding="utf-8")
        scratch_repo(tmp)
        git(tmp, "add", "-A")
        return tmp

    def test_catches_a_real_cross_file_duplicate(self):
        found = dc.check_all(self.repo(TWICE))
        self.assertTrue(found, "a genuine 15+ word shared passage was not caught")
        self.assertTrue(any("a.md" in f and "b.md" in f for f in found))

    def test_short_overlap_under_window_is_not_flagged(self):
        line = "Run bash scripts/validate.sh before committing."
        self.assertEqual(dc.check_all(self.repo({"a.md": f"# A\n\n{line}\n", "b.md": f"# B\n\n{line}\n"})), [])

    def test_declared_marker_suppresses_a_real_duplicate(self):
        original = dict(dc.DECLARED_MARKERS)
        dc.DECLARED_MARKERS[MARKER] = "test-only declared marker"
        self.addCleanup(lambda: (dc.DECLARED_MARKERS.clear(), dc.DECLARED_MARKERS.update(original)))
        self.assertEqual(dc.check_all(self.repo(TWICE)), [])

    def test_a_repo_declares_reuse_in_its_own_allow_file_with_a_reason(self):
        allow = {"docs/DUPLICATION-ALLOW.json": json.dumps({"markers": {MARKER: "a routing table repeats its own description on purpose"}})}
        self.assertEqual(dc.check_all(self.repo({**TWICE, **allow})), [])

    def test_a_repo_marker_with_no_reason_declares_nothing(self):
        for reason in ("", "   "):
            allow = {"docs/DUPLICATION-ALLOW.json": json.dumps({"markers": {MARKER: reason}})}
            self.assertTrue(dc.check_all(self.repo({**TWICE, **allow})), "a marker with no reason must not hide a duplicate")

    def test_a_broken_allow_file_does_not_hide_duplicates_or_crash(self):
        self.assertTrue(dc.check_all(self.repo({**TWICE, "docs/DUPLICATION-ALLOW.json": "{not json"})))

    def test_no_finding_across_a_single_file(self):
        self.assertEqual(dc.check_all(self.repo({"a.md": f"# A\n\n{LONG_PASSAGE}\n{LONG_PASSAGE}\n"})), [])


if __name__ == "__main__":
    unittest.main()
