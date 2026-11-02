"""Direct tests for the launcher commands that had none: skills, discover, sync-hooks,
audit-fleet, placement drift, and the scheduler tick.

Every test runs against a scratch checkout and a scratch HOME. Nothing reaches the network, and
git reads no machine config (tests/_support.py).
"""

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, load_script, scratch_repo

TEMPLATES = REPO_ROOT / "core" / "templates" / "project"
launcher = load_script("scripts/olivercode", "olivercode_launcher")
tick = load_script("scripts/local-scheduler/tick.py", "scheduler_tick_commands")


def quiet(fn, *args, **kwargs):
    """Run fn with stdout captured; return (result, printed text)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = fn(*args, **kwargs)
    return result, out.getvalue()


class ScratchHome(unittest.TestCase):
    """A scratch HOME and checkout that no test can leave behind."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-fleetcmd-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.oc = self.tmp / "oc"
        self.oc.mkdir()

    def add_skill(self, name, description="Does a thing."):
        folder = self.oc / "skills" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(
            f'---\nname: {name}\ndescription: "{description}"\n---\n\nBody.\n', encoding="utf-8")
        return folder


class TestCommandSkills(ScratchHome):
    def run_skills(self, *argv):
        with mock.patch.object(launcher, "OC_ROOT", self.oc):
            return quiet(launcher.command_skills, list(argv))

    def test_lists_every_skill_with_a_count(self):
        self.add_skill("alpha", "First skill.")
        self.add_skill("beta", "Second skill.")
        code, out = self.run_skills()
        self.assertEqual(code, 0)
        self.assertIn("alpha", out)
        self.assertIn("Second skill.", out)
        self.assertIn("2 skill(s).", out)

    def test_grep_filters_by_name_and_description(self):
        self.add_skill("alpha", "Sorts mail.")
        self.add_skill("beta", "Pulls reports.")
        code, out = self.run_skills("--grep", "REPORTS")
        self.assertEqual(code, 0)
        self.assertIn("beta", out)
        self.assertNotIn("alpha", out)
        self.assertIn("1 skill(s).", out)

    def test_a_grep_with_no_match_says_so_and_exits_zero(self):
        self.add_skill("alpha")
        code, out = self.run_skills("--grep", "zzz")
        self.assertEqual(code, 0)
        self.assertIn("No skills match 'zzz'.", out)

    def test_a_checkout_with_no_skills_fails(self):
        code, out = self.run_skills()
        self.assertEqual(code, 1)
        self.assertIn("No skills found", out)

    def test_grep_without_a_term_fails(self):
        self.add_skill("alpha")
        code, out = self.run_skills("--grep")
        self.assertEqual(code, 1)
        self.assertIn("--grep requires a search term", out)

    def test_a_long_description_is_cut_to_100_characters(self):
        self.add_skill("alpha", "w" * 150)
        _, out = self.run_skills()
        self.assertIn("w" * 97 + "...", out)
        self.assertNotIn("w" * 98, out)


class TestCommandDiscover(ScratchHome):
    def setUp(self):
        super().setUp()
        self.fleet = self.tmp / "fleet"
        self.fleet.mkdir()

    def discover(self, *roots):
        return quiet(launcher.command_discover, self.oc, list(roots))

    def test_reports_each_repo_with_its_rules_file_and_hooks_state(self):
        governed = scratch_repo(self.fleet / "governed")
        (governed / "CLAUDE.md").write_text("rules\n")
        git(governed, "config", "core.hooksPath", ".githooks")
        bare = scratch_repo(self.fleet / "bare")
        (bare / "AGENTS.md").write_text("rules\n")
        code, out = self.discover(self.fleet)
        self.assertEqual(code, 0)
        self.assertRegex(out, r"governed\s+rules=CLAUDE\.md\s+hooksPath=\.githooks")
        self.assertRegex(out, r"bare\s+rules=AGENTS\.md\s+hooksPath=unset\s+<- ungoverned")
        self.assertIn("2 repo(s).", out)

    def test_prints_a_profile_skeleton_with_explicit_paths(self):
        scratch_repo(self.fleet / "widgets")
        _, out = self.discover(self.fleet)
        self.assertIn('"canonicalValidationCommand": "<command>"', out)
        self.assertIn(f'"path": "{self.fleet / "widgets"}"', out)

    def test_skips_the_framework_checkout_and_vendored_noise(self):
        scratch_repo(self.oc)
        scratch_repo(self.fleet / "node_modules" / "dep")
        scratch_repo(self.fleet / "real")
        _, out = self.discover(self.oc.parent)
        self.assertIn("real", out)
        self.assertNotIn("dep", out)
        self.assertIn("1 repo(s).", out)

    def test_no_repos_fails_and_names_the_roots(self):
        code, out = self.discover(self.fleet)
        self.assertEqual(code, 1)
        self.assertIn(f"No git repositories found under: {self.fleet}", out)

    def test_never_changes_a_repo(self):
        repo = scratch_repo(self.fleet / "widgets")
        before = git(repo, "status", "--porcelain").stdout
        self.discover(self.fleet)
        self.assertEqual(git(repo, "status", "--porcelain").stdout, before)
        self.assertFalse((repo / ".githooks").exists())


class TestCommandSyncHooks(ScratchHome):
    def setUp(self):
        super().setUp()
        (self.oc / "core" / "templates").mkdir(parents=True)
        shutil.copytree(TEMPLATES, self.oc / "core" / "templates" / "project")
        self.fleet = self.tmp / "fleet"
        self.fleet.mkdir()
        self.private = {}

    def sync(self, profiles):
        with mock.patch.object(launcher, "load_repo_profiles", return_value=(profiles, None)), \
                mock.patch.object(launcher, "_private_repos", return_value=self.private):
            return quiet(launcher.command_sync_hooks, self.oc, self.fleet)

    def test_a_fleet_repo_gets_the_public_hooks_and_a_hooks_path(self):
        repo = scratch_repo(self.fleet / "alpha")
        code, out = self.sync({"alpha": {}})
        self.assertEqual(code, 0)
        self.assertIn("[OK] alpha: hooks synced", out)
        self.assertEqual((repo / ".githooks" / "pre-commit").read_bytes(), (TEMPLATES / "pre-commit").read_bytes())
        self.assertTrue(os.access(repo / ".githooks" / "pre-commit", os.X_OK))
        self.assertEqual(git(repo, "config", "--get", "core.hooksPath").stdout.strip(), ".githooks")
        for name in ("pre-push", "commit-msg"):
            self.assertTrue((repo / ".githooks" / name).is_file(), name)
        self.assertIn("1 target(s) synced, 0 skipped.", out)

    def test_a_private_profile_gets_the_private_variant_as_its_live_hook(self):
        repo = scratch_repo(self.fleet / "vault")
        self.sync({"vault": {"private": True}})
        self.assertEqual((repo / ".githooks" / "pre-commit").read_bytes(),
                         (TEMPLATES / "pre-commit-private").read_bytes())

    def test_a_repo_missing_from_this_machine_is_skipped(self):
        code, out = self.sync({"ghost": {}})
        self.assertEqual(code, 0)
        self.assertIn("[SKIP] ghost: not present on this machine", out)
        self.assertIn("0 target(s) synced, 1 skipped.", out)

    def test_a_declared_variant_keeps_its_pre_commit_and_still_gets_pre_push(self):
        repo = scratch_repo(self.fleet / "custom")
        (repo / ".githooks").mkdir()
        (repo / ".githooks" / "pre-commit").write_text("custom\n")
        _, out = self.sync({"custom": {"hookVariant": "bespoke"}})
        self.assertEqual((repo / ".githooks" / "pre-commit").read_text(), "custom\n")
        self.assertTrue((repo / ".githooks" / "pre-push").is_file())
        self.assertIn("declared hook variant (bespoke)", out)

    def test_a_private_repo_outside_the_fleet_is_synced_with_the_private_variant(self):
        repo = scratch_repo(self.tmp / "elsewhere" / "notes")
        self.private = {"notes": repo}
        _, out = self.sync({})
        self.assertIn("[OK] notes: private-variant hook synced", out)
        self.assertEqual((repo / ".githooks" / "pre-commit").read_bytes(),
                         (TEMPLATES / "pre-commit-private").read_bytes())

    def test_a_private_repo_with_no_git_folder_is_skipped(self):
        self.private = {"notes": self.tmp / "nowhere"}
        _, out = self.sync({})
        self.assertIn("[SKIP] notes: no .git", out)

    def test_a_second_run_changes_nothing(self):
        repo = scratch_repo(self.fleet / "alpha")
        self.sync({"alpha": {}})
        first = (repo / ".githooks" / "pre-commit").read_bytes()
        code, _ = self.sync({"alpha": {}})
        self.assertEqual(code, 0)
        self.assertEqual((repo / ".githooks" / "pre-commit").read_bytes(), first)


class TestCommandAuditFleet(ScratchHome):
    def setUp(self):
        super().setUp()
        (self.oc / "skills" / "audit" / "scripts").mkdir(parents=True)

    def audit(self, skills_root=None, runner=None):
        done = subprocess.CompletedProcess([], 0, stdout="12 skills, 0 findings\n", stderr="")
        runner = runner or mock.Mock(return_value=done)
        with mock.patch.object(launcher, "_skills_root", return_value=skills_root), \
                mock.patch.object(launcher.subprocess, "run", runner):
            code, out = quiet(launcher.command_audit_fleet, self.oc)
        return code, out, runner

    def test_a_checkout_without_the_audit_skill_fails(self):
        shutil.rmtree(self.oc / "skills" / "audit")
        code, out, _ = self.audit()
        self.assertEqual(code, 1)
        self.assertIn("this checkout is missing skills/audit", out)

    def test_writes_a_log_with_one_line_per_check(self):
        code, out, _ = self.audit()
        self.assertEqual(code, 0)
        log = (self.oc / "runtime" / "manifests" / "logs" / "audit-fleet.log").read_text()
        self.assertIn("olivercode-skills check_skill_structure.py: ok -- 12 skills, 0 findings", log)
        self.assertIn("[INFO] no skills folder set for this machine", out)

    def test_checks_the_machines_skills_folder_too_and_skips_one_that_is_gone(self):
        mine = self.tmp / "my-skills"
        mine.mkdir()
        _, out, runner = self.audit(skills_root=mine)
        self.assertEqual(runner.call_count, 2)
        scanned = [call.args[0][-1] for call in runner.call_args_list]
        self.assertEqual(scanned, [str(mine), str(self.oc / "skills")])
        _, out, runner = self.audit(skills_root=self.tmp / "gone")
        self.assertEqual(runner.call_count, 1)
        self.assertIn("[SKIP] skills:", out)

    def test_a_finding_is_reported_as_fail_and_never_fixed(self):
        failing = mock.Mock(return_value=subprocess.CompletedProcess([], 1, stdout="1 finding\n", stderr=""))
        code, out, _ = self.audit(runner=failing)
        self.assertEqual(code, 0)
        self.assertIn("[FAIL] check_skill_structure.py: 1 finding", out)

    def test_a_check_that_prints_nothing_is_still_logged(self):
        silent = mock.Mock(return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""))
        _, out, _ = self.audit(runner=silent)
        self.assertIn("(no output)", out)


class TestPlacementDrift(ScratchHome):
    def setUp(self):
        super().setUp()
        self.skills = self.home / ".claude" / "skills"
        patcher = mock.patch.object(launcher, "_check_fleet_hooks", return_value=(0, 0, 0))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.add_skill("alpha")
        self.add_skill("beta")

    def drift(self):
        return quiet(launcher._check_placement_drift, self.oc)

    def link(self, name, target=None):
        self.skills.mkdir(parents=True, exist_ok=True)
        (self.skills / name).symlink_to(target or self.oc / "skills" / name)

    def test_no_claude_skills_folder_is_a_skip(self):
        (passed, failed, skipped), out = self.drift()
        self.assertEqual((passed, failed, skipped), (0, 0, 1))
        self.assertIn("~/.claude/skills/ not present", out)

    def test_a_checkout_nothing_links_to_is_a_warning_and_not_drift(self):
        self.skills.mkdir(parents=True)
        (passed, failed, skipped), out = self.drift()
        self.assertEqual(failed, 0)
        self.assertEqual(skipped, 1)
        self.assertIn("not the machine's installed OliverCode", out)

    def test_every_skill_linked_passes(self):
        self.link("alpha")
        self.link("beta")
        (passed, failed, skipped), out = self.drift()
        self.assertEqual((passed, failed, skipped), (2, 0, 0))
        self.assertIn("all 2 OliverCode skills correctly symlinked", out)

    def test_a_skill_with_no_link_fails_and_is_named(self):
        self.link("alpha")
        (_, failed, _), out = self.drift()
        self.assertEqual(failed, 1)
        self.assertIn("not symlinked at ~/.claude/skills/: beta", out)

    def test_a_link_to_another_checkout_fails_and_is_named(self):
        self.link("alpha")
        other = self.tmp / "other"
        other.mkdir()
        self.link("beta", other)
        (_, failed, _), out = self.drift()
        self.assertEqual(failed, 1)
        self.assertIn("pointing elsewhere: beta", out)

    def test_a_broken_link_fails_and_is_named(self):
        self.link("alpha")
        self.link("beta")
        self.link("stale", self.tmp / "moved")
        (_, failed, _), out = self.drift()
        self.assertEqual(failed, 1)
        self.assertIn("broken symlinks in ~/.claude/skills/: stale", out)

    def test_the_fleet_hook_counts_are_added_in(self):
        self.link("alpha")
        self.link("beta")
        with mock.patch.object(launcher, "_check_fleet_hooks", return_value=(3, 2, 1)):
            (passed, failed, skipped), _ = self.drift()
        self.assertEqual((passed, failed, skipped), (5, 2, 1))


class TestTickJobs(unittest.TestCase):
    """The scheduler decides what is due from marker files, runs jobs in order, and touches a
    marker only after a job succeeds. tests/test_scheduler_tick.py covers a hang and a failure."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-tickjobs-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        patcher = mock.patch.object(tick, "LOG_DIR", self.tmp / "logs")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ok = subprocess.CompletedProcess([], 0, stdout="done", stderr="")

    def run_main(self, jobs, runner):
        with mock.patch.object(tick, "JOBS", jobs), mock.patch.object(tick.subprocess, "run", runner):
            return tick.main()

    def test_a_successful_job_touches_its_marker_and_logs_ok(self):
        marker = self.tmp / "marker"
        tick.ensure_dirs()
        with mock.patch.object(tick.subprocess, "run", return_value=self.ok):
            tick.run_job("push-fleet", marker, ["push-fleet"])
        self.assertTrue(marker.exists())
        self.assertIn("push-fleet: OK", (self.tmp / "logs" / "scheduler.log").read_text())
        self.assertIn("done", (self.tmp / "logs" / "push-fleet.log").read_text())

    def test_the_job_runs_the_launcher_with_its_arguments_and_the_timeout(self):
        tick.ensure_dirs()
        runner = mock.Mock(return_value=self.ok)
        with mock.patch.object(tick.subprocess, "run", runner):
            tick.run_job("audit-fleet", self.tmp / "m", ["audit-fleet"])
        argv = runner.call_args.args[0]
        self.assertEqual(argv[1:], [str(tick.OC_ROOT / "scripts" / "olivercode"), "audit-fleet"])
        self.assertEqual(runner.call_args.kwargs["timeout"], tick.JOB_TIMEOUT_S)

    def test_jobs_run_in_listed_order(self):
        first, second = self.tmp / "first", self.tmp / "second"
        runner = mock.Mock(return_value=self.ok)
        self.run_main([("one", first, 0, ["one"]), ("two", second, 0, ["two"])], runner)
        self.assertEqual([call.args[0][-1] for call in runner.call_args_list], ["one", "two"])

    def test_a_job_that_is_not_due_is_left_alone(self):
        recent, stale = self.tmp / "recent", self.tmp / "stale"
        recent.touch()
        runner = mock.Mock(return_value=self.ok)
        self.run_main([("recent", recent, 3600, ["recent"]), ("stale", stale, 3600, ["stale"])], runner)
        self.assertEqual([call.args[0][-1] for call in runner.call_args_list], ["stale"])

    def test_a_marker_older_than_the_interval_makes_the_job_due(self):
        marker = self.tmp / "marker"
        marker.touch()
        old = marker.stat().st_mtime - 7200
        os.utime(marker, (old, old))
        runner = mock.Mock(return_value=self.ok)
        self.run_main([("late", marker, 3600, ["late"])], runner)
        self.assertEqual(runner.call_count, 1)
        self.assertLess(tick.seconds_since(marker), 60)

    def test_a_missing_marker_counts_as_infinitely_old(self):
        self.assertEqual(tick.seconds_since(self.tmp / "none"), float("inf"))

    def test_the_shipped_jobs_run_push_fleet_then_audit_fleet(self):
        self.assertEqual([job[0] for job in tick.JOBS], ["push-fleet", "audit-fleet"])
        self.assertEqual([job[3] for job in tick.JOBS], [["push-fleet"], ["audit-fleet"]])


if __name__ == "__main__":
    unittest.main()
