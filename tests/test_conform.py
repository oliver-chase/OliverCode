"""`olivercode conform`: each requirement in docs/CONTRACT.md passes on a bootstrapped repo and fails, with its fix, when broken."""

import json
import subprocess
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, load_script, scratch_repo, quiet, temp_dir

launcher = load_script("scripts/olivercode", "olivercode_launcher")
from lib import cmd_fleet  # noqa: E402  (load_script put scripts/ on the path)
from lib import conform  # noqa: E402  (load_script put scripts/ on the path)

TEMPLATES = REPO_ROOT / "core" / "templates" / "project"
TODAY = date(2026, 11, 2)


class ConformBase(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-conform-")
        self.repo = scratch_repo(self.tmp / "widgets")
        quiet(launcher.command_bootstrap, REPO_ROOT, self.repo, False)
        (self.repo / "scripts").mkdir(exist_ok=True)
        (self.repo / "scripts" / "validate.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
        (self.repo / "README.md").write_text("# widgets\n")
        (self.repo / "CLAUDE.md").write_text("Run `bash scripts/validate.sh` before committing.\n")
        cmd_fleet._install_hook_pair(self.repo, TEMPLATES, private_repo=False)
        quiet(launcher.command_size, REPO_ROOT, self.repo, True)

    def rows(self, **kwargs):
        rows = conform.check_repo(self.repo, oc_root=REPO_ROOT, offline=True, today=TODAY, **kwargs)
        return {row.requirement: row for row in rows}

    def contract(self, text):
        path = self.repo / "docs" / "repo-structure-contract.md"
        path.write_text(path.read_text() + text)


class TestRequirements(ConformBase):
    def test_a_bootstrapped_repo_passes_every_check_that_can_run_offline(self):
        rows = self.rows()
        for name in ("layout", "validation", "hooks", "managed-files", "size"):
            self.assertEqual("pass", rows[name].status, f"{name}: {rows[name].detail}")
        self.assertEqual("skip", rows["board"].status)
        self.assertEqual("manual", rows["audit"].status)

    def test_a_missing_root_doc_fails_layout_with_the_bootstrap_fix(self):
        (self.repo / "README.md").unlink()
        row = self.rows()["layout"]
        self.assertEqual("fail", row.status)
        self.assertIn("README.md", row.detail)
        self.assertIn("olivercode bootstrap", row.fix)

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
        self.assertEqual(("fail", "olivercode sync-hooks"), (row.status, row.fix))

    def test_a_declared_variant_passes_with_a_note_when_only_pre_commit_differs(self):
        (self.repo / ".githooks" / "pre-commit").write_text("#!/usr/bin/env bash\nexit 0\n")
        self.assertEqual("fail", self.rows()["hooks"].status)
        row = self.rows(variant="custom gate")["hooks"]
        self.assertEqual("pass", row.status)
        self.assertIn("declared hook variant", row.detail)

    def test_a_private_repo_is_not_failed_for_running_the_private_pre_commit(self):
        cmd_fleet._install_hook_pair(self.repo, TEMPLATES, private_repo=True)
        self.assertEqual("pass", self.rows(private=True)["managed-files"].status)

    def test_an_edited_strict_managed_file_fails(self):
        (self.repo / "QUALITY_BASELINE.md").write_text("changed\n")
        row = self.rows()["managed-files"]
        self.assertEqual("fail", row.status)
        self.assertIn("QUALITY_BASELINE.md", row.detail)

    def test_growing_past_the_baseline_allowance_fails_size(self):
        (self.repo / "big.py").write_text("x = 1\n" * 500)
        subprocess.run(["git", "-C", str(self.repo), "add", "big.py"], check=True)
        self.assertEqual("fail", self.rows()["size"].status)

    def test_an_unset_baseline_fails_size(self):
        path = self.repo / "docs" / "SIZE-BASELINE.json"
        path.write_text(json.dumps({"lines": None}))
        self.assertEqual("fail", self.rows()["size"].status)


class TestNetworkChecks(ConformBase):
    def board(self, result):
        with mock.patch.object(conform.backlog_setup, "boards_health", return_value=result):
            return conform.board(self.repo, offline=False)

    def test_a_board_that_differs_fails_with_the_backlog_setup_fix(self):
        row = self.board((0, 1, 0))
        self.assertEqual("fail", row.status)
        self.assertIn("backlog-setup", row.fix)

    def test_a_board_that_matches_passes_and_an_unreachable_one_skips(self):
        self.assertEqual("pass", self.board((1, 0, 0)).status)
        self.assertEqual("skip", self.board((0, 0, 1)).status)

    def about(self, stdout, returncode=0):
        runner = mock.Mock(return_value=subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=""))
        return conform.docs(self.repo, offline=False, runner=runner)

    def test_an_about_with_a_description_and_topics_passes(self):
        self.assertEqual("pass", self.about(json.dumps({"description": "x", "repositoryTopics": [{"name": "a"}]})).status)

    def test_an_empty_about_fails_and_an_unreachable_gh_skips(self):
        self.assertEqual("fail", self.about(json.dumps({"description": " ", "repositoryTopics": []})).status)
        self.assertEqual("skip", self.about("", returncode=1).status)


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
        (self.repo / "README.md").unlink()
        (code, out) = quiet(launcher.command_conform, REPO_ROOT, self.repo, None, True)
        self.assertEqual(1, code)
        self.assertIn("[FAIL] layout", out)

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
        self.assertNotIn("layout", out)

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


if __name__ == "__main__":
    unittest.main()
