"""Tests for scripts/lib/skills_catalog.py: the list `olivercode skills` prints.

It covers the catalog itself and every frontmatter shape, including the ones that must not
crash or mislabel a skill.
"""

import tempfile
import unittest
from pathlib import Path

from _support import load_script

catalog = load_script("scripts/lib/skills_catalog.py", "skills_catalog")


class SkillsCatalogBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def skill(self, folder, text):
        path = self.root / "skills" / folder / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")
        return path


class ParseFrontmatter(SkillsCatalogBase):
    def test_quoted_values_lose_their_quotes(self):
        path = self.skill("a", "---\nname: \"alpha\"\ndescription: 'Does A: and more.'\n---\n")
        self.assertEqual(("alpha", "Does A: and more."), catalog._parse_skill_frontmatter(path))

    def test_no_frontmatter_at_all_keeps_the_folder_name(self):
        path = self.skill("some-skill", "# Some Skill\n\nNo frontmatter here.\n")
        self.assertEqual(("some-skill", ""), catalog._parse_skill_frontmatter(path))

    def test_a_folded_block_joins_its_lines(self):
        path = self.skill("folded", "---\nname: folded\ndescription: >\n  Line one.\n  Line two.\n---\n")
        self.assertEqual(("folded", "Line one. Line two."), catalog._parse_skill_frontmatter(path))

    def test_an_empty_name_keeps_the_folder_name(self):
        path = self.skill("folder-name", "---\nname:\ndescription: x\n---\n")
        self.assertEqual("folder-name", catalog._parse_skill_frontmatter(path)[0])

    def test_frontmatter_that_never_closes_is_ignored(self):
        path = self.skill("open", "---\nname: wrong\ndescription: never closed\n")
        self.assertEqual(("open", ""), catalog._parse_skill_frontmatter(path))

    def test_a_literal_block_joins_its_lines_and_stops_at_the_next_key(self):
        path = self.skill(
            "lit",
            "---\ndescription: |-\n  First line.\n\n  Second line.\nname: lit-skill\n---\n",
        )
        self.assertEqual(("lit-skill", "First line. Second line."), catalog._parse_skill_frontmatter(path))

    def test_an_unreadable_skill_file_falls_back_to_the_folder_name(self):
        path = self.root / "skills" / "broken" / "SKILL.md"
        path.mkdir(parents=True)  # a directory where the file should be
        self.assertEqual(("broken", ""), catalog._parse_skill_frontmatter(path))


class LoadSkills(SkillsCatalogBase):
    def test_no_skills_folder_means_an_empty_catalog(self):
        self.assertEqual([], catalog._load_skills(self.root))

    def test_skills_are_sorted_by_declared_name_and_folders_without_skill_md_skipped(self):
        self.skill("z-folder", "---\nname: apple\ndescription: first\n---\n")
        self.skill("a-folder", "---\nname: zebra\ndescription: last\n---\n")
        (self.root / "skills" / "docs").mkdir()
        (self.root / "skills" / "docs" / "README.md").write_text("not a skill")
        self.assertEqual(
            [("apple", "first"), ("zebra", "last")],
            catalog._load_skills(self.root),
        )

if __name__ == "__main__":
    unittest.main()
