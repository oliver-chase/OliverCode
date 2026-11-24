"""Grooming assigns epics within limits (#1099)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "backlog" / "scripts"))
import board_grooming  # noqa: E402
from lib import cmd_groom  # noqa: E402


class Gh:
    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        return ""


def story(title, body=""):
    return {"title": title, "body": body, "labels": []}


EPIC = story("Rank the work queue by files overlap", "Work type: Epic\nFiles area: scripts/lib/rank.py\nPriority: P1\n")


class TestEpics(unittest.TestCase):
    def run_assign(self, stories, mine=None):
        gh = Gh()
        mine = {} if mine is None else mine
        out = cmd_groom.assign_epics("o/r", stories, mine, set(), gh, "c.json")
        return out, mine, gh

    def test_shared_files_set_the_epic_line_and_comment_with_undo(self):
        stories = {1: EPIC, 2: story("Tune it", "Files area: scripts/lib/rank.py\nPriority: P2\n")}
        (linked, _), mine, gh = self.run_assign(stories)
        self.assertEqual([2], linked)
        self.assertIn("Epic: #1\nPriority: P2", stories[2]["body"])
        self.assertEqual({"2": 1}, mine["epics"])
        self.assertIn("--undo 2", gh.calls[-1][-1])

    def test_generic_words_never_match_and_a_comment_says_so(self):
        stories = {1: story("Groom status board lines", "Work type: Epic\n"), 2: story("Groom status board checks")}
        (linked, _), mine, gh = self.run_assign(stories)
        self.assertEqual([], linked)
        self.assertNotIn("Epic:", stories[2]["body"])
        self.assertIn("no epic", gh.calls[-1][-1])

    def test_no_open_epic_means_no_comment(self):
        _, _, gh = self.run_assign({2: story("Tune it", "Files area: scripts/lib/x.py\n")})
        self.assertEqual([], gh.calls)

    def test_epics_get_no_epic_line(self):
        stories = {1: EPIC, 2: story("Rank the work queue by files overlap", "Work type: Epic\nFiles area: scripts/lib/rank.py\n")}
        (linked, _), _, _ = self.run_assign(stories)
        self.assertEqual([], linked)

    def test_a_removed_line_is_not_set_again(self):
        stories = {1: EPIC, 2: story("Tune it", "Files area: scripts/lib/rank.py\n")}
        _, mine, _ = self.run_assign(stories)
        stories[2]["body"] = "Files area: scripts/lib/rank.py\n"
        (linked, _), _, _ = self.run_assign(stories, mine)
        self.assertEqual([], linked)

    def test_a_line_removed_after_two_passes_is_not_set_again(self):
        stories = {1: EPIC, 2: story("Tune it", "Files area: scripts/lib/rank.py\n")}
        _, mine, _ = self.run_assign(stories)
        self.run_assign(stories, mine)
        stories[2]["body"] = "Files area: scripts/lib/rank.py\n"
        (linked, _), _, _ = self.run_assign(stories, mine)
        self.assertEqual([], linked)

    def test_three_stories_with_a_theme_make_one_proposal(self):
        stories = {n: story(f"Cache invalidation {w}") for n, w in ((5, "alpha"), (6, "beta"), (7, "gamma"))}
        found = board_grooming.themes(stories)
        self.assertEqual([5, 6, 7], found[0][1])

    def test_blank_priority_comes_from_the_epic(self):
        stories = {1: EPIC, 2: story("Tune it", "Epic: #1\n")}
        got = {f["number"]: f["fields"] for f in cmd_groom.filled([], stories, [])}
        self.assertEqual("P1", got[2]["priority"])

    def test_proposal_queues_one_owner_line_with_a_real_command_and_files_nothing(self):
        stories = {n: story(f"Cache invalidation {w}") for n, w in ((5, "alpha"), (6, "beta"), (7, "gamma"))}
        found = board_grooming.themes(stories)
        with mock.patch.object(cmd_groom.cmd_owner, "add_once") as add:
            cmd_groom.propose_epics("b", found, stories, "o/r")
        add.assert_called_once()
        kwargs = add.call_args.kwargs
        self.assertTrue(kwargs["command"].startswith("olivercode story outbox add --repo o/r --title "))
        self.assertIn("#5, #6, #7", add.call_args.args[2])

    def test_undo_removes_the_line_and_records_the_epic(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "state.json"
            calls = []

            def gh(args):
                calls.append(args)
                return "Files area: x\nEpic: #1\nPriority: P2\n" if "--jq" in args else ""

            with mock.patch.object(cmd_groom, "_state", return_value=state):
                self.assertTrue(cmd_groom.undo_epic("o/r", 2, "c.json", gh))
            patch = next(c for c in calls if "PATCH" in c)
            self.assertNotIn("Epic:", patch[-1])
            self.assertEqual({"2": [1]}, json.loads(state.read_text())["o/r"]["epic_declined"])

    def test_undo_command_rejects_bad_arguments(self):
        self.assertEqual(1, cmd_groom.command_undo(["--undo", "x", "--config", "c"]))


if __name__ == "__main__":
    unittest.main()
