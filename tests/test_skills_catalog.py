"""`skill_dirs` lists each folder under skills/ that holds a SKILL.md, sorted by name."""

import tempfile
import unittest
from pathlib import Path

from _support import load_script

load_script("scripts/olivercode", "olivercode_launcher_skills_catalog")
from lib.skills_catalog import skill_dirs  # noqa: E402


class TestSkillDirs(unittest.TestCase):
    def test_lists_only_folders_with_a_skill_file_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("zeta", "alpha"):
                (root / name).mkdir()
                (root / name / "SKILL.md").write_text("x", encoding="utf-8")
            (root / "empty").mkdir()
            (root / "note.md").write_text("x", encoding="utf-8")
            self.assertEqual([p.name for p in skill_dirs(root)], ["alpha", "zeta"])


if __name__ == "__main__":
    unittest.main()
