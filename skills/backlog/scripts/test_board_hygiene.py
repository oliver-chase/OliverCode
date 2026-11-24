"""Test the sweep checks (status drift, required fields, duplicate cards, close gate), the REST reads and the config guards.
Run: python3 -m unittest discover -p "test_*.py"   (from this folder)
"""
import contextlib
import json
import re
import subprocess
import sys
import tempfile
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import check_board_hygiene as bh

CONFIG = {"repoOwner": "o", "repoName": "r", "fields": {"area": {}}}


def item(number, status, area="gtm"):
    content = {"number": number, "repository": "o/r", "title": "t"}
    return {"content": content, "status": status, "area": area, "priority": "P1", "size": "S", "work Type": "Story"}


class DimensionScoping(unittest.TestCase):
    """--dimension limits a run to the named dimensions. No network: every read is replaced."""
    CFG = json.loads((Path(__file__).resolve().parent / "fixtures" / "backlog-config.json").read_text(encoding="utf-8"))

    def run_main(self, *flags):
        calls = []
        def spy(name):
            return lambda *a, **k: calls.append(name) or []
        patches = [
            mock.patch.object(bh, "load_config", return_value=self.CFG),
            mock.patch.object(bh, "load_items", return_value=[]),
            mock.patch.object(bh, "live_status_names", return_value={}),
            mock.patch.object(bh, "check_required_fields", spy("fields")),
            mock.patch.object(bh, "check_status_drift", spy("drift")),
            mock.patch.object(bh, "check_duplicate_cards", spy("duplicates")),
            mock.patch.object(bh, "check_close_gate", spy("close-gate")),
            mock.patch.object(bh, "check_grooming", spy("groom")),
            mock.patch("sys.argv", ["check_board_hygiene.py", "--config", "x.json", *flags]),
        ]
        with contextlib.ExitStack() as stack, redirect_stdout(io.StringIO()):
            for p in patches:
                stack.enter_context(p)
            bh.main()
        return calls

    def test_no_flag_runs_every_dimension(self):
        self.assertEqual({"fields", "drift", "duplicates", "close-gate", "groom"},
                         set(self.run_main()))

    def test_one_dimension_runs_alone(self):
        self.assertEqual(["fields"], self.run_main("--dimension", "fields"))

    def test_the_post_filing_pair_runs_only_fields_and_duplicates(self):
        self.assertEqual(["fields", "duplicates"],
                         self.run_main("--dimension", "fields", "--dimension", "duplicates"))


class Drift(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(bh, "run_gh_soft", return_value=None))  # no REST read, so the fake gh below answers
        self.enterContext(mock.patch.object(bh, "run_gh", lambda args: json.dumps([
            {"number": 1, "state": "CLOSED", "title": "t"},
            {"number": 2, "state": "OPEN", "title": "t"},
            {"number": 3, "state": "OPEN", "title": "t"},
        ])))

    def test_closed_issue_on_open_status_and_open_issue_off_board_are_flagged(self):
        problems = bh.check_status_drift([item(1, "In Progress"), item(2, "Complete")], CONFIG)
        self.assertEqual(3, len(problems))

    def test_matching_state_is_clean(self):
        items = [item(1, "Complete"), item(2, "Backlog"), item(3, "Ready")]
        self.assertEqual([], bh.check_status_drift(items, CONFIG))

    def test_missing_area_is_a_required_field_gap(self):
        self.assertEqual(1, len(bh.check_required_fields([item(2, "Backlog", area=None)], CONFIG)))
        # gh names the Work type key by the board's own spelling, so any case counts as set.
        cfg = {"fields": {"workType": {}}}
        lower = item(5, "Ready")
        lower["work type"] = lower.pop("work Type")
        bare = item(6, "Ready")
        del bare["work Type"]
        found = bh.check_required_fields([lower, bare], cfg, {"Ready"})
        self.assertEqual(1, len(found))
        self.assertIn("#6", found[0])
        # A card with no Status is open work with every field to fill.
        nostatus = item(7, None)
        nostatus["priority"] = None
        found = bh.check_required_fields([nostatus], cfg, {"Ready"})
        self.assertEqual(1, len(found))
        self.assertIn("status", found[0])
        self.assertIn("priority", found[0])


class BoardSpelling(unittest.TestCase):
    """A board that names its columns "Done" and "In progress" and has no Work Type field."""
    CFG = {"repoOwner": "o", "repoName": "r", "fields": {"status": {"id": "F", "options": {
        "Backlog": "a", "Ready": "b", "In Progress": "c", "Complete": "d"}}}}
    LIVE = {"a": "Backlog", "b": "Ready", "c": "In progress", "d": "Done"}

    def test_finished_and_open_names_come_from_the_live_board(self):
        finished, open_names = bh.resolve_statuses(self.CFG, self.LIVE)
        self.assertEqual("Done", finished)
        self.assertEqual({"Backlog", "Ready", "In progress"}, open_names)

    def test_extra_open_columns_stay_open(self):
        for keys, finished_key in ((["Todo", "In Progress", "Done"], "Done"),
                                   (["Backlog", "Ready", "In progress", "In review", "Done"], "Done")):
            cfg = {"fields": {"status": {"id": "F", "options": {k: k for k in keys}}}}
            finished, open_names = bh.resolve_statuses(cfg, {k: k for k in keys})
            self.assertEqual(finished_key, finished)
            self.assertEqual(set(keys) - {finished_key}, open_names)

    def test_done_on_a_closed_issue_is_clean(self):
        with mock.patch.object(bh, "run_gh_soft", return_value=None), \
                mock.patch.object(bh, "run_gh", lambda args: json.dumps([{"number": 1, "state": "CLOSED", "title": "t"}])):
            self.assertEqual([], bh.check_status_drift([item(1, "Done")], self.CFG, "Done"))

    def test_the_issue_list_and_the_board_come_from_rest_when_it_answers(self):
        rest_issues = [{"number": 1, "state": "CLOSED", "title": "t"}]
        with mock.patch.object(bh.board_rest, "repo_issues", return_value=rest_issues), \
                mock.patch.object(bh, "run_gh", side_effect=AssertionError("GraphQL read")):
            self.assertEqual([], bh.check_status_drift([item(1, "Done")], self.CFG, "Done"))
        with mock.patch.object(bh.board_rest, "project_items", return_value=[{"id": 1}]), \
                mock.patch.object(bh, "run_gh", side_effect=AssertionError("GraphQL read")):
            self.assertEqual([{"id": 1}], bh.fetch_items(self.CFG))

    def test_work_type_is_not_required_when_the_board_has_no_such_field(self):
        it = item(2, "In progress")
        del it["work Type"]
        _, open_names = bh.resolve_statuses(self.CFG, self.LIVE)
        self.assertEqual([], bh.check_required_fields([it], self.CFG, open_names))

    def test_in_progress_items_are_checked_under_the_board_spelling(self):
        it = item(2, "In progress")
        it["size"] = None
        _, open_names = bh.resolve_statuses(self.CFG, self.LIVE)
        self.assertEqual(1, len(bh.check_required_fields([it], self.CFG, open_names)))


class DuplicateCards(unittest.TestCase):
    def test_two_cards_for_one_issue_are_reported_with_their_statuses(self):
        items = [item(1, "Backlog"), item(1, "Complete"), item(2, "Ready")]
        found = bh.check_duplicate_cards(items)
        self.assertEqual(["o/r#1: 2 cards (Backlog, Complete, conflicting Status)"], found)

    def test_one_card_per_issue_is_clean(self):
        self.assertEqual([], bh.check_duplicate_cards([item(1, "Ready"), item(2, "Ready")]))


class Grooming(unittest.TestCase):
    @staticmethod
    def titled(number, status, title, work="Story"):
        found = item(number, status)
        found["content"]["title"] = title
        found["work Type"] = work
        return found

    def test_an_epic_moves_with_its_stories(self):
        epics = [self.titled(n, s, "e", "Epic") for n, s in
                 ((10, "Ready"), (11, "Ready"), (12, "Backlog"), (13, "In Progress"), (14, "Ready"), (15, "Complete"))]
        moves = {n: (status, text) for n, status, text in bh.epic_moves(
            epics, {10: (0, 0), 11: (4, 1), 12: (3, 3), 13: (4, 0), 14: (2, 2), 15: (2, 2)}, "Complete")}
        self.assertEqual({10, 11, 12, 14}, set(moves), "13 has no closed story and no move; 15 is already Complete")
        self.assertEqual("Backlog", moves[10][0])
        self.assertIn("not built directly", moves[10][1])
        self.assertEqual("In Progress", moves[11][0])
        self.assertIn("1 of 4 sub-issues are closed", moves[11][1])
        self.assertEqual("Complete", moves[12][0])
        self.assertEqual("Complete", moves[14][0], "a Ready epic whose sub-issues are all closed completes, not Backlog")

    def test_built_work_lagging_epics_and_overlapping_titles_are_flagged(self):
        builder = [{"body": "Agent action\n- Agent: b\n- Role: builder\n- Result: built"}]
        found = bh.built_not_moved([item(1, "Ready"), item(2, "QA"), item(3, "Backlog")],
                                   {1: builder, 2: builder, 3: [{"body": "a note"}]})
        self.assertEqual(["#1"], [f.split()[0] for f in found])

        epics = [self.titled(n, s, "e", "Epic") for n, s in
                 ((10, "Ready"), (11, "Backlog"), (12, "In Progress"), (13, "Complete"))]
        found = bh.epic_rollup(epics, {10: (3, 3), 11: (4, 1), 12: (4, 1), 13: (2, 2)}, "Complete")
        self.assertEqual(2, len(found))
        self.assertTrue(found[0].startswith("#10") and found[0].endswith("to Complete"))
        self.assertTrue(found[1].startswith("#11") and found[1].endswith("to In Progress"))

        stories = [self.titled(20, "Ready", "Fix the audit skill script paths"),
                   self.titled(21, "Backlog", "Audit skill: one script path style"),
                   self.titled(22, "Ready", "Rewrite the README"),
                   self.titled(23, "Ready", "Epic: audit skill script paths", "Epic")]
        found = bh.overlapping_titles(stories, {"Ready", "Backlog"})
        self.assertEqual(1, len(found))
        self.assertIn("#20 and #21", found[0])
        template = [self.titled(30, "Ready", "sampleeditor is audited and its ledger is current"),
                    self.titled(31, "Ready", "sample-planning-tool is audited and its ledger is current")]
        self.assertEqual([], bh.overlapping_titles(template, {"Ready"}), "one template, two subjects")


class EpicSummariesScope(unittest.TestCase):
    def test_an_epic_of_another_repo_is_not_queried(self):
        own = {"number": 1, "repository": "acme/widgets"}
        other = {"number": 2, "repository": "acme/other"}
        items = [{"content": c, "status": "Backlog", "work Type": "Epic"} for c in (own, other)]
        asked = []

        def runner(args):
            asked.append(args[-1])
            return '{"data": {"repository": {"e1": {"subIssuesSummary": {"total": 3, "completed": 1}}}}}'

        out = bh.epic_summaries(items, {"repoOwner": "acme", "repoName": "widgets"}, "Complete", runner)
        self.assertEqual({1: (3, 1)}, out)
        self.assertIn("e1:", asked[0])
        self.assertNotIn("e2:", asked[0])


class GroomingReads(unittest.TestCase):
    """The grooming sweep batches its epic reads and reads comments only for waiting items."""

    def test_epics_share_aliased_queries_and_only_waiting_items_have_comments_read(self):
        items = [Grooming.titled(n, "In Progress", "e", "Epic") for n in range(100, 130)]
        items += [Grooming.titled(1, "Ready", "story one"), Grooming.titled(2, "QA", "story two"),
                  Grooming.titled(3, "Backlog", "story three"), Grooming.titled(4, "Complete", "story four")]
        foreign = Grooming.titled(9, "Ready", "story of another repo")
        foreign["content"]["repository"] = "o/other"
        items.append(foreign)
        calls = []

        def runner(args):
            calls.append(args)
            if args[:2] == ["api", "graphql"]:
                query = args[3]
                numbers = [int(n) for n in re.findall(r"\be(\d+):", query)]
                repo = {f"e{n}": {"subIssuesSummary": {"total": 2, "completed": 2}} for n in numbers}
                return json.dumps({"data": {"repository": repo}})
            if args[-1] == "repos/o/r/issues/1/comments":
                return json.dumps([[{"body": "Agent action\n- Agent: b\n- Role: builder\n- Result: built"}]])
            return "[]"

        found = bh.check_grooming(items, CONFIG, "Complete", {"Ready", "Backlog"}, runner)
        graphql = [c for c in calls if c[:2] == ["api", "graphql"]]
        rest = [c[-1] for c in calls if c[:2] != ["api", "graphql"]]
        self.assertEqual(2, len(graphql), "30 epics fit in two chunks, not 30 calls")
        self.assertEqual(["repos/o/r/issues/1/comments", "repos/o/r/issues/3/comments"], rest)
        self.assertEqual(len(calls), 4, "the card of another repo is never looked up")
        self.assertTrue(any(f.startswith("o/other#9") and "another repo" in f for f in found))
        self.assertEqual(30, sum(1 for f in found if "sub-issues closed" in f))
        self.assertTrue(any(f.startswith("#1 ") and "builder entry" in f for f in found))


class ConfigLoading(unittest.TestCase):
    def test_no_path_or_a_missing_file_exits_with_a_message_naming_the_flag(self):
        for path in (None, Path("/nonexistent/backlog-config.json")):
            with self.assertRaises(SystemExit) as raised:
                bh.load_config(path)
            self.assertIn("--config", str(raised.exception))
        self.assertIn("shared/backlog-config.example.json", str(raised.exception))

    def test_existing_file_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backlog-config.json"
            path.write_text(json.dumps(CONFIG))
            self.assertEqual(CONFIG, bh.load_config(path))


class ListLimit(unittest.TestCase):
    def test_a_board_at_the_list_limit_stops_the_run(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict("os.environ", {"OLIVERCODE_HOME": home}), \
                mock.patch.object(bh.gh_budget, "points_refusal", return_value=""), \
                mock.patch.object(bh, "run_gh_soft", return_value=None), \
                mock.patch.object(bh, "run_gh", lambda args: json.dumps({"items": [{}] * bh.ITEM_LIMIT})), \
                self.assertRaises(SystemExit) as raised:
            bh.load_items({"projectNumber": 1, "projectOwner": "o"})
        self.assertIn("limit", str(raised.exception))


class CloseGateDimension(unittest.TestCase):
    CFG = {"repoOwner": "o", "repoName": "r", "closeGateFromIssue": 50}

    @staticmethod
    def runner(comments_by_issue, reasons=None):
        def run(args):
            number = int(args[-1].split("/")[-2] if args[-1].endswith("/comments") else args[0].split("/")[-1])
            if "--slurp" in args:
                return subprocess.CompletedProcess([], 0, json.dumps([comments_by_issue.get(number, [])]), "")
            if ".state_reason" in args:
                return subprocess.CompletedProcess([], 0, f"{(reasons or {}).get(number, 'null')}\n", "")
            return subprocess.CompletedProcess([], 0, "", "")
        return run

    def test_an_issue_closed_without_the_mark_is_flagged_with_its_number_and_fix(self):
        items = [item(60, "Complete"), item(61, "Complete")]
        found = bh.check_close_gate(items, self.CFG, runner=self.runner({61: [{"body": "done\n\nClosed by complete_story.py."}], 60: [{"body": "Closing."}]}))
        self.assertEqual(1, len(found))
        self.assertIn("#60", found[0])
        self.assertIn("reopen #60 and run complete_story.py --story 60", found[0])

    def test_a_duplicate_closed_as_not_planned_is_not_flagged(self):
        comments = {60: [{"body": "Duplicate of #70. Findings folded into #70."}]}
        self.assertEqual([], bh.check_close_gate([item(60, "Complete")], self.CFG, runner=self.runner(comments, {60: "not_planned"})))

    def test_a_completed_close_without_the_mark_is_still_flagged(self):
        comments = {60: [{"body": "Closing."}]}
        found = bh.check_close_gate([item(60, "Complete")], self.CFG, runner=self.runner(comments, {60: "completed"}))
        self.assertEqual(1, len(found))
        self.assertIn("reopen #60 and run complete_story.py --story 60", found[0])

    def test_a_comment_that_only_quotes_the_mark_does_not_count(self):
        quoted = {60: [{"body": "> Closed by complete_story.py."}, {"body": "Closed by complete_story.py. is the mark\nthanks"}]}
        self.assertEqual(1, len(bh.check_close_gate([item(60, "Complete")], self.CFG, runner=self.runner(quoted))))

    def test_older_and_open_items_and_a_null_key_are_not_read(self):
        def boom(args):
            raise AssertionError("read")
        self.assertEqual([], bh.check_close_gate([item(49, "Complete"), item(70, "In Progress")], self.CFG, runner=boom))
        self.assertEqual([], bh.check_close_gate([item(60, "Complete")], dict(self.CFG, closeGateFromIssue=None), runner=boom))

    def test_a_failed_read_stops_the_check_and_a_bad_key_is_refused(self):
        bad = lambda args: subprocess.CompletedProcess([], 1, "", "boom")
        with self.assertRaises(SystemExit):
            bh.check_close_gate([item(60, "Complete")], self.CFG, runner=bad)
        with self.assertRaises(SystemExit):
            bh.check_close_gate([], dict(self.CFG, closeGateFromIssue="50"))


class ImportIsolation(unittest.TestCase):
    def test_no_test_module_reads_the_live_config_at_import(self):
        here = Path(__file__).resolve().parent
        code = ("import sys, pathlib, importlib\n"
                "sys.path.insert(0, sys.argv[1])\n"
                "real_read = pathlib.Path.read_text\n"
                "real_open = pathlib.Path.open\n"
                "def hit(p):\n"
                "    return p.name == 'backlog-config.json' and p.parent.name == 'docs'\n"
                "def read(self, *a, **k):\n"
                "    if hit(self): raise FileNotFoundError(self)\n"
                "    return real_read(self, *a, **k)\n"
                "def opn(self, *a, **k):\n"
                "    if hit(self): raise FileNotFoundError(self)\n"
                "    return real_open(self, *a, **k)\n"
                "pathlib.Path.read_text = read\n"
                "pathlib.Path.open = opn\n"
                "importlib.import_module(sys.argv[2])\n")
        for module in sorted(here.glob("test_*.py")):
            with self.subTest(module=module.name):
                run = subprocess.run([sys.executable, "-c", code, str(here), module.stem],
                                     capture_output=True, text=True)
                self.assertEqual(0, run.returncode, run.stderr)


class ForkGuard(unittest.TestCase):
    REAL = {"repoOwner": "owner", "repoName": "Repo", "projectNumber": 1, "projectId": "PVT_x", "fields": {}}

    def repo(self, tmp, origin):
        subprocess.run(["git", "init", "-q", tmp], check=True)
        subprocess.run(["git", "-C", tmp, "remote", "add", "origin", origin], check=True)

    def write(self, tmp, config):
        path = Path(tmp) / "backlog-config.json"
        path.write_text(json.dumps(config))
        return path

    def test_a_config_for_another_owners_repo_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.repo(tmp, "https://github.com/someone-else/Repo.git")
            with self.assertRaises(SystemExit) as raised:
                bh.load_config(self.write(tmp, self.REAL))
        self.assertIn("fork", str(raised.exception))
        self.assertIn("backlog-config.example.json", str(raised.exception))

    def test_the_owners_own_checkout_loads_over_https_and_ssh(self):
        for origin in ("https://github.com/owner/Repo.git", "git@github.com:owner/repo.git"):
            with tempfile.TemporaryDirectory() as tmp:
                self.repo(tmp, origin)
                self.assertEqual(self.REAL, bh.load_config(self.write(tmp, self.REAL)))

    def test_the_example_is_refused_as_a_live_config(self):
        example = Path(__file__).resolve().parents[3] / "shared" / "backlog-config.example.json"
        with self.assertRaises(SystemExit) as raised:
            bh.load_config(example)
        self.assertIn("placeholder", str(raised.exception))


class BudgetAndCache(unittest.TestCase):
    CFG = {"projectOwner": "o", "projectNumber": 1}

    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        patcher = mock.patch.dict("os.environ", {"OLIVERCODE_HOME": home.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_fresh_shared_copy_is_reused_without_a_gh_call(self):
        with mock.patch.object(bh, "fetch_items", return_value=[{"id": 1}]) as fetch, \
                mock.patch.object(bh.gh_budget, "points_refusal", return_value=""):
            self.assertEqual(bh.load_items(self.CFG), [{"id": 1}])
            self.assertEqual(bh.load_items(self.CFG), [{"id": 1}])
            self.assertEqual(fetch.call_count, 1)

    def test_no_cache_reads_live_again(self):
        with mock.patch.object(bh, "fetch_items", return_value=[]) as fetch, \
                mock.patch.object(bh.gh_budget, "points_refusal", return_value=""):
            bh.load_items(self.CFG)
            bh.load_items(self.CFG, use_cache=False)
            self.assertEqual(fetch.call_count, 2)

    def test_a_low_budget_stops_the_sweep_and_says_it_did_not_run(self):
        with mock.patch.object(bh, "fetch_items") as fetch, \
                mock.patch.object(bh.gh_budget, "points_refusal", return_value="GitHub has 100 GraphQL points left."):
            with self.assertRaises(SystemExit) as cm:
                bh.load_items(self.CFG)
            self.assertIn("did not run", str(cm.exception))
            fetch.assert_not_called()
