"""Tests for check_skill_folder.py (SKILL-FOLDER-1)."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import check_skill_folder as csf


class SkillFolder(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        files = {
            "fam/a/SKILL.md": "# A\n", "fam/a/references/x.md": "x\n",
            "fam/a/DECISIONS.md": "dev\n",
            "fam/a/scripts/test_run.py": "x\n", "fam/a/scripts/run.py": "x\n",
            "fam/a/scripts/__pycache__/run.cpython-312.pyc": "x\n",
            "fam/a/.env.local": "KEY=1\n",
            "fam/DECISIONS.md": "family level\n",
            "solo/SKILL.md": "# S\n", "solo/DECISIONS.md": "owner\n"}
        for rel, text in files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)

    def test_scan_lists_developer_files_in_skill_folders_only(self):
        got = sorted(str(r) for r in csf.scan(self.root))
        self.assertEqual(got, ["fam/a/.env.local", "fam/a/DECISIONS.md",
                               "fam/a/scripts/__pycache__/run.cpython-312.pyc", "solo/DECISIONS.md"])

    def test_gate_checks_only_given_files(self):
        bad = csf.gate(self.root, [str(self.root / "fam/a/DECISIONS.md"), str(self.root / "fam/a/SKILL.md"),
                                    str(self.root / "fam/DECISIONS.md")])
        self.assertEqual([str(b) for b in bad], ["fam/a/DECISIONS.md"])

    def test_a_folder_argument_passes_the_gate(self):
        self.assertEqual(csf.gate(self.root, [str(self.root / "fam/a")]), [])

    def test_a_deleted_file_passes_the_gate(self):
        self.assertEqual(csf.gate(self.root, [str(self.root / "fam/a/gone/DECISIONS.md")]), [])

    def test_main_exits_one_for_a_developer_file_and_zero_for_a_clean_one(self):
        saved, csf.SKILLS_ROOT = csf.SKILLS_ROOT, self.root
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(csf.main([str(self.root / "fam/a/DECISIONS.md")]), 1)
                self.assertEqual(csf.main([str(self.root / "fam/a/SKILL.md")]), 0)
        finally:
            csf.SKILLS_ROOT = saved

    def test_is_dev(self):
        for rel in ("DECISIONS.md", "x/.env.local", "references/a.local", "scripts/a.pyc", "__pycache__/a.txt"):
            self.assertTrue(csf.is_dev(rel), rel)
        for rel in ("SKILL.md", "README.md", "scripts/run.py", "scripts/test_x.py", "references/guide.md", ".env.local.example"):
            self.assertFalse(csf.is_dev(rel), rel)


if __name__ == "__main__":
    unittest.main()
