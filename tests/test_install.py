"""Install makes the fleet folder a local git repo with one commit, offers a private GitHub copy once, and health repairs a loose folder (#993)."""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, quiet, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_initfleet, cmd_install, health_checks  # noqa: E402

IDENTITY = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}


class FleetRepo(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, IDENTITY)
        patch.start()
        self.addCleanup(patch.stop)

    def commits(self, dest: Path) -> int:
        done = subprocess.run(["git", "-C", str(dest), "rev-list", "--count", "HEAD"], capture_output=True, text=True)
        return int(done.stdout.strip()) if done.returncode == 0 else 0

    def test_the_template_holds_config_only_and_no_board_config(self):
        names = {p.name for p in cmd_initfleet.TEMPLATE.iterdir()}
        self.assertEqual(names, {"repo-profiles.json", "owner-rules.json", "owner-queue.jsonl", "review-config.json", "CLAUDE.md"})

    def test_a_first_install_makes_one_commit_and_asks_once_before_any_push(self):
        dest = temp_dir(self) / "fleet"
        pushed = []
        asked = []
        ask = lambda question: asked.append(question) or "n"  # noqa: E731
        error, _ = quiet(cmd_install.fleet_repo_step, dest, ask, lambda argv: pushed.append(argv) or 0)
        self.assertEqual("", error)
        self.assertEqual(1, self.commits(dest))
        self.assertEqual(1, len(asked))
        self.assertEqual([], pushed)

    def test_a_yes_pushes_through_init_fleet_and_outside_a_terminal_nothing_is_asked(self):
        dest = temp_dir(self) / "fleet"
        pushed = []
        quiet(cmd_install.fleet_repo_step, dest, lambda q: "y", lambda argv: pushed.append(argv) or 0)
        self.assertEqual([["--dir", str(dest)]], pushed)
        other = temp_dir(self) / "other"
        quiet(cmd_install.fleet_repo_step, other, None, lambda argv: pushed.append(argv) or 0)
        self.assertEqual(1, len(pushed))
        self.assertEqual(1, self.commits(other))

    def test_a_loose_folder_keeps_its_files_and_health_makes_it_a_repo(self):
        dest = temp_dir(self) / "fleet"
        dest.mkdir()
        (dest / "repo-profiles.json").write_text('{"repos": []}')
        self.assertEqual((1, 0, 0), quiet(health_checks._check_fleet_repo, dest)[0])
        self.assertEqual('{"repos": []}', (dest / "repo-profiles.json").read_text())
        self.assertEqual(1, self.commits(dest))
        self.assertEqual((1, 0, 0), quiet(health_checks._check_fleet_repo, dest)[0])
        self.assertEqual(1, self.commits(dest))

    def test_a_local_fleet_repo_takes_the_owner_and_name_in_its_placeholders(self):
        dest = temp_dir(self) / "fleet"
        cmd_initfleet.scaffold_local(dest)
        self.assertTrue(cmd_initfleet.fill_placeholders(dest, "me", "fleet"))
        self.assertIn('"me/fleet"', (dest / "review-config.json").read_text())
        self.assertFalse(cmd_initfleet.fill_placeholders(dest, "me", "fleet"))


class BoardStep(unittest.TestCase):
    """Install gives each registered repo its board once gh is ready, and stops before any board when it is not (#994)."""

    def gh(self, code, scopes="'project', 'repo'"):
        stderr = f"Token scopes: {scopes}" if code == 0 else "not logged in"
        return mock.patch.object(health_checks, "_gh_auth_status", return_value=subprocess.CompletedProcess(["gh"], code, "", stderr))

    def test_a_signed_out_gh_stops_the_board_step_before_any_repo(self):
        repo = temp_dir(self) / "widget"
        repo.mkdir()
        with self.gh(1), mock.patch("lib.cmd_fleet.command_backlog_setup") as setup:
            problem, out = quiet(cmd_install.board_step, [("widget", repo)])
        setup.assert_not_called()
        self.assertIn("gh auth login", problem)
        self.assertIn("gh auth login", out)

    def test_each_repo_without_a_config_gets_its_board_and_a_valid_one_is_left(self):
        root = temp_dir(self)
        widget, gadget = root / "widget", root / "gadget"
        for repo in (widget, gadget):
            repo.mkdir()
        (widget / "CLAUDE.md").write_text("# widget\n")
        valid = {"repoOwner": "me", "repoName": "gadget", "projectOwner": "me", "projectNumber": 3, "projectId": "PVT_x"}
        applied = []
        loaded = lambda path: valid if "gadget" in str(path) or applied else None  # noqa: E731
        with self.gh(0), mock.patch("lib.backlog_setup.load_config", side_effect=loaded), \
                mock.patch("lib.cmd_fleet.command_backlog_setup", side_effect=lambda argv: applied.append(argv) or 0) as setup:
            problem, out = quiet(cmd_install.board_step, [("widget", widget), ("gadget", gadget)])
        self.assertEqual("", problem)
        setup.assert_called_once_with([str(widget), "--apply"])
        self.assertIn("backlog-config.json", (widget / "CLAUDE.md").read_text())
        self.assertIn("projects/3", out)




class DesignFile(unittest.TestCase):
    """Install asks once for the owner's design file, the guide names it, and a repo that follows it passes health (#995)."""

    def setUp(self):
        self.config = temp_dir(self) / "olivercode.local.json"
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(self.config)})
        patch.start()
        self.addCleanup(patch.stop)

    def test_install_asks_once_and_a_path_is_saved_as_the_design_file(self):
        from lib import local_config
        own = temp_dir(self) / "mine.md"
        own.write_text("mine\n")
        asked = []
        quiet(cmd_install.design_step, lambda q: asked.append(q) or str(own))
        quiet(cmd_install.design_step, lambda q: asked.append(q) or str(own))
        self.assertEqual(str(own), local_config.load_local()["designFile"])
        self.assertEqual(1, len(asked))

    def test_a_blank_answer_keeps_the_shipped_design_and_is_not_asked_again(self):
        from lib import local_config
        asked = []
        quiet(cmd_install.design_step, lambda q: asked.append(q) or "")
        quiet(cmd_install.design_step, lambda q: asked.append(q) or "")
        self.assertNotIn("designFile", local_config.load_local())
        self.assertTrue(local_config.load_local()["designAsked"])
        self.assertEqual(1, len(asked))

    def test_the_guide_names_design_file_and_the_relink_command(self):
        from lib import cmd_guide
        from lib.local_config import OC_ROOT
        _, out = quiet(cmd_guide.command_guide, OC_ROOT)
        line = next(l for l in out.splitlines() if "designFile" in l)
        self.assertIn("olivercode install", line)
        self.assertIn("~/.claude/DESIGN.md", line)

    def test_a_repo_following_the_users_design_file_passes_and_one_matching_neither_fails(self):
        root = temp_dir(self)
        oc = root / "oc"
        (oc / "docs").mkdir(parents=True)
        (oc / "docs" / "VOICE.md").write_text("voice\n")
        (oc / "docs" / "DESIGN.md").write_text("shipped\n")
        own = root / "mine.md"
        own.write_text("mine\nown rules\n")
        suite = root / "suite"
        (suite / "docs").mkdir(parents=True)
        (suite / "docs" / "VOICE.md").write_text("voice\nsuite\n")
        (suite / "docs" / "DESIGN.md").write_text("mine\nown rules\nmore\n")
        (suite / "skills" / "x").mkdir(parents=True)
        (suite / "skills" / "x" / "SKILL.md").write_text("x\n")
        skills = root / "claude-skills"
        skills.mkdir()
        (skills / "x").symlink_to(suite / "skills" / "x")
        with mock.patch.dict(os.environ, {"OLIVERCODE_DESIGN_FILE": str(own)}):
            _, out = quiet(health_checks._check_voice_copies, oc, skills)
            self.assertIn("DESIGN.md keeps the shared text", out)
            (suite / "docs" / "DESIGN.md").write_text("other\n")
            _, out = quiet(health_checks._check_voice_copies, oc, skills)
            self.assertIn("DESIGN.md changes the shared text", out)




if __name__ == "__main__":
    unittest.main()
