"""Tests for scripts/lib/health_checks.py: the checks `olivercode health` tallies.

Every check returns (passed, failed, skipped). A check that reads outside this repo must
degrade to a skip when that context is missing, and must fail only on a real problem.
"""

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from _support import git, load_script, scratch_repo

health = load_script("scripts/lib/health_checks.py", "health_checks")


def quiet(fn, *args):
    """Run a check without its report lines, returning (result, printed text)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = fn(*args)
    return result, out.getvalue()


class HealthBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()


class VaultSkillLinks(HealthBase):
    def setUp(self):
        super().setUp()
        self.skills = self.root / "skills-folder"
        self.linked = self.root / "home" / ".claude" / "skills"
        env = mock.patch.dict(os.environ, {"HOME": str(self.root / "home")})
        env.start()
        self.addCleanup(env.stop)

    def skill(self, rel):
        folder = self.skills / rel
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("---\nname: x\n---\n")
        return folder

    def check(self):
        return quiet(health._check_vault_skill_links, self.skills)[0]

    def test_no_skills_folder_set_is_not_checked(self):
        self.assertEqual((0, 0, 0), quiet(health._check_vault_skill_links, None)[0])

    def test_a_missing_folder_or_missing_link_dir_skips(self):
        self.assertEqual((0, 0, 1), self.check())
        self.skill("alpha")
        self.assertEqual((0, 0, 1), self.check())

    def test_linked_skills_pass_including_one_nested_in_a_family_folder(self):
        self.linked.mkdir(parents=True)
        for folder in (self.skill("alpha"), self.skill("family/beta")):
            (self.linked / folder.name).symlink_to(folder)
        (self.skills / "docs" / "guide").mkdir(parents=True)
        (self.skills / "docs" / "guide" / "SKILL.md").write_text("not a skill")
        self.assertEqual((2, 0, 0), self.check())

    def test_an_unlinked_a_broken_and_a_misdirected_skill_each_fail(self):
        self.linked.mkdir(parents=True)
        self.skill("unlinked")
        broken = self.skill("broken")
        (self.linked / "broken").symlink_to(self.root / "nowhere")
        misdirected = self.skill("misdirected")
        (self.linked / "misdirected").symlink_to(broken)
        self.assertEqual((0, 3, 0), self.check())


class RemotesResolve(HealthBase):
    def repo(self, name, origin=None):
        path = self.root / name
        scratch_repo(path)
        if origin:
            git(path, "remote", "add", "origin", origin)
        return path

    def check(self, repos, ls_remote_stderr=None, ls_remote_code=0):
        real_run = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            if "ls-remote" in cmd and ls_remote_stderr is not None:
                return subprocess.CompletedProcess(cmd, ls_remote_code, stdout="", stderr=ls_remote_stderr)
            return real_run(cmd, *args, **kwargs)

        with mock.patch.object(health.subprocess, "run", fake_run):
            return quiet(health._check_remotes_resolve, repos)[0]

    def test_a_reachable_remote_passes(self):
        bare = self.root / "remote.git"
        scratch_repo(bare, bare=True)
        work = self.repo("work", origin=str(bare))
        (work / "f").write_text("x")
        git(work, "add", "f")
        git(work, "commit", "-qm", "x")
        git(work, "push", "-q", "origin", "HEAD:main")
        self.assertEqual((1, 0, 0), self.check([("work", work)]))

    def test_a_denied_remote_fails(self):
        work = self.repo("work", origin="https://example.invalid/gone.git")
        # The two messages hosts actually send: GitHub over ssh, and git itself over https.
        self.assertEqual((0, 1, 0), self.check([("work", work)], "ERROR: Repository not found.", 128))
        self.assertEqual(
            (0, 1, 0),
            self.check([("work", work)], "fatal: repository 'https://example.invalid/gone.git/' not found", 128),
        )

    def test_a_network_error_and_an_unknown_error_only_warn(self):
        work = self.repo("work", origin="https://example.invalid/x.git")
        self.assertEqual((0, 0, 1), self.check([("work", work)], "Could not resolve host: example.invalid", 128))
        self.assertEqual((0, 0, 1), self.check([("work", work)], "fatal: something odd", 128))

    def test_a_local_only_repo_warns_and_a_non_repo_is_ignored(self):
        local = self.repo("local")
        plain = self.root / "plain"
        plain.mkdir()
        self.assertEqual((0, 0, 1), self.check([("local", local), ("plain", plain)]))

    def test_nothing_to_check_skips_once(self):
        self.assertEqual((0, 0, 1), self.check([]))


class OversizedTracked(HealthBase):
    def repo(self, name, files):
        path = self.root / name
        scratch_repo(path)
        for rel, size in files.items():
            (path / rel).write_bytes(b"x" * size)
        git(path, "add", ".")
        return path

    def check(self, repos):
        with mock.patch.object(health, "GITHUB_FILE_LIMIT", 100):
            return quiet(health._check_oversized_tracked, repos)

    def test_a_tracked_file_over_the_limit_fails_its_repo(self):
        big = self.repo("big", {"small.txt": 10, "huge.bin": 101})
        ok = self.repo("ok", {"small.txt": 100})
        (result, out) = self.check([("big", big), ("ok", ok)])
        self.assertEqual((1, 1, 0), result)
        self.assertIn("big: huge.bin", out)

    def test_an_untracked_large_file_is_ignored(self):
        path = self.repo("repo", {"small.txt": 10})
        (path / "untracked.bin").write_bytes(b"x" * 500)
        self.assertEqual((1, 0, 0), self.check([("repo", path)])[0])

    def test_no_git_repo_skips_once(self):
        plain = self.root / "plain"
        plain.mkdir()
        self.assertEqual((0, 0, 1), self.check([("plain", plain)])[0])


class TestFleetLocations(unittest.TestCase):
    """A repo placed by config that is gone is a FAIL. A repo never placed is only a note."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="olivercode-fleetloc-")).resolve()
        self.addCleanup(__import__("shutil").rmtree, self.root, ignore_errors=True)
        self.fleet = self.root / "fleet"
        self.fleet.mkdir()

    def check(self, profiles, repo_paths=None):
        config = self.root / "local.json"
        config.write_text(json.dumps({"repoPaths": {n: str(p) for n, p in (repo_paths or {}).items()}}))
        with mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(config)}):
            return quiet(health._check_fleet_locations, profiles, self.fleet)

    def test_a_repo_missing_at_a_configured_location_fails_naming_path_and_entry(self):
        gone = self.root / "moved" / "alpha"
        profiles = {"alpha": {}, "beta": {"path": "elsewhere/beta"}}
        (passed, failed, skipped), out = self.check(profiles, {"alpha": gone})
        self.assertEqual((0, 2, 0), (passed, failed, skipped))
        self.assertIn(f"[FAIL] alpha: no repo at {gone}. Update repoPaths.alpha in olivercode.local.json", out)
        self.assertIn(f"{self.fleet / 'elsewhere' / 'beta'}. Update profiles.beta.path in repo-profiles.json", out)

    def test_a_repo_never_cloned_is_a_note_and_does_not_fail(self):
        (passed, failed, _), out = self.check({"gamma": {}})
        self.assertEqual((0, 0), (passed, failed))
        self.assertIn("gamma", out)

    def test_a_repo_present_at_its_configured_path_passes(self):
        here = scratch_repo(self.root / "here")
        self.assertEqual((1, 0, 0), self.check({"alpha": {}}, {"alpha": here})[0])


if __name__ == "__main__":
    unittest.main()
