"""Tests for scripts/lib/health_checks.py: the checks `olivercode health` tallies.

Every check returns (passed, failed, skipped). A check that reads outside this repo must
degrade to a skip when that context is missing, and must fail only on a real problem.
"""

import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from _support import git, load_script, scratch_repo, quiet, temp_dir

health = load_script("scripts/lib/health_checks.py", "health_checks")
from lib import health_topology  # noqa: E402


class HealthBase(unittest.TestCase):
    def setUp(self):
        self.root = temp_dir(self, resolve=True)


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


    def test_a_skill_folder_inside_the_checkout_is_left_to_the_placement_check(self):
        """One dangling link must not print a FAIL here and a second one from the placement drift check."""
        self.linked.mkdir(parents=True)
        (self.linked / "alpha").symlink_to(self.root / "nowhere")
        self.skill("alpha")
        result, out = quiet(health._check_vault_skill_links, self.skills, self.skills)
        self.assertEqual((0, 0, 1), result)
        self.assertNotIn("[FAIL]", out)


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

    def test_two_repos_with_one_name_are_each_probed(self):
        first, second = self.repo("one", origin="https://example.invalid/a.git"), self.repo("two", origin="https://example.invalid/b.git")
        seen = []
        real_run = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            if "ls-remote" in cmd:
                seen.append(cmd[-1])
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return real_run(cmd, *args, **kwargs)

        with mock.patch.object(health.subprocess, "run", fake_run):
            result = quiet(health._check_remotes_resolve, [("same", first), ("same", second)])[0]
        self.assertEqual((2, 0, 0), result)
        self.assertEqual(["https://example.invalid/a.git", "https://example.invalid/b.git"], sorted(seen))

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
        with mock.patch.object(health_topology, "GITHUB_FILE_LIMIT", 100):
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
        self.root = temp_dir(self, "olivercode-fleetloc-", resolve=True)
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


class PythonVersion(unittest.TestCase):
    def check(self, version):
        with mock.patch.object(health.shutil, "which", return_value="/x/python3"), \
                mock.patch.object(health, "python_version", return_value=version):
            return quiet(health._check_python)

    def test_an_old_python_fails_naming_found_minimum_and_fix(self):
        (result, out) = self.check((3, 9))
        self.assertEqual(result, (0, 1, 0))
        self.assertIn("3.9", out)
        self.assertIn(f"{health.MIN_PYTHON[0]}.{health.MIN_PYTHON[1]}", out)
        self.assertIn("brew install python@", out)

    def test_the_minimum_passes(self):
        self.assertEqual(self.check(health.MIN_PYTHON)[0], (1, 0, 0))

    def test_a_missing_python_fails(self):
        with mock.patch.object(health.shutil, "which", return_value=None):
            result, out = quiet(health._check_python)
        self.assertEqual(result, (0, 1, 0))
        self.assertIn("brew install", out)


class LauncherLink(HealthBase):
    oc = Path("/oc")

    def test_no_launcher_is_not_checked(self):
        self.assertEqual(quiet(health._check_launcher, self.oc, self.root / "olivercode")[0], (0, 0, 0))

    def test_a_link_to_a_missing_folder_fails_with_the_repair(self):
        link = self.root / "olivercode"
        link.symlink_to(self.root / "gone" / "scripts" / "olivercode")
        result, out = quiet(health._check_launcher, self.oc, link)
        self.assertEqual(result, (0, 1, 0))
        self.assertIn(str(self.root / "gone"), out)
        self.assertIn(f"ln -sf /oc/scripts/olivercode {link}", out)

    def test_a_live_link_passes(self):
        real = self.root / "real"
        real.write_text("#!/bin/sh\n")
        link = self.root / "olivercode"
        link.symlink_to(real)
        self.assertEqual(quiet(health._check_launcher, self.oc, link)[0], (1, 0, 0))

    def test_a_wrapper_with_a_spaced_project_folder_fails_naming_it(self):
        wrapper = self.root / "olivercode"
        wrapper.write_text(f'#!/bin/bash\nPROJECT="{self.root}/Old Vault/OliverCode"\nexec python3 "$PROJECT/scripts/olivercode" "$@"\n')
        result, out = quiet(health._check_launcher, self.oc, wrapper)
        self.assertEqual(result, (0, 1, 0))
        self.assertIn("Old Vault/OliverCode", out)

    def test_a_wrapper_script_naming_a_missing_launcher_fails(self):
        wrapper = self.root / "olivercode"
        wrapper.write_text(f"#!/bin/sh\nexec python3 {self.root}/old/scripts/olivercode \"$@\"\n")
        result, out = quiet(health._check_launcher, self.oc, wrapper)
        self.assertEqual(result, (0, 1, 0))
        self.assertIn("old/scripts/olivercode", out)


class GhAuth(unittest.TestCase):
    """`olivercode health` names a signed-out gh. A fake runner stands in for `gh auth status`, so no live call is made."""

    @staticmethod
    def fake(code, scopes="'project', 'repo'"):
        stderr = f"Token scopes: {scopes}" if code == 0 else "not logged in"
        return lambda: subprocess.CompletedProcess(["gh", "auth", "status"], code, "", stderr)

    def test_a_signed_in_gh_passes(self):
        self.assertEqual(quiet(health._check_gh_auth, self.fake(0))[0], (1, 0, 0))

    def test_a_token_without_the_project_scope_fails_one_line_naming_the_refresh(self):
        result, out = quiet(health._check_gh_auth, self.fake(0, "'repo'"))
        self.assertEqual(result, (0, 1, 0))
        self.assertEqual(1, out.count("[FAIL]"))
        self.assertIn("gh auth refresh -s project", out)

    def test_a_signed_out_gh_warns_and_names_the_fix(self):
        result, out = quiet(health._check_gh_auth, self.fake(1))
        self.assertEqual(result, (0, 0, 1))
        self.assertIn("[WARN]", out)
        self.assertIn("gh auth login", out)

    def test_a_missing_gh_is_a_skip(self):
        def missing():
            raise FileNotFoundError("gh")
        self.assertEqual(quiet(health._check_gh_auth, missing)[0], (0, 0, 1))


class ManagedHooksOnly(HealthBase):
    """Claude Code ignores ~/.claude/settings.json hooks when managed settings set allowManagedHooksOnly."""

    def managed(self, content=None):
        path = self.root / "managed-settings.json"
        if content is not None:
            path.write_text(json.dumps(content))
        return path

    def check(self, path):
        with mock.patch("builtins.print") as shown:
            result = health._check_managed_hooks_only(path)
        return result, " ".join(str(c.args[0]) for c in shown.call_args_list if c.args)

    def test_the_lock_warns_unless_managed_settings_carry_the_hooks_and_no_file_says_nothing(self):
        result, text = self.check(self.managed())
        self.assertEqual(((0, 0, 0), ""), (result, text))
        result, text = self.check(self.managed({"theme": "dark"}))
        self.assertEqual(((0, 0, 0), ""), (result, text))
        result, text = self.check(self.managed({"allowManagedHooksOnly": True}))
        self.assertEqual((0, 0, 1), result)
        self.assertIn("[WARN]", text)
        self.assertIn("ignores", text)
        self.assertIn("managed settings", text)
        carried = {"allowManagedHooksOnly": True, "hooks": health._claude_settings.merge({}, health._claude_settings.HOOKS_DIR)["hooks"]}
        result, text = self.check(self.managed(carried))
        self.assertEqual(((1, 0, 0)), result)


class SleepSettings(unittest.TestCase):
    """The Keep the machine awake section of docs/SETUP.md: `olivercode health` names a sleep that would stop work. A fake runner stands in for `pmset -g`, so the live machine is never read."""

    SAFE = " sleep                0\n displaysleep         0\n"
    UNSAFE = " sleep                1 (sleep prevented by powerd)\n displaysleep         5\n"

    def test_a_sleep_that_would_stop_work_warns_with_the_fix(self):
        result, out = quiet(health._check_sleep, lambda: self.UNSAFE, "darwin")
        self.assertEqual(result, (0, 0, 1))
        self.assertIn("[WARN]", out)
        self.assertIn("caffeinate -dimsu", out)
        self.assertIn("System Settings", out)

    def test_safe_settings_print_no_warning(self):
        result, out = quiet(health._check_sleep, lambda: self.SAFE, "darwin")
        self.assertEqual(result, (1, 0, 0))
        self.assertNotIn("[WARN]", out)

    def test_a_system_sleep_held_by_caffeinate_does_not_count(self):
        text = " sleep                1 (sleep prevented by caffeinate)\n displaysleep         0\n"
        self.assertIsNone(health.sleep_warning(text))

    def test_a_host_that_is_not_macos_skips(self):
        self.assertEqual(quiet(health._check_sleep, lambda: self.UNSAFE, "linux")[0], (0, 0, 0))


class StaleWorktreeHook(HealthBase):
    """#902: a worktree branched before main removed a gate still runs that gate, so its hook is named as stale."""

    def setUp(self):
        super().setUp()
        self.repo = scratch_repo(self.root / "app", branch="main")
        (self.repo / "core" / "hooks" / "gates").mkdir(parents=True)
        (self.repo / "core" / "hooks" / "gates" / "duplicate.sh").write_text("# Duplicate text gate\n")
        (self.repo / "core" / "templates" / "project").mkdir(parents=True)
        (self.repo / "core" / "templates" / "project" / "pre-commit").write_text("#!/bin/bash\n")
        (self.repo / ".githooks").mkdir()
        os.symlink("../core/templates/project/pre-commit", self.repo / ".githooks" / "pre-commit")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "Base (#1)")
        self.wt = self.root / "app-1"
        git(self.repo, "worktree", "add", "-q", str(self.wt), "-b", "story/1")
        git(self.repo, "rm", "-q", "core/hooks/gates/duplicate.sh")  # main drops the gate, as #619 did
        git(self.repo, "commit", "-qm", "Drop the duplicate gate (#619)")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    def test_a_worktree_branched_before_a_gate_was_removed_is_stale_and_names_the_change(self):
        why = health.stale_hook(self.wt)
        self.assertIn("core/hooks/gates/duplicate.sh", why)
        self.assertIn("origin/main", why)

    def test_a_worktree_rebased_onto_main_is_current(self):
        git(self.wt, "rebase", "-q", "origin/main")
        self.assertEqual("", health.stale_hook(self.wt))

    def test_a_checkout_without_gates_or_without_origin_main_says_nothing(self):
        plain = scratch_repo(self.root / "plain", branch="main")
        (plain / "README.md").write_text("x\n")
        git(plain, "add", "-A")
        git(plain, "commit", "-qm", "Base (#2)")
        git(plain, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertEqual("", health.stale_hook(plain))
        self.assertEqual("", health.stale_hook(self.wt, base="origin/nothing"))

class TestGhVersion(unittest.TestCase):
    def test_an_old_gh_fails_naming_the_version_and_a_command(self):
        from lib import cli
        run = mock.Mock(return_value=mock.Mock(stdout="gh version 2.40.1 (2024-01-01)\n"))
        problem = cli.gh_problem(run)
        self.assertIn("2.48", problem)
        self.assertIn(cli.GH_FIX, problem)
        result, out = quiet(health._check_gh_version, lambda: problem)
        self.assertEqual((0, 1, 0), result)

    def test_a_new_or_missing_gh_passes(self):
        from lib import cli
        self.assertIsNone(cli.gh_problem(mock.Mock(return_value=mock.Mock(stdout="gh version 2.60.0 (x)"))))
        self.assertIsNone(cli.gh_problem(mock.Mock(side_effect=FileNotFoundError)))

