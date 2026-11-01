"""Fixture tests for check_retired_terms.py: a retired term in a SKILL.md, README.md or governance
doc fails. A decision file, an allow marker, a test folder or a clean file never fails.

Run from this scripts/ folder: python3 -m unittest test_check_retired_terms
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import check_retired_terms as rt

# Built from parts so the real-fleet scan does not read this file as a teaching doc.
OLD_LIST = "OLD" + "_LIST_TERM"
OLD_PHRASE = "Declare each item in the " + "legacy-thing" + " file."
TERMS = {"terms": [
    {"id": "old-list", "pattern": OLD_LIST, "decision": "DEC-1", "use": "Use the new list."},
    {"id": "old-phrase", "pattern": "legacy[-_]thing", "decision": "DEC-2", "use": "Use the new file."},
    {"id": "new-owner", "pattern": "never-matches-xyz", "decision": "NEW-2", "use": "Owns a reversal."},
]}


def run(root, terms=TERMS):
    """Run main() over `root` with a temporary term list; return (exit code, stdout)."""
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "terms.json"
        listing.write_text(json.dumps(terms), encoding="utf-8")
        out = io.StringIO()
        with mock.patch.object(rt, "LIST_FILE", listing), mock.patch.object(sys, "argv", ["check_retired_terms.py", str(root)]), \
                contextlib.redirect_stdout(out):
            code = rt.main()
    return code, out.getvalue()


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ScannedFleetData(unittest.TestCase):
    def test_a_scanned_fleet_reads_its_own_term_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ".fleet-audit/retired-terms.json", json.dumps(TERMS))
            write(tmp, "fam/a/SKILL.md", f"Still says {OLD_LIST}.\n")
            out = io.StringIO()
            with mock.patch.object(sys, "argv", ["check_retired_terms.py", tmp]), contextlib.redirect_stdout(out):
                code = rt.main()
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("old-list", out.getvalue())


class Scan(unittest.TestCase):
    def test_term_in_a_skill_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "fam/alpha/SKILL.md", f"Set {OLD_LIST} in the script.\n")
            code, out = run(tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("old-list", out)
        self.assertIn("DEC-1", out)

    def test_phrase_in_a_readme_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "fam/README.md", OLD_PHRASE + "\n")
            code, out = run(tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("old-phrase", out)

    def test_term_in_a_governance_doc_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "skill-governance/skill-creation/references/baseline.md", f"Use {OLD_LIST}.\n")
            code, out = run(tmp)
        self.assertEqual(code, 1, out)

    def test_clean_tree_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "fam/alpha/SKILL.md", "Declare each item in the new file.\n")
            write(tmp, "skill-governance/README.md", "Governance.\n")
            code, out = run(tmp)
        self.assertEqual(code, 0, out)

    def test_decisions_file_may_name_the_term(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "fam/DECISIONS.md", f"| `X` | {OLD_LIST} was retired. |\n")
            write(tmp, "skill-governance/DECISIONS.md", f"| `Y` | {OLD_LIST} was retired. |\n")
            code, out = run(tmp)
        self.assertEqual(code, 0, out)

    def test_allow_marker_skips_the_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "fam/alpha/SKILL.md", f"Old name: {OLD_LIST}. <!-- allow-retired -->\n")
            code, out = run(tmp)
        self.assertEqual(code, 0, out)

    def test_a_reference_file_is_scanned_and_a_tests_folder_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "fam/alpha/tests/SKILL.md", f"{OLD_LIST}\n")
            code, out = run(tmp)
            self.assertEqual(code, 0, out)
            write(tmp, "fam/alpha/references/scratch.md", f"{OLD_LIST}\n")
            code, out = run(tmp)
        self.assertEqual(code, 1, out)

    def test_phrase_matches_case_and_spacing_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "fam/alpha/SKILL.md", "Read the LEGACY" + "_Thing file and copy it.\n")
            code, out = run(tmp)
        self.assertEqual(code, 1, out)


class Reversals(unittest.TestCase):
    ROW = "| `OLD-1` | The old model. Reversed by `NEW-9`. |\n"

    def test_a_reversal_with_no_list_row_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "skill-governance/DECISIONS.md", self.ROW)
            code, out = run(tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("NEW-9", out)

    def test_a_reversal_whose_decision_owns_a_row_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "skill-governance/DECISIONS.md", "| `OLD-1` | The old model. Reversed by `NEW-2`. |\n")
            code, out = run(tmp)
        self.assertEqual(code, 0, out)

    def test_the_allow_marker_excuses_a_reversal_that_retires_no_wording(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "fam/DECISIONS.md", self.ROW.rstrip() + " <!-- allow-retired -->\n")
            code, out = run(tmp)
        self.assertEqual(code, 0, out)


class ListFile(unittest.TestCase):
    @unittest.skipUnless(rt.LIST_FILE.is_file(), "this fleet keeps no audit data here; its own gates read it")
    def test_every_entry_names_a_real_decision(self):
        decisions = "".join(p.read_text(encoding="utf-8", errors="ignore")
                            for p in rt.FLEET_ROOT.rglob("DECISIONS.md") if "worktrees" not in p.parts)
        for term_id, _rx, decision, use in rt.load_terms():
            self.assertIn(f"`{decision}`", decisions, term_id)
            self.assertTrue(use.strip(), term_id)

    @unittest.skipUnless(rt.LIST_FILE.is_file(), "this fleet keeps no audit data here; its own gates read it")
    def test_the_real_list_loads(self):
        self.assertIsInstance(rt.load_terms(), list)

    def test_an_empty_list_finds_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "fam/alpha/SKILL.md", f"Set {OLD_LIST}.\n")
            self.assertEqual(run(tmp, {"terms": []})[0], 0)


if __name__ == "__main__":
    unittest.main()
