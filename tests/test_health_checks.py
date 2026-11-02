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


class WaiverExpiry(HealthBase):
    def run_check(self, data):
        path = self.root / "repo-profiles.json"
        if data is not None:
            path.write_text(data if isinstance(data, str) else json.dumps(data))
        with mock.patch.object(health, "registry_file", lambda _root, _name: path):
            return quiet(health._check_waiver_expiry, self.root)

    @staticmethod
    def day(offset):
        return (datetime.now(timezone.utc) + timedelta(days=offset)).isoformat()

    def test_no_registry_skips(self):
        self.assertEqual((0, 0, 1), self.run_check(None)[0])

    def test_an_unreadable_registry_fails(self):
        self.assertEqual((0, 1, 0), self.run_check("{broken")[0])

    def test_no_waivers_passes(self):
        self.assertEqual((1, 0, 0), self.run_check({"profiles": {}, "unmanagedRepoWaivers": []})[0])

    def test_current_waivers_pass_and_name_the_next_expiry(self):
        data = {
            "unmanagedRepoWaivers": [{"name": "a", "reason": "r", "expiresAt": self.day(30)}],
            "profiles": {"b": {"approvedStrictVariances": [
                {"target": "lint", "reason": "r", "expiresAt": self.day(10)}]}},
        }
        result, out = self.run_check(data)
        self.assertEqual((1, 0, 0), result)
        self.assertIn("2 waiver(s) current", out)
        self.assertIn(str((datetime.now(timezone.utc) + timedelta(days=10)).date()), out)

    def test_each_expired_waiver_fails(self):
        data = {
            "unmanagedRepoWaivers": [{"name": "a", "reason": "r", "expiresAt": self.day(-3)}],
            "profiles": {"b": {"approvedMaintainabilityVariances": [
                {"target": "size", "reason": "r", "expiresAt": "2020-01-01T00:00:00Z"}]}},
        }
        result, out = self.run_check(data)
        self.assertEqual((0, 2, 0), result)
        self.assertIn("b: size variance: EXPIRED", out)

    def test_an_unparsable_date_fails(self):
        data = {"unmanagedRepoWaivers": [{"name": "a", "reason": "r", "expiresAt": "next spring"}]}
        self.assertEqual((0, 1, 0), self.run_check(data)[0])

    def test_a_waiver_without_a_reason_fails_even_without_a_date(self):
        data = {"unmanagedRepoWaivers": [{"name": "a", "reason": "  "}]}
        self.assertEqual((0, 1, 0), self.run_check(data)[0])

    def test_a_null_reason_or_a_non_text_date_fails_without_crashing_the_run(self):
        self.assertEqual((0, 1, 0), self.run_check(
            {"unmanagedRepoWaivers": [{"name": "a", "reason": None, "expiresAt": self.day(5)}]})[0])
        self.assertEqual((0, 1, 0), self.run_check(
            {"unmanagedRepoWaivers": [{"name": "a", "reason": "r", "expiresAt": 20270101}]})[0])

    def test_a_date_without_a_timezone_mixes_with_one_that_has_it(self):
        naive = (datetime.now() + timedelta(days=5)).replace(microsecond=0).isoformat()
        data = {"unmanagedRepoWaivers": [
            {"name": "a", "reason": "r", "expiresAt": naive},
            {"name": "b", "reason": "r", "expiresAt": self.day(20)},
        ]}
        self.assertEqual((1, 0, 0), self.run_check(data)[0])


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


if __name__ == "__main__":
    unittest.main()
