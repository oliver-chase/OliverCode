"""`olivercode board groom`: drifted and missing cards are reported, nothing is written to GitHub, and an unchanged repo costs no board read (#660, #1275)."""

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
            batch.assert_not_called()
            self.assertEqual(sum(1 for c in note.call_args_list if "3 card(s) have drifted" in c.args[1]), 1)


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


class FakeGh:
    """A gh that serves reads and records every write verb, so a test can prove groom wrote nothing (#1275)."""

    WRITES = ("edit", "create", "close", "reopen", "label", "project-item-edit", "item-edit", "item-add", "comment", "-X", "PATCH", "POST")

    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        return ""

    def writes(self):
        return [c for c in self.calls if any(w in c for w in self.WRITES)]


class TestGroomImportedPriorities(unittest.TestCase):
    """#743, #1275: a priority copied in from a file is reported, and groom labels nothing and files no rerank story."""

    def fixture(self):
        body = "**As the owner**, I want a thing, so that x.\n\nDetail: Source: gap-analysis-2.md (S{n}).\nPriority: P1. Size: S. Work type: Story."
        stories = {n: {"number": n, "title": f"Imported {n}", "body": body.format(n=n), "labels": []} for n in range(1, 11)}
        stories[11] = {"number": 11, "title": "Typed by hand", "body": "Priority: P2. Size: S.", "labels": []}
        return stories

    def test_imported_priorities_are_listed_and_a_reviewed_one_is_left_out(self):
        stories = self.fixture()
        self.assertEqual(list(range(1, 11)), cmd_groom.imported(stories))
        stories[3]["labels"] = [cmd_groom.REVIEWED]
        self.assertNotIn(3, cmd_groom.imported(stories))

    def test_the_label_and_rerank_writers_are_gone(self):
        self.assertFalse(hasattr(cmd_groom, "review_imported"))
        self.assertFalse(hasattr(cmd_groom, "RERANK_BODY"))


class TestGroomWritesNothing(unittest.TestCase):
    """#1275: groom reports what it found and changes no issue body, label, link, status, field or state, and creates no issue or label."""

    def groom(self, gh, stories, cards, issues):
        home, repo = temp_dir(self), temp_dir(self)
        (repo / "docs").mkdir()
        config = repo / "docs" / "backlog-config.json"
        config.write_text(json.dumps({"repoOwner": "o", "repoName": "r"}))
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}), mock.patch.object(cmd_groom.gh_budget, "refusal", return_value=""), \
                mock.patch.object(cmd_groom.gh_budget, "points_refusal", return_value=""), mock.patch.object(cmd_groom, "fingerprint", return_value="fp"), \
                mock.patch("check_board_hygiene.load_items", return_value=cards), mock.patch("board_rest.repo_issues", return_value=issues), \
                mock.patch.object(cmd_groom, "open_stories", return_value=stories), mock.patch("batch_project.main") as batch, \
                mock.patch("subprocess.run") as sub, mock.patch.object(cmd_groom.cmd_owner, "note") as note:
            ok = cmd_groom.groom_board("R", config, True, 1.0, run=gh)
        return ok, batch, sub, note

    def test_open_stories_on_the_board_are_reported_and_nothing_is_changed(self):
        imported = "Source: gap.md.\nPriority: P1. Size: S."
        stories = {1: {"number": 1, "title": "Add a thing", "body": "x", "labels": []}, 2: {"number": 2, "title": "Imported", "body": imported, "labels": []},
                   3: {"number": 3, "title": "Closed upstream", "body": "Priority: P2. Size: S.", "labels": []}}
        cards = [{"content": {"number": 1}, "status": "Backlog"}, {"content": {"number": 3}, "status": "Ready"}]
        gh = FakeGh()
        ok, batch, sub, note = self.groom(gh, stories, cards, [{"number": 1, "state": "OPEN"}, {"number": 2, "state": "OPEN"}, {"number": 3, "state": "CLOSED"}])
        self.assertTrue(ok)
        batch.assert_not_called()
        self.assertEqual([], [c for c in sub.call_args_list if c.args and c.args[0][:1] == ["gh"]])
        self.assertEqual([], gh.writes())
        said = " ".join(c.args[1] for c in note.call_args_list)
        self.assertIn("card(s) have drifted, are missing or lack Priority, Size or Ready", said)
        self.assertIn("1 imported priorities have not been judged", said)

    def test_no_function_in_groom_calls_a_gh_write_or_the_board_batch_writer(self):
        text = (REPO_ROOT / "scripts" / "lib" / "cmd_groom.py").read_text(encoding="utf-8")
        for needle in ("batch_project", '"issue", "edit"', '"label", "create"', '"issue", "create"', "intake.candidate", "--add-label"):
            self.assertNotIn(needle, text)


class TestGroomRunsTheSweepsChecks(unittest.TestCase):
    def test_all_runs_the_intake_and_repeated_blocker_reports_after_the_boards(self):
        config = Path("/x/r/docs/backlog-config.json")
        with mock.patch.object(cmd_groom, "groom_board", return_value=True), mock.patch.object(cmd_groom.gh_budget, "refusal", return_value=""), \
                mock.patch.object(cmd_groom.gh_budget, "points_refusal", return_value=""), \
                mock.patch.object(cmd_groom, "boards", return_value=[("R", config)]), mock.patch("lib.cmd_sweep.repos", return_value=[("R", "o/r", 3)]), \
                mock.patch("lib.intake.repeated_blockers", return_value=["gate 4: x blocked 3 times, latest t"]) as repeated, mock.patch("lib.intake.run", return_value=1) as intake_run:
            self.assertEqual(1, cmd_groom.command_groom(["--all"]))
        repeated.assert_called_once_with()
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
        with mock.patch.object(cmd_sweep, "OC_ROOT", repo), mock.patch.object(cmd_sweep, "backlog_config", return_value={"projectOwner": "owner", "projectNumber": 15}):
            self.assertEqual([], cmd_sweep.boards())


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
