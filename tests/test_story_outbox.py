"""The story outbox queues a request while GitHub is held, flush files and clears it, and health counts the unfiled ones."""

import os
import subprocess
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, quiet, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_ghreplay, gh_budget, story_outbox  # noqa: E402


class Runner:
    def __init__(self, fail=""):
        self.calls, self.fail = [], fail

    def __call__(self, args):
        self.calls.append(args)
        if self.fail:
            return subprocess.CompletedProcess(args, 1, "", self.fail)
        return subprocess.CompletedProcess(args, 0, f"https://github.com/acme/widget/issues/{700 + len(self.calls)}\n", "")


class TestOutbox(unittest.TestCase):
    def setUp(self):
        home = temp_dir(self)
        p = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home), "OLIVERCODE_GH_POINTS_FLOOR": "0"})
        p.start()
        self.addCleanup(p.stop)

    def test_a_held_budget_queues_the_request_and_health_counts_it(self):
        gh_budget.note_limit(who="test")
        runner = Runner()
        code, out = quiet(story_outbox.command_story, ["outbox", "add", "--repo", "acme/widget", "--title", "Fix it", "--body", "Because."], runner)
        self.assertEqual(0, code)
        self.assertEqual([], runner.calls)
        self.assertEqual(1, story_outbox.count())
        self.assertIn("1 request(s) wait", out)

    def test_an_olivercode_story_naming_another_repo_is_refused_before_the_outbox(self):
        runner = Runner()
        with mock.patch.object(story_outbox.repo_name_guard, "fleet_names", return_value=["zz-example-repo"]):
            code, out = quiet(story_outbox.command_story, ["outbox", "add", "--repo", "acme/OliverCode", "--title", "Fix it",
                                                           "--body", "Sync with zz-example-repo."], runner)
        self.assertEqual(1, code)
        self.assertIn("line 2", out)
        self.assertNotIn("zz-example-repo", out)
        self.assertEqual([], runner.calls)
        self.assertEqual(0, story_outbox.count())

    def test_an_add_during_a_flush_is_kept_and_a_direct_add_hides_a_fleet_name(self):
        story_outbox.add("acme/widget", "One", "a")

        def runner(args):
            story_outbox.add("acme/widget", "Late", "c")
            return Runner()(args)
        story_outbox.flush(runner)
        self.assertEqual(["Late"], [i["title"] for i in story_outbox.waiting()])
        with mock.patch.object(story_outbox.repo_name_guard, "fleet_names", return_value=["zz-example-repo"]):
            story_outbox.add("acme/OliverCode", "Fix zz-example-repo", "Sync zz-example-repo.")
        self.assertNotIn("zz-example-repo", story_outbox.outbox_file().read_text())

    def test_flush_files_each_waiting_request_and_clears_the_outbox(self):
        gh_budget.note_limit(who="test")
        story_outbox.add("acme/widget", "One", "a")
        story_outbox.add("acme/widget", "Two", "b")
        gh_budget.clear()
        runner = Runner()
        code, out = quiet(story_outbox.command_story, ["outbox", "flush"], runner)
        self.assertEqual(0, code)
        self.assertEqual(2, len(runner.calls))
        self.assertEqual(0, story_outbox.count())
        self.assertFalse(story_outbox.outbox_file().exists())
        self.assertIn("Filed #701 in acme/widget: One", out)

    def test_a_limit_hit_during_flush_keeps_the_rest_waiting_and_starts_a_hold(self):
        story_outbox.add("acme/widget", "One", "a")
        story_outbox.add("acme/widget", "Two", "b")
        code, _ = quiet(story_outbox.command_story, ["outbox", "flush"], Runner(fail="API rate limit exceeded"))
        self.assertEqual(1, code)
        self.assertEqual(2, story_outbox.count())
        self.assertTrue(gh_budget.blocked_until())

    def test_flush_saves_the_remaining_list_after_each_create_so_a_crash_files_no_duplicate(self):
        story_outbox.add("acme/widget", "One", "a")
        story_outbox.add("acme/widget", "Two", "b")
        runner = Runner()
        seen = []

        def crashing(args):
            seen.append([i["title"] for i in story_outbox.waiting()])
            if len(seen) == 2:
                raise KeyboardInterrupt
            return runner(args)

        with self.assertRaises(KeyboardInterrupt):
            story_outbox.flush(crashing)
        self.assertEqual(["Two"], [i["title"] for i in story_outbox.waiting()])
        again = Runner()
        story_outbox.flush(again)
        self.assertEqual(1, len(again.calls))
        self.assertIn("Two", again.calls[0])

    def test_add_refuses_an_entry_whose_repo_and_title_already_wait(self):
        gh_budget.note_limit(who="test")
        story_outbox.add("acme/widget", "One", "a")
        story_outbox.add("acme/widget", "One", "different body")
        story_outbox.add("acme/other", "One", "a")
        self.assertEqual(2, story_outbox.count())
        code, out = quiet(story_outbox.command_story, ["outbox", "add", "--repo", "acme/widget", "--title", "One", "--body", "x"], Runner())
        self.assertEqual(0, code)
        self.assertEqual(2, story_outbox.count())

    def test_the_replay_job_sends_the_outbox_in_order_and_names_each_issue(self):
        story_outbox.add("acme/widget", "One", "a")
        story_outbox.add("acme/widget", "Two", "b")
        runner = Runner()
        report = cmd_ghreplay.run(runner)
        self.assertEqual(["One", "Two"], [c[c.index("--title") + 1] for c in runner.calls])
        self.assertEqual(0, story_outbox.count())
        self.assertIn("Filed #701 in acme/widget: One", report)
        self.assertIn("Filed #702 in acme/widget: Two", report)

    def test_the_replay_job_sends_nothing_over_the_hourly_write_cap(self):
        story_outbox.add("acme/widget", "One", "a")
        with mock.patch.object(gh_budget, "WRITES_PER_HOUR", 1):
            gh_budget.reserve_write()
            runner = Runner()
            report = cmd_ghreplay.run(runner)
        self.assertEqual([], runner.calls)
        self.assertEqual(1, story_outbox.count())
        self.assertIn("1 story request(s) wait", report)

    def test_the_replay_job_reports_a_missing_gh_and_keeps_the_queue(self):
        story_outbox.add("acme/widget", "One", "a")

        def missing(args):
            raise FileNotFoundError("gh")
        report = cmd_ghreplay.run(missing)
        self.assertIn("Story outbox failed: gh", report)
        self.assertEqual(1, story_outbox.count())

    def test_the_replay_job_sends_nothing_during_a_graphql_hold(self):
        story_outbox.add("acme/widget", "One", "a")
        gh_budget.note_limit(who="test", resources=("graphql",))
        runner = Runner()
        report = cmd_ghreplay.run(runner)
        self.assertEqual([], runner.calls)
        self.assertEqual(1, story_outbox.count())
        self.assertIn("1 story request(s) wait", report)

    def test_health_warns_while_requests_are_unfiled_and_passes_once_flushed(self):
        from lib.cmd_health import command_health
        fleet = temp_dir(self)
        story_outbox.add("acme/widget", "One", "a")
        out = quiet(command_health, fleet)[1]
        self.assertIn("[WARN] 1 story request(s) are unfiled", out)
        quiet(story_outbox.command_story, ["outbox", "flush"], Runner())
        self.assertIn("[OK] no unfiled story requests", quiet(command_health, fleet)[1])


if __name__ == "__main__":
    unittest.main()
