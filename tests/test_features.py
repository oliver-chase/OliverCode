"""`olivercode features` and the conform `features` row: each register row is on or off per repo, and an off row names its enable command (#723, #727)."""

import io
import json
import os
import plistlib
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from _support import REPO_ROOT, load_script, temp_dir

load_script("scripts/olivercode", "olivercode_launcher")
from lib import conform, features  # noqa: E402  (load_script put scripts/ on the path)


class FeaturesBase(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-features-")
        self.home = self.tmp / "home"
        self.repo = self.tmp / "widgets"
        (self.repo / "docs").mkdir(parents=True)
        (self.repo / "docs" / "backlog-config.json").write_text(json.dumps(
            {"repoName": "widgets", "fields": {"status": {}, "priority": {}, "size": {}, "area": {}}}))
        (self.repo / ".olivercode").mkdir()
        (self.repo / ".olivercode" / "policy.json").write_text("{}")
        # Gates are not under test here, so the hooks row is replaced by a fixed answer.
        self._hooks = features.TESTS["hooks"]
        features.TESTS["hooks"] = lambda repo, home: True
        self.addCleanup(features.TESTS.__setitem__, "hooks", self._hooks)
        # The machine rows that read the real PATH and settings are fixed for the same reason.
        for row, answer in (("headless-builders", True), ("unfinished-work-snapshot", True)):
            old = features.TESTS[row]
            features.TESTS[row] = lambda repo, home, answer=answer: answer
            self.addCleanup(features.TESTS.__setitem__, row, old)

    def turn_on_machine(self, *skip):
        agents = self.home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True, exist_ok=True)
        oc = self.home / ".olivercode"
        oc.mkdir(parents=True, exist_ok=True)
        for name in ("owner-queue.jsonl", "relays.jsonl"):
            if name not in skip:
                (oc / name).write_text("{}\n")
        for label in ("burndown", "lessons", "sweep", "groom", "maintain", "gap-sweep", "fleet-sync", "gh-replay", "version-cut", "board-sweep", "review"):
            if label not in skip:
                (agents / f"com.olivercode.{label}.plist").write_text("x")


class TestRegister(unittest.TestCase):
    def test_every_row_has_a_check_an_enable_command_and_a_test(self):
        rows = features.load()
        self.assertGreaterEqual(len(rows), 12)
        for row in rows:
            for field in features.FIELDS:
                self.assertIn(field, row)
            self.assertTrue(row["check"].strip() and row["enable"].strip(), row["id"])
            self.assertIn(row["id"], features.TESTS)
        self.assertEqual(len(rows), len({r["id"] for r in rows}))

    def test_a_row_with_no_check_command_is_refused(self):
        bad = [{"id": "owner-queue", "title": "Owner queue", "check": "", "enable": "olivercode board sweep", "owner_only": False, "freshness": "exists", "explain": "x"}]
        with self.assertRaises(ValueError) as ctx:
            features.evaluate(Path("."), rows=bad)
        self.assertIn("check", str(ctx.exception))

    def test_a_row_with_no_test_is_refused(self):
        bad = [{"id": "nothing", "title": "T", "check": "c", "enable": "e", "owner_only": False, "freshness": "exists", "explain": "x"}]
        with self.assertRaises(ValueError):
            features.evaluate(Path("."), rows=bad)


class TestExplain(FeaturesBase):
    def test_a_row_without_an_explain_line_is_refused(self):
        row = {k: v for k, v in features.load()[0].items() if k != "explain"}
        with self.assertRaises(ValueError) as ctx:
            features.explain(self.repo, self.home, [row])
        self.assertIn("explain", str(ctx.exception))

    def test_every_scheduled_job_has_a_line_and_shows_whether_it_is_loaded(self):
        import re
        labels = set()
        for path in (REPO_ROOT / "scripts" / "lib").glob("*.py"):
            labels |= set(re.findall(r'LABEL = "com\.olivercode\.([a-z-]+)"', path.read_text(encoding="utf-8")))
        self.assertTrue(labels)
        self.assertEqual(set(), labels - set(features.JOB_GUIDE), "a scheduled job has no explain line in features.JOB_GUIDE")
        self.assertIn("[NOT LOADED] Fleet sync", features.explain(self.repo, self.home))
        self.turn_on_machine()
        self.assertIn("[LOADED] Fleet sync", features.explain(self.repo, self.home))

    def test_the_command_prints_the_guide(self):
        lines = []
        self.assertEqual(0, features.command_features(["--explain"], out=lines.append))
        self.assertIn("Scheduled jobs", lines[0])


class TestFeatures(FeaturesBase):
    def test_a_repo_with_two_features_off_lists_both_with_their_enable_commands(self):
        self.turn_on_machine("sweep", "burndown")
        state = {f.id: f for f in features.evaluate(self.repo, self.home)}
        self.assertFalse(state["nightly-sweep"].on)
        self.assertFalse(state["burndown"].on)
        self.assertTrue(state["owner-queue"].on)
        gaps = features.off(self.repo, self.home)
        self.assertEqual(["burndown", "nightly-sweep"], sorted(g.id for g in gaps))
        self.assertEqual("olivercode board sweep --schedule", features.command_for(state["nightly-sweep"], self.repo))

    def test_the_command_prints_on_and_off_per_row_and_the_enable_command_for_each_off_row(self):
        lines = []
        with redirect_stdout(io.StringIO()):
            rc = features.command_features(["--repo", str(self.repo)], out=lines.append)
        text = "\n".join(lines)
        self.assertEqual(1, rc)
        self.assertIn("[OFF] Nightly sweep", text)
        self.assertIn("Enable: olivercode board sweep --schedule", text)
        self.assertIn("[ON ] Board baseline", text)

    def test_the_command_refuses_an_unknown_repo_and_missing_flags(self):
        lines = []
        self.assertEqual(1, features.command_features(["--repo", "no-such-repo-xyz"], out=lines.append))
        self.assertEqual(1, features.command_features([], out=lines.append))

    def test_an_owner_only_row_is_not_a_gap(self):
        rows = [{"id": "owner-queue", "title": "Owner queue", "check": "c", "enable": "e", "owner_only": True, "freshness": "exists", "explain": "x"}]
        self.assertEqual([], features.off(self.repo, self.home, rows))
        self.assertFalse(features.evaluate(self.repo, self.home, rows)[0].on)


class TestInventory(FeaturesBase):
    """Every part OliverCode ships has a register row (#749)."""

    def register(self):
        import json as _json
        data = _json.loads((REPO_ROOT / "docs" / "STANDARDS.json").read_text())
        return data, {c for r in data["features"] for c in r["covers"]} | set(data["utilities"])

    def test_every_launcher_command_has_a_row_or_is_listed_as_a_utility(self):
        from lib import cli
        _, known = self.register()
        missing = sorted({c[0].split()[1] for c in cli.COMMANDS} - known)
        self.assertEqual([], missing, f"add a row to docs/STANDARDS.json (covers) or list as a utility: {missing}")

    def test_every_launchd_job_label_has_a_row(self):
        import re
        _, known = self.register()
        labels = set()
        for path in (REPO_ROOT / "scripts" / "lib").glob("*.py"):
            labels |= set(re.findall(r'["\'](com\.olivercode\.[a-z-]+)["\']', path.read_text(encoding="utf-8")))
        missing = sorted(labels - known)
        self.assertEqual([], missing, f"add a row to docs/STANDARDS.json (covers) for each job: {missing}")

    def test_every_command_with_a_schedule_flag_has_a_row_that_is_a_job(self):
        from lib import cli
        data, _ = self.register()
        scheduled = {c[0].split()[1] for c in cli.COMMANDS if "--schedule" in c[0] or "--schedule" in c[1]}
        jobs = {c for r in data["features"] if r["freshness"] == "last-run" for c in r["covers"]}
        self.assertEqual([], sorted(scheduled - jobs))

    def test_the_gaps_the_first_list_missed_are_rows(self):
        ids = {r["id"] for r in features.load()}
        for needed in ("headless-builders", "worktree-cleanup", "unfinished-work-snapshot"):
            self.assertIn(needed, ids)

    def test_three_unused_parts_all_print_with_their_enable_command(self):
        self.turn_on_machine("gap-sweep", "fleet-sync", "gh-replay")
        lines = []
        features.command_features(["--repo", str(self.repo)], out=lines.append, home=self.home)
        text = "\n".join(lines)
        for title, enable in (("Gap sweep", "olivercode gap-sweep --schedule"), ("Fleet sync", "olivercode fleet-sync --schedule"),
                              ("GitHub write replay", "olivercode gh-limit --schedule")):
            self.assertIn(f"[OFF] {title}", text)
            self.assertIn(f"Enable: {enable}", text)


class TestFreshness(FeaturesBase):
    def job(self, label, log_lines=None, interval=900, log_age=0, plist_age=0):
        """Install a loaded job fixture: a real plist, its log and the mtimes that say when it last ran."""
        agents = self.home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True, exist_ok=True)
        log = self.home / f"{label}.out"
        if log_lines is not None:
            log.write_text("\n".join(log_lines) + "\n")
            os.utime(log, (time.time() - log_age,) * 2)
        plist = agents / f"com.olivercode.{label}.plist"
        plist.write_bytes(plistlib.dumps({"Label": plist.stem, "StartInterval": interval, "StandardOutPath": str(log)}))
        os.utime(plist, (time.time() - plist_age,) * 2)

    def states(self, exit_code=0, only=None):
        old = features.EXIT
        features.EXIT = lambda label: exit_code if only is None or label.endswith(only) else 0
        self.addCleanup(setattr, features, "EXIT", old)
        return {f.id: f for f in features.evaluate(self.repo, self.home)}

    def test_a_loaded_job_that_exited_non_zero_shows_failing_with_the_error_line(self):
        self.turn_on_machine("burndown")
        self.job("burndown", ["start", "Error: gh refused the board read"])
        found = self.states(exit_code=1)["burndown"]
        self.assertEqual("failing", found.state)
        self.assertFalse(found.on)
        self.assertEqual("Error: gh refused the board read", found.note)
        features.EXIT = lambda label: 1
        self.assertIn("burndown", [g.id for g in features.off(self.repo, self.home)])

    def test_a_logged_missing_gh_is_history_once_the_job_path_holds_gh(self):
        self.turn_on_machine("burndown")
        miss = "FileNotFoundError: [Errno 2] No such file or directory: 'gh'"
        self.job("burndown", [miss])
        self.assertEqual("failing", self.states(exit_code=1)["burndown"].state)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text("")
        plist = self.home / "Library" / "LaunchAgents" / "com.olivercode.burndown.plist"
        data = plistlib.loads(plist.read_bytes())
        data["EnvironmentVariables"] = {"PATH": str(bin_dir)}
        plist.write_bytes(plistlib.dumps(data))
        self.assertEqual("on", self.states(exit_code=1)["burndown"].state)

    def test_a_job_inside_its_interval_is_on_and_one_past_twice_its_interval_is_stale(self):
        self.turn_on_machine("burndown", "sweep")
        self.job("burndown", ["ok"], interval=900, log_age=600)
        self.job("sweep", ["ok"], interval=900, log_age=2000)
        found = self.states()
        self.assertEqual("on", found["burndown"].state)
        self.assertEqual("stale", found["nightly-sweep"].state)
        self.assertFalse(found["nightly-sweep"].on)

    def test_a_job_with_an_empty_log_that_ran_cleanly_is_on_however_old_the_log_is(self):
        self.turn_on_machine("burndown", "sweep")
        self.job("burndown", ["ok"], log_age=10**6)
        self.job("sweep", ["ok"], log_age=10**6)
        silent = self.home / "sweep.out"
        silent.write_text("")
        os.utime(silent, (time.time() - 10**6,) * 2)
        found = self.states()
        self.assertEqual("on", found["nightly-sweep"].state)
        self.assertEqual("stale", found["burndown"].state)

    def test_a_job_that_has_not_logged_is_dated_by_its_install(self):
        self.turn_on_machine("burndown")
        self.job("burndown", None, plist_age=60)
        self.assertEqual("on", self.states()["burndown"].state)

    def test_failing_and_stale_rows_are_gaps_conform_fails_with_their_reason(self):
        self.turn_on_machine("burndown", "sweep")
        self.job("burndown", ["Error: boom"])
        self.job("sweep", ["ok"], log_age=10**6)
        self.states(exit_code=1, only="burndown")
        row = conform.features(self.repo, home=self.home)
        self.assertEqual("fail", row.status)
        self.assertIn("Burndown (failing: Error: boom)", row.detail)
        self.assertIn("stale", row.detail)

    def test_the_command_prints_failing_and_stale_rows(self):
        self.turn_on_machine("burndown")
        self.job("burndown", ["Error: boom"])
        found = {f.id: f for f in self.states(exit_code=1).values()}
        self.assertEqual("failing", found["burndown"].state)

    def test_every_register_row_names_a_freshness_check(self):
        for row in features.load():
            self.assertIn(row["freshness"], features.FRESHNESS, row["id"])
            self.assertEqual(row["id"] in features.JOBS, row["freshness"] == "last-run", row["id"])


class TestRetire(FeaturesBase):
    def retire(self, name="burndown", reason="The page is replaced"):
        records = []
        removed = features.retire(name, reason, home=self.home, record=lambda *a: records.append(a), repo=self.repo)
        return removed, records

    def test_retiring_turns_jobs_off_removes_files_and_records_the_reason(self):
        self.turn_on_machine()
        removed, records = self.retire()
        self.assertEqual(["com.olivercode.burndown"], removed)
        self.assertFalse((self.home / "Library" / "LaunchAgents" / "com.olivercode.burndown.plist").exists())
        self.assertEqual("The page is replaced", records[0][0])
        self.assertEqual("retire-burndown", records[0][1])
        self.assertEqual({"burndown": "The page is replaced"}, features.retired(self.home))
        removed, _ = self.retire("owner-queue", "Not used")
        self.assertFalse((self.home / ".olivercode" / "owner-queue.jsonl").exists())

    def test_conform_passes_and_lists_the_retired_feature_with_its_reason(self):
        self.turn_on_machine("burndown")
        self.assertEqual("fail", conform.features(self.repo, home=self.home).status)
        self.retire()
        row = conform.features(self.repo, home=self.home)
        self.assertEqual("pass", row.status)
        self.assertIn("Burndown", row.detail)
        self.assertIn("The page is replaced", row.detail)

    def test_a_feature_that_is_off_without_a_retire_record_still_fails(self):
        self.turn_on_machine("burndown", "sweep")
        self.retire()
        row = conform.features(self.repo, home=self.home)
        self.assertEqual("fail", row.status)
        self.assertIn("Nightly sweep", row.detail)
        self.assertNotIn("Burndown", row.detail)

    def test_the_command_prints_retired_and_skips_it_in_the_gap_count(self):
        self.turn_on_machine("burndown")
        self.retire()
        self.assertEqual([], features.off(self.repo, self.home))
        shown = features.evaluate(self.repo, self.home)
        self.assertEqual("The page is replaced", next(f for f in shown if f.id == "burndown").retired)

    def test_retire_needs_a_known_feature_and_a_reason(self):
        with self.assertRaises(ValueError):
            features.retire("nothing", "x", home=self.home)
        with self.assertRaises(ValueError):
            features.retire("burndown", " ", home=self.home)
        self.assertEqual(1, features.command_features(["--retire", "burndown"], out=lambda _: None))


class TestConformFeatures(FeaturesBase):
    def test_conform_fails_naming_both_enable_commands_when_two_features_are_off(self):
        self.turn_on_machine("sweep", "burndown")
        row = conform.features(self.repo, home=self.home)
        self.assertEqual("fail", row.status)
        self.assertIn("olivercode board sweep --schedule", row.fix)
        self.assertIn("olivercode board burndown --schedule", row.fix)

    def test_conform_passes_when_every_feature_is_on(self):
        self.turn_on_machine()
        self.assertEqual("pass", conform.features(self.repo, home=self.home).status)

    def test_the_features_row_is_a_conform_requirement_an_exception_can_name(self):
        self.assertIn("features", {c.__name__ for c in conform.CHECKS})

    def test_check_repo_carries_the_features_row(self):
        self.turn_on_machine("sweep")
        rows = {r.requirement: r for r in conform.check_repo(self.repo, oc_root=REPO_ROOT, offline=True, home=self.home)}
        self.assertEqual("fail", rows["features"].status)


if __name__ == "__main__":
    unittest.main()
