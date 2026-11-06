"""Test the sweep checks (status drift, required fields, duplicate cards, QA sign-off), the REST reads and the config guards.
Run: python3 -m unittest discover -p "test_*.py"   (from this folder)
"""
import json
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
            mock.patch.object(bh, "check_qa_signoff", spy("qa-signoff")),
            mock.patch.object(bh, "check_grooming", spy("groom")),
            mock.patch("sys.argv", ["check_board_hygiene.py", "--config", "x.json", *flags]),
        ]
        out = io.StringIO()
        for p in patches:
            p.start()
        try:
            with redirect_stdout(out):
                bh.main()
        finally:
            mock.patch.stopall()
        return calls

    def test_no_flag_runs_every_dimension(self):
        self.assertEqual({"fields", "drift", "duplicates", "qa-signoff", "groom"},
                         set(self.run_main()))

    def test_one_dimension_runs_alone(self):
        self.assertEqual(["fields"], self.run_main("--dimension", "fields"))

    def test_the_post_filing_pair_runs_only_fields_and_duplicates(self):
        self.assertEqual(["fields", "duplicates"],
                         self.run_main("--dimension", "fields", "--dimension", "duplicates"))


class Drift(unittest.TestCase):
    def setUp(self):
        self.real_run_gh = bh.run_gh
        bh.run_gh = lambda args: json.dumps([
            {"number": 1, "state": "CLOSED", "title": "t"},
            {"number": 2, "state": "OPEN", "title": "t"},
            {"number": 3, "state": "OPEN", "title": "t"},
        ])

    def tearDown(self):
        bh.run_gh = self.real_run_gh

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
        real = bh.run_gh
        bh.run_gh = lambda args: json.dumps([{"number": 1, "state": "CLOSED", "title": "t"}])
        try:
            self.assertEqual([], bh.check_status_drift([item(1, "Done")], self.CFG, "Done"))
        finally:
            bh.run_gh = real

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


class ConfigLoading(unittest.TestCase):
    def test_no_path_or_a_missing_file_exits_with_a_message_naming_the_flag(self):
        for path in (None, Path("/nonexistent/backlog-config.json")):
            with self.assertRaises(SystemExit) as raised:
                bh.load_config(path)
            self.assertIn("--config", str(raised.exception))

    def test_existing_file_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backlog-config.json"
            path.write_text(json.dumps(CONFIG))
            self.assertEqual(CONFIG, bh.load_config(path))


class ListLimit(unittest.TestCase):
    def test_a_board_at_the_list_limit_stops_the_run(self):
        real = bh.run_gh
        bh.run_gh = lambda args: json.dumps({"items": [{}] * bh.ITEM_LIMIT})
        try:
            with self.assertRaises(SystemExit) as raised:
                bh.load_items({"projectNumber": 1, "projectOwner": "o"})
        finally:
            bh.run_gh = real
        self.assertIn("limit", str(raised.exception))


class QaSignoffDimension(unittest.TestCase):
    CFG = {"repoOwner": "o", "repoName": "r", "qaRequiredFromIssue": 50}
    BODY = "Scenario: Work is finished\n"

    @staticmethod
    def comment(agent, role, result):
        return {"body": f"Agent action\n- Agent: {agent}\n- Role: {role}\n- Result: {result}"}

    def runner(self, comments_by_issue, calls=None):
        def run(args):
            if calls is not None:
                calls.append(args)
            number = int(args[-1].split("/")[-2] if args[-1].endswith("/comments") else args[0].split("/")[-1])
            if "--slurp" in args:
                return subprocess.CompletedProcess([], 0, json.dumps([comments_by_issue.get(number, [])]), "")
            return subprocess.CompletedProcess([], 0, self.BODY, "")
        return run

    GOOD = [comment.__func__("b", "builder", "built"), comment.__func__("q", "qa", "PASS; confirmed: Work is finished")]

    def test_a_complete_item_without_a_sign_off_is_flagged_and_a_signed_one_is_not(self):
        items = [item(60, "Complete"), item(61, "Complete")]
        found = bh.check_qa_signoff(items, self.CFG, runner=self.runner({61: self.GOOD}))
        self.assertEqual(1, len(found))
        self.assertIn("#60", found[0])

    def test_issues_below_the_start_and_open_items_are_not_read(self):
        calls = []
        items = [item(49, "Complete"), item(70, "In Progress")]
        self.assertEqual([], bh.check_qa_signoff(items, self.CFG, runner=self.runner({}, calls)))
        self.assertEqual([], calls)

    def test_a_null_or_absent_key_turns_the_dimension_off(self):
        calls = []
        for cfg in ({"repoOwner": "o", "repoName": "r"}, dict(self.CFG, qaRequiredFromIssue=None)):
            self.assertEqual([], bh.check_qa_signoff([item(60, "Complete")], cfg, runner=self.runner({}, calls)))
        self.assertEqual([], calls)

    def test_a_lone_qa_comment_does_not_count(self):
        lone = [self.comment("A", "qa", "PASS; confirmed: Work is finished")]
        self.assertEqual(1, len(bh.check_qa_signoff([item(60, "Complete")], self.CFG, runner=self.runner({60: lone}))))

    def test_a_failed_read_stops_the_run(self):
        def bad(args):
            return subprocess.CompletedProcess([], 1, "", "boom")
        with self.assertRaises(SystemExit) as raised:
            bh.check_qa_signoff([item(60, "Complete")], self.CFG, runner=bad)
        self.assertIn("boom", str(raised.exception))

    def test_a_non_number_key_is_refused(self):
        with self.assertRaises(SystemExit):
            bh.check_qa_signoff([], dict(self.CFG, qaRequiredFromIssue="50"))

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

    def test_a_missing_config_message_names_the_example(self):
        with self.assertRaises(SystemExit) as raised:
            bh.load_config(Path("/nonexistent/backlog-config.json"))
        self.assertIn("shared/backlog-config.example.json", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
