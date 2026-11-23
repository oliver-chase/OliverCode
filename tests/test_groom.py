"""`olivercode board groom`: drifted and missing cards are fixed and an unchanged repo costs no board read (#660)."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "backlog" / "scripts"))
import check_board_hygiene  # noqa: E402
from lib import cmd_groom  # noqa: E402


def drift(items, states):
    return [{"number": n, "fields": {"status": "Complete" if k == "close" else "Backlog"}} for n, k in check_board_hygiene.status_drift(items, states)]


class TestGroom(unittest.TestCase):
    def test_drift_is_fixed_and_an_unchanged_repo_is_skipped(self):
        home, repo = temp_dir(self), temp_dir(self)
        (repo / "docs").mkdir()
        config = repo / "docs" / "backlog-config.json"
        config.write_text(json.dumps({"repoOwner": "o", "repoName": "r"}))
        cards = [{"content": {"number": 1}, "status": "Ready"}, {"content": {"number": 2}, "status": "Complete"}]
        fixes = drift(cards, {1: "CLOSED", 2: "OPEN", 3: "OPEN", 4: "CLOSED"})
        self.assertEqual([f["number"] for f in fixes], [1, 2, 3])
        self.assertEqual(fixes[0]["fields"]["status"], "Complete")
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}), mock.patch.object(cmd_groom.gh_budget, "refusal", return_value=""), \
                mock.patch.object(cmd_groom.gh_budget, "points_refusal", return_value=""), mock.patch.object(cmd_groom, "fingerprint", return_value="fp"), \
                mock.patch("check_board_hygiene.load_items", return_value=cards) as load, mock.patch("board_rest.repo_issues", return_value=[{"number": n, "state": s} for n, s in {1: "CLOSED", 2: "OPEN", 3: "OPEN", 4: "CLOSED"}.items()]), \
                mock.patch.object(cmd_groom, "open_stories", return_value={}), mock.patch("batch_project.main") as batch, mock.patch.object(cmd_groom.cmd_owner, "note") as note:
            self.assertTrue(cmd_groom.groom_board("R", config, False, 1.0))
            self.assertTrue(cmd_groom.groom_board("R", config, False, 2.0))
            self.assertEqual(load.call_count, 1)
            self.assertEqual(batch.call_count, 1)
            self.assertEqual(sum(1 for c in note.call_args_list if "fixed 3 card(s)" in c.args[1]), 1)


class TestGroomNames(unittest.TestCase):
    """#840: groom flags a name that differs from its README heading and stays quiet when every name matches."""

    def groom(self, readme):
        home, repo = temp_dir(self), temp_dir(self)
        (repo / "docs").mkdir()
        (repo / "README.md").write_text(readme, encoding="utf-8")
        config = repo / "docs" / "backlog-config.json"
        config.write_text(json.dumps({"repoOwner": "o", "repoName": "r"}))
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}), mock.patch.object(cmd_groom.gh_budget, "refusal", return_value=""), \
                mock.patch.object(cmd_groom.gh_budget, "points_refusal", return_value=""), mock.patch.object(cmd_groom, "fingerprint", return_value="fp"), \
                mock.patch("check_board_hygiene.load_items", return_value=[]), mock.patch("board_rest.repo_issues", return_value=[]), \
                mock.patch.object(cmd_groom, "open_stories", return_value={}), mock.patch("batch_project.main"), mock.patch.object(cmd_groom.cmd_owner, "note") as note:
            self.assertTrue(cmd_groom.groom_board("R", config, True, 1.0))
        return [c.args[1] for c in note.call_args_list if "name difference" in c.args[1]]

    def test_an_identifier_that_differs_from_its_heading_is_flagged_with_the_fix(self):
        notes = self.groom("## Gallery\n\nBuilt hourly by `olivercode showcase`.\n")
        self.assertEqual(len(notes), 1)
        self.assertIn('"Gallery"', notes[0])
        self.assertIn("`showcase`", notes[0])
        self.assertIn("use one name in both", notes[0])

    def test_names_that_all_match_flag_nothing(self):
        self.assertEqual(self.groom("## Dispatch planning\n\nRun `olivercode dispatch`.\n"), [])


class TestGroomFields(unittest.TestCase):
    def card(self, number, status="Backlog", **fields):
        return {"content": {"number": number, "title": f"t{number}"}, "status": status, **fields}

    def test_blank_priority_and_size_are_filled_and_an_unblocked_backlog_story_is_readied(self):
        items = [self.card(1), self.card(2, priority="P1", size="S"), self.card(3), self.card(4, **{"work Type": "Epic"}), self.card(5)]
        stories = {1: {"title": "Add a thing", "body": "Priority: P1. Size: M. Work type: Story."},
                   2: {"title": "Fine", "body": "x"},
                   3: {"title": "Leaks a secret", "body": "short", "labels": []},
                   4: {"title": "Epic", "body": "x"},
                   5: {"title": "Held", "body": "Blocked by #3", "labels": []}}
        got = {f["number"]: f["fields"] for f in cmd_groom.filled(items, stories, [])}
        self.assertEqual(got[1], {"priority": "P1", "size": "M", "status": "Ready"})
        self.assertEqual(got[2], {"status": "Ready"})
        self.assertEqual(got[3], {"priority": "P0", "size": "XS", "status": "Ready"})
        self.assertNotIn("status", got[4])
        self.assertNotIn("status", got[5])

    def test_a_flagged_story_stays_in_backlog_while_an_unflagged_one_is_readied(self):
        items = [self.card(1), self.card(2)]
        stories = {1: {"title": "Add a thing", "body": "Priority: P1. Size: M."}, 2: {"title": "Rewrite me", "body": "Priority: P1. Size: M."}}
        got = {f["number"]: f["fields"] for f in cmd_groom.filled(items, stories, [], hold={2})}
        self.assertEqual(got[1]["status"], "Ready")
        self.assertNotIn("status", got.get(2, {}))

    def test_both_stories_of_a_duplicate_pair_are_held(self):
        self.assertEqual({12, 34}, cmd_groom.pair_numbers(["#12 and #34 share add, thing: possible duplicate or superseded pair, close one or link them"]))

    def test_a_card_that_is_missing_is_added_with_its_fields_in_one_fix(self):
        got = cmd_groom.filled([], {7: {"title": "bug: it fails", "body": "x" * 1500}}, drift([], {7: "OPEN"}))
        self.assertEqual(got, [{"number": 7, "fields": {"status": "Ready", "priority": "P1", "size": "M"}}])

    def test_a_failed_read_of_the_open_stories_raises_so_groom_records_no_ok(self):
        with self.assertRaises(RuntimeError):
            cmd_groom.open_stories("o/r", run=lambda args: None)

    def test_stale_means_no_success_or_one_older_than_the_limit(self):
        self.assertTrue(cmd_groom.stale(24, now=1e6, state={}, slugs=["a/b"]))
        self.assertTrue(cmd_groom.stale(24, now=1e6, state={"a/b": {"ok": 1e6 - 25 * 3600}}, slugs=["a/b"]))
        self.assertFalse(cmd_groom.stale(24, now=1e6, state={"a/b": {"ok": 1e6 - 3600}}, slugs=["a/b"]))
        self.assertTrue(cmd_groom.stale(48, now=1e6, state={"a/b": {"ok": 1e6 - 1}}, slugs=["a/b", "c/d"]))


class TestGroomImportedPriorities(unittest.TestCase):
    """#743: a priority copied in from a file is flagged until one rerank story judges it against the code."""

    def fixture(self):
        body = "**As the owner**, I want a thing, so that x.\n\nDetail: Source: gap-analysis-2.md (S{n}).\nPriority: P1. Size: S. Work type: Story."
        stories = {n: {"number": n, "title": f"Imported {n}", "body": body.format(n=n), "labels": []} for n in range(1, 11)}
        stories[11] = {"number": 11, "title": "Typed by hand", "body": "Priority: P2. Size: S.", "labels": []}
        return stories

    def run_groom(self, stories, mine):
        calls, filed = [], []
        line = cmd_groom.review_imported("o/r", stories, mine, 722, run=lambda a: calls.append(a) or "",
                                         file=lambda *a: filed.append(a))
        return line, calls, filed

    def test_ten_imported_issues_are_flagged_and_one_rerank_story_is_filed(self):
        import check_story_format
        stories, mine = self.fixture(), {}
        line, calls, filed = self.run_groom(stories, mine)
        flagged = [int(c[2]) for c in calls if c[:2] == ["issue", "edit"] and cmd_groom.FLAG in c]
        self.assertEqual(flagged, list(range(1, 11)))
        self.assertEqual(len(filed), 1)
        self.assertEqual(filed[0][1], "Rerank 10 imported priorities against the code")
        self.assertEqual(check_story_format.check_body(filed[0][2]), [])
        self.assertIn("#10", filed[0][2])
        self.assertIn("one rerank candidate added for 10", line)
        _, calls, filed = self.run_groom(stories, mine)
        self.assertEqual((calls, filed), ([], []))

    def test_the_flags_clear_after_the_rerank_closes(self):
        stories, mine = self.fixture(), {}
        self.run_groom(stories, mine)
        stories[12] = {"number": 12, "title": "Rerank 10 imported priorities against the code", "body": "", "labels": []}
        _, calls, filed = self.run_groom(stories, mine)
        self.assertEqual((calls, filed), ([], []))
        del stories[12]
        line, calls, filed = self.run_groom(stories, mine)
        cleared = [int(c[2]) for c in calls if c[:2] == ["issue", "edit"] and cmd_groom.REVIEWED in c]
        self.assertEqual(cleared, list(range(1, 11)))
        self.assertTrue(all(cmd_groom.REVIEWED in s["labels"] and cmd_groom.FLAG not in s["labels"] for n, s in stories.items() if n <= 10))
        self.assertEqual(filed, [])
        self.assertEqual(mine, {})
        self.assertEqual(cmd_groom.imported(stories), [])

    def test_a_rerank_still_waiting_in_the_outbox_clears_nothing(self):
        stories, mine = self.fixture(), {}
        self.run_groom(stories, mine)
        _, calls, filed = self.run_groom(stories, mine)
        self.assertEqual((calls, filed), ([], []))
        self.assertEqual(mine["rerank"]["numbers"], list(range(1, 11)))


class TestGroomRunsTheSweepsChecks(unittest.TestCase):
    def test_all_runs_the_intake_and_repeated_blocker_checks_after_the_boards(self):
        config = Path("/x/r/docs/backlog-config.json")
        with mock.patch.object(cmd_groom, "groom_board", return_value=True), mock.patch.object(cmd_groom.gh_budget, "refusal", return_value=""), \
                mock.patch.object(cmd_groom.gh_budget, "points_refusal", return_value=""), \
                mock.patch.object(cmd_groom, "boards", return_value=[("R", config)]), mock.patch("lib.cmd_sweep.repos", return_value=[("R", "o/r", 3)]), \
                mock.patch("lib.intake.prevention", return_value=[]) as prevention, mock.patch("lib.intake.run", return_value=1) as intake_run:
            self.assertEqual(1, cmd_groom.command_groom(["--all"]))
        prevention.assert_called_once_with("o/r", 3)
        intake_run.assert_called_once_with([("R", "o/r", 3)])

    def test_a_held_budget_skips_the_intake_check_and_a_single_config_never_runs_it(self):
        with mock.patch.object(cmd_groom.gh_budget, "refusal", return_value="held. later"), mock.patch("lib.intake.run") as intake_run:
            self.assertEqual(0, cmd_groom.check_intake([("R", Path("a.json"))], out=lambda t: None))
        intake_run.assert_not_called()
        with mock.patch.object(cmd_groom, "groom_board", return_value=True), mock.patch.object(cmd_groom, "check_intake") as check:
            self.assertEqual(0, cmd_groom.command_groom(["--config", "/x/r/docs/backlog-config.json"]))
        check.assert_not_called()


class TestGroomScheduling(unittest.TestCase):
    def test_maintain_fix_grooms_every_board_and_a_check_only_run_does_not(self):
        from lib import maintain
        with mock.patch.object(cmd_groom, "command_groom", return_value=0) as run:
            self.assertEqual(maintain.check_groom(False), [])
            self.assertEqual(maintain.check_groom(True), [])
        run.assert_called_once_with(["--all"])
        with mock.patch.object(cmd_groom, "command_groom", return_value=1):
            self.assertEqual(maintain.check_groom(True)[0].step, "groom")


class TestGroomHealth(unittest.TestCase):
    def test_health_warns_before_the_first_groom_and_the_clean_clone_install_passes(self):
        text = (REPO_ROOT / "scripts" / "lib" / "cmd_health.py").read_text(encoding="utf-8")
        self.assertIn("no board has been groomed yet", text)
        self.assertLess(text.index("no board has been groomed yet"), text.index("t.fail(f\"a board has not been groomed"))


class TestAForkCarryingTheOwnersConfig(unittest.TestCase):
    """A checkout whose origin differs from the repo its config names is never groomed or swept (#687)."""

    def fork(self):
        import subprocess
        repo = temp_dir(self)
        (repo / "docs").mkdir()
        (repo / "docs" / "backlog-config.json").write_text(json.dumps(
            {"repoOwner": "owner", "repoName": "OliverCode", "projectOwner": "owner", "projectNumber": 15, "projectId": "PVT_1", "fields": {}}))
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/me/my-fork.git"], check=True)
        return repo

    def test_groom_refuses_the_inherited_config_and_reads_no_board(self):
        home, repo = temp_dir(self), self.fork()
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}), mock.patch.object(cmd_groom.gh_budget, "refusal", return_value=""), \
                mock.patch.object(cmd_groom.gh_budget, "points_refusal", return_value=""), mock.patch("check_board_hygiene.load_items") as load, \
                mock.patch.object(cmd_groom.cmd_owner, "note") as note:
            self.assertFalse(cmd_groom.groom_board("Fork", repo / "docs" / "backlog-config.json"))
        load.assert_not_called()
        self.assertIn("names owner/OliverCode's Project, but this checkout's origin is me/my-fork", note.call_args.args[1])

    def test_the_sweep_skips_the_inherited_config(self):
        from lib import cmd_sweep
        repo = self.fork()
        with mock.patch.object(cmd_sweep, "OC_ROOT", repo), mock.patch.object(cmd_sweep, "load_repo_profiles", return_value=({}, None)), \
                mock.patch.object(cmd_sweep, "backlog_config", return_value={"projectOwner": "owner", "projectNumber": 15}):
            self.assertEqual([], cmd_sweep.boards())
