"""Direct tests for the launcher commands that had none: skills, discover, sync-hooks,
audit-fleet and placement drift.

Every test runs against a scratch checkout and a scratch HOME. Nothing reaches the network, and
git reads no machine config (tests/_support.py).
"""

import os
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, load_script, scratch_repo, quiet, temp_dir

TEMPLATES = REPO_ROOT / "core" / "templates" / "project"
launcher = load_script("scripts/olivercode", "olivercode_launcher")
from lib import local_config  # noqa: E402  (load_script put scripts/ on the path)
from lib import cmd_fleet, cmd_health, cmd_repo  # noqa: E402


class ScratchHome(unittest.TestCase):
    """A scratch HOME and checkout that no test can leave behind."""

    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-fleetcmd-", resolve=True)
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
        with mock.patch.object(cmd_repo, "OC_ROOT", self.oc):
            return quiet(launcher.command_skills, list(argv))

    def test_grep_filters_by_name_and_description(self):
        self.add_skill("alpha", "Sorts mail.")
        self.add_skill("beta", "Pulls reports.")
        code, out = self.run_skills("--grep", "REPORTS")
        self.assertEqual(code, 0)
        self.assertIn("beta", out)
        self.assertNotIn("alpha", out)

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

    def test_prints_a_profile_skeleton_with_explicit_paths(self):
        scratch_repo(self.fleet / "widgets")
        _, out = self.discover(self.fleet)
        self.assertIn('"canonicalValidationCommand": "<command>"', out)
        self.assertIn(f'"path": "{self.fleet / "widgets"}"', out)

    def test_skips_a_linked_worktree(self):
        scratch_repo(self.fleet / "real")
        wt = self.fleet / "_worktrees" / "real-wt"
        wt.mkdir(parents=True)
        (wt / ".git").write_text("gitdir: ../../real/.git/worktrees/real-wt\n")
        _, out = self.discover(self.fleet)
        self.assertNotIn("real-wt", out)

    def test_skips_the_framework_checkout_and_vendored_noise(self):
        scratch_repo(self.oc)
        scratch_repo(self.fleet / "node_modules" / "dep")
        scratch_repo(self.fleet / "real")
        _, out = self.discover(self.oc.parent)
        self.assertIn("real", out)
        self.assertNotIn("dep", out)

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
        with mock.patch.object(cmd_fleet, "load_repo_profiles", return_value=(profiles, None)), \
                mock.patch.object(cmd_fleet, "_private_repos", return_value=self.private):
            return quiet(launcher.command_sync_hooks, self.oc, self.fleet)

    def test_a_fleet_repo_gets_the_public_hooks_and_a_hooks_path(self):
        repo = scratch_repo(self.fleet / "alpha")
        (repo / ".githooks").mkdir()
        (repo / ".githooks" / "pre-commit-private").write_text("stale\n")
        code, out = self.sync({"alpha": {}})
        self.assertEqual(code, 0)
        self.assertIn("[OK] alpha: hooks synced", out)
        self.assertEqual(["commit-msg", "pre-commit", "pre-push"], sorted(p.name for p in (repo / ".githooks").iterdir()))
        self.assertEqual((repo / ".githooks" / "pre-commit").read_bytes(), (TEMPLATES / "pre-commit").read_bytes())
        self.assertTrue(os.access(repo / ".githooks" / "pre-commit", os.X_OK))
        self.assertEqual(git(repo, "config", "--get", "core.hooksPath").stdout.strip(), ".githooks")
        for name in ("pre-push", "commit-msg"):
            self.assertTrue((repo / ".githooks" / name).is_file(), name)

    def test_a_private_profile_gets_the_private_variant_as_its_live_hook(self):
        repo = scratch_repo(self.fleet / "vault")
        (repo / ".githooks").mkdir()
        (repo / ".githooks" / "pre-commit-private").write_text("stale\n")
        self.sync({"vault": {"private": True}})
        self.assertEqual((repo / ".githooks" / "pre-commit").read_bytes(),
                         (TEMPLATES / "pre-commit-private").read_bytes())
        self.assertFalse((repo / ".githooks" / "pre-commit-private").exists())

    def test_a_repo_missing_from_this_machine_is_skipped(self):
        code, out = self.sync({"ghost": {}})
        self.assertEqual(code, 0)
        self.assertIn("ghost", out)

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
        self.assertIn("[OK] notes", out)
        self.assertEqual((repo / ".githooks" / "pre-commit").read_bytes(),
                         (TEMPLATES / "pre-commit-private").read_bytes())

    def test_a_private_repo_with_no_git_folder_is_skipped(self):
        self.private = {"notes": self.tmp / "nowhere"}
        _, out = self.sync({})
        self.assertIn("[SKIP] notes: no .git", out)

    def test_with_the_harness_config_it_touches_nothing_outside_the_temp_dir(self):
        """No fixture config: the machine's olivercode.local.json must not reach the run."""
        self.assertEqual(os.environ["OLIVERCODE_LOCAL_CONFIG"], os.devnull)
        self.assertEqual(({}, {}), (cmd_fleet._private_repos(), local_config.repo_paths()))
        (self.oc / "shared").mkdir()
        (self.oc / "shared" / "repo-profiles.json").write_text('{"profiles": {}}')
        scratch_repo(self.fleet / "alpha")
        with mock.patch.object(cmd_fleet, "registry_gap", return_value=None):
            code, out = quiet(launcher.command_sync_hooks, self.oc, self.fleet)
        self.assertEqual(code, 0)
        self.assertIn("0 target(s) synced, 0 skipped.", out)
        self.assertFalse((self.fleet / "alpha" / ".githooks").exists())

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
        with mock.patch.object(cmd_fleet, "_skills_root", return_value=skills_root), \
                mock.patch.object(launcher.subprocess, "run", runner):
            code, out = quiet(launcher.command_audit_fleet, self.oc)
        return code, out, runner

    def test_a_check_that_crashes_exits_one_and_findings_exit_zero(self):
        for returncode, stderr in ((2, ""), (1, "Traceback (most recent call last):")):
            done = subprocess.CompletedProcess([], returncode, stdout="a finding\n", stderr=stderr)
            code, _, _ = self.audit(runner=mock.Mock(return_value=done))
            self.assertEqual(code, 1)

    def test_a_checkout_without_the_audit_skill_fails(self):
        shutil.rmtree(self.oc / "skills" / "audit")
        code, out, _ = self.audit()
        self.assertEqual(code, 1)
        self.assertIn("this checkout is missing skills/audit", out)

    def test_prints_one_line_per_check(self):
        code, out, _ = self.audit()
        self.assertEqual(code, 0)
        self.assertIn("12 skills", out)
        self.assertIn("no skills folder", out)

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
        self.assertIn("[FAIL]", out)

    def test_a_check_that_prints_nothing_is_still_logged(self):
        silent = mock.Mock(return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""))
        _, out, _ = self.audit(runner=silent)
        self.assertIn("(no output)", out)


class TestPlacementDrift(ScratchHome):
    def setUp(self):
        super().setUp()
        self.skills = self.home / ".claude" / "skills"
        self.add_skill("alpha")
        self.add_skill("beta")

    def drift(self):
        return quiet(cmd_health._check_placement_drift, self.oc)

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
        self.assertIn("installed OliverCode", out)

    def test_every_skill_linked_passes(self):
        self.link("alpha")
        self.link("beta")
        (passed, failed, skipped), out = self.drift()
        self.assertEqual((passed, failed, skipped), (2, 0, 0))
        self.assertIn("all 2", out)

    def test_a_skill_with_no_link_fails_and_is_named(self):
        self.link("alpha")
        (_, failed, _), out = self.drift()
        self.assertEqual(failed, 1)
        self.assertIn("beta", out)

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
        self.assertIn("stale", out)


if __name__ == "__main__":
    unittest.main()
