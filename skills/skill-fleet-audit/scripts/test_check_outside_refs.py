"""Tests for check_outside_refs.py (OUTSIDE-REF-1)."""
import tempfile
import unittest
from pathlib import Path

import check_outside_refs as cor


class OutsideRefs(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for rel, text in {
            "fam/a/SKILL.md": "# A\n\nRead the rules.\n",
            "fam/a/references/x.md": "Source: the Notes vault folder.\n",
            "fam/a/references/y.md": "Lives in 04 - Growth Strategy.\n",
            "fam/a/references/z.md": "Also titled the Accelerator.\n",
            "fam/a/README.md": "The vault holds this.\n",
            "fam/a/tests/t.md": "The vault holds this.\n",
            "fam/a/scripts/test_x.py": "# the vault holds this\n",
            "fam/README.md": "The vault holds this.\n",
            "solo/SKILL.md": "Search the vault first.\n",
            "skill-governance/g/SKILL.md": "Never name the vault. Formerly 04 - Growth.\n",
            "skill-governance/g/references/ok.md": "Never name the vault or a name history such as formerly.\n",
        }.items():
            p = self.tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)

    def test_flags_skill_text_at_either_depth_and_skips_readmes_and_tests(self):
        files = sorted(str(r) for r, _, _ in cor.scan(self.tmp))
        self.assertEqual(files, ["fam/a/references/x.md", "fam/a/references/y.md", "fam/a/references/z.md",
                                 "skill-governance/g/SKILL.md", "solo/SKILL.md"])

    def test_the_governance_family_may_say_vault_but_not_name_a_numbered_folder(self):
        got = {str(r): t for r, _, t in cor.scan(self.tmp) if str(r).startswith("skill-governance")}
        self.assertEqual(["skill-governance/g/SKILL.md"], list(got))

    def test_staged_file_list_limits_the_scan(self):
        got = cor.scan(self.tmp, [self.tmp / "fam/a/references/x.md"])
        self.assertEqual([str(r) for r, _, _ in got], ["fam/a/references/x.md"])

    def test_the_name_field_is_not_a_place_the_skill_names(self):
        skill = self.tmp / "solo2/SKILL.md"
        skill.parent.mkdir()
        skill.write_text("---\nname: vault-folders\n---\n\nRead the rules.\n")
        self.assertEqual([], [r for r, _, _ in cor.scan(self.tmp) if str(r).startswith("solo2")])
        skill.write_text("---\nname: vault-folders\n---\n\nSearch the vault first.\n")
        self.assertEqual(1, len([r for r, _, _ in cor.scan(self.tmp) if str(r).startswith("solo2")]))

    def test_a_staged_file_that_names_the_framework_repo_fails(self):
        bad = self.tmp / "fam/a/notes.txt"
        bad.write_text("see " + "Oliver" + "Code docs\n")
        self.assertEqual(len(cor.repo_word_hits([str(bad)])), 1)
        self.assertEqual(cor.repo_word_hits([str(self.tmp / "fam/a/SKILL.md")]), [])

    def test_ablation_without_the_pattern_nothing_is_caught(self):
        saved = cor.PATTERN, cor.STRICT_PATTERN
        try:
            cor.PATTERN = cor.STRICT_PATTERN = __import__("re").compile(r"never matches here")
            self.assertEqual(cor.scan(self.tmp), [])
        finally:
            cor.PATTERN, cor.STRICT_PATTERN = saved


if __name__ == "__main__":
    unittest.main()
