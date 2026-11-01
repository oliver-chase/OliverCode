"""Smoke tests for _parse_skill_frontmatter() in scripts/lib/skills_catalog.py,
which `olivercode skills` lists from."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "skills_catalog", REPO_ROOT / "scripts/lib/skills_catalog.py")
catalog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(catalog)


class TestFrontmatterParser(unittest.TestCase):
    def _write_skill(self, tmpdir, content):
        skill_dir = Path(tmpdir) / "some-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(content, encoding="utf-8")
        return skill_md

    def test_plain_description(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = self._write_skill(
                tmpdir,
                "---\nname: some-skill\ndescription: A plain one-line description.\n---\n\n# Some Skill\n",
            )
            name, description = catalog._parse_skill_frontmatter(skill_md)
            self.assertEqual(name, "some-skill")
            self.assertEqual(description, "A plain one-line description.")

    def test_folded_block_scalar_description(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = self._write_skill(
                tmpdir,
                "---\nname: some-skill\ndescription: >\n  Line one of the description.\n  Line two continues it.\n---\n\n# Some Skill\n",
            )
            name, description = catalog._parse_skill_frontmatter(skill_md)
            self.assertEqual(name, "some-skill")
            self.assertEqual(description, "Line one of the description. Line two continues it.")

    def test_missing_frontmatter_falls_back_to_dirname(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = self._write_skill(tmpdir, "# Some Skill\n\nNo frontmatter here.\n")
            name, description = catalog._parse_skill_frontmatter(skill_md)
            self.assertEqual(name, "some-skill")  # falls back to the parent dir name
            self.assertEqual(description, "")


if __name__ == "__main__":
    unittest.main()
