"""Fixture tests for check_plan_doc_leak.py: each of the three checks goes red on a bad fixture
and green on a clean one. Each test runs the script as a subprocess against a temp folder, so no
real fleet state and no `.env.local` is read.

Run from this scripts/ folder: python3 -m unittest test_check_plan_doc_leak

Fixture strings that the script itself detects are assembled from parts, so this file does not
trip the same gate when the real fleet is scanned.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "check_plan_doc_leak.py"
SPEC_CITE = "SPE" + "C-12"
DATE = "2026" + "-01-15"
CLEAN_SKILL = "---\nname: fam-skill\ndescription: Builds a thing.\n---\n\nRun the build step. Check the output.\n"


def scan(files):
    """Write {relative path: text} under a temp folder, run the script on it, return (code, stdout)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        proc = subprocess.run([sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True)
    return proc.returncode, proc.stdout


class CleanTree(unittest.TestCase):
    def test_clean_fixture_exits_zero_on_all_three_checks(self):
        code, out = scan({"fam/fam-skill/SKILL.md": CLEAN_SKILL, "fam/fam-skill/references/notes.md": "Plain text.\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("Banned-path check: clean", out)
        self.assertIn("SPEC-N citation check: clean", out)
        self.assertIn("History-language check: clean", out)


class BannedPath(unittest.TestCase):
    def test_plan_doc_paths_fail(self):
        for rel in ("fam/docs/plans/idea.md", "fam/docs/specs/idea.md", "fam/execution-backlog-v2.md", "fam/_BACKLOG.md"):
            with self.subTest(rel=rel):
                code, out = scan({rel: "Some plan.\n"})
                self.assertEqual(code, 1, out)
                self.assertIn("banned plan-doc/backlog file", out)


class SpecCitation(unittest.TestCase):
    def test_spec_id_fails(self):
        code, out = scan({"fam/fam-skill/SKILL.md": CLEAN_SKILL + f"See {SPEC_CITE} for context.\n"})
        self.assertEqual(code, 1, out)
        self.assertIn(SPEC_CITE, out)


class HistoryLanguage(unittest.TestCase):
    def history_scan(self, line, rel="fam/fam-skill/SKILL.md"):
        return scan({rel: CLEAN_SKILL + line + "\n"})

    def test_each_history_shape_fails(self):
        for line in (f"Changed on {DATE}.", "Tracked in issue #123.", "Fixed in #45.",
                     "This was legacy behavior.", "The step was formerly manual.", "Now renamed.",
                     "Previously it ran twice.", "That form is deprecated.", "Needs no longer apply.",
                     "Rule 3 (confirmed by the user).", "Behavior confirmed live."):
            with self.subTest(line=line):
                code, out = self.history_scan(line)
                self.assertEqual(code, 1, out)
                self.assertIn("history language", out)

    def test_reference_files_are_scanned(self):
        code, out = self.history_scan("Previously it ran twice.", rel="fam/fam-skill/references/r.md")
        self.assertEqual(code, 1, out)

    def test_allow_marker_exempts_the_line(self):
        code, out = self.history_scan("Quoted rule: previously it ran twice. <!-- allow-history -->")
        self.assertEqual(code, 0, out)

    def test_decisions_and_readme_are_out_of_scope(self):
        for rel in ("fam/fam-skill/DECISIONS.md", "fam/fam-skill/README.md"):
            with self.subTest(rel=rel):
                code, out = scan({rel: "Previously it ran twice.\n"})
                self.assertEqual(code, 0, out)

    def test_non_skill_prose_is_out_of_scope(self):
        code, out = scan({"fam/fam-skill/notes.md": "Previously it ran twice.\n"})
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
