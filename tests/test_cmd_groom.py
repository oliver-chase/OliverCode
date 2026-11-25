"""The word leak is not a security story (#1039), and grooming checks filed stories against each other (#1134)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, git, scratch_repo

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_groom  # noqa: E402


class TestPriority(unittest.TestCase):
    def test_the_word_leak_is_not_a_security_story_but_a_leaked_key_is(self):
        self.assertEqual("P2", cmd_groom.priority_of({"title": "Fix a memory leak in the cache", "body": ""}))
        self.assertEqual("P0", cmd_groom.priority_of({"title": "A leaked token in the log", "body": ""}))
        self.assertEqual("P0", cmd_groom.priority_of({"title": "Keys leaked in the log", "body": ""}))


class TestSize(unittest.TestCase):
    def test_a_stated_small_size_is_raised_to_match_a_wide_files_area(self):
        files = ", ".join(f"scripts/file_{i}.py" for i in range(19))
        story = {"body": f"Size: XS\n\nFiles area: {files}\n"}
        self.assertEqual("XL", cmd_groom.size_of(story))

    def test_a_stated_size_that_covers_the_files_area_is_preserved(self):
        story = {"body": "Size: M\n\nFiles area: scripts/a.py\n"}
        self.assertEqual("M", cmd_groom.size_of(story))

    def test_ready_card_size_is_raised_but_backlog_card_is_not_rewritten(self):
        story = {"body": "Size: XS\n\nFiles area: " + ", ".join(f"scripts/f{i}.py" for i in range(9))}
        items = [{"content": {"number": 42}, "size": "XS", "status": "Ready"}]
        ready = cmd_groom.filled(items, {42: story}, [])
        self.assertEqual("L", ready[0]["fields"]["size"])
        items[0]["status"] = "Backlog"
        backlog = cmd_groom.filled(items, {42: story}, [])
        self.assertNotIn("size", backlog[0]["fields"])

    def test_a_missing_board_size_is_filled_even_when_the_story_is_not_ready(self):
        story = {"body": "Size: S\n\nFiles area: scripts/a.py"}
        items = [{"content": {"number": 43}, "size": "", "status": "Backlog"}]
        result = cmd_groom.filled(items, {43: story}, [])
        self.assertEqual("S", result[0]["fields"]["size"])


if __name__ == "__main__":
    unittest.main()


def story(files="", body="", title="A story", given="Given a thing", epic=""):
    gher = f"```gherkin\nFeature: F\n  Scenario: S\n    {given}\n    When it runs\n    Then it works\n```\n"
    return {"title": title, "body": gher + (f"Epic: #{epic}\n" if epic else "") + (f"Files area: {files}\n" if files else "") + body}


class TestCrossStoryChecks(unittest.TestCase):
    def test_two_waiting_stories_that_share_a_file_and_do_not_block_each_other_are_a_pair(self):
        stories = {5: story("a.py, b.py"), 6: story("b.py, c.py"), 7: story("z.py")}
        self.assertEqual([(5, 6, ["b.py"])], cmd_groom.shared_file_pairs(stories, {5, 6, 7}))

    def test_a_blocked_by_line_either_way_clears_the_pair_and_an_epic_or_unwaiting_story_is_left_out(self):
        self.assertEqual([], cmd_groom.shared_file_pairs({5: story("b.py"), 6: story("b.py", body="Blocked by: #5\n")}, {5, 6}))
        self.assertEqual([], cmd_groom.shared_file_pairs({5: story("b.py", body="Blocked by: #6\n"), 6: story("b.py")}, {5, 6}))
        self.assertEqual([], cmd_groom.shared_file_pairs({5: story("b.py"), 6: story("b.py", body="Work type: Epic\n")}, {5, 6}))
        self.assertEqual([], cmd_groom.shared_file_pairs({5: story("b.py"), 6: story("b.py")}, {5}))

    def test_matching_given_lines_under_different_titles_are_a_duplicate_pair_that_keeps_the_lower_number(self):
        stories = {5: story(title="Add alerts", given="Given the nightly job failed"), 6: story(title="Notify on failure", given="Given  the nightly JOB failed"),
                   7: story(title="Other", given="Given something else")}
        pairs = cmd_groom.same_given_pairs(stories, {5, 6, 7})
        self.assertEqual(["#5 and #6 share their Given lines under different titles, keep #5"], pairs)
        self.assertEqual((5, 6), cmd_groom.pair_of(pairs[0]))  # the line is in the form the duplicate flow reads
        self.assertEqual([], cmd_groom.same_given_pairs({5: story(title="Same"), 6: story(title="same")}, {5, 6}), "equal titles are the exact-duplicate case")

    def test_a_story_that_two_stories_name_as_their_epic_is_a_split_parent_unless_it_is_an_epic(self):
        stories = {10: story(), 11: story(epic=10), 20: story(body="Work type: Epic\n"), 21: story(epic=20), 22: story(epic=20)}
        self.assertEqual({}, cmd_groom.split_parents(stories, {}), "one open child is not a split")
        self.assertEqual({10: [11, 30]}, cmd_groom.split_parents(stories, {30: 10}), "a closed child counts")
        self.assertNotIn(20, cmd_groom.split_parents(stories, {}), "an epic is meant to have children")

    def test_a_line_count_that_is_off_by_more_than_ten_percent_is_reported_with_the_current_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scratch_repo(root, branch="main")
            (root / "mod.py").write_text("x = 1\n" * 100)
            git(root, "add", ".")
            git(root, "commit", "-q", "-m", "m")
            stories = {5: story(body="mod.py is at 150 lines today\n"), 6: story(body="`mod.py` is at 105 lines\n"), 7: story(body="no claim\n")}
            self.assertEqual([(5, "mod.py", 150, 100)], cmd_groom.stale_line_claims(stories, root))

    def test_each_finding_is_commented_once_and_a_split_parent_is_returned_for_backlog(self):
        posted = []
        run = lambda args: (posted.append(args), "ok")[1]
        stories = {5: story("b.py"), 6: story("b.py"), 10: story(), 11: story(epic=10), 12: story(epic=10)}
        mine = {}
        moved = cmd_groom.comment_story_checks("o/r", stories, {5, 6, 10}, {}, Path("."), mine, run)
        self.assertEqual({10}, moved)
        bodies = [a[-1] for a in posted]
        self.assertEqual(3, len(bodies), bodies)  # one per story of the file pair, one on the parent
        self.assertTrue(any("shares b.py" in b and "#6" in b for b in bodies))
        self.assertTrue(any("#11, #12" in b and "Backlog" in b for b in bodies))
        posted.clear()
        cmd_groom.comment_story_checks("o/r", stories, {5, 6, 10}, {}, Path("."), mine, run)
        self.assertEqual([], posted, "the same finding is not commented twice")
