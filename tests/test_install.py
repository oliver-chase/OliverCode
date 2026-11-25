"""Install makes the fleet folder a local git repo with one commit, offers a private GitHub copy once, and health repairs a loose folder (#993)."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, quiet, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_initfleet, cmd_install, health_checks, health_env  # noqa: E402

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

    def test_a_loose_folder_fails_health_and_stays_untouched_until_made_a_repo(self):
        dest = temp_dir(self) / "fleet"
        dest.mkdir()
        (dest / "repo-profiles.json").write_text('{"repos": []}')
        self.assertEqual((0, 1, 0), quiet(health_checks._check_fleet_repo, dest)[0])
        self.assertEqual('{"repos": []}', (dest / "repo-profiles.json").read_text())
        self.assertFalse((dest / ".git").exists())
        cmd_initfleet.make_local_repo(dest)
        self.assertEqual((1, 0, 0), quiet(health_checks._check_fleet_repo, dest)[0])
        self.assertEqual(1, self.commits(dest))

    def test_a_local_fleet_repo_takes_the_owner_and_name_in_its_placeholders(self):
        dest = temp_dir(self) / "fleet"
        cmd_initfleet.scaffold_local(dest)
        self.assertTrue(cmd_initfleet.fill_placeholders(dest, "me", "fleet"))
        self.assertIn('"me/fleet"', (dest / "review-config.json").read_text())
        self.assertFalse(cmd_initfleet.fill_placeholders(dest, "me", "fleet"))

    def test_init_fleet_on_the_local_repo_adds_a_remote_and_nests_no_repo(self):
        dest = temp_dir(self) / "fleet"
        quiet(cmd_install.fleet_repo_step, dest, None, None)
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
        return mock.patch.object(health_env, "_gh_auth_status", return_value=subprocess.CompletedProcess(["gh"], code, "", stderr))

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

    RULE = "Interactive work stays interactive"

    def test_each_doc_and_the_guide_state_the_one_rule(self):
        from lib import cmd_guide
        for path in ("CLAUDE.md", "docs/RULES.md", "README.md"):
            self.assertIn(self.RULE, (REPO_ROOT / path).read_text(encoding="utf-8"), path)
        self.assertIn(self.RULE, " ".join(cmd_guide.HOW_WORK_RUNS))

    def test_the_first_steps_end_on_building_a_story_in_install_and_the_guide(self):
        from lib import cmd_guide
        self.assertIn("3. Use Claude Code normally. When you want durable tracking or unattended execution, file a bounded story and delegate it with `olivercode dispatch N` or `olivercode drain REPO`.", cmd_install.INTRODUCTION)
        _, out = quiet(cmd_guide.command_guide, REPO_ROOT)
        self.assertIn("3. Use Claude Code normally.", out)
        self.assertIn("durable tracking or unattended execution", out)




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

    def test_an_existing_design_file_setting_does_not_prompt_again(self):
        from lib import local_config
        own = temp_dir(self) / "mine.md"
        own.write_text("mine\n")
        self.config.write_text(json.dumps({"designFile": str(own)}))
        asked = []
        quiet(cmd_install.design_step, lambda q: asked.append(q) or "")
        self.assertEqual([], asked)
        self.assertEqual(str(own), local_config.load_local()["designFile"])

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




def _commits(dest: Path) -> int:
    done = subprocess.run(["git", "-C", str(dest), "rev-list", "--count", "HEAD"], capture_output=True, text=True)
    return int(done.stdout.strip()) if done.returncode == 0 else 0


class FleetStep(unittest.TestCase):
    """Install connects the one fleet repo beside the checkout, merges other copies into it and names it as fleetRegistry (#1057)."""

    def setUp(self):
        self.root = temp_dir(self)
        self.checkout = self.root / "OliverCode"
        self.checkout.mkdir()
        self.home = self.root / "home"
        self.config = self.root / "olivercode.local.json"
        patch = mock.patch.dict(os.environ, {**IDENTITY, "HOME": str(self.home), "OLIVERCODE_LOCAL_CONFIG": str(self.config)})
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("OLIVERCODE_FLEET_DIR", None)
        self.fleet = self.root / "olivercode-fleet"

    def saved(self) -> dict:
        return json.loads(self.config.read_text()) if self.config.is_file() else {}

    def test_a_first_install_names_the_fleet_olivercode_fleet_beside_the_checkout(self):
        error, _ = quiet(cmd_install.fleet_step, self.checkout)
        self.assertEqual("", error)
        self.assertTrue((self.fleet / "repo-profiles.json").is_file())
        self.assertEqual(1, _commits(self.fleet))
        self.assertEqual(str(self.fleet / "repo-profiles.json"), self.saved()["fleetRegistry"])
        self.assertFalse((self.home / ".olivercode" / "fleet").exists())

    def test_a_clone_beside_the_checkout_is_used_and_no_folder_is_made_under_olivercode(self):
        cmd_initfleet.scaffold_local(self.fleet)
        cmd_initfleet.make_local_repo(self.fleet)
        _, out = quiet(cmd_install.fleet_step, self.checkout)
        self.assertEqual(str(self.fleet / "repo-profiles.json"), self.saved()["fleetRegistry"])
        self.assertIn(str(self.fleet), out)
        self.assertFalse((self.home / ".olivercode" / "fleet").exists())
        self.assertEqual(1, _commits(self.fleet))

    def test_other_copies_merge_into_olivercode_fleet_and_the_other_copy_is_removed(self):
        cmd_initfleet.scaffold_local(self.fleet)
        cmd_initfleet.make_local_repo(self.fleet)
        (self.checkout / "shared-profiles.json").write_text("{}")
        other = self.home / ".olivercode" / "fleet"
        other.mkdir(parents=True)
        (other / "repo-profiles.json").symlink_to(self.checkout / "shared-profiles.json")
        (other / "owner-rules.json").write_text('{"from": "other"}')
        (other / "review-config.json").write_text('{"old": true}')
        (other / "notes.md").write_text("only in the other copy")
        self.config.write_text(json.dumps({"fleetRegistry": str(other / "repo-profiles.json")}))
        owner_rules = (self.fleet / "owner-rules.json").read_text()

        _, out = quiet(cmd_install.fleet_step, self.checkout)

        self.assertEqual("only in the other copy", (self.fleet / "notes.md").read_text())
        self.assertEqual(owner_rules, (self.fleet / "owner-rules.json").read_text())
        self.assertFalse((self.fleet / "repo-profiles.json").is_symlink())
        self.assertFalse(other.exists())
        self.assertEqual(str(self.fleet / "repo-profiles.json"), self.saved()["fleetRegistry"])
        self.assertEqual(2, _commits(self.fleet))
        for line in ("moved notes.md", "kept owner-rules.json", "kept review-config.json", "dropped repo-profiles.json"):
            self.assertIn(line, out)

    def test_nothing_else_found_prints_the_path_once_and_changes_nothing(self):
        cmd_initfleet.scaffold_local(self.fleet)
        cmd_initfleet.make_local_repo(self.fleet)
        self.config.write_text(json.dumps({"fleetRegistry": str(self.fleet / "repo-profiles.json")}))
        before = self.config.read_text()
        _, out = quiet(cmd_install.fleet_step, self.checkout)
        self.assertEqual(before, self.config.read_text())
        self.assertEqual(1, out.count("Fleet repo:"))
        self.assertEqual(1, _commits(self.fleet))

    def test_a_repeat_install_links_a_stale_default_registry_and_does_not_collide(self):
        cmd_initfleet.scaffold_local(self.fleet)
        cmd_initfleet.make_local_repo(self.fleet)
        self.home.mkdir(parents=True, exist_ok=True)
        stale = self.home / "stale.json"
        stale.write_text("{}")
        default = self.home / ".olivercode" / "fleet" / "repo-profiles.json"
        default.parent.mkdir(parents=True)
        default.symlink_to(stale)
        self.config.write_text(json.dumps({"fleetRegistry": str(self.fleet / "repo-profiles.json")}))
        for _ in range(2):
            error, _ = quiet(cmd_install.fleet_step, self.checkout)
            self.assertEqual("", error)
            self.assertEqual((self.fleet / "repo-profiles.json").resolve(), default.resolve())

    def test_a_github_copy_is_cloned_on_yes_and_no_repo_is_created(self):
        with mock.patch("lib.cmd_initfleet.github_login", return_value=("me", "")), \
                mock.patch("lib.cmd_initfleet.github_repo_kind", return_value=("fleet", "")), \
                mock.patch("lib.cmd_initfleet.connect_fleet", return_value=0) as connect:
            error, _ = quiet(cmd_install.fleet_step, self.checkout, lambda question: "y")
        self.assertEqual("", error)
        connect.assert_called_once_with(self.fleet, "me", "olivercode-fleet")
        self.assertFalse(self.fleet.exists())
        self.assertEqual(str(self.fleet / "repo-profiles.json"), self.saved()["fleetRegistry"])


class CityStep(unittest.TestCase):
    """Install sets up City on the desktop and the phone, and the guide repeats it (#999)."""

    def setUp(self):
        self.config = temp_dir(self) / "olivercode.local.json"
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(self.config), "CLAUDE_CODE_ENTRYPOINT": "claude-desktop"})
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_first_desktop_install_says_the_skill_publishes_city_and_names_each_phone_step_once(self):
        from lib import cmd_guide
        _, out = quiet(cmd_install.city_step)
        self.assertIn("publishes the status page as the OliverCode City artifact", out)
        for step in cmd_guide.PHONE_STEPS:
            self.assertEqual(1, out.count(step))

    def test_a_second_install_reuses_the_saved_url_and_stops_once_the_phone_is_confirmed(self):
        self.config.write_text(json.dumps({"cityArtifact": "https://claude.ai/artifact/abc", "cityOnPhone": True}))
        url, out = quiet(cmd_install.city_step)
        self.assertEqual("https://claude.ai/artifact/abc", url)
        self.assertIn("no second artifact", out)
        self.assertNotIn("Phone:", out)

    def test_outside_the_desktop_app_it_prints_the_page_path_and_the_publish_command_and_skips_the_rest(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_ENTRYPOINT": "cli"}):
            _, out = quiet(cmd_install.city_step)
        self.assertIn("status.html", out)
        self.assertIn("`olivercode status publish`", out)
        self.assertIn("skipped", out)
        self.assertNotIn("Install the Claude app", out)

    def test_the_guide_names_the_url_the_phone_steps_and_the_republish_command(self):
        from lib import cmd_guide
        self.config.write_text(json.dumps({"cityArtifact": "https://claude.ai/artifact/abc"}))
        _, out = quiet(cmd_guide.command_guide, REPO_ROOT)
        self.assertIn("https://claude.ai/artifact/abc", out)
        self.assertIn("Open the pinned OliverCode City artifact.", out)
        self.assertIn("olivercode status publish", out)


class CheckoutLink(unittest.TestCase):
    def test_install_links_the_checkout_root_at_the_documented_path(self):
        self.assertEqual(Path("."), cmd_install.RULE_LINKS["olivercode"])


if __name__ == "__main__":
    unittest.main()
