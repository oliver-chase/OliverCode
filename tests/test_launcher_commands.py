"""Tests for the launcher's command surface: `install`, `bootstrap`, and argument
handling.

Argument handling gets tests because an ignored unknown flag is a wrong success:
`sync-hooks --root /somewhere` would sync the default fleet and report that it worked.
"""

import contextlib
import importlib.util
import os
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "scripts" / "olivercode"


def _load():
    loader = SourceFileLoader("olivercode_launcher", str(LAUNCHER))
    spec = importlib.util.spec_from_loader("olivercode_launcher", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


launcher = _load()
from lib import local_config  # noqa: E402  (importable once the launcher put scripts/ on the path)


class NoLocalConfig(unittest.TestCase):
    """Points local_config at a file that does not exist, so this machine's gitignored
    olivercode.local.json (a `repoPaths` entry named alpha, say) cannot change the result."""

    def setUp(self):
        empty = tempfile.TemporaryDirectory()  # a private folder, so no other process can create the file
        self.addCleanup(empty.cleanup)
        for patcher in (mock.patch.object(local_config, "LOCAL_FILE", Path(empty.name) / "olivercode.local.json"),
                        mock.patch.dict(os.environ, {k: v for k, v in os.environ.items()
                                                     if k not in ("OLIVERCODE_VAULT_ROOT", "OLIVERCODE_SKILLS_ROOT")}, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)


class TestInstall(unittest.TestCase):
    """`install` activates a checkout. Its one hard property: never destroy rules
    the operator already had -- that file is often their whole accumulated ruleset."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-install-"))
        self._home = Path.home
        Path.home = staticmethod(lambda: self.tmp)  # type: ignore[assignment]

    def tearDown(self):
        Path.home = self._home  # type: ignore[assignment]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_virgin_home_gets_symlinks(self):
        self.assertEqual(launcher.command_install(REPO_ROOT), 0)
        claude_md = self.tmp / ".claude" / "CLAUDE.md"
        self.assertTrue(claude_md.is_symlink())
        self.assertEqual(claude_md.resolve(), (REPO_ROOT / "CLAUDE.md").resolve())
        voice = self.tmp / ".claude" / "VOICE.md"
        self.assertEqual(voice.resolve(), (REPO_ROOT / "docs" / "VOICE.md").resolve())
        linked = [p for p in (self.tmp / ".claude" / "skills").iterdir() if p.is_symlink()]
        self.assertGreater(len(linked), 0, "no skills were linked")

    def test_existing_real_claude_md_is_backed_up_not_destroyed(self):
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "CLAUDE.md").write_text("my existing rules\n", encoding="utf-8")

        launcher.command_install(REPO_ROOT)

        backup = claude_dir / "CLAUDE.md.pre-olivercode"
        self.assertTrue(backup.is_file(), "existing rules were not backed up")
        self.assertIn("my existing rules", backup.read_text())
        self.assertTrue((claude_dir / "CLAUDE.md").is_symlink())

    def test_is_idempotent(self):
        self.assertEqual(launcher.command_install(REPO_ROOT), 0)
        self.assertEqual(launcher.command_install(REPO_ROOT), 0)
        self.assertTrue((self.tmp / ".claude" / "CLAUDE.md").is_symlink())

    def test_replaces_a_symlink_pointing_elsewhere(self):
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        decoy = self.tmp / "decoy.md"
        decoy.write_text("other", encoding="utf-8")
        (claude_dir / "CLAUDE.md").symlink_to(decoy)

        launcher.command_install(REPO_ROOT)

        self.assertEqual(
            (claude_dir / "CLAUDE.md").resolve(), (REPO_ROOT / "CLAUDE.md").resolve()
        )
        backup = claude_dir / "CLAUDE.md.pre-olivercode"
        self.assertTrue(backup.is_symlink(), "the owner's link was deleted, not backed up")
        self.assertEqual(backup.resolve(), decoy.resolve())

    def _skill(self):
        return next(p.name for p in sorted((REPO_ROOT / "skills").iterdir()) if (p / "SKILL.md").is_file())

    def _all_backups(self):
        return [p for p in (self.tmp / ".claude").rglob("*") if ".pre-olivercode" in p.name]

    def test_relinks_links_an_older_install_left_by_a_moved_checkout_without_a_backup(self):
        claude_dir = self.tmp / ".claude"
        (claude_dir / "skills").mkdir(parents=True)
        old = self.tmp / "old" / "OliverCode"
        (claude_dir / "CLAUDE.md").symlink_to(old / "CLAUDE.md")
        (claude_dir / "skills" / self._skill()).symlink_to(old / "skills" / self._skill())
        launcher.command_install(REPO_ROOT)
        self.assertEqual((claude_dir / "CLAUDE.md").resolve(), (REPO_ROOT / "CLAUDE.md").resolve())
        self.assertEqual(self._all_backups(), [])

    def test_relinks_a_recorded_link_whose_checkout_moved_without_a_backup(self):
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        old = str(self.tmp / "old" / "OliverCode" / "CLAUDE.md")
        (claude_dir / "CLAUDE.md").symlink_to(old)
        launcher._write_record(claude_dir, {"CLAUDE.md": old})
        launcher.command_install(REPO_ROOT)
        self.assertEqual(self._all_backups(), [])

    def test_records_every_link_it_wrote(self):
        launcher.command_install(REPO_ROOT)
        claude_dir = self.tmp / ".claude"
        record = launcher._read_record(claude_dir)
        links = [p for p in claude_dir.rglob("*") if p.is_symlink()]
        self.assertEqual(record, {str(p.relative_to(claude_dir)): os.readlink(p) for p in links})

    def test_backs_up_a_lone_dangling_link_of_the_owners(self):
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "CLAUDE.md").symlink_to("/Volumes/Ext/dotfiles/CLAUDE.md")  # a drive not mounted
        launcher.command_install(REPO_ROOT)
        backup = claude_dir / "CLAUDE.md.pre-olivercode"
        self.assertTrue(backup.is_symlink(), "the owner's dangling link was replaced with no backup")
        self.assertEqual(os.readlink(backup), "/Volumes/Ext/dotfiles/CLAUDE.md")

    def test_backs_up_a_dangling_link_the_record_does_not_name(self):
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        launcher._write_record(claude_dir, {"CLAUDE.md": "/somewhere/else/CLAUDE.md"})
        (claude_dir / "CLAUDE.md").symlink_to(self.tmp / "old" / "OliverCode" / "CLAUDE.md")
        launcher.command_install(REPO_ROOT)
        self.assertTrue((claude_dir / "CLAUDE.md.pre-olivercode").is_symlink())

    def test_backs_up_a_live_link_into_another_checkout_and_reinstall_adds_none(self):
        fork = self.tmp / "fork"
        (fork / "docs").mkdir(parents=True)
        (fork / "CLAUDE.md").write_text("fork rules")
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "CLAUDE.md").symlink_to(fork / "CLAUDE.md")
        launcher.command_install(REPO_ROOT)
        self.assertEqual((claude_dir / "CLAUDE.md.pre-olivercode").resolve(), (fork / "CLAUDE.md").resolve())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            launcher.command_install(REPO_ROOT)
        self.assertIn("[ALREADY] ~/.claude/CLAUDE.md", out.getvalue())
        self.assertEqual(len(self._all_backups()), 1)

    def test_installs_the_claude_code_hooks_and_keeps_the_owners_settings(self):
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "settings.json").write_text(json.dumps({"model": "opus"}))
        self.assertEqual(launcher.command_install(REPO_ROOT), 0)
        settings = json.loads((claude_dir / "settings.json").read_text())
        self.assertEqual(settings["model"], "opus")
        self.assertEqual(launcher._claude_settings.missing(claude_dir / "settings.json"), [])

    def _install(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = launcher.command_install(REPO_ROOT)
        return rc, out.getvalue()

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
        (skills / "retired-skill").symlink_to(REPO_ROOT / "skills" / "retired-skill")
        (skills / "owners-skill").symlink_to(self.tmp / "nowhere" / "retired-skill")
        rc, out = self._install()
        self.assertIn("retired-skill", out)
        self.assertFalse((skills / "retired-skill").is_symlink())
        self.assertTrue((skills / "owners-skill").is_symlink(), "a link into anywhere else is the owner's")

    def test_leaves_a_broken_settings_file_alone_and_fails(self):
        claude_dir = self.tmp / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "settings.json").write_text("{not json")
        self.assertEqual(launcher.command_install(REPO_ROOT), 1)
        self.assertEqual((claude_dir / "settings.json").read_text(), "{not json")


class TestUninstall(unittest.TestCase):
    """`uninstall` removes what install wrote in ~/.claude and nothing of the owner's."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-uninstall-"))
        self._home = Path.home
        Path.home = staticmethod(lambda: self.tmp)  # type: ignore[assignment]
        self.claude = self.tmp / ".claude"

    def tearDown(self):
        Path.home = self._home  # type: ignore[assignment]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _quiet(self, fn):
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(REPO_ROOT)

    def _links_into_checkout(self):
        root = REPO_ROOT.resolve()
        return [p for p in self.claude.rglob("*") if p.is_symlink() and p.resolve().is_relative_to(root)]

    def test_removes_every_link_and_hook_install_wrote(self):
        self.claude.mkdir(parents=True)
        (self.claude / "settings.json").write_text(json.dumps({"model": "opus"}))
        self.assertEqual(self._quiet(launcher.command_install), 0)
        self.assertTrue(self._links_into_checkout())
        self.assertEqual(self._quiet(launcher.command_uninstall), 0)
        self.assertEqual(self._links_into_checkout(), [])
        self.assertFalse((self.claude / "CLAUDE.md").is_symlink())
        self.assertFalse((self.claude / "VOICE.md").is_symlink())
        self.assertEqual(json.loads((self.claude / "settings.json").read_text()), {"model": "opus"})

    def test_restores_the_rules_install_backed_up(self):
        self.claude.mkdir(parents=True)
        (self.claude / "CLAUDE.md").write_text("my existing rules\n", encoding="utf-8")
        self._quiet(launcher.command_install)
        self._quiet(launcher.command_uninstall)
        self.assertFalse((self.claude / "CLAUDE.md").is_symlink())
        self.assertEqual((self.claude / "CLAUDE.md").read_text(), "my existing rules\n")
        self.assertFalse((self.claude / "CLAUDE.md.pre-olivercode").exists())

    def test_keeps_links_and_folders_that_are_not_this_checkouts(self):
        elsewhere = self.tmp / "elsewhere"
        (elsewhere / "their-skill").mkdir(parents=True)
        (elsewhere / "rules.md").write_text("theirs")
        (self.claude / "skills" / "vendor-skill").mkdir(parents=True)
        (self.claude / "skills" / "their-skill").symlink_to(elsewhere / "their-skill")
        self._quiet(launcher.command_install)
        for name in ("CLAUDE.md", "VOICE.md"):  # the owner re-pointed both after install
            (self.claude / name).unlink()
            (self.claude / name).symlink_to(elsewhere / "rules.md")
        self._quiet(launcher.command_uninstall)
        for name in ("CLAUDE.md", "VOICE.md"):
            self.assertEqual((self.claude / name).resolve(), (elsewhere / "rules.md").resolve(), name)
        self.assertEqual((self.claude / "skills" / "their-skill").resolve(), (elsewhere / "their-skill").resolve())
        self.assertTrue((self.claude / "skills" / "vendor-skill").is_dir())

    def _tree(self):
        return sorted((str(p.relative_to(self.tmp)), p.is_symlink()) for p in self.tmp.rglob("*"))

    def test_is_idempotent(self):
        self._quiet(launcher.command_install)
        self.assertEqual(self._quiet(launcher.command_uninstall), 0)
        tree = self._tree()
        self.assertEqual(self._quiet(launcher.command_uninstall), 0)
        self.assertEqual(self._tree(), tree)

    def test_a_fresh_home_is_left_with_no_settings_file(self):
        self._quiet(launcher.command_install)
        self._quiet(launcher.command_uninstall)
        self.assertFalse((self.claude / "settings.json").exists(), "an empty {} settings file was left behind")
        self.assertEqual([p for p in self.claude.rglob("*") if p.is_file() or p.is_symlink()], [])

    def test_removes_dangling_links_left_by_a_checkout_that_moved(self):
        old = self.tmp / "old" / "OliverCode"
        skill = next(p.name for p in (REPO_ROOT / "skills").iterdir() if (p / "SKILL.md").is_file())
        skills = self.claude / "skills"
        skills.mkdir(parents=True)
        (self.claude / "CLAUDE.md").symlink_to(old / "CLAUDE.md")
        (self.claude / "VOICE.md").symlink_to(old / "docs" / "VOICE.md")
        (skills / skill).symlink_to(old / "skills" / skill)
        (skills / "not-shipped").symlink_to(old / "skills" / "not-shipped")  # not a skill this checkout ships
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(launcher.command_uninstall(REPO_ROOT), 0)
        for path in (self.claude / "CLAUDE.md", self.claude / "VOICE.md", skills / skill):
            self.assertFalse(path.is_symlink(), path)
        self.assertTrue((skills / "not-shipped").is_symlink())
        self.assertIn("1 of them dangling", out.getvalue())

    def test_keeps_a_lone_dangling_link_on_a_machine_never_installed(self):
        (self.claude / "skills").mkdir(parents=True)
        (self.claude / "CLAUDE.md").symlink_to("/Volumes/Ext/dotfiles/CLAUDE.md")
        skill = next(p.name for p in sorted((REPO_ROOT / "skills").iterdir()) if (p / "SKILL.md").is_file())
        (self.claude / "skills" / skill).symlink_to(f"/Volumes/X/my-skills/skills/{skill}")
        self._quiet(launcher.command_uninstall)
        self.assertTrue((self.claude / "CLAUDE.md").is_symlink())
        self.assertTrue((self.claude / "skills" / skill).is_symlink())

    def test_removes_a_recorded_dangling_link_and_keeps_an_unrecorded_one(self):
        (self.claude / "skills").mkdir(parents=True)
        old = str(self.tmp / "old" / "OliverCode" / "CLAUDE.md")
        (self.claude / "CLAUDE.md").symlink_to(old)
        skill = next(p.name for p in sorted((REPO_ROOT / "skills").iterdir()) if (p / "SKILL.md").is_file())
        (self.claude / "skills" / skill).symlink_to(self.tmp / "old" / "OliverCode" / "skills" / skill)
        launcher._write_record(self.claude, {"CLAUDE.md": old})
        self._quiet(launcher.command_uninstall)
        self.assertFalse((self.claude / "CLAUDE.md").is_symlink())
        self.assertTrue((self.claude / "skills" / skill).is_symlink(), "a link the record does not name was removed")
        self.assertFalse((self.claude / launcher.INSTALL_RECORD).exists())

    def test_restores_another_checkouts_links_it_backed_up(self):
        fork = self.tmp / "fork"
        fork.mkdir()
        (fork / "CLAUDE.md").write_text("fork rules")
        self.claude.mkdir(parents=True)
        (self.claude / "CLAUDE.md").symlink_to(fork / "CLAUDE.md")
        self._quiet(launcher.command_install)
        self._quiet(launcher.command_uninstall)
        self.assertEqual((self.claude / "CLAUDE.md").resolve(), (fork / "CLAUDE.md").resolve())

    def test_restores_the_newest_backup_and_lists_the_older_one(self):
        self.claude.mkdir(parents=True)
        (self.claude / "CLAUDE.md").write_text("first\n")
        self._quiet(launcher.command_install)
        (self.claude / "CLAUDE.md").unlink()
        (self.claude / "CLAUDE.md").write_text("second\n")
        self._quiet(launcher.command_install)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            launcher.command_uninstall(REPO_ROOT)
        self.assertEqual((self.claude / "CLAUDE.md").read_text(), "second\n")
        self.assertEqual((self.claude / "CLAUDE.md.pre-olivercode").read_text(), "first\n")
        self.assertIn("CLAUDE.md.pre-olivercode", out.getvalue())

    def test_restores_an_owners_link_install_backed_up(self):
        self.claude.mkdir(parents=True)
        mine = self.tmp / "mine.md"
        mine.write_text("mine")
        (self.claude / "CLAUDE.md").symlink_to(mine)
        self._quiet(launcher.command_install)
        self._quiet(launcher.command_uninstall)
        self.assertEqual((self.claude / "CLAUDE.md").resolve(), mine.resolve())

    def test_names_the_owners_own_skills_copy_correctly(self):
        (self.claude / "skills.pre-olivercode").mkdir(parents=True)
        self._quiet(launcher.command_install)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            launcher.command_uninstall(REPO_ROOT)
        self.assertIn("skills.pre-olivercode is your own copy", out.getvalue())
        self.assertNotIn("An earlier install made", out.getvalue())
        self.assertTrue((self.claude / "skills.pre-olivercode").is_dir())

    def test_leaves_a_broken_settings_file_alone_and_fails(self):
        self._quiet(launcher.command_install)
        (self.claude / "settings.json").write_text("{not json")
        self.assertEqual(self._quiet(launcher.command_uninstall), 1)
        self.assertEqual((self.claude / "settings.json").read_text(), "{not json")
        self.assertEqual(self._links_into_checkout(), [], "the links still come out")

    def test_rejects_an_unknown_flag_without_touching_home(self):
        env = {**os.environ, "HOME": str(self.tmp)}
        self._quiet(launcher.command_install)
        result = subprocess.run([sys.executable, str(LAUNCHER), "uninstall", "--bogus"],
                                capture_output=True, text=True, cwd=str(self.tmp), env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected argument", result.stdout)
        self.assertTrue((self.claude / "CLAUDE.md").is_symlink())


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

    def test_sync_hooks_rejects_unknown_flag(self):
        result = self._run("sync-hooks", "--bogus")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected argument", result.stdout)

    def test_health_rejects_unknown_flag(self):
        result = self._run("health", "--bogus")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected argument", result.stdout)

    def test_invalid_command_still_fails(self):
        result = self._run("not-a-command")
        self.assertNotEqual(result.returncode, 0)

    def test_help_aliases_all_exit_zero(self):
        for args in ([], ["--help"], ["-h"], ["help"]):
            self.assertEqual(self._run(*args).returncode, 0, f"{args} should exit 0")




class TestRepoPathResolution(NoLocalConfig):
    """Adopting into an existing setup usually means repos are NOT siblings. Before
    the `path` field they could not be registered at all -- the name WAS the path."""

    def test_defaults_to_sibling_convention(self):
        got = launcher._resolve_repo_path("alpha", {}, Path("/fleet"))
        self.assertEqual(got, Path("/fleet/alpha"))

    def test_absolute_path_wins(self):
        got = launcher._resolve_repo_path("alpha", {"path": "/elsewhere/deep/alpha"}, Path("/fleet"))
        self.assertEqual(got, Path("/elsewhere/deep/alpha"))

    def test_relative_path_resolves_against_fleet_root(self):
        got = launcher._resolve_repo_path("alpha", {"path": "sub/alpha"}, Path("/fleet"))
        self.assertEqual(got, Path("/fleet/sub/alpha"))

    def test_tilde_is_expanded(self):
        got = launcher._resolve_repo_path("alpha", {"path": "~/work/alpha"}, Path("/fleet"))
        self.assertEqual(got, Path.home() / "work" / "alpha")

class TestBootstrap(unittest.TestCase):
    """`bootstrap` executes the manifest that nothing previously read. Its modes are
    the correctness property: strict overwrites, presence must never clobber."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-bootstrap-"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, dry=False):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = launcher.command_bootstrap(REPO_ROOT, self.tmp, dry)
        return rc, out.getvalue()

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
        self.assertTrue((self.tmp / "docs" / "repo-structure-contract.md").is_file())

    def test_presence_files_are_never_clobbered(self):
        self._run()
        claude = self.tmp / "CLAUDE.md"          # presence mode in the manifest
        claude.write_text("MY REPO RULES\n", encoding="utf-8")
        self._run()
        self.assertIn("MY REPO RULES", claude.read_text())

    def test_hooks_are_executable(self):
        self._run()
        self.assertTrue(os.access(self.tmp / ".githooks" / "pre-commit", os.X_OK))

    def _fake_checkout(self, manifest: dict) -> Path:
        """An OliverCode root holding only a bootstrap manifest, so one rule is tested alone."""
        root = Path(tempfile.mkdtemp(prefix="olivercode-fakeoc-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / "shared").mkdir()
        (root / "shared" / "project-bootstrap-manifest.json").write_text(json.dumps(manifest))
        return root

    def test_required_directories_are_made_even_when_no_file_lands_in_them(self):
        oc = self._fake_checkout({"requiredDirectories": ["empty/dir", ".github/workflows"]})
        with contextlib.redirect_stdout(io.StringIO()):
            rc = launcher.command_bootstrap(oc, self.tmp, False)
        self.assertEqual(rc, 0)
        self.assertTrue((self.tmp / "empty" / "dir").is_dir())
        self.assertTrue((self.tmp / ".github" / "workflows").is_dir())

    def test_a_template_source_missing_from_the_checkout_fails(self):
        oc = self._fake_checkout({"templatedFiles": [{"source": "core/gone.md", "target": "gone.md"}]})
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = launcher.command_bootstrap(oc, self.tmp, False)
        self.assertEqual(rc, 1)
        self.assertIn("core/gone.md", out.getvalue())

    def test_refuses_a_non_git_directory(self):
        plain = Path(tempfile.mkdtemp(prefix="olivercode-nongit-"))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = launcher.command_bootstrap(REPO_ROOT, plain, False)
            self.assertEqual(rc, 1, "must refuse a directory with no .git")
        finally:
            shutil.rmtree(plain, ignore_errors=True)

class TestFleetIteration(NoLocalConfig):
    """health and sync-hooks each had their own copy of this filter and had drifted:
    one compared the self-skip case-sensitively, the other did not."""

    def test_framework_repo_is_excluded_regardless_of_casing(self):
        profiles = {"OliverCode": {}, "olivercode": {}, "OLIVERCODE": {}, "product-repo": {}}
        names = [n for n, _, _ in launcher._iter_fleet(profiles, Path("/fleet"))]
        self.assertEqual(names, ["product-repo"])

    def test_yields_the_resolved_path(self):
        profiles = {"alpha": {"path": "/elsewhere/alpha"}, "beta": {}}
        got = {n: p for n, _, p in launcher._iter_fleet(profiles, Path("/fleet"))}
        self.assertEqual(got["alpha"], Path("/elsewhere/alpha"))
        self.assertEqual(got["beta"], Path("/fleet/beta"))

    def test_yields_the_profile_for_variant_lookups(self):
        profiles = {"alpha": {"hookVariant": "custom"}}
        _, profile, _ = next(iter(launcher._iter_fleet(profiles, Path("/fleet"))))
        self.assertEqual(profile.get("hookVariant"), "custom")


class TestWaiverExpiryDateHandling(unittest.TestCase):
    """One waiver written without a timezone must not crash the whole health run.

    min() over mixed offset-naive and offset-aware datetimes raises TypeError;
    reproduced live before the fix normalized both sides identically."""

    def test_mixed_naive_and_aware_expiry_dates(self):
        tmp = Path(tempfile.mkdtemp(prefix="olivercode-waiver-"))
        try:
            (tmp / "shared").mkdir()
            (tmp / "shared" / "repo-profiles.json").write_text(json.dumps({
                "unmanagedRepoWaivers": [
                    {"name": "a", "reason": "r", "expiresAt": "2099-06-01T00:00:00+00:00"},
                    {"name": "b", "reason": "r", "expiresAt": "2099-07-01T00:00:00"},
                ]}))
            with contextlib.redirect_stdout(io.StringIO()):
                passed, failed, skipped = launcher._check_waiver_expiry(tmp)
            self.assertEqual((passed, failed), (1, 0))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_expired_waiver_fails(self):
        tmp = Path(tempfile.mkdtemp(prefix="olivercode-waiver-"))
        try:
            (tmp / "shared").mkdir()
            (tmp / "shared" / "repo-profiles.json").write_text(json.dumps({
                "unmanagedRepoWaivers": [
                    {"name": "a", "reason": "r", "expiresAt": "2000-01-01T00:00:00+00:00"},
                ]}))
            with contextlib.redirect_stdout(io.StringIO()):
                passed, failed, _ = launcher._check_waiver_expiry(tmp)
            self.assertEqual((passed, failed), (0, 1))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_expired_variance_on_a_profile_fails(self):
        tmp = Path(tempfile.mkdtemp(prefix="olivercode-waiver-"))
        try:
            (tmp / "shared").mkdir()
            (tmp / "shared" / "repo-profiles.json").write_text(json.dumps({
                "profiles": {"a": {"approvedStrictVariances": [
                    {"target": "x", "reason": "r", "expiresAt": "2000-01-01T00:00:00+00:00"},
                ]}}}))
            with contextlib.redirect_stdout(io.StringIO()):
                passed, failed, _ = launcher._check_waiver_expiry(tmp)
            self.assertEqual((passed, failed), (0, 1))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestPushFleetExitCode(unittest.TestCase):
    """A blocked push must exit non-zero: the local scheduler touches its marker on exit 0,
    so a push that failed and exited 0 was logged OK and not retried for hours."""

    def _git(self, *args, cwd):
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                       env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull})

    def _repo_ahead_of(self, remote: Path) -> Path:
        repo = self.tmp / "work"
        self._git("clone", "-q", str(remote), str(repo), cwd=self.tmp)
        self._git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                  "--allow-empty", "-m", "next", cwd=repo)
        return repo

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-pushfleet-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.remote = self.tmp / "remote.git"
        self._git("init", "-q", "--bare", "-b", "main", str(self.remote), cwd=self.tmp)
        seed = self.tmp / "seed"
        self._git("init", "-q", "-b", "main", str(seed), cwd=self.tmp)
        self._git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                  "--allow-empty", "-m", "seed", cwd=seed)
        self._git("push", "-q", str(self.remote), "main", cwd=seed)

    def _run(self, repo: Path) -> int:
        oc_root = self.tmp / "oc"
        oc_root.mkdir()
        with mock.patch.object(launcher, "_private_repos", return_value={"target": repo}), \
             mock.patch.object(launcher, "_push_repos", return_value=[]), \
             mock.patch.object(launcher, "load_repo_profiles", return_value=({}, None)), \
             mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull}), \
             contextlib.redirect_stdout(io.StringIO()):
            # OliverCode itself is a target too; an absent .git makes it a plain SKIP.
            return launcher.command_push_fleet(oc_root, dry_run=False)

    def test_blocked_push_exits_nonzero(self):
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.assertEqual(self._run(self._repo_ahead_of(self.remote)), 1)

    def test_successful_push_exits_zero(self):
        self.assertEqual(self._run(self._repo_ahead_of(self.remote)), 0)


if __name__ == "__main__":
    unittest.main()

