"""Scheduled tasks and launchd jobs must name real tracked paths, and health warns on three interrupted runs.

Every test builds its own tasks folder, LaunchAgents folder and repo under a temporary folder, so the real ones are never read.
"""

import json
import plistlib
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, git, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import schedules  # noqa: E402


class Schedules(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-schedules-", resolve=True)
        self.tasks = self.tmp / "tasks"
        self.agents = self.tmp / "agents"
        self.root = self.tmp / "Repos"
        self.tasks.mkdir()
        self.agents.mkdir()
        self.repo = scratch_repo(self.root / "shop")
        (self.repo / "run.py").write_text("print(1)\n")
        (self.repo / "loose.py").write_text("print(2)\n")
        git(self.repo, "add", "run.py")
        git(self.repo, "commit", "-qm", "init")

    def task(self, name, body):
        (self.tasks / name).mkdir()
        (self.tasks / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}\n")

    def plist(self, name, label, args, **extra):
        (self.agents / name).write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": args, **extra}))

    def check(self, **kw):
        kw.setdefault("runs", {})
        kw.setdefault("crons", {})
        kw.setdefault("archived", lambda p: None)
        return schedules.check(self.tasks, self.agents, repo_root=self.root, home=self.tmp, **kw)

    def test_a_page_refresh_task_is_listed_with_its_cost_and_warns_naming_the_token_free_path(self):
        self.task("dash-refresh", "Rebuild the dashboard and republish it to its artifact each morning.")
        self.task("other", "Count the files.")
        self.plist("p.plist", "co.x.pageRefresh", ["/bin/sh", "-c", f"{self.repo}/run.py dashboard refresh"])
        self.assertEqual(schedules.refreshes(self.tasks, self.agents, self.tmp, prefixes=("co.x",)),
                         [("dash-refresh", True), ("co.x.pageRefresh", False)])
        found = [f for f in self.check() if f.task == "dash-refresh"]
        self.assertEqual(len(found), 1)
        self.assertIn("starts a Claude session", found[0].text)
        self.assertIn("starts no Claude session", found[0].text)

    def test_a_launchd_job_that_starts_claude_without_a_gate_warns_and_a_gated_one_does_not(self):
        self.plist("a.plist", "co.x.open", ["/bin/sh", "-c", f"claude -p run {self.repo}/run.py"])
        self.plist("b.plist", "co.x.gated", ["/bin/sh", "-c", f"{self.repo}/run.py gate && claude -p run {self.repo}/run.py"])
        found = [(f.level, f.task) for f in self.check() if "names no gate command" in f.text and f.task.startswith("co.x")]
        self.assertEqual(found, [("FAIL", "co.x.open")])

    def test_a_recurring_task_that_names_no_gate_command_fails_with_its_runs_per_day_and_the_fix(self):
        self.task("polls", "Check the inbox and reply to anything new.")
        self.task("gated", f"Run `{self.repo}/run.py gate`. When it prints no work, stop. Otherwise reply.")
        self.task("paused", "Check the inbox.")
        self.task("manual", "Check the inbox.")
        crons = {"polls": ("0 */2 * * *", True), "gated": ("0 */2 * * *", True), "paused": ("0 * * * *", False)}
        found = [f for f in self.check(crons=crons) if "gate" in f.text]
        self.assertEqual([(f.level, f.task) for f in found], [("FAIL", "polls")])
        self.assertIn("baseline rule 17", found[0].text)
        self.assertIn("12 times a day", found[0].text)
        self.assertEqual(schedules.runs_per_day("0 6 * * 3,5"), 2 / 7)
        self.assertEqual(schedules.runs_per_day("*/15 * * * *"), 96)

    def test_crons_are_read_from_the_apps_scheduled_tasks_file(self):
        folder = self.tmp / "sessions" / "acct" / "proj"
        folder.mkdir(parents=True)
        (folder / "scheduled-tasks.json").write_text(json.dumps({"scheduledTasks": [
            {"id": "a", "cronExpression": "40 4 * * *", "enabled": True},
            {"id": "b", "cronExpression": "0 * * * *", "enabled": False},
            {"id": "c", "enabled": True}]}))
        self.assertEqual(schedules.task_crons(self.tmp / "sessions"), {"a": ("40 4 * * *", True), "b": ("0 * * * *", False)})

    def test_missing_path_fails(self):
        self.task("nightly", f"Run {self.repo}/gone.py now.")
        found = self.check()
        self.assertEqual([(f.level, f.task) for f in found], [("FAIL", "nightly")])
        self.assertIn("gone.py", found[0].text)

    def test_a_path_with_a_space_in_a_folder_name_is_read_whole(self):
        spaced = self.tmp / "Notes Vault" / "scripts"
        spaced.mkdir(parents=True)
        (spaced / "refresh.py").write_text("print(1)\n")
        self.task("notes", f"Run python3 {spaced}/refresh.py each morning.")
        self.assertEqual(schedules.paths_in(f"Run python3 {spaced}/refresh.py each morning.", home=self.tmp), [f"{spaced}/refresh.py"])
        self.assertEqual([f for f in self.check() if "does not exist" in f.text], [])

    def test_retired_name_fails(self):
        self.task("old", "Read ~/Documents/old-vault and the legacy-flow folder.")
        with mock.patch.object(schedules, "settings", return_value={"retiredNames": ["legacy-flow", "Documents/old-vault"]}):
            texts = [f.text for f in self.check() if f.level == "FAIL"]
        self.assertTrue(any("Documents/old-vault" in t for t in texts))
        self.assertTrue(any("legacy-flow" in t for t in texts))

    def test_tracked_path_passes_and_untracked_script_warns(self):
        self.task("good", f"Run {self.repo}/run.py")
        self.assertEqual(self.check(), [])
        self.task("loose", f"Run {self.repo}/loose.py then read {self.repo}")
        self.assertEqual([(f.level, f.task) for f in self.check()], [("WARN", "loose")])

    def test_archived_repo_fails(self):
        self.task("good", f"Run {self.repo}/run.py")
        found = self.check(archived=lambda p: "archived")
        self.assertEqual([f.level for f in found], ["FAIL"])
        self.assertIn("archived", found[0].text)

    def test_third_party_plist_is_ignored_and_ours_is_checked(self):
        gone = str(self.tmp / "Updater" / "missing")
        self.plist("g.plist", "com.google.keystone", [gone])
        self.assertEqual(self.check(), [])
        self.plist("o.plist", "co.mine.job", ["/bin/bash", str(self.repo / "missing.sh")])
        self.assertEqual([(f.level, f.task) for f in self.check()], [("FAIL", "co.mine.job")])

    def test_label_prefix_makes_a_plist_ours(self):
        self.plist("p.plist", "co.mine.job", ["/bin/true"], WorkingDirectory="/nowhere/else")
        self.assertEqual(self.check(), [])
        self.assertEqual(len(self.check(prefixes=("co.mine.",))), 1)

    def test_three_interrupted_runs_warn_and_two_do_not(self):
        three = {"t": [schedules.Run(1, "interrupted"), schedules.Run(2, "interrupted"), schedules.Run(3, "failed")]}
        self.assertEqual([(f.level, f.task) for f in self.check(runs=three)], [("WARN", "t")])
        self.assertEqual(self.check(runs={"t": three["t"][1:]}), [])
        mixed = {"t": [schedules.Run(1, "interrupted"), schedules.Run(2, "ok"), schedules.Run(3, "failed")]}
        self.assertEqual(self.check(runs=mixed), [])

    def test_runs_are_read_from_session_files(self):
        folder = self.tmp / "sessions" / "a" / "b"
        folder.mkdir(parents=True)
        extras = [{"lastTurnCutShort": True}, {"error": "limit"}, {"postTurnSummary": {"status_category": "blocked"}}, {"completedTurns": 1}]
        for i, extra in enumerate(extras):
            (folder / f"local_{i}.json").write_text(json.dumps({"scheduledTaskId": "x", "createdAt": i, **extra}))
        (folder / "local_9.json").write_text(json.dumps({"createdAt": 9}))
        got = schedules.task_runs(self.tmp / "sessions")
        self.assertEqual([r.state for r in got["x"]], ["interrupted", "failed", "failed", "ok"])
        self.assertIsNone(schedules.task_runs(self.tmp / "none"))


    def test_audit_ranks_jobs_by_spend_and_flags_ungated_models(self):
        """#783 (docs/SETUP.md, Recurring jobs audit): the audit lists each recurring job with its schedule, model start, gate and spend, highest spend first."""
        for name, text in (("busy", "Sweep the inbox with the model."), ("gated", "Run the gate first, then work.")):
            (self.tasks / name).mkdir()
            (self.tasks / name / "SKILL.md").write_text(text)
        (self.agents / "poll.plist").write_bytes(plistlib.dumps({"Label": "com.olivercode.poll", "ProgramArguments": [str(self.repo / "run.py")], "StartInterval": 600}))
        rows = schedules.audit_rows(7, self.tasks, self.agents, self.tmp, crons={"busy": ("0 * * * *", True)}, spend={"busy": 500, "gated": 10})
        self.assertEqual(["busy", "gated", "com.olivercode.poll"], [r["name"] for r in rows])
        self.assertEqual((True, True), (rows[0]["model"], rows[0]["convert"]))
        self.assertFalse(rows[1]["convert"])
        self.assertEqual(("launchd", "every 600 s", False), (rows[2]["kind"], rows[2]["schedule"], rows[2]["model"]))
        report = schedules.audit_report(7, tasks_dir=self.tasks, agents_dir=self.agents, home=self.tmp, crons={}, spend={"busy": 500})
        self.assertIn("### Recurring jobs audit", (REPO_ROOT / "docs" / "SETUP.md").read_text(encoding="utf-8"))
        self.assertIn("olivercode usage jobs --days 7", report)
        self.assertIn("1 of 3 jobs start a model and name no gate", report)


if __name__ == "__main__":
    unittest.main()
