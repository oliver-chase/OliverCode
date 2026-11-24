"""`olivercode board groom`: drifted and missing cards are fixed and an unchanged repo costs no board read (#660)."""

import json
import os
import plistlib
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, quiet, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "backlog" / "scripts"))
import check_board_hygiene  # noqa: E402
from lib import cmd_groom, cmd_health, cmd_install, launchd  # noqa: E402


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


class TestDuplicatesAreLinked(unittest.TestCase):
    """#1089: a duplicate pair whose Files areas overlap gets one comment on each story naming the one to keep, and the owner is not asked for it."""

    def setUp(self):
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(temp_dir(self))})
        patch.start()
        self.addCleanup(patch.stop)
        repo = temp_dir(self)
        (repo / "docs").mkdir()
        self.config = repo / "docs" / "backlog-config.json"
        self.config.write_text(json.dumps({"repoOwner": "o", "repoName": "r"}))
        titles = {1: "Add the duplicate link to groom", 2: "Add the duplicate link to groom now"}  # identical titles are exact duplicates, closed by #1100
        self.items = [{"content": {"number": n, "title": titles[n]}, "status": "Backlog", "priority": "P1", "size": "S"} for n in (1, 2)]
        self.stories = {n: {"number": n, "title": titles[n], "body": "Files area: scripts/lib/a.py\n", "labels": []} for n in (1, 2)}

    def groom(self, run):
        with mock.patch.object(cmd_groom.gh_budget, "refusal", return_value=""), mock.patch.object(cmd_groom.gh_budget, "points_refusal", return_value=""), \
                mock.patch.object(cmd_groom, "fingerprint", return_value="fp"), mock.patch("check_board_hygiene.load_items", return_value=self.items), \
                mock.patch("board_rest.repo_issues", return_value=[]), mock.patch.object(cmd_groom, "open_stories", return_value=self.stories), \
                mock.patch("batch_project.main"), mock.patch.object(cmd_groom.cmd_owner, "note") as note:
            return cmd_groom.groom_board("R", self.config, True, 1.0, run=run), note

    def test_a_pair_is_linked_once_and_the_owner_is_never_asked_for_it(self):
        run = mock.Mock(return_value="")
        ok, note = self.groom(run)
        self.assertTrue(ok)
        self.assertEqual([c.args[0][3] for c in run.call_args_list], ["repos/o/r/issues/1/comments", "repos/o/r/issues/2/comments"])
        self.assertTrue(all("Keep #1 and close #2" in c.args[0][-1] for c in run.call_args_list))
        self.assertFalse(any("possible duplicate" in c.args[1] for c in note.call_args_list))
        again = mock.Mock(return_value="")
        self.groom(again)
        again.assert_not_called()

    def test_a_pair_without_a_shared_files_area_is_not_linked_and_still_goes_to_the_owner(self):
        self.stories[2]["body"] = "Files area: scripts/lib/b.py\n"
        run = mock.Mock(return_value="")
        _, note = self.groom(run)
        run.assert_not_called()
        self.assertTrue(any("possible duplicate" in c.args[1] for c in note.call_args_list))


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

    def test_only_an_exact_duplicate_is_closed_and_never_deleted(self):
        body = lambda f: f"Files area: {f}\n"
        stories = {1: {"title": "Do the thing", "body": body("a.py")}, 2: {"title": "do  the thing", "body": body("a.py")},
                   3: {"title": "Do the thing", "body": body("b.py")}, 4: {"title": "Do the thing", "body": ""}}
        self.assertEqual([(2, 1, ["a.py"])], cmd_groom.exact_duplicates(stories))
        calls = []
        self.assertEqual([2], cmd_groom.close_duplicates("o/r", stories, run=lambda a: calls.append(a) or "ok"))
        self.assertIn("#1", calls[0][-1])
        self.assertIn("a.py", calls[0][-1])
        self.assertNotIn("DELETE", [c for call in calls for c in call])
        self.assertIn("state=closed", calls[1])

    def test_a_story_whose_comment_fails_stays_open(self):
        stories = {1: {"title": "T", "body": "Files area: a.py\n"}, 2: {"title": "T", "body": "Files area: a.py\n"}}
        self.assertEqual([], cmd_groom.close_duplicates("o/r", stories, run=lambda a: None))

    def test_a_card_that_is_missing_is_added_with_its_fields_in_one_fix(self):
        got = cmd_groom.filled([], {7: {"title": "bug: it fails", "body": "x" * 1500}}, drift([], {7: "OPEN"}))
        self.assertEqual(got, [{"number": 7, "fields": {"status": "Ready", "priority": "P1", "size": "XS"}}])

    def test_size_comes_from_files_and_scenarios_not_body_length(self):
        files = "Files area: a.py, b.py, c.py, d.py, e.py, f.py\n"
        scenarios = "".join(f"  Scenario: s{i}\n" for i in range(4))
        self.assertEqual(cmd_groom.size_of({"body": files + scenarios}), "L")
        self.assertEqual(cmd_groom.size_of({"body": "x" * 9000}), "XS")
        self.assertEqual(cmd_groom.size_of({"body": files + scenarios + "Size: S"}), "S")

    def test_a_ready_oversized_story_moves_to_backlog_and_one_split_story_is_filed(self):
        big = "Files area: " + ", ".join(f"f{i}.py" for i in range(9)) + "\n" + "".join(f"  Scenario: s{i}\n" for i in range(4))
        small = "Files area: a.py\n  Scenario: one\n"
        items = [self.card(1, "Ready"), self.card(2, "Ready"), self.card(3, "Ready")]
        stories = {1: {"title": "Big", "body": big}, 2: {"title": "Small", "body": small}, 3: {"title": "Parted", "body": big},
                   4: {"title": "Part", "body": "Split from #3\n"}}
        found = cmd_groom.oversized(items, stories)
        self.assertEqual(found, {1})
        filed = []
        got = cmd_groom.file_splits("o/r", "docs/backlog-config.json", stories, found, file=lambda *a: filed.append(a))
        self.assertEqual(got, [1])
        self.assertIn("olivercode board groom --config docs/backlog-config.json", filed[0][2])
        fixes = {f["number"]: f["fields"] for f in cmd_groom.filled(items, stories, [], hold=found, split=found)}
        self.assertEqual(fixes[1]["status"], "Backlog")
        self.assertNotIn("status", fixes[2])
        again = cmd_groom.file_splits("o/r", "c", {**stories, 9: {"title": "Split #1 into smaller stories", "body": ""}}, found, file=lambda *a: filed.append(a))
        self.assertEqual(again, [])

    def test_a_ready_oversized_story_gets_one_comment_saying_it_must_be_split(self):
        """#1132: the card moves to Backlog (covered above) and a comment on the story itself says it must be split, once per story."""
        big = "Files area: " + ", ".join(f"f{i}.py" for i in range(9)) + "\n" + "".join(f"  Scenario: s{i}\n" for i in range(4))
        stories = {1: {"title": "Big", "body": big}}
        mine = {}
        calls = []
        commented = cmd_groom.comment_oversized("o/r", {1}, stories, mine, run=lambda a: calls.append(a) or "ok")
        self.assertEqual([1], commented)
        self.assertEqual("repos/o/r/issues/1/comments", calls[0][1])
        self.assertIn("Split it into thin stories", calls[0][-1])
        again = mock.Mock(return_value="ok")
        self.assertEqual([], cmd_groom.comment_oversized("o/r", {1}, stories, mine, run=again))
        again.assert_not_called()

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


class TestGroomImpact(unittest.TestCase):
    def stories(self):
        body = lambda blocked, files: f"Blocked by: {blocked}.\nFiles area: {files}"
        return {1: {"body": body("none", "a.py")}, 2: {"body": body("#1", "b.py")}, 3: {"body": body("#1, #2", "a.py")}}

    def test_a_story_that_frees_others_is_counted(self):
        found = cmd_groom.impact(self.stories())
        self.assertEqual(found[1]["unblocks"], 2)
        self.assertEqual(found[2]["unblocks"], 1)
        self.assertEqual(found[3]["unblocks"], 0)

    def test_shared_files_are_counted_both_ways(self):
        found = cmd_groom.impact(self.stories())
        self.assertEqual(found[1]["shares"], [3])
        self.assertEqual(found[3]["shares"], [1])
        self.assertEqual(found[2]["shares"], [])

    def test_the_drain_reads_the_count_without_a_model(self):
        home = temp_dir(self)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            cmd_groom._state().parent.mkdir(parents=True, exist_ok=True)
            cmd_groom._state().write_text(json.dumps({"o/r": {"impact": {"1": {"unblocks": 2, "shares": []}}}}))
            self.assertEqual(cmd_groom.unblocks_of("o/r", 1), 2)
            self.assertEqual(cmd_groom.unblocks_of("o/r", 9), 0)


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
    def health(self, state):
        config = temp_dir(self) / "backlog-config.json"
        config.write_text(json.dumps({"repoOwner": "o", "repoName": "r"}))
        with mock.patch("lib.cmd_sweep.boards", return_value=[("R", config)]), mock.patch.object(cmd_groom, "load_state", return_value=state):
            return quiet(cmd_health.command_health)[1]

    def test_health_warns_before_the_first_groom(self):
        self.assertIn("[WARN] no board has been groomed yet", self.health({}))

    def test_health_passes_after_a_fresh_groom(self):
        with mock.patch.object(cmd_groom, "stale", return_value=False):
            self.assertIn("every board was groomed within", self.health({"o/r": {"ok": True}}))


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
                mock.patch.object(cmd_groom.gh_budget, "points_refusal", return_value=""), mock.patch("check_board_hygiene.load_items") as load:
            self.assertFalse(cmd_groom.groom_board("Fork", repo / "docs" / "backlog-config.json"))
            (line,) = [i for i in cmd_groom.cmd_owner.items() if i["status"] == "open"]
        load.assert_not_called()
        self.assertIn("names owner/OliverCode's Project, but this checkout's origin is me/my-fork", line["error"])

    def test_the_sweep_skips_the_inherited_config(self):
        from lib import cmd_sweep
        repo = self.fork()
        with mock.patch.object(cmd_sweep, "OC_ROOT", repo), mock.patch.object(cmd_sweep, "load_repo_profiles", return_value=({}, None)), \
                mock.patch.object(cmd_sweep, "backlog_config", return_value={"projectOwner": "owner", "projectNumber": 15}):
            self.assertEqual([], cmd_sweep.boards())


class TestGhFindsItself(unittest.TestCase):
    """#1010: the nightly job's PATH lacks gh, so groom runs gh from PATH and else from the Homebrew folder."""

    def test_gh_runs_the_one_on_path_and_else_the_homebrew_copy(self):
        with mock.patch.object(cmd_groom.shutil, "which", return_value=None), mock.patch.object(cmd_groom.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "out", "")
            self.assertEqual("out", cmd_groom.gh(["api", "user"]))
        self.assertEqual("/opt/homebrew/bin/gh", run.call_args.args[0][0])
        with mock.patch.object(cmd_groom.shutil, "which", return_value="/usr/local/bin/gh"), mock.patch.object(cmd_groom.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            cmd_groom.gh(["api", "user"])
        self.assertEqual("/usr/local/bin/gh", run.call_args.args[0][0])

    def test_a_run_without_gh_on_path_adds_the_homebrew_folder_for_its_subprocesses(self):
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}), mock.patch.object(cmd_groom.shutil, "which", return_value=None), \
                mock.patch.object(cmd_groom.Path, "is_file", return_value=True):
            cmd_groom.put_gh_on_path()
            self.assertEqual("/opt/homebrew/bin:/usr/bin:/bin", os.environ["PATH"])


class TestGroomFailureReachesTheOwner(unittest.TestCase):
    """#1010: a board that fails to groom leaves one open owner line naming the board, the error and the retry, and a good run closes it."""

    def setUp(self):
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(temp_dir(self))})
        patch.start()
        self.addCleanup(patch.stop)
        repo = temp_dir(self)
        (repo / "docs").mkdir()
        self.config = repo / "docs" / "backlog-config.json"
        self.config.write_text(json.dumps({"repoOwner": "o", "repoName": "r"}))

    def groom(self, fingerprint, now):
        with mock.patch.object(cmd_groom.gh_budget, "refusal", return_value=""), mock.patch.object(cmd_groom.gh_budget, "points_refusal", return_value=""), \
                mock.patch.object(cmd_groom, "fingerprint", **fingerprint), mock.patch("check_board_hygiene.load_items", return_value=[]), \
                mock.patch("board_rest.repo_issues", return_value=[]), mock.patch.object(cmd_groom, "open_stories", return_value={}), mock.patch("batch_project.main"):
            return cmd_groom.groom_board("R", self.config, True, now)

    def open_lines(self):
        return [i for i in cmd_groom.cmd_owner.items() if i["status"] == "open"]

    def test_a_failed_groom_leaves_one_open_line_and_a_good_run_closes_it(self):
        error = "[Errno 2] No such file or directory: 'gh'"
        self.assertFalse(self.groom({"side_effect": FileNotFoundError(error)}, 1.0))
        self.assertFalse(self.groom({"side_effect": FileNotFoundError(error)}, 2.0))
        (line,) = self.open_lines()
        self.assertIn("R (o/r) did not groom", line["step"])
        self.assertEqual(error, line["error"])
        self.assertEqual(f"olivercode board groom --config {self.config}", line["command"])
        from lib import cmd_status
        self.assertIn("R (o/r) did not groom", "\n".join(cmd_status.waiting_lines()))  # the digest shows it the same day
        self.assertTrue(self.groom({"return_value": "fp"}, 3.0))
        self.assertEqual([], self.open_lines())
        self.assertEqual([], cmd_status.waiting_lines())


class TestFilingFit(unittest.TestCase):
    """The filing check (#1004): overlap with open stories and missing paths, with no model call."""

    def main_repo(self, *paths):
        repo = temp_dir(self)
        for p in paths:
            (repo / p).parent.mkdir(parents=True, exist_ok=True)
            (repo / p).write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init"], check=True)
        return repo

    def test_an_open_story_sharing_a_file_is_named_in_a_related_line(self):
        repo = self.main_repo("scripts/lib/cmd_groom.py")
        stories = {5: {"body": "Files area: scripts/lib/cmd_groom.py, docs/a.md"}, 6: {"body": "Files area: docs/b.md"}}
        body, lines = cmd_groom.fit("Files area: scripts/lib/cmd_groom.py\n", "New", stories, repo)
        self.assertEqual("Files area: scripts/lib/cmd_groom.py\nRelated: #5 (Files area overlaps)\n", body)
        self.assertEqual([], lines)

    def test_a_folder_that_holds_an_open_stories_file_overlaps_it(self):
        repo = self.main_repo("scripts/lib/cmd_groom.py")
        body, _ = cmd_groom.fit("Files area: scripts/lib/\n", "New", {7: {"body": "Files area: scripts/lib/cmd_groom.py"}}, repo)
        self.assertIn("Related: #7 (Files area overlaps)", body)

    def test_a_related_line_is_replaced_and_never_doubled(self):
        repo = self.main_repo("scripts/lib/cmd_groom.py")
        stories = {5: {"body": "Files area: scripts/lib/cmd_groom.py"}}
        once, _ = cmd_groom.fit("Files area: scripts/lib/cmd_groom.py\n", "New", stories, repo)
        twice, _ = cmd_groom.fit(once, "New", stories, repo)
        self.assertEqual(once, twice)
        self.assertEqual(1, twice.count("Related:"))

    def test_a_path_that_is_not_on_main_is_printed_with_the_story_and_the_story_still_files(self):
        repo = self.main_repo("scripts/lib/cmd_groom.py")
        body, lines = cmd_groom.fit("Files area: scripts/lib/cmd_groom.py, scripts/lib/gone.py\n", "Fix the gap", {}, repo)
        self.assertEqual(["Fix the gap: Files area names scripts/lib/gone.py, which is not on main and no Creates line names it"], lines)
        self.assertIn("Files area: scripts/lib/cmd_groom.py, scripts/lib/gone.py", body)

    def test_a_path_the_story_creates_is_not_flagged_and_a_folder_on_main_is_not_either(self):
        repo = self.main_repo("scripts/lib/cmd_groom.py")
        text = "Files area: scripts/lib/new.py, scripts/lib/, new file\nCreates: scripts/lib/new.py\n"
        self.assertEqual([], cmd_groom.fit(text, "New", {}, repo)[1])

    def test_a_word_in_the_files_area_is_not_read_as_a_path(self):
        repo = self.main_repo("scripts/lib/cmd_groom.py")
        self.assertEqual([], cmd_groom.fit("Files area: scripts/lib/cmd_groom.py, new\n", "New", {}, repo)[1])

    def test_a_repo_git_cannot_read_says_the_check_did_not_run(self):
        repo = temp_dir(self)
        _, lines = cmd_groom.fit("Files area: scripts/lib/cmd_groom.py\n", "New", {}, repo)
        self.assertEqual(["New: the Files area check did not run, because git cannot read main"], lines)

    def test_the_fit_command_writes_the_related_line_and_prints_the_missing_path(self):
        repo = self.main_repo("scripts/lib/cmd_groom.py")
        (repo / "docs").mkdir()
        config = repo / "docs" / "backlog-config.json"
        config.write_text(json.dumps({"repoOwner": "o", "repoName": "r"}))
        body_file = temp_dir(self) / "body.md"
        body_file.write_text("Files area: scripts/lib/cmd_groom.py, scripts/lib/gone.py\n", encoding="utf-8")
        argv = ["--fit", str(body_file), "--title", "New story", "--config", str(config)]
        with mock.patch.object(cmd_groom, "open_stories", return_value={9: {"body": "Files area: scripts/lib/cmd_groom.py"}}) as read, \
                mock.patch("builtins.print") as out:
            self.assertEqual(0, cmd_groom.command_groom(argv))
        read.assert_called_once_with("o/r")
        self.assertIn("Related: #9 (Files area overlaps)", body_file.read_text(encoding="utf-8"))
        out.assert_called_once_with("New story: Files area names scripts/lib/gone.py, which is not on main and no Creates line names it")

    def test_a_failed_read_of_the_open_stories_still_lets_the_story_file(self):
        repo = self.main_repo("scripts/lib/cmd_groom.py")
        (repo / "docs").mkdir()
        config = repo / "docs" / "backlog-config.json"
        config.write_text(json.dumps({"repoOwner": "o", "repoName": "r"}))
        body_file = temp_dir(self) / "body.md"
        body_file.write_text("Files area: scripts/lib/cmd_groom.py\n", encoding="utf-8")
        with mock.patch.object(cmd_groom, "open_stories", side_effect=RuntimeError("no network")), mock.patch("builtins.print") as out:
            self.assertEqual(0, cmd_groom.command_fit(["--fit", str(body_file), "--title", "New", "--config", str(config)]))
        self.assertEqual("Files area: scripts/lib/cmd_groom.py\n", body_file.read_text(encoding="utf-8"))
        out.assert_called_once_with("New: the Related check did not run (no network), so the story files without it")


class TestRepairOldPlists(unittest.TestCase):
    """#1010: a job plist installed before the PATH fix has none, so install rewrites it with one and reloads it."""

    def setUp(self):
        self.home = temp_dir(self)
        self.folder = self.home / "Library" / "LaunchAgents"
        self.folder.mkdir(parents=True)

    def test_an_old_job_plist_with_no_path_is_rewritten_with_one_and_reloaded(self):
        old = self.folder / "com.olivercode.maintain.plist"
        old.write_bytes(plistlib.dumps({"Label": "com.olivercode.maintain", "ProgramArguments": ["python3"]}))
        run = mock.Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        with mock.patch.object(launchd.shutil, "which", return_value="/opt/homebrew/bin/gh"), mock.patch("builtins.print"):
            self.assertEqual(["com.olivercode.maintain"], cmd_install.repair_job_plists(self.home, run))
        self.assertEqual("/opt/homebrew/bin", plistlib.loads(old.read_bytes())["EnvironmentVariables"]["PATH"].split(":")[0])
        self.assertIn("bootstrap", run.call_args_list[-1].args[0])

    def test_a_plist_that_already_names_a_path_is_left_alone(self):
        ok = self.folder / "com.olivercode.fleet-sync.plist"
        ok.write_bytes(plistlib.dumps({"Label": "com.olivercode.fleet-sync", "EnvironmentVariables": {"PATH": "/x"}}))
        run = mock.Mock()
        self.assertEqual([], cmd_install.repair_job_plists(self.home, run))
        run.assert_not_called()


class TestGroomEpicLinksAndArea(unittest.TestCase):
    """#1109: a story becomes a sub-issue of the epic its Epic line names, and a story with no Area gets one from its Files area."""

    def items(self):
        return [{"content": {"number": 10, "title": "e"}, "status": "Backlog", "work Type": "Epic"},
                {"content": {"number": 11, "title": "s"}, "status": "Backlog", "work Type": "Story"},
                {"content": {"number": 12, "title": "s2"}, "status": "Backlog", "work Type": "Story", "area": "backlog"},
                {"content": {"number": 13, "title": "s3"}, "status": "Backlog", "work Type": "Story"}]

    def stories(self, epic=10):
        body = lambda f: f"Epic: #{epic}\nFiles area: {f}"
        return {11: {"id": 111, "body": body("scripts/lib/cmd_groom.py, tests/test_groom.py")},
                12: {"id": 112, "body": body("scripts/lib/cmd_groom.py, tests/test_groom.py")},
                13: {"id": 113, "body": body("scripts/lib/cmd_groom.py, skills/audit/x.py")}}

    def test_an_unlinked_story_is_linked_and_a_linked_one_is_left(self):
        calls = []
        def run(args):
            calls.append(args)
            return "12" if "-X" not in args else ""
        linked, wrong = cmd_groom.link_epics("o/r", self.stories(), self.items(), run)
        self.assertEqual((linked, wrong), ([11, 13], {}))
        self.assertIn("sub_issue_id=111", [a for c in calls for a in c])

    def test_an_epic_line_naming_a_story_links_nothing(self):
        calls = []
        linked, wrong = cmd_groom.link_epics("o/r", self.stories(11), self.items(), lambda a: calls.append(a) or "")
        self.assertEqual((linked, wrong, calls), ([], {12: 11, 13: 11}, []))

    def test_area_comes_from_the_board_and_a_spread_is_fleet_wide(self):
        options = {"backlog": 1, "audit": 2, "fleet-wide": 3}
        self.assertEqual(cmd_groom.area_fixes(self.items(), self.stories(), options), {11: "backlog", 13: "fleet-wide"})
