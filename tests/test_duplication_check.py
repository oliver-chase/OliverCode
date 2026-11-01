"""Tests for the cross-doc duplication check. GATE-DUPLICATION-1 in docs/DECISIONS.md.

A genuine cross-file duplicate is caught, a declared marker suppresses it, a short
overlap under the window is not noise, and ablating a declared marker re-exposes the
duplicate it was masking.
"""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "dc", REPO_ROOT / "scripts" / "lib" / "duplication_check.py"
)
dc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dc)


def _repo(tmp: Path, files: dict[str, str]) -> Path:
    """A throwaway git repo with the given tracked markdown files staged."""
    tmp.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "."], cwd=tmp, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    return tmp


# A real 15-word passage, long enough to clear WINDOW on its own.
LONG_PASSAGE = (
    "hook enforcement fails open if core hookspath is unset points at a missing "
    "directory or the hook is not executable and prints nothing"
)


class TestDuplicationCheck(unittest.TestCase):
    def test_shipped_tree_is_clean(self):
        # The real gate this repo runs on itself -- must stay green, or the gate
        # that ships in validate.sh is failing its own build.
        self.assertEqual(dc.check_all(REPO_ROOT), [])

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
