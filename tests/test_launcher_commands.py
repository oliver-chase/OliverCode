"""Tests for the launcher's command surface: `install`, `bootstrap`, and argument
handling.

Argument handling gets tests because ignoring an unknown flag silently produced a
*wrong success*: `sync-hooks --root /somewhere` ignored the flag, synced the default
fleet, and printed "6 target(s) synced".
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

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "scripts" / "olivercode"


def _load():
    loader = SourceFileLoader("olivercode_launcher", str(LAUNCHER))
    spec = importlib.util.spec_from_loader("olivercode_launcher", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


launcher = _load()


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




class TestRepoPathResolution(unittest.TestCase):
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
        self.assertFalse(str(got).startswith("~"))
        self.assertTrue(str(got).endswith("work/alpha"))

class TestSelfSkipIsCaseInsensitive(unittest.TestCase):
    """`discover` emits profile names from directory names, so the framework repo
    arrives as "OliverCode". A lowercase-only self-skip let that through and
    sync-hooks would have installed FLEET hooks into the framework repo itself."""

    def test_source_uses_case_insensitive_comparison(self):
        # Moved to lib/repo_profiles.py 2026-09-15 (iter_fleet), scripts/olivercode
        # imports it under its original _iter_fleet name -- read the real source.
        src = (REPO_ROOT / "scripts" / "lib" / "repo_profiles.py").read_text(encoding="utf-8")
        self.assertIn('name.lower() == "olivercode"', src)
        self.assertNotIn('if name == "olivercode"', src)




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

    def test_refuses_a_non_git_directory(self):
        plain = Path(tempfile.mkdtemp(prefix="olivercode-nongit-"))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = launcher.command_bootstrap(REPO_ROOT, plain, False)
            self.assertEqual(rc, 1, "must refuse a directory with no .git")
        finally:
            shutil.rmtree(plain, ignore_errors=True)

class TestFleetIteration(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()


class TestWaiverExpiryDateHandling(unittest.TestCase):
    """One waiver written without a timezone must not crash the whole health run.

    min() over mixed offset-naive and offset-aware datetimes raises TypeError;
    reproduced live before the fix normalized both sides identically."""

    def test_mixed_naive_and_aware_expiry_dates(self):
        import contextlib, io, json
        tmp = Path(tempfile.mkdtemp(prefix="olivercode-waiver-"))
        try:
            (tmp / "shared").mkdir()
            (tmp / "shared" / "repo-map.json").write_text(json.dumps({
                "unmanagedRepoWaivers": [
                    {"name": "a", "reason": "r", "expiresAt": "2099-06-01T00:00:00+00:00"},
                    {"name": "b", "reason": "r", "expiresAt": "2099-07-01T00:00:00"},
                ]}))
            with contextlib.redirect_stdout(io.StringIO()):
                passed, failed, skipped = launcher._check_waiver_expiry(tmp)
            self.assertEqual((passed, failed), (1, 0))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
