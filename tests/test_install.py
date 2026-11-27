"""Install asks nothing and makes no fleet repo, a local fleet folder passes health only as a repo, and init-fleet reuses it (#993, #1282)."""

import io
import json
import os
import plistlib
import shutil
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

    def local_repo(self, dest: Path, scaffold: bool = False) -> None:
        """A fleet folder that is already a git repo with one commit, as an earlier install left it."""
        if scaffold:
            shutil.copytree(cmd_initfleet.TEMPLATE, dest)
        for step in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "--allow-empty", "-m", "Start"]):
            subprocess.run(["git", "-C", str(dest), *step], check=True, capture_output=True)

    def test_the_template_holds_config_only_and_no_board_config(self):
        names = {p.name for p in cmd_initfleet.TEMPLATE.iterdir()}
        self.assertEqual(names, {"repo-profiles.json", "owner-rules.json", "owner-queue.jsonl", "review-config.json", "CLAUDE.md"})

    def test_a_loose_folder_fails_health_and_stays_untouched_until_made_a_repo(self):
        dest = temp_dir(self) / "fleet"
        dest.mkdir()
        (dest / "repo-profiles.json").write_text('{"repos": []}')
        self.assertEqual((0, 1, 0), quiet(health_checks._check_fleet_repo, dest)[0])
        self.assertEqual('{"repos": []}', (dest / "repo-profiles.json").read_text())
        self.assertFalse((dest / ".git").exists())
        self.local_repo(dest)
        self.assertEqual((1, 0, 0), quiet(health_checks._check_fleet_repo, dest)[0])
        self.assertEqual(1, self.commits(dest))

    def test_a_local_fleet_repo_takes_the_owner_and_name_in_its_placeholders(self):
        dest = temp_dir(self) / "fleet"
        shutil.copytree(cmd_initfleet.TEMPLATE, dest)
        self.assertTrue(cmd_initfleet.fill_placeholders(dest, "me", "fleet"))
        self.assertIn('"me/fleet"', (dest / "review-config.json").read_text())
        self.assertFalse(cmd_initfleet.fill_placeholders(dest, "me", "fleet"))

    def test_init_fleet_on_the_local_repo_adds_a_remote_and_nests_no_repo(self):
        dest = temp_dir(self) / "fleet"
        self.local_repo(dest, scaffold=True)
        calls = []

        def runner(args):
            calls.append(args)
            if args[:3] == ["gh", "api", "repos/me/olivercode-fleet"] and ".name" in args:
                return 1, "gh: Not Found (HTTP 404)"
            if args[:3] == ["gh", "api", "repos/me/olivercode-fleet"] and args[-1] == ".private":
                return 0, "true"
            if args[:3] == ["gh", "api", "repos/me/olivercode-fleet/collaborators?affiliation=direct"]:
                return 0, "[]"
            return 0, ""

        code = quiet(cmd_initfleet.command_init_fleet, ["--owner", "me", "--dir", str(dest)], runner)[0]
        self.assertEqual(0, code)
        git = [args[3:] for args in calls if args[:2] == ["git", "-C"]]
        self.assertIn(["remote", "add", "origin", "https://github.com/me/olivercode-fleet.git"], git)
        self.assertNotIn("init", [step[0] for step in git])
        self.assertEqual([dest / ".git"], list(dest.rglob(".git")))


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

    def test_a_config_naming_another_owners_repo_is_treated_as_absent_and_set_up(self):
        repo = temp_dir(self) / "widget"
        (repo / "docs").mkdir(parents=True)
        (repo / "CLAUDE.md").write_text("# widget\n")
        theirs = {"repoOwner": "someone", "repoName": "widget", "projectOwner": "someone", "projectNumber": 3, "projectId": "PVT_x"}
        (repo / "docs" / "backlog-config.json").write_text(json.dumps(theirs))
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/me/widget.git"], check=True)
        with self.gh(0), mock.patch("lib.cmd_fleet.command_backlog_setup", return_value=0) as setup:
            problem, _ = quiet(cmd_install.board_step, [("widget", repo)])
        self.assertEqual("", problem)
        setup.assert_called_once_with([str(repo), "--apply"])

    def test_a_config_naming_this_repo_is_left_alone(self):
        repo = temp_dir(self) / "widget"
        (repo / "docs").mkdir(parents=True)
        mine = {"repoOwner": "me", "repoName": "widget", "projectOwner": "me", "projectNumber": 3, "projectId": "PVT_x"}
        (repo / "docs" / "backlog-config.json").write_text(json.dumps(mine))
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:me/widget.git"], check=True)
        with self.gh(0), mock.patch("lib.cmd_fleet.command_backlog_setup") as setup:
            quiet(cmd_install.board_step, [("widget", repo)])
        setup.assert_not_called()


class WhoBuilds(unittest.TestCase):
    """The install text, the guide, the README, RULES.md and CLAUDE.md state one rule for who builds a board story (#1013)."""

    RULE = "A chat never builds a board story by hand"

    def test_each_doc_and_the_guide_state_the_one_rule(self):
        from lib import cmd_guide
        for path in ("CLAUDE.md", "docs/RULES.md", "README.md"):
            self.assertIn(self.RULE, (REPO_ROOT / path).read_text(encoding="utf-8"), path)
        self.assertIn(self.RULE, " ".join(cmd_guide.HOW_WORK_RUNS))

    def test_the_first_steps_end_on_building_a_story_in_install(self):
        self.assertIn("3. File your first story: say what you want in Claude Code, then build it with `olivercode dispatch N` or `olivercode drain REPO`", cmd_install.INTRODUCTION)
        # The approved archive copy has no first-story line; its How it works steps name dispatch and drain instead.
        from lib import cmd_guide
        _, out = quiet(cmd_guide.command_guide, REPO_ROOT)
        self.assertIn("olivercode dispatch 42", out)
        self.assertIn("olivercode drain REPO", out)




class DesignFile(unittest.TestCase):
    """The guide names the design file, and a repo that follows it passes health (#995)."""

    def setUp(self):
        self.config = temp_dir(self) / "olivercode.local.json"
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(self.config)})
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_guide_names_design_file_and_the_relink_command(self):
        from lib import cmd_guide
        from lib.local_config import OC_ROOT
        _, out = quiet(cmd_guide.command_guide, OC_ROOT, "design")
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





class InstallAsksNothing(unittest.TestCase):
    """Install reads no input, links the design file the config names, makes no fleet repo and copies the settings of the checkout installed before (#1282)."""

    def setUp(self):
        root = temp_dir(self)
        self.claude = root / ".claude"
        self.config = root / "olivercode.local.json"
        self.prior = root / "prior"
        self.prior.mkdir()
        (self.prior / "CLAUDE.md").write_text("prior rules\n")
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(self.config)})
        patch.start()
        self.addCleanup(patch.stop)
        self.root = root

    def install(self, terminal: bool = True) -> str:
        with mock.patch.object(cmd_install, "_claude_dir", return_value=self.claude), \
                mock.patch.object(cmd_install, "owner_terminal", return_value=terminal), \
                mock.patch.object(cmd_install, "_schedule_replay"), mock.patch.object(cmd_install, "_queue_shim"), \
                mock.patch.object(cmd_install, "board_step"), \
                mock.patch("builtins.input", side_effect=AssertionError("install read input")), \
                mock.patch("sys.stdin", io.StringIO("")):
            _, out = quiet(cmd_install.command_install, REPO_ROOT)
        return out

    def test_install_with_a_terminal_and_empty_stdin_finishes_and_links_the_shipped_design(self):
        out = self.install()
        self.assertEqual((REPO_ROOT / "docs" / "DESIGN.md").resolve(), (self.claude / "DESIGN.md").resolve())
        self.assertNotIn("designAsked", self.config.read_text() if self.config.is_file() else "")
        self.assertNotIn("Path to your own design file", out)

    def test_a_design_file_in_the_config_is_linked_and_a_leftover_designAsked_is_tolerated(self):
        own = self.root / "mine.md"
        own.write_text("mine\n")
        self.config.write_text(json.dumps({"designFile": str(own), "designAsked": True}))
        self.install()
        self.assertEqual(own.resolve(), (self.claude / "DESIGN.md").resolve())

    def test_install_makes_no_fleet_repo_and_writes_no_fleet_registry(self):
        beside = REPO_ROOT.parent / "olivercode-fleet"
        existed = beside.exists()
        out = self.install()
        self.assertEqual(existed, beside.exists())
        self.assertNotIn("Fleet repo", out)
        self.assertNotIn("fleetRegistry", self.config.read_text() if self.config.is_file() else "")

    def test_a_second_checkout_copies_the_settings_of_the_one_the_claude_link_names(self):
        self.claude.mkdir()
        (self.claude / "CLAUDE.md").symlink_to(self.prior / "CLAUDE.md")
        (self.prior / "olivercode.local.json").write_text('{"maxBuilders": 3}')
        out = self.install()
        self.assertEqual({"maxBuilders": 3}, json.loads(self.config.read_text()))
        self.assertEqual(1, out.count("[COPIED]"))
        self.assertEqual((REPO_ROOT / "CLAUDE.md").resolve(), (self.claude / "CLAUDE.md").resolve())

    def test_an_existing_settings_file_is_never_overwritten(self):
        self.claude.mkdir()
        (self.claude / "CLAUDE.md").symlink_to(self.prior / "CLAUDE.md")
        (self.prior / "olivercode.local.json").write_text('{"maxBuilders": 3}')
        self.config.write_text('{"maxBuilders": 1}')
        out = self.install()
        self.assertEqual({"maxBuilders": 1}, json.loads(self.config.read_text()))
        self.assertNotIn("[COPIED]", out)

    def test_nothing_is_copied_when_the_link_names_this_checkout_or_the_other_has_no_settings(self):
        self.claude.mkdir()
        (self.claude / "CLAUDE.md").symlink_to(self.prior / "CLAUDE.md")
        self.assertNotIn("[COPIED]", self.install())
        self.assertFalse(self.config.is_file())


class CityShortcut(unittest.TestCase):
    """Install puts an OliverCode City shortcut on the Desktop once and uninstall removes it; `status page --open` shows the page (#1363)."""

    def setUp(self):
        root = temp_dir(self)
        self.claude = root / ".claude"
        self.desktop = root / "Desktop"
        self.desktop.mkdir()
        self.home = root / "home"
        self.page = self.home / "city.html"
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(root / "olivercode.local.json"), "OLIVERCODE_HOME": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)

    def fake_refresh(self, root=None):
        self.home.mkdir(parents=True, exist_ok=True)
        self.page.write_text("<html>City</html>\n")
        return 0

    def install(self, refresh=None) -> str:
        with mock.patch.object(cmd_install, "_claude_dir", return_value=self.claude), \
                mock.patch.object(cmd_install, "_desktop", return_value=self.desktop), \
                mock.patch.object(cmd_install, "owner_terminal", return_value=False), \
                mock.patch.object(cmd_install, "_schedule_replay"), mock.patch.object(cmd_install, "_queue_shim"), \
                mock.patch("lib.city.refresh", side_effect=refresh or self.fake_refresh) as refreshed:
            _, out = quiet(cmd_install.command_install, REPO_ROOT)
        self.refreshed = refreshed
        return out

    def uninstall(self) -> str:
        with mock.patch.object(cmd_install, "_claude_dir", return_value=self.claude), \
                mock.patch.object(cmd_install, "_desktop", return_value=self.desktop), \
                mock.patch.object(cmd_install, "_queue_shim"), mock.patch.object(cmd_install, "_claude_settings"), \
                mock.patch.object(cmd_install, "remove_jobs", return_value=[]):
            _, out = quiet(cmd_install.command_uninstall, REPO_ROOT)
        return out

    def shortcut(self) -> Path:
        return self.desktop / cmd_install.CITY_SHORTCUT

    def test_install_writes_city_first_then_a_webloc_pointing_at_it(self):
        out = self.install()
        self.assertEqual(1, self.refreshed.call_count)
        self.assertTrue(self.page.is_file())
        with self.shortcut().open("rb") as f:
            self.assertEqual(self.page.as_uri(), plistlib.load(f)["URL"])
        self.assertIn("[ADDED] ~/Desktop/OliverCode City.webloc", out)

    def test_a_page_already_written_is_not_rewritten_before_the_shortcut(self):
        self.home.mkdir(parents=True)
        self.page.write_text("kept\n")
        self.install()
        self.assertEqual(0, self.refreshed.call_count)
        self.assertEqual("kept\n", self.page.read_text())
        self.assertTrue(self.shortcut().is_file())

    def test_no_shortcut_when_city_cannot_be_written(self):
        out = self.install(refresh=lambda root=None: 1)
        self.assertFalse(self.shortcut().exists())
        self.assertIn("[WARN] ~/Desktop/OliverCode City.webloc not written", out)

    def test_a_shortcut_the_owner_deleted_is_not_written_again_by_update(self):
        self.install()
        self.shortcut().unlink()
        out = self.install()
        self.assertFalse(self.shortcut().exists())
        self.assertNotIn("[ADDED]", out)
        self.assertTrue(cmd_install._record_city(self.claude))

    def test_a_shortcut_install_did_not_write_is_left_alone_and_survives_uninstall(self):
        self.shortcut().write_text("the owner's own\n")
        self.install()
        self.assertEqual("the owner's own\n", self.shortcut().read_text())
        self.uninstall()
        self.assertTrue(self.shortcut().exists())

    def test_uninstall_removes_the_shortcut_install_added(self):
        self.install()
        out = self.uninstall()
        self.assertFalse(self.shortcut().exists())
        self.assertIn("[REMOVED] ~/Desktop/OliverCode City.webloc", out)

    def test_status_page_open_writes_the_page_and_opens_it_in_the_browser(self):
        from lib import city
        with mock.patch.object(city, "write", return_value=0) as write, mock.patch.object(city, "page_path", return_value=self.page), \
                mock.patch.object(city.repo_state, "origin", return_value="o/r"), mock.patch("lib.city.webbrowser.open") as opened:
            self.fake_refresh()
            city.command_page(["--open"])
        self.assertEqual(1, write.call_count)
        opened.assert_called_once_with(self.page.as_uri())

    def test_status_page_without_open_does_not_open_a_browser(self):
        from lib import city
        with mock.patch.object(city, "write", return_value=0), mock.patch.object(city.repo_state, "origin", return_value="o/r"), \
                mock.patch("lib.city.webbrowser.open") as opened:
            city.command_page([])
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
