"""A tracked file that names another of the owner's repos fails validate.sh, and a clean tree passes.

The names are the git checkouts directly under repoRoot and `privateRepos` in olivercode.local.json. Each test
writes its own root and config into a scratch folder, so no real owner name is needed and this machine's config is never read.
"""

import json
import os
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, git, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import fleet_name_check  # noqa: E402


def make_repo(case, checkouts, files, private=()):
    """A scratch repo tracking `files`, under a repoRoot holding a checkout per name in `checkouts` and a config naming `private`."""
    root = temp_dir(case)
    for name in checkouts:
        (root / name / ".git").mkdir(parents=True)
    repo = scratch_repo(root / "repo")
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fixture")
    config = root / "local.json"
    config.write_text(json.dumps({"repoRoot": str(root), "privateRepos": {n: str(root / n) for n in private}}), encoding="utf-8")
    patch = mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(config)})
    patch.start()
    case.addCleanup(patch.stop)
    return repo


class FleetNameCheckTests(unittest.TestCase):
    def test_a_tracked_line_naming_a_checkout_fails_with_file_and_line(self):
        repo = make_repo(self, ["widget-app"], {"docs/note.md": "one\nsee acme/widget-app for the rest\n"})
        failures = fleet_name_check.check_all(repo)
        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0].startswith("docs/note.md:2 "), failures[0])

    def test_a_tracked_line_naming_a_private_repo_fails(self):
        repo = make_repo(self, [], {"docs/note.md": "see acme/notes-vault\n"}, private=["notes-vault"])
        self.assertEqual(len(fleet_name_check.check_all(repo)), 1)

    def test_a_bare_common_word_name_does_not_match_but_owner_name_does(self):
        repo = make_repo(self, ["docs", "site"], {"a.md": "docs/site/index.md and the docs\n", "b.md": "see acme/docs\n"})
        failures = fleet_name_check.check_all(repo)
        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0].startswith("b.md:1 "), failures[0])

    def test_a_clean_tree_passes(self):
        repo = make_repo(self, ["widget-app"], {"docs/note.md": "nothing private here\n"})
        self.assertEqual(fleet_name_check.check_all(repo), [])

    def test_the_framework_name_and_short_names_are_not_other_repo_names(self):
        repo = make_repo(self, ["olivercode", "ab"], {"docs/note.md": "olivercode and ab appear\n"})
        self.assertEqual(fleet_name_check.check_all(repo), [])

    def test_a_longer_word_containing_a_name_does_not_match(self):
        repo = make_repo(self, ["widget-app"], {"docs/note.md": "widget-apps are plural\n"})
        self.assertEqual(fleet_name_check.check_all(repo), [])

    def test_a_machine_with_no_other_repo_has_no_names_to_find(self):
        repo = make_repo(self, [], {"docs/note.md": "widget-app appears but nothing names it\n"})
        self.assertEqual(fleet_name_check.check_all(repo), [])


if __name__ == "__main__":
    unittest.main()
