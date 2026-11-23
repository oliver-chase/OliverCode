"""Install writes the handoff autoMode rules for the owner's terminal run, prints them for an agent run (#708)."""

import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, load_script, temp_dir

load_script("scripts/olivercode", "olivercode_launcher")
from lib import claude_settings as cs  # noqa: E402
from lib import cmd_install  # noqa: E402


class TestAutoModeSettings(unittest.TestCase):
    def setUp(self):
        self.dir = temp_dir(self, "oc-automode-")
        self.path = self.dir / "settings.json"

    def test_owner_run_writes_rules_beside_existing_keys_and_backs_up(self):
        before = {"theme": "dark", "autoMode": {"allow": ["$defaults", "mine"]}}
        self.path.write_text(json.dumps(before))
        result, backup = cs.install_automode(self.path)
        self.assertEqual(result, "added")
        self.assertEqual(json.loads(backup.read_text()), before)
        now = json.loads(self.path.read_text())
        self.assertEqual(now["theme"], "dark")
        self.assertEqual(now["autoMode"]["allow"][:2], ["$defaults", "mine"])
        for key, rules in cs.AUTOMODE.items():
            for rule in rules:
                self.assertIn(rule, now["autoMode"][key])
        self.assertTrue(any("list_sessions" in r for r in now["autoMode"]["allow"]))

    def test_second_run_changes_nothing(self):
        cs.install_automode(self.path)
        text = self.path.read_text()
        self.assertEqual(cs.install_automode(self.path), ("already", None))
        self.assertEqual(self.path.read_text(), text)
        self.assertEqual(len(list(self.dir.glob("settings.json.pre-olivercode*"))), 0)

    def test_remove_restores_the_owners_autoMode(self):
        before = {"autoMode": {"allow": ["$defaults", "mine"]}, "model": "x"}
        self.path.write_text(json.dumps(before))
        cs.install(self.path)
        cs.install_automode(self.path)
        cs.remove(self.path)
        after = json.loads(self.path.read_text())
        self.assertEqual(after, before)

    def test_remove_drops_autoMode_the_installer_created(self):
        self.path.write_text(json.dumps({"model": "x"}))
        cs.install_automode(self.path)
        cs.remove(self.path)
        self.assertEqual(json.loads(self.path.read_text()), {"model": "x"})

    def test_bad_shape_is_refused_untouched(self):
        self.path.write_text(json.dumps({"autoMode": "nope"}))
        with self.assertRaises(ValueError):
            cs.install_automode(self.path)
        self.assertEqual(json.loads(self.path.read_text()), {"autoMode": "nope"})


class TestAutoModeNamesTheCheckout(unittest.TestCase):
    def test_the_rules_name_the_checkout_and_do_not_say_the_owner_runs_olivercode(self):
        rules = cs.automode_rules(Path("/work/OC"))
        text = " ".join(r for group in rules.values() for r in group)
        self.assertIn("/work/OC", text)
        self.assertNotIn("~/Developer/Repos/OliverCode", text)
        self.assertNotIn("The owner runs OliverCode", text)


class TestInstallKeepsTheUsersOwnRulesFiles(unittest.TestCase):
    def install(self, claude, env=None):
        out = io.StringIO()
        with mock.patch.object(cmd_install, "_claude_dir", return_value=claude), mock.patch.object(cmd_install, "owner_terminal", return_value=False), \
                mock.patch.object(cmd_install, "_schedule_replay"), \
                mock.patch.object(cmd_install, "_queue_shim"), mock.patch.dict("os.environ", env or {}), contextlib.redirect_stdout(out):
            cmd_install.command_install(REPO_ROOT)
        return out.getvalue()

    def test_an_existing_voice_and_design_file_are_not_replaced(self):
        claude = temp_dir(self, "oc-keep-") / ".claude"
        claude.mkdir()
        (claude / "VOICE.md").write_text("my voice")
        (claude / "DESIGN.md").write_text("my design")
        out = self.install(claude)
        self.assertEqual((claude / "VOICE.md").read_text(), "my voice")
        self.assertEqual((claude / "DESIGN.md").read_text(), "my design")
        self.assertFalse((claude / "VOICE.md").is_symlink())
        self.assertEqual(list(claude.glob("VOICE.md.pre-olivercode*")), [])
        self.assertIn("[KEPT] ~/.claude/VOICE.md", out)

    def test_a_designFile_setting_names_the_file_install_links(self):
        claude = temp_dir(self, "oc-design-") / ".claude"
        mine = claude.parent / "mine-design.md"
        mine.write_text("my design")
        self.install(claude, {"OLIVERCODE_DESIGN_FILE": str(mine)})
        self.assertEqual((claude / "DESIGN.md").resolve(), mine.resolve())


class TestInstallCommand(unittest.TestCase):
    def run_install(self, owner):
        home = temp_dir(self, "oc-automode-home-")
        claude = home / ".claude"
        out = io.StringIO()
        with mock.patch.object(cmd_install, "_claude_dir", return_value=claude), \
                mock.patch.object(cmd_install, "owner_terminal", return_value=owner), \
                mock.patch.object(cmd_install, "_schedule_replay"), \
                mock.patch.object(cmd_install, "_queue_shim"), \
                contextlib.redirect_stdout(out):
            cmd_install.command_install(REPO_ROOT)
        return claude / "settings.json", out.getvalue()

    def test_owner_terminal_writes_rules(self):
        path, out = self.run_install(True)
        self.assertIn("autoMode", json.loads(path.read_text()))
        self.assertIn("autoMode rules", out)

    def test_agent_run_prints_block_and_writes_none(self):
        path, out = self.run_install(False)
        self.assertNotIn("autoMode", json.loads(path.read_text()))
        self.assertIn('"autoMode"', out)
        self.assertIn("mcp__ccd_session_mgmt__list_sessions", out)

    def test_owner_terminal_detection_refuses_an_agent_session(self):
        with mock.patch("sys.stdin.isatty", return_value=True), mock.patch("sys.stdout.isatty", return_value=True), \
                mock.patch.dict("os.environ", {"CLAUDECODE": "1"}):
            self.assertFalse(cmd_install.owner_terminal())


if __name__ == "__main__":
    unittest.main()
