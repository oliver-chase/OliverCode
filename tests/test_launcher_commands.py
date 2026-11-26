"""Tests for the launcher's command surface: `install`, `bootstrap`, and argument
handling.

Argument handling gets tests because an ignored unknown flag is a wrong success:
`sync-hooks --root /somewhere` would sync the default fleet and report that it worked.
"""

import contextlib
import io
import os
import json
import plistlib
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, load_script, quiet, scratch_repo, temp_dir

LAUNCHER = REPO_ROOT / "scripts" / "olivercode"
launcher = load_script("scripts/olivercode", "olivercode_launcher")
from lib import claude_settings, cmd_install  # noqa: E402  (load_script put scripts/ on the path)


class HomeCase(unittest.TestCase):
    """A test case whose home folder is a fresh temporary folder."""

    def setUp(self):
        self.tmp = temp_dir(self)
        self.enterContext(mock.patch.object(Path, "home", staticmethod(lambda: self.tmp)))
        self.enterContext(mock.patch.dict(os.environ, {"HOME": str(self.tmp), "OLIVERCODE_HOME": str(self.tmp / "oc-home")}))
        self.root = self._make_checkout()

    def _make_checkout(self):
        """A throwaway OliverCode checkout with gates and one skill, so no test touches the real clone or its git config."""
        root = scratch_repo(self.tmp / "checkout")
        (root / "skills" / "demo-skill").mkdir(parents=True)
        (root / "skills" / "demo-skill" / "SKILL.md").write_text("---\nname: demo-skill\n---\n")
        (root / "docs").mkdir()
        (root / "CLAUDE.md").write_text("rules\n")
        (root / "docs" / "VOICE.md").write_text("voice\n")
        (root / ".githooks").mkdir()
        (root / ".githooks" / "pre-commit").write_text("#!/bin/sh\n")
        (root / ".githooks" / "pre-commit").chmod(0o755)
        return root


class TestInstall(HomeCase):
    """`install` activates a checkout. Its one hard property: never destroy rules
    the operator already had -- that file is often their whole accumulated ruleset."""

    def test_virgin_home_gets_symlinks(self):
        self.assertEqual(cmd_install.command_install(self.root), 0)
        claude_md = self.tmp / ".claude" / "CLAUDE.md"
        self.assertTrue(claude_md.is_symlink())
        self.assertEqual(claude_md.resolve(), (self.root / "CLAUDE.md").resolve())
        voice = self.tmp / ".claude" / "VOICE.md"
        self.assertEqual(voice.resolve(), (self.root / "docs" / "VOICE.md").resolve())
        linked = [p for p in (self.tmp / ".claude" / "skills").iterdir() if p.is_symlink()]
        self.assertGreater(len(linked), 0, "no skills were linked")

    def test_install_loads_the_gh_replay_job_only_for_the_real_home(self):
        with mock.patch("lib.cmd_ghreplay.schedule", return_value=0) as sched:
            cmd_install.command_install(self.root)  # HOME is a temp folder here
            sched.assert_not_called()
            real = self.tmp  # a home that matches the account's own home folder
            with mock.patch("pwd.getpwuid", return_value=mock.Mock(pw_dir=str(real))), \
                 mock.patch.object(cmd_install.sys, "platform", "darwin"):
                cmd_install._schedule_replay()
            sched.assert_called_once_with(True)

    def test_install_unloads_and_deletes_the_idle_sessions_job_the_command_it_ran_is_gone(self):
        agents = self.tmp / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        plist = agents / "com.olivercode.idle-sessions.plist"
        plist.write_text("<plist/>", encoding="utf-8")
        ran = mock.Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            gone = cmd_install.retire_removed_jobs(self.tmp, run=ran)
        self.assertEqual(["com.olivercode.idle-sessions"], gone)
        self.assertFalse(plist.exists())
        self.assertEqual("bootout", ran.call_args[0][0][1])

    def test_existing_real_claude_md_is_backed_up_not_destroyed(self):
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "CLAUDE.md").write_text("my existing rules\n", encoding="utf-8")

        cmd_install.command_install(self.root)

        backup = claude_dir / "CLAUDE.md.pre-olivercode"
        self.assertTrue(backup.is_file(), "existing rules were not backed up")
        self.assertIn("my existing rules", backup.read_text())
        self.assertTrue((claude_dir / "CLAUDE.md").is_symlink())

    def _skill(self):
        return next(p.name for p in sorted((self.root / "skills").iterdir()) if (p / "SKILL.md").is_file())

    def _all_backups(self):
        return [p for p in (self.tmp / ".claude").rglob("*") if ".pre-olivercode" in p.name]

    def test_relinks_links_an_older_install_left_by_a_moved_checkout_without_a_backup(self):
        claude_dir = self.tmp / ".claude"
        (claude_dir / "skills").mkdir(parents=True)
        old = self.tmp / "old" / "OliverCode"
        (claude_dir / "CLAUDE.md").symlink_to(old / "CLAUDE.md")
        (claude_dir / "skills" / self._skill()).symlink_to(old / "skills" / self._skill())
        cmd_install.command_install(self.root)
        self.assertEqual((claude_dir / "CLAUDE.md").resolve(), (self.root / "CLAUDE.md").resolve())
        self.assertEqual(self._all_backups(), [])

    def test_relinks_a_recorded_link_whose_checkout_moved_without_a_backup(self):
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        old = str(self.tmp / "old" / "OliverCode" / "CLAUDE.md")
        (claude_dir / "CLAUDE.md").symlink_to(old)
        cmd_install._write_record(claude_dir, {"CLAUDE.md": old})
        cmd_install.command_install(self.root)
        self.assertEqual(self._all_backups(), [])

    def test_records_every_link_it_wrote(self):
        cmd_install.command_install(self.root)
        claude_dir = self.tmp / ".claude"
        record = cmd_install._read_record(claude_dir)
        links = [p for p in claude_dir.rglob("*") if p.is_symlink()]
        self.assertEqual(record, {str(p.relative_to(claude_dir)): os.readlink(p) for p in links})

    def test_backs_up_a_lone_dangling_link_of_the_owners(self):
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "CLAUDE.md").symlink_to("/Volumes/Ext/dotfiles/CLAUDE.md")  # a drive not mounted
        cmd_install.command_install(self.root)
        backup = claude_dir / "CLAUDE.md.pre-olivercode"
        self.assertTrue(backup.is_symlink(), "the owner's dangling link was replaced with no backup")
        self.assertEqual(os.readlink(backup), "/Volumes/Ext/dotfiles/CLAUDE.md")

    def test_backs_up_a_dangling_link_the_record_does_not_name(self):
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        cmd_install._write_record(claude_dir, {"CLAUDE.md": "/somewhere/else/CLAUDE.md"})
        (claude_dir / "CLAUDE.md").symlink_to(self.tmp / "old" / "OliverCode" / "CLAUDE.md")
        cmd_install.command_install(self.root)
        self.assertTrue((claude_dir / "CLAUDE.md.pre-olivercode").is_symlink())

    def test_backs_up_a_live_link_into_another_checkout_and_reinstall_adds_none(self):
        fork = self.tmp / "fork"
        (fork / "docs").mkdir(parents=True)
        (fork / "CLAUDE.md").write_text("fork rules")
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "CLAUDE.md").symlink_to(fork / "CLAUDE.md")
        cmd_install.command_install(self.root)
        self.assertEqual((claude_dir / "CLAUDE.md.pre-olivercode").resolve(), (fork / "CLAUDE.md").resolve())
        self.assertIn("[ALREADY] ~/.claude/CLAUDE.md", quiet(cmd_install.command_install, self.root)[1])
        self.assertEqual(len(self._all_backups()), 1)

    def test_installs_the_claude_code_hooks_and_keeps_the_owners_settings(self):
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "settings.json").write_text(json.dumps({"model": "opus"}))
        self.assertEqual(cmd_install.command_install(self.root), 0)
        settings = json.loads((claude_dir / "settings.json").read_text())
        self.assertEqual(settings["model"], "opus")
        self.assertEqual(claude_settings.missing(claude_dir / "settings.json"), [])

    def _install(self, root=None):
        return quiet(cmd_install.command_install, root or self.root)

    def _checkout(self):
        return self.root

    def test_a_first_install_ends_with_the_introduction_and_three_first_steps(self):
        rc, out = self._install()
        self.assertEqual(rc, 0)
        intro = out[out.index("How OliverCode works"):].strip()
        self.assertLessEqual(len(intro.splitlines()), 20)
        for habit in ("Work in one thread per topic", "Never start a builder in a chat"):
            self.assertIn(habit, intro)
        for phrase in ("one thread", "each request becomes a story", "olivercode dispatch N",
                       "olivercode drain REPO", "validates", "olivercode status"):
            self.assertIn(phrase.lower(), intro.lower())
        steps = [line.strip() for line in intro.splitlines() if line.strip()[:2] in ("1.", "2.", "3.")]
        self.assertEqual(len(steps), 3)
        self.assertIn("discover", steps[0])
        self.assertIn("health", steps[1])
        self.assertIn("story", steps[2])

    def test_a_repeat_install_prints_one_line_that_points_to_the_guide(self):
        self._install()
        rc, out = self._install()
        self.assertEqual(rc, 0)
        self.assertNotIn("How OliverCode works", out)
        guide_lines = [line for line in out.splitlines() if "olivercode guide" in line]
        self.assertEqual(len(guide_lines), 1)

    def test_unset_hooks_path_is_set_to_githooks(self):
        root = self._checkout()
        rc, out = self._install(root)
        self.assertEqual(rc, 0)
        self.assertEqual(git(root, "config", "--get", "core.hooksPath").stdout.strip(), ".githooks")
        self.assertIn("core.hooksPath", out)

    def test_hooks_path_elsewhere_is_left_alone_with_a_warning(self):
        root = self._checkout()
        git(root, "config", "core.hooksPath", ".git/hooks")
        rc, out = self._install(root)
        self.assertEqual(git(root, "config", "--get", "core.hooksPath").stdout.strip(), ".git/hooks")
        self.assertIn("[WARN]", out)
        self.assertIn(f"git -C {root} config core.hooksPath .githooks", out)

    def test_a_checkout_path_with_spaces_gets_its_hooks_path_set(self):
        root = scratch_repo(self.tmp / "with space" / "checkout")
        (root / ".githooks").mkdir()
        (root / ".githooks" / "pre-commit").write_text("#!/bin/sh\n")
        (root / ".githooks" / "pre-commit").chmod(0o755)
        (root / "CLAUDE.md").write_text("rules\n")
        (root / "docs").mkdir()
        (root / "docs" / "VOICE.md").write_text("voice\n")
        (root / "skills").mkdir()
        rc, out = self._install(root)
        self.assertEqual(git(root, "config", "--get", "core.hooksPath").stdout.strip(), ".githooks")
        self.assertIn("[SET]", out)

    def test_a_folder_inside_another_repo_never_sets_that_repos_hooks_path(self):
        parent = scratch_repo(self.tmp / "parent")
        root = parent / "oc"
        for d in (".githooks", "skills", "docs"):
            (root / d).mkdir(parents=True)
        (root / ".githooks" / "pre-commit").write_text("#!/bin/sh\n")
        (root / ".githooks" / "pre-commit").chmod(0o755)
        (root / "CLAUDE.md").write_text("rules\n")
        (root / "docs" / "VOICE.md").write_text("voice\n")
        self._install(root)
        self.assertEqual(git(parent, "config", "--get", "core.hooksPath", check=False).stdout.strip(), "")

    def test_a_non_executable_pre_commit_names_chmod(self):
        root = self._checkout()
        git(root, "config", "core.hooksPath", ".githooks")
        (root / ".githooks" / "pre-commit").chmod(0o644)
        rc, out = self._install(root)
        self.assertIn("chmod +x", out)

    def test_hooks_path_already_githooks_changes_nothing(self):
        root = self._checkout()
        git(root, "config", "core.hooksPath", ".githooks")
        rc, out = self._install(root)
        self.assertEqual(git(root, "config", "--get", "core.hooksPath").stdout.strip(), ".githooks")
        self.assertIn("[ALREADY] core.hooksPath", out)
        self.assertNotIn("[SET]", out)

    def test_a_file_where_the_claude_folder_belongs_fails_and_is_left_alone(self):
        (self.tmp / ".claude").write_text("not a folder")
        rc, out = self._install()
        self.assertEqual(rc, 1)
        self.assertIn("is not a directory", out)
        self.assertEqual((self.tmp / ".claude").read_text(), "not a folder")

    def test_a_file_where_the_skills_folder_belongs_fails_and_is_left_alone(self):
        (self.tmp / ".claude").mkdir()
        (self.tmp / ".claude" / "skills").write_text("not a folder")
        rc, out = self._install()
        self.assertEqual(rc, 1)
        self.assertIn("is not a directory", out)
        self.assertEqual((self.tmp / ".claude" / "skills").read_text(), "not a folder")

    def test_a_broken_skill_link_fails_install_and_is_named(self):
        skills = self.tmp / ".claude" / "skills"
        skills.mkdir(parents=True)
        (skills / "dead-skill").symlink_to(self.tmp / "nowhere")
        rc, out = self._install()
        self.assertEqual(rc, 1)
        self.assertIn("broken symlinks", out)
        self.assertIn("dead-skill", out)

    def test_removes_its_own_link_to_a_skill_the_checkout_no_longer_has(self):
        skills = self.tmp / ".claude" / "skills"
        skills.mkdir(parents=True)
        (skills / "retired-skill").symlink_to(self.root / "skills" / "retired-skill")
        (skills / "owners-skill").symlink_to(self.tmp / "nowhere" / "retired-skill")
        rc, out = self._install()
        self.assertIn("retired-skill", out)
        self.assertFalse((skills / "retired-skill").is_symlink())
        self.assertTrue((skills / "owners-skill").is_symlink(), "a link into anywhere else is the owner's")

    def test_leaves_a_broken_settings_file_alone_and_fails(self):
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "settings.json").write_text("{not json")
        self.assertEqual(cmd_install.command_install(self.root), 1)
        self.assertEqual((claude_dir / "settings.json").read_text(), "{not json")


class TestUninstall(HomeCase):
    """`uninstall` removes what install wrote in ~/.claude and nothing of the owner's."""

    def setUp(self):
        super().setUp()
        self.claude = self.tmp / ".claude"

    def _quiet(self, fn):
        return quiet(fn, self.root)[0]

    def _links_into_checkout(self):
        root = self.root.resolve()
        return [p for p in self.claude.rglob("*") if p.is_symlink() and p.resolve().is_relative_to(root)]

    def test_removes_every_link_and_hook_install_wrote(self):
        self.claude.mkdir(parents=True)
        (self.claude / "settings.json").write_text(json.dumps({"model": "opus"}))
        self.assertEqual(self._quiet(cmd_install.command_install), 0)
        self.assertTrue(self._links_into_checkout())
        self.assertEqual(self._quiet(cmd_install.command_uninstall), 0)
        self.assertEqual(self._links_into_checkout(), [])
        self.assertFalse((self.claude / "CLAUDE.md").is_symlink())
        self.assertFalse((self.claude / "VOICE.md").is_symlink())
        self.assertEqual(json.loads((self.claude / "settings.json").read_text()), {"model": "opus"})

    def test_restores_the_rules_install_backed_up(self):
        self.claude.mkdir(parents=True)
        (self.claude / "CLAUDE.md").write_text("my existing rules\n", encoding="utf-8")
        self._quiet(cmd_install.command_install)
        self._quiet(cmd_install.command_uninstall)
        self.assertFalse((self.claude / "CLAUDE.md").is_symlink())
        self.assertEqual((self.claude / "CLAUDE.md").read_text(), "my existing rules\n")
        self.assertFalse((self.claude / "CLAUDE.md.pre-olivercode").exists())

    def test_keeps_links_and_folders_that_are_not_this_checkouts(self):
        elsewhere = self.tmp / "elsewhere"
        (elsewhere / "their-skill").mkdir(parents=True)
        (elsewhere / "rules.md").write_text("theirs")
        (self.claude / "skills" / "vendor-skill").mkdir(parents=True)
        (self.claude / "skills" / "their-skill").symlink_to(elsewhere / "their-skill")
        self._quiet(cmd_install.command_install)
        for name in ("CLAUDE.md", "VOICE.md"):  # the owner re-pointed both after install
            (self.claude / name).unlink()
            (self.claude / name).symlink_to(elsewhere / "rules.md")
        self._quiet(cmd_install.command_uninstall)
        for name in ("CLAUDE.md", "VOICE.md"):
            self.assertEqual((self.claude / name).resolve(), (elsewhere / "rules.md").resolve(), name)
        self.assertEqual((self.claude / "skills" / "their-skill").resolve(), (elsewhere / "their-skill").resolve())
        self.assertTrue((self.claude / "skills" / "vendor-skill").is_dir())

    def _plist(self, label, checkout):
        agents = self.tmp / "Library" / "LaunchAgents"
        agents.mkdir(parents=True, exist_ok=True)
        path = agents / f"{label}.plist"
        path.write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": ["/usr/bin/python3", str(checkout / "scripts" / "olivercode"), "x"]}))
        return path

    def test_removes_every_job_this_checkout_creates_and_boots_each_out(self):
        from lib import cmd_boardsweep, cmd_fleetsync, cmd_ghreplay, cmd_version, maintain
        labels = [m.LABEL for m in (cmd_boardsweep, cmd_fleetsync, cmd_ghreplay, cmd_version, maintain)]
        self.assertEqual(5, len(set(labels)))
        labels.append("com.olivercode.from-a-newer-version")  # not in this code, but it runs this checkout
        plists = [self._plist(label, self.root) for label in labels]
        other = self._plist("com.olivercode.other-checkout", self.tmp / "elsewhere")
        ran = mock.Mock()
        with mock.patch.object(cmd_install.launchd, "supported", return_value=True):
            code, out = quiet(cmd_install.command_uninstall, self.root, ran)
        self.assertEqual(0, code)
        self.assertFalse(any(p.exists() for p in plists))
        self.assertTrue(other.exists())
        booted = sorted(c.args[0][2].split("/")[-1] for c in ran.call_args_list if c.args[0][1] == "bootout")
        self.assertEqual(sorted(labels), booted)
        self.assertEqual(len(labels), out.count("[JOB] removed"))
        self.assertIn(f"{len(labels)} scheduled job(s) removed", out.strip().splitlines()[-1])

    def test_nothing_to_remove_exits_0_without_calling_launchctl(self):
        ran = mock.Mock()
        with mock.patch.object(cmd_install.launchd, "supported", return_value=True):
            code, out = quiet(cmd_install.command_uninstall, self.root, ran)
        self.assertEqual(0, code)
        ran.assert_not_called()
        self.assertIn("0 scheduled job(s) removed", out.strip().splitlines()[-1])

    def test_removes_managed_and_retired_hook_entries_from_any_checkout(self):
        def entry(script, root):
            return {"matcher": "x", "hooks": [{"type": "command", "command": f'python3 "{root}/scripts/hooks/{script}"'}]}
        mine = {"matcher": "Edit", "hooks": [{"type": "command", "command": "~/mine.sh"}]}
        self.claude.mkdir(parents=True)
        hooks = {"PreToolUse": [mine, entry("pretool_guard.py", self.root), entry("denial_watch.py", "/old/OliverCode")],
                 "Stop": [entry("wip_save.py", "/moved/OliverCode")]}
        (self.claude / "settings.json").write_text(json.dumps({"hooks": hooks}))
        self.assertEqual(self._quiet(cmd_install.command_uninstall), 0)
        saved = (self.claude / "settings.json").read_text()
        self.assertNotIn("scripts/hooks", saved)
        self.assertEqual({"hooks": {"PreToolUse": [mine]}}, json.loads(saved))

    def _tree(self):
        return sorted((str(p.relative_to(self.tmp)), p.is_symlink()) for p in self.tmp.rglob("*"))

    def test_is_idempotent(self):
        self._quiet(cmd_install.command_install)
        self.assertEqual(self._quiet(cmd_install.command_uninstall), 0)
        tree = self._tree()
        self.assertEqual(self._quiet(cmd_install.command_uninstall), 0)
        self.assertEqual(self._tree(), tree)

    def test_a_fresh_home_is_left_with_no_settings_file(self):
        self._quiet(cmd_install.command_install)
        self._quiet(cmd_install.command_uninstall)
        self.assertFalse((self.claude / "settings.json").exists(), "an empty {} settings file was left behind")
        self.assertEqual([p for p in self.claude.rglob("*") if p.is_file() or p.is_symlink()], [])

    def test_removes_dangling_links_left_by_a_checkout_that_moved(self):
        old = self.tmp / "old" / "OliverCode"
        skill = next(p.name for p in (self.root / "skills").iterdir() if (p / "SKILL.md").is_file())
        skills = self.claude / "skills"
        skills.mkdir(parents=True)
        (self.claude / "CLAUDE.md").symlink_to(old / "CLAUDE.md")
        (self.claude / "VOICE.md").symlink_to(old / "docs" / "VOICE.md")
        (skills / skill).symlink_to(old / "skills" / skill)
        (skills / "not-shipped").symlink_to(old / "skills" / "not-shipped")  # not a skill this checkout ships
        rc, out = quiet(cmd_install.command_uninstall, self.root)
        self.assertEqual(rc, 0)
        for path in (self.claude / "CLAUDE.md", self.claude / "VOICE.md", skills / skill):
            self.assertFalse(path.is_symlink(), path)
        self.assertTrue((skills / "not-shipped").is_symlink())
        self.assertIn("1 of them dangling", out)

    def test_keeps_a_lone_dangling_link_on_a_machine_never_installed(self):
        (self.claude / "skills").mkdir(parents=True)
        (self.claude / "CLAUDE.md").symlink_to("/Volumes/Ext/dotfiles/CLAUDE.md")
        skill = next(p.name for p in sorted((self.root / "skills").iterdir()) if (p / "SKILL.md").is_file())
        (self.claude / "skills" / skill).symlink_to(f"/Volumes/X/my-skills/skills/{skill}")
        self._quiet(cmd_install.command_uninstall)
        self.assertTrue((self.claude / "CLAUDE.md").is_symlink())
        self.assertTrue((self.claude / "skills" / skill).is_symlink())

    def test_removes_a_recorded_dangling_link_and_keeps_an_unrecorded_one(self):
        (self.claude / "skills").mkdir(parents=True)
        old = str(self.tmp / "old" / "OliverCode" / "CLAUDE.md")
        (self.claude / "CLAUDE.md").symlink_to(old)
        skill = next(p.name for p in sorted((self.root / "skills").iterdir()) if (p / "SKILL.md").is_file())
        (self.claude / "skills" / skill).symlink_to(self.tmp / "old" / "OliverCode" / "skills" / skill)
        cmd_install._write_record(self.claude, {"CLAUDE.md": old})
        self._quiet(cmd_install.command_uninstall)
        self.assertFalse((self.claude / "CLAUDE.md").is_symlink())
        self.assertTrue((self.claude / "skills" / skill).is_symlink(), "a link the record does not name was removed")
        self.assertFalse((self.claude / cmd_install.INSTALL_RECORD).exists())

    def test_restores_another_checkouts_links_it_backed_up(self):
        fork = self.tmp / "fork"
        fork.mkdir()
        (fork / "CLAUDE.md").write_text("fork rules")
        self.claude.mkdir(parents=True)
        (self.claude / "CLAUDE.md").symlink_to(fork / "CLAUDE.md")
        self._quiet(cmd_install.command_install)
        self._quiet(cmd_install.command_uninstall)
        self.assertEqual((self.claude / "CLAUDE.md").resolve(), (fork / "CLAUDE.md").resolve())

    def test_restores_the_newest_backup_and_lists_the_older_one(self):
        self.claude.mkdir(parents=True)
        (self.claude / "CLAUDE.md").write_text("first\n")
        self._quiet(cmd_install.command_install)
        (self.claude / "CLAUDE.md").unlink()
        (self.claude / "CLAUDE.md").write_text("second\n")
        self._quiet(cmd_install.command_install)
        out = quiet(cmd_install.command_uninstall, self.root)[1]
        self.assertEqual((self.claude / "CLAUDE.md").read_text(), "second\n")
        self.assertEqual((self.claude / "CLAUDE.md.pre-olivercode").read_text(), "first\n")
        self.assertIn("CLAUDE.md.pre-olivercode", out)

    def test_names_the_owners_own_skills_copy_correctly(self):
        (self.claude / "skills.pre-olivercode").mkdir(parents=True)
        self._quiet(cmd_install.command_install)
        out = quiet(cmd_install.command_uninstall, self.root)[1]
        self.assertIn("skills.pre-olivercode", out)
        self.assertNotIn("An earlier install made", out)
        self.assertTrue((self.claude / "skills.pre-olivercode").is_dir())

    def test_leaves_a_broken_settings_file_alone_and_fails(self):
        self._quiet(cmd_install.command_install)
        (self.claude / "settings.json").write_text("{not json")
        self.assertEqual(self._quiet(cmd_install.command_uninstall), 1)
        self.assertEqual((self.claude / "settings.json").read_text(), "{not json")
        self.assertEqual(self._links_into_checkout(), [], "the links still come out")

    def test_rejects_an_unknown_flag_without_touching_home(self):
        env = {**os.environ, "HOME": str(self.tmp), "OLIVERCODE_HOME": str(self.tmp / "oc-home")}
        self._quiet(cmd_install.command_install)
        result = subprocess.run([sys.executable, str(LAUNCHER), "uninstall", "--bogus"],
                                capture_output=True, text=True, cwd=str(self.tmp), env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected argument", result.stdout)
        self.assertIn("olivercode uninstall", result.stdout)
        self.assertIn("olivercode guide uninstall", result.stdout)
        self.assertEqual(1, len(result.stdout.strip().splitlines()), result.stdout)
        self.assertTrue((self.claude / "CLAUDE.md").is_symlink())
        # Every command that takes no extra word refuses one before it acts.
        for cmd in ("install", "health", "update", "sync-hooks",
                    "conform . ", "discover --root . "):
            with self.subTest(cmd):
                done = subprocess.run([sys.executable, str(LAUNCHER), *cmd.split(), "--bogus"],
                                      capture_output=True, text=True, cwd=str(self.tmp), env=env)
                self.assertEqual(1, done.returncode, done.stdout + done.stderr)
                self.assertIn("unexpected argument", done.stdout)
                self.assertEqual(1, len(done.stdout.strip().splitlines()), done.stdout)


class TestRootFlag(unittest.TestCase):
    def test_extracts_root_and_leaves_remaining_args(self):
        root, rest = launcher._take_root_flag(["--root", "/tmp", "extra"])
        self.assertEqual(root, Path("/tmp"))
        self.assertEqual(rest, ["extra"])

    def test_absent_root_returns_none(self):
        root, rest = launcher._take_root_flag(["something"])
        self.assertIsNone(root)
        self.assertEqual(rest, ["something"])

    def test_missing_value_exits(self):
        with self.assertRaises(SystemExit):
            launcher._take_root_flag(["--root"])

    def test_nonexistent_directory_exits(self):
        with self.assertRaises(SystemExit):
            launcher._take_root_flag(["--root", "/definitely/not/a/dir"])


class TestUnknownArgsRejected(unittest.TestCase):
    """An ignored flag is a wrong success. These must fail loudly."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(LAUNCHER), *args],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )

    def test_invalid_command_still_fails(self):
        result = self._run("not-a-command")
        self.assertNotEqual(result.returncode, 0)

    def test_help_aliases_all_exit_zero(self):
        for args in ([], ["--help"], ["-h"], ["help"]):
            self.assertEqual(self._run(*args).returncode, 0, f"{args} should exit 0")


class TestBootstrap(unittest.TestCase):
    """`bootstrap` executes the project bootstrap manifest. Its modes are
    the correctness property: strict overwrites, presence must never clobber."""

    def setUp(self):
        self.tmp = scratch_repo(temp_dir(self, "olivercode-bootstrap-"))

    def _run(self, dry=False, oc=REPO_ROOT):
        return quiet(launcher.command_bootstrap, oc, self.tmp, dry)

    def test_dry_run_writes_nothing(self):
        rc, _ = self._run(dry=True)
        self.assertEqual(rc, 0)
        written = [p for p in self.tmp.rglob("*") if p.is_file() and ".git" not in p.parts]
        self.assertEqual(written, [], "dry run must not write")

    def test_stamps_the_manifest(self):
        rc, _ = self._run()
        self.assertEqual(rc, 0)
        self.assertTrue((self.tmp / "QUALITY_BASELINE.md").is_file())
        self.assertTrue((self.tmp / ".githooks" / "pre-commit").is_file())
        self.assertTrue((self.tmp / ".githooks" / "commit-msg").is_file())
        self.assertTrue((self.tmp / "docs" / "repo-structure-contract.md").is_file())
        for hook in ("pre-commit", "commit-msg"):
            self.assertTrue(os.access(self.tmp / ".githooks" / hook, os.X_OK), hook)

    def _fake_checkout(self, manifest: dict) -> Path:
        """An OliverCode root holding only a bootstrap manifest, so one rule is tested alone."""
        root = temp_dir(self, "olivercode-fakeoc-")
        (root / "shared").mkdir()
        (root / "shared" / "project-bootstrap-manifest.json").write_text(json.dumps(manifest))
        return root

    def test_required_directories_are_made_even_when_no_file_lands_in_them(self):
        oc = self._fake_checkout({"requiredDirectories": ["empty/dir", ".github/workflows"]})
        rc, _ = self._run(oc=oc)
        self.assertEqual(rc, 0)
        self.assertTrue((self.tmp / "empty" / "dir").is_dir())
        self.assertTrue((self.tmp / ".github" / "workflows").is_dir())

    def test_a_template_source_missing_from_the_checkout_fails(self):
        oc = self._fake_checkout({"templatedFiles": [{"source": "core/gone.md", "target": "gone.md"}]})
        rc, out = self._run(oc=oc)
        self.assertEqual(rc, 1)
        self.assertIn("core/gone.md", out)

    def test_refuses_a_non_git_directory(self):
        plain = temp_dir(self, "olivercode-nongit-")
        self.assertEqual(quiet(launcher.command_bootstrap, REPO_ROOT, plain, False)[0], 1, "must refuse a directory with no .git")
