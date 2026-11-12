"""scripts/lib/consistency_check.py: each check passes on this repo and fails when one thing breaks."""

import unittest

from _support import REPO_ROOT, load_script, temp_dir

load_script("scripts/olivercode")  # puts scripts/ on sys.path
from lib import consistency_check as cc  # noqa: E402


def skill(root, name, body="Body.\n", declared=None):
    folder = root / "skills" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {declared or name}\ndescription: x\n---\n\n{body}")


class ConsistencyCheck(unittest.TestCase):
    def setUp(self):
        self.root = temp_dir(self)
        skill(self.root, "alpha")
        (self.root / "skills" / "INDEX.md").write_text("| `alpha` | x |\n")

    def test_this_repo_is_consistent(self):
        self.assertEqual([], cc.check_all(REPO_ROOT))

    def test_a_matching_index_passes(self):
        self.assertEqual([], cc.check_all(self.root))

    def test_a_skill_missing_from_the_index_fails(self):
        skill(self.root, "beta")
        self.assertIn("beta", " ".join(cc.check_skill_index(self.root)))

    def test_a_frontmatter_name_that_differs_from_the_folder_fails(self):
        skill(self.root, "gamma", declared="other")
        (self.root / "skills" / "INDEX.md").write_text("| `alpha` | x |\n| `gamma` | x |\n")
        self.assertIn("declares name: other", " ".join(cc.check_skill_index(self.root)))

    def test_a_reference_to_a_skill_this_repo_does_not_ship_fails(self):
        ghost = "/".join(("skills", "ghost"))
        (self.root / "skills" / "alpha" / "SKILL.md").write_text(f"---\nname: alpha\n---\n\nSee {chr(96)}{ghost}{chr(96)}.\n")
        self.assertIn("skills/ghost", " ".join(cc.check_skill_cross_references(self.root)))


if __name__ == "__main__":
    unittest.main()
