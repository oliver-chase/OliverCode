"""Tests for the cross-doc duplication check. GATE-DUPLICATION-1 in docs/DECISIONS.md.

A genuine cross-file duplicate is caught, a declared marker suppresses it, a short
overlap under the window is not noise, and ablating a declared marker re-exposes the
duplicate it was masking.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _support import git, load_script, scratch_repo

dc = load_script("scripts/lib/duplication_check.py", "dc")


def _repo(tmp: Path, files: dict[str, str]) -> Path:
    """A throwaway git repo with the given tracked markdown files staged."""
    tmp.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    scratch_repo(tmp)
    git(tmp, "add", "-A")
    return tmp


# A real 15-word passage, long enough to clear WINDOW on its own.
LONG_PASSAGE = (
    "hook enforcement fails open if core hookspath is unset points at a missing "
    "directory or the hook is not executable and prints nothing"
)


class TestDuplicationCheck(unittest.TestCase):
    def test_catches_a_real_cross_file_duplicate(self):
        with tempfile.TemporaryDirectory(prefix="olivercode-dup-") as tmp:
            work = _repo(
                Path(tmp),
                {
                    "a.md": f"# A\n\n{LONG_PASSAGE}\n",
                    "b.md": f"# B\n\n{LONG_PASSAGE}\n",
                },
            )
            found = dc.check_all(work)
            self.assertTrue(found, "a genuine 15+ word shared passage was not caught")
            self.assertTrue(any("a.md" in f and "b.md" in f for f in found))

    def test_short_overlap_under_window_is_not_flagged(self):
        with tempfile.TemporaryDirectory(prefix="olivercode-dup-") as tmp:
            work = _repo(
                Path(tmp),
                {
                    "a.md": "# A\n\nRun bash scripts/validate.sh before committing.\n",
                    "b.md": "# B\n\nRun bash scripts/validate.sh before committing.\n",
                },
            )
            self.assertEqual(dc.check_all(work), [])

    def test_declared_marker_suppresses_a_real_duplicate(self):
        marker = "hook enforcement fails open if core hookspath is unset"
        original = dict(dc.DECLARED_MARKERS)
        dc.DECLARED_MARKERS[marker] = "test-only declared marker"
        try:
            with tempfile.TemporaryDirectory(prefix="olivercode-dup-") as tmp:
                work = _repo(
                    Path(tmp),
                    {
                        "a.md": f"# A\n\n{LONG_PASSAGE}\n",
                        "b.md": f"# B\n\n{LONG_PASSAGE}\n",
                    },
                )
                self.assertEqual(dc.check_all(work), [])
        finally:
            dc.DECLARED_MARKERS.clear()
            dc.DECLARED_MARKERS.update(original)

    def _allow_repo(self, tmp: str, entry: dict) -> Path:
        files = {"a.md": f"# A\n\n{LONG_PASSAGE}\n", "b.md": f"# B\n\n{LONG_PASSAGE}\n",
                 "docs/DUPLICATION-ALLOW.json": json.dumps({"markers": entry})}
        return _repo(Path(tmp), files)

    def test_a_repo_declares_reuse_in_its_own_allow_file_with_a_reason(self):
        marker = "hook enforcement fails open if core hookspath is unset"
        with tempfile.TemporaryDirectory(prefix="olivercode-dup-") as tmp:
            work = self._allow_repo(tmp, {marker: "a routing table repeats its own description on purpose"})
            self.assertEqual(dc.check_all(work), [])

    def test_a_repo_marker_with_no_reason_declares_nothing(self):
        marker = "hook enforcement fails open if core hookspath is unset"
        for reason in ("", "   "):
            with tempfile.TemporaryDirectory(prefix="olivercode-dup-") as tmp:
                work = self._allow_repo(tmp, {marker: reason})
                self.assertTrue(dc.check_all(work), "a marker with no reason must not hide a duplicate")

    def test_a_broken_allow_file_does_not_hide_duplicates_or_crash(self):
        with tempfile.TemporaryDirectory(prefix="olivercode-dup-") as tmp:
            work = _repo(Path(tmp), {"a.md": f"# A\n\n{LONG_PASSAGE}\n", "b.md": f"# B\n\n{LONG_PASSAGE}\n",
                                     "docs/DUPLICATION-ALLOW.json": "{not json"})
            self.assertTrue(dc.check_all(work))

    def test_ablation_neutering_a_marker_re_exposes_the_duplicate(self):
        # Same shape as the manual ablation run when this gate was built: remove a
        # real declared marker, confirm the check goes red, restore it.
        real_marker = next(iter(dc.DECLARED_MARKERS))
        saved_reason = dc.DECLARED_MARKERS.pop(real_marker)
        try:
            words = real_marker.split()
            passage = " ".join(words + ["padding"] * max(0, dc.WINDOW - len(words)))
            with tempfile.TemporaryDirectory(prefix="olivercode-dup-") as tmp:
                work = _repo(
                    Path(tmp),
                    {
                        "a.md": f"# A\n\n{passage}\n",
                        "b.md": f"# B\n\n{passage}\n",
                    },
                )
                found = dc.check_all(work)
                self.assertTrue(found, "neutering a declared marker did not re-expose it")
        finally:
            dc.DECLARED_MARKERS[real_marker] = saved_reason

    def test_no_finding_across_a_single_file(self):
        with tempfile.TemporaryDirectory(prefix="olivercode-dup-") as tmp:
            work = _repo(Path(tmp), {"a.md": f"# A\n\n{LONG_PASSAGE}\n{LONG_PASSAGE}\n"})
            self.assertEqual(dc.check_all(work), [])


if __name__ == "__main__":
    unittest.main()
