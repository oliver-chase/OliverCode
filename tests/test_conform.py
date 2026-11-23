"""`olivercode conform`: each requirement in docs/CONTRACT.md passes on a bootstrapped repo and fails, with its fix, when broken."""

import atexit
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, load_script, scratch_repo, quiet, temp_dir

launcher = load_script("scripts/olivercode", "olivercode_launcher")
from lib import cmd_fleet  # noqa: E402  (load_script put scripts/ on the path)
from lib import conform  # noqa: E402  (load_script put scripts/ on the path)

TEMPLATES = REPO_ROOT / "core" / "templates" / "project"
TODAY = date(2026, 11, 2)


_TEMPLATE = []


def _template_repo():
    """The bootstrapped repo every test starts from, built once and copied per test."""
    if not _TEMPLATE:
        holder = Path(tempfile.mkdtemp(prefix="olivercode-conform-template-"))
        atexit.register(shutil.rmtree, holder, ignore_errors=True)
        repo = scratch_repo(holder / "widgets")
        quiet(launcher.command_bootstrap, REPO_ROOT, repo, False)
        (repo / "scripts").mkdir(exist_ok=True)
        (repo / "scripts" / "validate.sh").write_text("#!/usr/bin/env bash\n# managed:validate-queue\nexit 0\n")
        (repo / ".gitignore").write_text(".env.*\n.env\n*.pem\n*.key\n.secrets/\n")
        (repo / "README.md").write_text("# widgets\n")
        (repo / "CLAUDE.md").write_text("Run `bash scripts/validate.sh` before committing.\n")
        (repo / ".olivercode").mkdir(exist_ok=True)
        (repo / ".olivercode" / "policy.json").write_text("{}\n")
        cmd_fleet._install_hook_pair(repo, TEMPLATES, private_repo=False)
        _TEMPLATE.append(repo)
    return _TEMPLATE[0]


class ConformBase(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-conform-")
        self.repo = self.tmp / "widgets"
        shutil.copytree(_template_repo(), self.repo, symlinks=True)

    def rows(self, **kwargs):
        rows = conform.check_repo(self.repo, oc_root=REPO_ROOT, offline=True, today=TODAY, **kwargs)
        return {row.requirement: row for row in rows}

    def contract(self, text):
        path = self.repo / "docs" / "repo-structure-contract.md"
        path.write_text(path.read_text() + text)


class TestRequirements(ConformBase):
    def test_a_bootstrapped_repo_passes_every_check_that_can_run_offline(self):
        rows = self.rows()
        for name in ("ignore", "validation", "hooks", "managed-files", "permission-policy"):
            self.assertEqual("pass", rows[name].status, f"{name}: {rows[name].detail}")
        self.assertEqual("skip", rows["board"].status)
        self.assertEqual("skip", rows["unfinished-work-snapshot"].status, "only the engine checkout reads the machine's settings")

    def test_the_contract_keeps_the_rows_that_protect_a_repo_and_none_of_the_self_rules(self):
        names = {check.__name__.replace("_", "-") for check in conform.CHECKS}
        kept = {"ignore", "hooks", "engine-only", "fleet-private", "issues", "managed-files", "tests", "delete-on-merge", "branches", "sleep-setting", "board",
                "validation", "permission-policy", "unfinished-work-snapshot"}
        self.assertEqual(kept, names)
        contract = (REPO_ROOT / "docs" / "CONTRACT.md").read_text()
        for gone in ("layout", "readme", "folders", "docs", "learning", "research", "audit", "automation", "live-launcher", "dead-selftest", "queue-bypass", "features", "machines"):
            self.assertNotIn(f"| `{gone}` |", contract)
        for row in kept:
            self.assertIn(f"| `{row}` |", contract)

    def test_the_register_and_its_commands_are_gone(self):
        self.assertFalse((REPO_ROOT / "docs" / "STANDARDS.json").exists())
        for module in ("features", "machines"):
            self.assertFalse((REPO_ROOT / "scripts" / "lib" / f"{module}.py").exists())

    def test_a_repo_with_no_permission_policy_fails_naming_the_init_command(self):
        (self.repo / ".olivercode" / "policy.json").unlink()
        row = self.rows()["permission-policy"]
        self.assertEqual("fail", row.status)
        self.assertEqual(f"olivercode policy init {self.repo}", row.fix)

    def test_the_snapshot_row_fails_on_the_engine_checkout_when_the_settings_lack_the_hook(self):
        (self.repo / "scripts" / "lib").mkdir()
        (self.repo / "scripts" / "lib" / "engine_only.py").write_text("x = 1\n")
        (self.tmp / ".claude").mkdir()
        (self.tmp / ".claude" / "settings.json").write_text("{}")
        row = conform.unfinished_work_snapshot(self.repo, home=self.tmp)
        self.assertEqual(("fail", "olivercode install"), (row.status, row.fix))
        with mock.patch.object(conform.claude_settings, "missing", return_value=[]):
            self.assertEqual("pass", conform.unfinished_work_snapshot(self.repo, home=self.tmp).status)

    def test_a_gitignore_missing_a_credential_pattern_fails_naming_it(self):
        self.assertEqual("pass", self.rows()["ignore"].status)
        (self.repo / ".gitignore").write_text(".env*\n*.key\n.secrets/*\n")
        row = self.rows()["ignore"]
        self.assertEqual("fail", row.status)
        self.assertIn("credentials.pem", row.detail)
        (self.repo / ".gitignore").unlink()
        self.assertEqual("fail", self.rows()["ignore"].status)

    def test_bootstrap_ships_a_gitignore_that_passes_the_ignore_row(self):
        (self.repo / ".gitignore").unlink()
        quiet(launcher.command_bootstrap, REPO_ROOT, self.repo, False)
        self.assertEqual("pass", self.rows()["ignore"].status)

    def test_a_repo_with_code_needs_a_tracked_test(self):
        self.assertEqual("skip", self.rows()["tests"].status, "the fixture repo holds no code")
        (self.repo / "app.py").write_text("print(1)\n")
        git(self.repo, "add", "app.py")
        self.assertEqual("fail", self.rows()["tests"].status)
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_app.py").write_text("x = 1\n")
        git(self.repo, "add", "tests")
        self.assertEqual("pass", self.rows()["tests"].status)

    def test_a_claude_md_that_does_not_name_the_validation_command_fails(self):
        (self.repo / "CLAUDE.md").write_text("Rules.\n")
        self.assertEqual("fail", self.rows()["validation"].status)

    def test_a_missing_validate_script_fails(self):
        (self.repo / "scripts" / "validate.sh").unlink()
        self.assertEqual("fail", self.rows()["validation"].status)

    def test_npm_run_validate_named_in_claude_md_passes_when_package_json_has_it(self):
        (self.repo / "scripts" / "validate.sh").unlink()
        (self.repo / "CLAUDE.md").write_text("Run `npm run validate` before committing.\n")
        (self.repo / "package.json").write_text('{"scripts": {"validate": "node test.js"}}')
        self.assertEqual("pass", self.rows()["validation"].status)

    def test_npm_run_check_without_the_package_script_fails(self):
        (self.repo / "scripts" / "validate.sh").unlink()
        (self.repo / "CLAUDE.md").write_text("Run `npm run check` before committing.\n")
        (self.repo / "package.json").write_text('{"scripts": {}}')
        self.assertEqual("fail", self.rows()["validation"].status)

    def test_unset_hooks_path_fails_with_the_sync_fix(self):
        subprocess.run(["git", "-C", str(self.repo), "config", "--unset", "core.hooksPath"], check=True)
        row = self.rows()["hooks"]
        self.assertEqual(("fail", "olivercode sync-hooks --commit --story N"), (row.status, row.fix))

    def test_a_declared_variant_passes_with_a_note_when_only_pre_commit_differs(self):
        (self.repo / ".githooks" / "pre-commit").write_text("#!/usr/bin/env bash\nexit 0\n")
        self.assertEqual("fail", self.rows()["hooks"].status)
        row = self.rows(variant="custom gate")["hooks"]
        self.assertEqual("pass", row.status)
        self.assertIn("declared hook variant", row.detail)

    def test_a_declared_variant_still_fails_when_pre_commit_is_missing_or_not_executable(self):
        (self.repo / ".githooks" / "pre-commit").chmod(0o644)
        self.assertEqual("fail", self.rows(variant="custom gate")["hooks"].status)
        (self.repo / ".githooks" / "pre-commit").unlink()
        self.assertEqual("fail", self.rows(variant="custom gate")["hooks"].status)

    def test_a_private_repo_is_not_failed_for_running_the_private_pre_commit(self):
        cmd_fleet._install_hook_pair(self.repo, TEMPLATES, private_repo=True)
        self.assertEqual("pass", self.rows(private=True)["managed-files"].status)

    def test_an_edited_strict_managed_file_fails(self):
        (self.repo / "QUALITY_BASELINE.md").write_text("changed\n")
        row = self.rows()["managed-files"]
        self.assertEqual("fail", row.status)
        self.assertIn("QUALITY_BASELINE.md", row.detail)

class TestNetworkChecks(ConformBase):
    def board(self, result, loaded=True, off=()):
        with mock.patch.object(conform.backlog_setup, "boards_health", return_value=result), \
                mock.patch.object(conform, "sweep_loaded", return_value=loaded), \
                mock.patch.object(conform.backlog_setup, "workflow_problems", return_value=list(off)):
            return conform.board(self.repo, offline=False)

    def test_a_board_with_no_loaded_sweep_job_fails_naming_what_is_off_with_the_fix(self):
        row = self.board((1, 0, 0), loaded=False, off=["Item closed is off"])
        self.assertEqual("fail", row.status)
        self.assertIn("sweep job is not loaded", row.detail)
        self.assertIn("Item closed is off", row.detail)
        self.assertEqual("Run `olivercode board sync --schedule`", row.fix)

    def test_a_board_that_differs_fails_with_the_backlog_setup_fix(self):
        row = self.board((0, 1, 0))
        self.assertEqual("fail", row.status)
        self.assertIn("backlog-setup", row.fix)

    def test_a_board_that_matches_passes_and_an_unreachable_one_skips(self):
        self.assertEqual("pass", self.board((1, 0, 0)).status)
        self.assertEqual("skip", self.board((0, 0, 1)).status)


class TestFleetPrivate(ConformBase):
    """The fleet privacy row, with a fake gh and a fake fleet folder (#822)."""

    def setUp(self):
        super().setUp()
        self.fleet = self.tmp / "fleet"
        self.fleet.mkdir()
        subprocess.run(["git", "init", "-q", str(self.fleet)], check=True)
        subprocess.run(["git", "-C", str(self.fleet), "remote", "add", "origin", "https://github.com/someone/their-fleet.git"], check=True)
        gate = self.repo / conform.ENGINE_GATE
        gate.parent.mkdir(parents=True, exist_ok=True)
        gate.write_text("")

    def check(self, info, people, offline=False):
        def gh(args, **_):
            body = people if args[-1].endswith("/collaborators") else info
            return subprocess.CompletedProcess(args, 0 if body is not None else 1, stdout=json.dumps(body), stderr="")
        with mock.patch.object(conform.local_config, "fleet_registry_path", return_value=self.fleet / "repo-profiles.json"):
            return conform.fleet_private(self.repo, offline=offline, runner=gh)

    def test_a_private_repo_with_only_its_owner_passes(self):
        self.assertEqual("pass", self.check({"private": True}, [{"login": "someone"}]).status)

    def test_a_public_repo_fails_with_the_visibility_fix(self):
        row = self.check({"private": False}, [{"login": "someone"}])
        self.assertEqual("fail", row.status)
        self.assertIn("--visibility private", row.fix)

    def test_a_collaborator_fails_with_the_removal_fix(self):
        row = self.check({"private": True}, [{"login": "someone"}, {"login": "friend"}])
        self.assertEqual("fail", row.status)
        self.assertIn("collaborator", row.detail)
        self.assertIn("Collaborators", row.fix)

    def test_it_skips_offline_off_the_engine_and_when_gh_is_silent(self):
        self.assertEqual("skip", self.check({"private": True}, [], offline=True).status)
        self.assertEqual("skip", self.check(None, None).status)
        (self.repo / conform.ENGINE_GATE).unlink()
        self.assertEqual("skip", self.check({"private": True}, []).status)


class TestIssues(ConformBase):
    """The open issues of the OliverCode repo never name a fleet repo, so the public board never leaks one (#814)."""

    def setUp(self):
        super().setUp()
        (self.repo / "docs" / "backlog-config.json").write_text(json.dumps({"repoOwner": "acme", "repoName": "OliverCode"}))

    def issues(self, found, names=("zz-example-repo",), offline=False):
        with mock.patch.object(conform.repo_name_guard, "default_names", return_value=list(names)):
            return conform.issues(self.repo, offline=offline, fetch=lambda slug: found)

    def test_an_open_issue_whose_title_names_a_fleet_repo_fails_naming_its_number(self):
        row = self.issues([{"number": 42, "title": "Sync zz-example-repo", "body": ""}, {"number": 43, "title": "Clean", "body": "fine"}])
        self.assertEqual("fail", row.status)
        self.assertIn("#42", row.detail)
        self.assertNotIn("#43", row.detail)
        self.assertNotIn("zz-example-repo", row.detail + row.fix)

    def test_an_open_issue_whose_body_names_a_fleet_repo_fails(self):
        row = self.issues([{"number": 7, "title": "Docs", "body": "Copy the layout from zz-example-repo."}])
        self.assertEqual("fail", row.status)
        self.assertIn("#7", row.detail)

    def test_open_issues_that_name_no_fleet_repo_pass(self):
        self.assertEqual("pass", self.issues([{"number": 1, "title": "Board sync", "body": "Keep it in step."}]).status)

    def test_it_skips_offline_for_another_repo_with_no_names_and_when_github_is_silent(self):
        self.assertEqual("skip", self.issues([], offline=True).status)
        self.assertEqual("skip", self.issues([{"number": 1, "title": "zz-example-repo", "body": ""}], names=()).status)
        self.assertEqual("skip", self.issues(None).status)
        (self.repo / "docs" / "backlog-config.json").write_text(json.dumps({"repoOwner": "acme", "repoName": "widgets"}))
        self.assertEqual("skip", self.issues([{"number": 1, "title": "zz-example-repo", "body": ""}]).status)


class TestTimeouts(ConformBase):
    def test_a_check_that_times_out_fails_its_row_and_the_rest_still_run(self):
        def slow(repo, **_):
            raise subprocess.TimeoutExpired("git", 60)
        with mock.patch.object(conform, "CHECKS", (slow, conform.ignore)):
            rows = {row.requirement: row for row in conform.check_repo(self.repo, offline=True)}
        self.assertEqual("fail", rows["slow"].status)
        self.assertIn("timed out after 60 seconds", rows["slow"].detail)
        self.assertIn("ignore", rows)


class TestExceptions(ConformBase):
    def test_a_recorded_exception_turns_the_failure_into_an_exception(self):
        (self.repo / "scripts" / "validate.sh").unlink()
        self.contract("\n## Contract exceptions\n\n- validation: the repo builds with make. Expires 2026-12-01\n")
        row = self.rows()["validation"]
        self.assertEqual("exception", row.status)
        self.assertIn("the repo builds with make", row.detail)

    def test_an_expired_exception_fails_and_leaves_the_requirement_failing(self):
        (self.repo / "scripts" / "validate.sh").unlink()
        self.contract("\n## Contract exceptions\n\n- validation: the repo builds with make. Expires 2026-10-01\n")
        rows = conform.check_repo(self.repo, oc_root=REPO_ROOT, offline=True, today=TODAY)
        by = {row.requirement: row for row in rows}
        self.assertEqual("fail", by["validation"].status)
        self.assertEqual("fail", by["exceptions"].status)
        self.assertIn("expired on 2026-10-01", by["exceptions"].detail)

    def test_an_entry_with_no_reason_or_an_unknown_requirement_fails(self):
        self.contract("\n## Contract exceptions\n\n- validation: . Expires 2026-12-01\n- nonsense: a reason. Expires 2026-12-01\n")
        _, bad = conform.exceptions(self.repo, TODAY)
        self.assertEqual(2, len(bad))

    def test_an_impossible_date_or_another_list_marker_is_an_unreadable_entry_and_never_a_crash(self):
        self.contract("\n## Contract exceptions\n\n- validation: x. Expires 2026-13-45\n* hooks: y. Expires 2027-01-01\n")
        _, bad = conform.exceptions(self.repo, TODAY)
        self.assertEqual(2, len(bad))

    def test_an_exception_for_a_passing_requirement_changes_nothing(self):
        self.contract("\n## Contract exceptions\n\n- validation: unused. Expires 2026-12-01\n")
        self.assertEqual("pass", self.rows()["validation"].status)


class TestCommand(ConformBase):
    def test_the_command_exits_non_zero_on_a_failure_and_zero_when_clean(self):
        (code, out) = quiet(launcher.command_conform, REPO_ROOT, self.repo, None, True)
        self.assertEqual(0, code, out)
        (self.repo / "scripts" / "validate.sh").unlink()
        (code, out) = quiet(launcher.command_conform, REPO_ROOT, self.repo, None, True)
        self.assertEqual(1, code)
        self.assertIn("[FAIL] validation", out)

    def test_hooks_only_checks_the_hooks_and_nothing_else(self):
        (self.repo / "scripts" / "validate.sh").unlink()
        code, out = quiet(launcher.command_conform, REPO_ROOT, self.repo, None, True, True)
        self.assertEqual(0, code, out)
        self.assertIn("[OK] hooks", out)
        self.assertNotIn("validation", out)

    def test_with_no_directory_it_prints_one_block_per_registered_repo(self):
        profiles = {"widgets": {}, "absent": {}}
        with mock.patch.object(cmd_fleet, "load_repo_profiles", return_value=(profiles, None)), \
                mock.patch.object(cmd_fleet, "registry_gap", return_value=""):
            code, out = quiet(launcher.command_conform, REPO_ROOT, None, self.tmp, True)
        self.assertEqual(0, code, out)
        self.assertIn("widgets\n", out)
        self.assertIn("absent is not cloned", out)
        self.assertIn("Checked 1", out)

    def test_a_directory_that_does_not_exist_is_rejected_and_not_reported_as_drift(self):
        code, out = quiet(launcher.command_conform, REPO_ROOT, self.tmp / "nope", None, True)
        self.assertEqual(1, code)
        self.assertIn("is not a directory", out)
        self.assertNotIn("validation", out)

    def test_a_directory_takes_its_hook_variant_from_the_registry(self):
        (self.repo / ".githooks" / "pre-commit").write_text("#!/usr/bin/env bash\nexit 0\n")
        code, _ = quiet(launcher.command_conform, REPO_ROOT, self.repo, self.tmp, True)
        self.assertEqual(1, code)
        profiles = {"widgets": {"hookVariant": "custom gate"}}
        with mock.patch.object(cmd_fleet, "load_repo_profiles", return_value=(profiles, None)):
            code, out = quiet(launcher.command_conform, REPO_ROOT, self.repo, self.tmp, True)
        self.assertEqual(0, code, out)
        self.assertIn("declared hook variant", out)

    def test_an_empty_fleet_reports_nothing_registered(self):
        with mock.patch.object(cmd_fleet, "load_repo_profiles", return_value=({}, None)), \
                mock.patch.object(cmd_fleet, "registry_gap", return_value=""):
            code, out = quiet(launcher.command_conform, REPO_ROOT, None, self.tmp, True)
        self.assertEqual(0, code)
        self.assertIn("no fleet registered", out)


    def test_private_repos_with_no_repo_checked_exit_1_and_keep_the_key_name(self):
        with mock.patch.object(cmd_fleet, "load_repo_profiles", return_value=({}, None)), \
                mock.patch.object(cmd_fleet, "registry_gap", return_value=""), \
                mock.patch.object(cmd_fleet, "_private_repos", return_value={"notes": self.tmp}):
            code, out = quiet(launcher.command_conform, REPO_ROOT, None, self.tmp, True)
        self.assertEqual(1, code, out)
        self.assertIn("No fleet is set", out)
        self.assertIn("`fleetRegistry`", out)


class TestSleepSetting(ConformBase):
    def check(self, text, system="darwin"):
        gate = self.repo / conform.ENGINE_GATE
        gate.parent.mkdir(parents=True, exist_ok=True)
        gate.write_text("")
        return conform.sleep_setting(self.repo, runner=lambda: text, system=system)

    def test_a_sleep_that_would_stop_work_fails_with_the_fix(self):
        row = self.check(" sleep 1\n displaysleep 5\n")
        self.assertEqual("fail", row.status)
        self.assertIn("caffeinate -dimsu", row.fix)

    def test_safe_settings_pass(self):
        self.assertEqual("pass", self.check(" sleep 0\n displaysleep 0\n").status)

    def test_a_host_that_is_not_macos_skips(self):
        self.assertEqual("skip", self.check(" sleep 1\n", system="linux").status)
