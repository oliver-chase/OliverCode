"""Tests for check_portability.py: the governance citation and an end-to-end run. Fixtures live in temp folders.

Run from this scripts/ folder: python3 -m unittest test_check_portability
"""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

import check_portability as cp

CITE = "Follow skill-governance/skill-creation/SKILL.md first."


class GovernanceCitation(unittest.TestCase):
    def test_a_loaded_governance_path_is_a_finding(self):
        self.assertEqual(len(cp.check_governance_citation("fam", Path("SKILL.md"), CITE)), 1)

    def test_a_plain_mention_without_a_verb_passes(self):
        self.assertEqual(cp.check_governance_citation("fam", Path("SKILL.md"), "See also skill-governance/x.md."), [])

    def test_governance_itself_may_cite_its_own_paths(self):
        self.assertEqual(cp.check_governance_citation("skill-governance", Path("SKILL.md"), CITE), [])


class Run(unittest.TestCase):
    def run_gate(self, files, argv=()):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, text in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text, encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cp.main([str(root), *argv])
        return code, out.getvalue()

    def test_clean_skill_is_green(self):
        code, out = self.run_gate({"fam/skill/SKILL.md": "Plain skill. Run the build.\n"})
        self.assertEqual(code, 0, out)

    def test_a_skill_citing_governance_blocks(self):
        code, out = self.run_gate({"fam/skill/SKILL.md": CITE + "\n"})
        self.assertEqual(code, 1, out)
        self.assertIn("never travels", out)

    def test_a_skill_inside_the_governance_family_may_cite_it(self):
        code, out = self.run_gate({"skill-governance/skill/SKILL.md": CITE + "\n"})
        self.assertEqual(code, 0, out)

    def test_a_single_skill_folder_as_the_scan_root_still_knows_its_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "skill-governance" / "skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(CITE + "\n")
            cwd = os.getcwd()
            os.chdir(skill)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cp.main(["."]), 0)
            finally:
                os.chdir(cwd)

    def test_a_citation_in_a_reference_file_blocks(self):
        code, out = self.run_gate({"fam/skill/SKILL.md": "x\n", "fam/skill/references/a.md": CITE + "\n"})
        self.assertEqual(code, 1, out)

    def test_ablation_check_off_lets_the_citation_through(self):
        saved = cp.check_governance_citation
        cp.check_governance_citation = lambda *a, **k: []
        try:
            code, _ = self.run_gate({"fam/skill/SKILL.md": CITE + "\n"})
        finally:
            cp.check_governance_citation = saved
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
