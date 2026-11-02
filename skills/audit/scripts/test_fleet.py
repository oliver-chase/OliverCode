"""Tests for _fleet.py: the fleet root, the scan-root argument and the shared skill walk."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fleet  # noqa: E402


class ScanRoot(unittest.TestCase):
    def test_first_non_flag_argument_is_the_root(self):
        self.assertEqual(_fleet.scan_root(["--blocking", "somewhere", "other"]), Path("somewhere"))

    def test_no_path_argument_returns_the_default(self):
        self.assertEqual(_fleet.scan_root(["--weight"]), _fleet.FLEET_ROOT)
        self.assertEqual(_fleet.scan_root([], Path("fallback")), Path("fallback"))


class FindSkills(unittest.TestCase):
    def make(self, tmp, rels):
        root = Path(tmp)
        for rel in rels:
            (root / rel).mkdir(parents=True)
            (root / rel / "SKILL.md").write_text("x\n", encoding="utf-8")
        return root

    def test_finds_root_level_and_family_level_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make(tmp, ["solo", "fam/a", "fam/b"])
            found = [p.relative_to(root).as_posix() for p in _fleet.find_skills(root)]
        self.assertEqual(found, ["fam/a", "fam/b", "solo"])

    def test_skips_docs_hidden_dirs_and_anything_deeper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make(tmp, ["fam/a", "docs/c", ".hidden/e", "fam/a/inner", "fam/deep/er/f", "fam/.h/g"])
            found = [p.relative_to(root).as_posix() for p in _fleet.find_skills(root)]
        self.assertEqual(found, ["fam/a"])

    def test_a_single_skill_folder_is_its_own_scan_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make(tmp, ["fam/a"])
            self.assertEqual(_fleet.find_skills(root / "fam" / "a"), [root / "fam" / "a"])

    def test_a_missing_root_has_no_skills(self):
        self.assertEqual(_fleet.find_skills(Path("/nonexistent-fleet-root")), [])


class FleetRoot(unittest.TestCase):
    def test_the_environment_variable_points_the_fleet_elsewhere(self):
        self.assertEqual(_fleet.fleet_root({_fleet.ROOT_ENV: "/tmp/elsewhere"}), Path("/tmp/elsewhere"))

    def test_without_the_variable_the_root_is_the_skills_folder_this_skill_sits_in(self):
        self.assertEqual(_fleet.fleet_root({}), Path(_fleet.__file__).resolve().parents[2])


class DescriptionWords(unittest.TestCase):
    def test_quoted_and_folded_descriptions_count_the_same(self):
        quoted = "---\nname: x\ndescription: \"One two three.\"\n---\n"
        folded = "---\nname: x\ndescription: >\n  One two three.\n---\n"
        self.assertEqual(_fleet.description_words(folded), 3)
        self.assertEqual(_fleet.description_words(quoted), 3)

    def test_no_description_is_zero(self):
        self.assertEqual(_fleet.description_words("---\nname: x\n---\n"), 0)


if __name__ == "__main__":
    unittest.main()
