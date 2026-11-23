"""A tracked file that names another fleet repo fails validate.sh, and a clean tree passes.

The fleet's names come from the registry this checkout reads. The test writes its own registry
into a scratch repo, so no owner name is needed and the registry on this machine is never read.
"""

import json
import sys
import unittest
from pathlib import Path

from _support import REPO_ROOT, git, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import fleet_name_check  # noqa: E402


def make_repo(case, profiles, files):
    """A scratch repo whose tracked registry names `profiles`, with each of `files` tracked."""
    repo = scratch_repo(temp_dir(case) / "repo")
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fixture")
    # The registry is never tracked: the real one is private, so the check reads it untracked.
    (repo / "shared").mkdir()
    (repo / "shared" / "repo-profiles.json").write_text(json.dumps({"profiles": profiles}), encoding="utf-8")
    return repo


class FleetNameCheckTests(unittest.TestCase):
    def test_a_tracked_line_naming_a_fleet_repo_fails_with_file_and_line(self):
        repo = make_repo(self, {"alpha-repo": {}, "olivercode": {}},
                         {"docs/note.md": "one\nsee alpha-repo for the rest\n"})
        failures = fleet_name_check.check_all(repo)
        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0].startswith("docs/note.md:2 "), failures[0])

    def test_a_clean_tree_passes(self):
        repo = make_repo(self, {"alpha-repo": {}}, {"docs/note.md": "nothing private here\n"})
        self.assertEqual(fleet_name_check.check_all(repo), [])

    def test_the_framework_name_and_short_names_are_not_fleet_names(self):
        repo = make_repo(self, {"olivercode": {}, "ab": {}}, {"docs/note.md": "olivercode and ab appear\n"})
        self.assertEqual(fleet_name_check.check_all(repo), [])

    def test_a_longer_word_containing_a_name_does_not_match(self):
        repo = make_repo(self, {"alpha-repo": {}}, {"docs/note.md": "alpha-repos are plural\n"})
        self.assertEqual(fleet_name_check.check_all(repo), [])

    def test_an_empty_registry_has_no_names_to_find(self):
        repo = make_repo(self, {}, {"docs/note.md": "alpha-repo appears but no registry names it\n"})
        self.assertEqual(fleet_name_check.check_all(repo), [])


if __name__ == "__main__":
    unittest.main()
