"""The leak scan names a tracked file that holds the owner's identifier, exempts the board file and writes a one-commit neutral release (#559)."""

import unittest
from pathlib import Path

from _support import REPO_ROOT, git, load_script, scratch_repo, temp_dir

leak_scan = load_script("scripts/qa/leak_scan.py")


def commit_as(repo: Path, name: str, mail: str, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", f"user.name={name}", "-c", f"user.email={mail}", "commit", "-q", "-m", message)


class TestLeakScan(unittest.TestCase):
    def setUp(self):
        self.repo = scratch_repo(temp_dir(self))
        git(self.repo, "remote", "add", "origin", "https://github.com/zebulon-quartz/Thing.git")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "backlog-config.json").write_text('{"repoOwner": "zebulon-quartz"}')
        (self.repo / "notes.md").write_text("see github.com/zebulon-quartz/Thing/issues/1")
        (self.repo / "clean.md").write_text("nothing here")
        commit_as(self.repo, "Zebulon Quartz", "zebulon" + chr(64) + "quartzmail.test", "Add files")

    def test_a_hit_is_named_and_the_board_file_is_exempt(self):
        result = leak_scan.scan(self.repo)
        self.assertEqual(result["files"], ["notes.md"])
        self.assertEqual(result["board"], ["docs/backlog-config.json"])
        self.assertGreaterEqual(result["authors"], 1)
        self.assertIn("notes.md", leak_scan.report(result))
        self.assertNotIn("zebulon", leak_scan.report(result).lower())

    def test_a_local_path_origin_names_no_owner(self):
        git(self.repo, "remote", "set-url", "origin", "/srv/Folders/Thing")
        self.assertNotIn("folders", leak_scan.identifiers(self.repo))

    def test_a_clean_repo_exits_zero(self):
        (self.repo / "notes.md").write_text("nothing")
        commit_as(self.repo, "Zebulon Quartz", "zebulon" + chr(64) + "quartzmail.test", "Scrub")
        self.assertEqual(leak_scan.scan(self.repo)["files"], [])

    def test_a_leak_added_inside_a_diff_hunk_counts_as_a_commit_hit(self):
        (self.repo / "clean.md").write_text("line one\nline two\nwrote to zebulon-quartz here\n")
        commit_as(self.repo, "Other Person", "other" + chr(64) + "elsewhere.test", "Add a leak")
        self.assertIn(git(self.repo, "rev-parse", "--short", "HEAD").stdout.strip(), leak_scan.scan(self.repo)["commits"])

    def test_the_release_is_one_commit_with_a_neutral_author(self):
        dest = temp_dir(self) / "out"
        leak_scan.release(self.repo, dest)
        self.assertEqual(git(dest, "rev-list", "--count", "HEAD").stdout.strip(), "1")
        self.assertEqual(git(dest, "log", "-1", "--format=%an <%ae>").stdout.strip(), "OliverCode Release <" + leak_scan.NEUTRAL_AUTHOR[1] + ">")

    def test_this_repo_has_no_hit_in_a_tracked_file(self):
        if not leak_scan.identifiers(REPO_ROOT):
            self.skipTest("this checkout has no history or origin to name an owner, so the scan has nothing to look for")
        result = leak_scan.scan(REPO_ROOT)
        self.assertEqual(result["files"], [], "an owner identifier sits in a tracked file; remove it or derive it from docs/backlog-config.json")


if __name__ == "__main__":
    unittest.main()
