"""Direct tests for the launcher commands that had none: sync-hooks and its commit step.

Every test runs against a scratch checkout and a scratch HOME. Nothing reaches the network, and
git reads no machine config (tests/_support.py).
"""

import json
import os
import shutil
import subprocess
import unittest
from unittest import mock

from _fleet_case import ScratchHome
from _support import REPO_ROOT, git, git_env, load_script, scratch_repo, quiet, temp_dir

TEMPLATES = REPO_ROOT / "core" / "templates" / "project"
launcher = load_script("scripts/olivercode", "olivercode_launcher")
from lib import local_config  # noqa: E402  (load_script put scripts/ on the path)
from lib import cmd_fleet, cmd_health, cmd_repo, gitfiles  # noqa: E402


class TestCommandSyncHooks(ScratchHome):
    def setUp(self):
        super().setUp()
        (self.oc / "core" / "templates").mkdir(parents=True)
        shutil.copytree(TEMPLATES, self.oc / "core" / "templates" / "project")
        self.fleet = self.tmp / "fleet"
        self.fleet.mkdir()
        self.private = {}

    def sync(self, private=None):
        with mock.patch.object(cmd_fleet, "_private_repos", return_value=private if private is not None else self.private):
            return quiet(launcher.command_sync_hooks, self.oc)

    def test_a_private_repo_gets_the_private_variant_as_its_live_hook_and_a_hooks_path(self):
        repo = scratch_repo(self.tmp / "vault")
        (repo / ".githooks").mkdir()
        (repo / ".githooks" / "pre-commit-private").write_text("stale\n")
        code, out = self.sync({"vault": repo})
        self.assertEqual(code, 0)
        self.assertIn("[OK] vault: private-variant hook synced", out)
        self.assertEqual(["commit-msg", "pre-commit", "pre-push"], sorted(p.name for p in (repo / ".githooks").iterdir()))
        self.assertEqual((repo / ".githooks" / "pre-commit").read_bytes(), (TEMPLATES / "pre-commit-private").read_bytes())
        self.assertTrue(os.access(repo / ".githooks" / "pre-commit", os.X_OK))
        self.assertEqual(git(repo, "config", "--get", "core.hooksPath").stdout.strip(), ".githooks")
        self.assertFalse((repo / ".githooks" / "pre-commit-private").exists())

    def test_a_private_repo_outside_repo_root_is_synced_with_the_private_variant(self):
        repo = scratch_repo(self.tmp / "elsewhere" / "notes")
        _, out = self.sync({"notes": repo})
        self.assertIn("[OK] notes", out)
        self.assertEqual((repo / ".githooks" / "pre-commit").read_bytes(),
                         (TEMPLATES / "pre-commit-private").read_bytes())

    def test_a_private_repo_with_no_git_folder_is_skipped(self):
        _, out = self.sync({"notes": self.tmp / "nowhere"})
        self.assertIn("[SKIP] notes: no .git", out)

    def test_with_the_harness_config_it_touches_nothing_outside_the_temp_dir(self):
        """No fixture config: the machine's olivercode.local.json must not reach the run."""
        self.assertEqual([], os.listdir(local_config.load_local()["repoRoot"]))
        self.assertEqual({}, cmd_fleet._private_repos())
        scratch_repo(self.fleet / "alpha")
        code, out = quiet(launcher.command_sync_hooks, self.oc)
        self.assertEqual(code, 0)
        self.assertIn("0 target(s) synced, 0 skipped.", out)
        self.assertFalse((self.fleet / "alpha" / ".githooks").exists())

    def test_a_second_run_changes_nothing(self):
        repo = scratch_repo(self.fleet / "alpha")
        self.sync({"alpha": repo})
        first = (repo / ".githooks" / "pre-commit").read_bytes()
        code, _ = self.sync({"alpha": repo})
        self.assertEqual(code, 0)
        self.assertEqual((repo / ".githooks" / "pre-commit").read_bytes(), first)


class TestSyncHooksCommit(ScratchHome):
    """`sync-hooks --commit`: the hook files sync wrote are committed by path, and only those."""

    def setUp(self):
        super().setUp()
        (self.oc / "core" / "templates").mkdir(parents=True)
        shutil.copytree(TEMPLATES, self.oc / "core" / "templates" / "project")
        self.fleet = self.tmp / "fleet"
        self.fleet.mkdir()
        env = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.tmp / "ochome")})
        env.start()
        self.addCleanup(env.stop)

    def repo(self, name="alpha"):
        repo = scratch_repo(self.fleet / name)
        (repo / "README").write_text("hello\n")
        git(repo, "add", "README")
        git(repo, "commit", "-q", "--no-verify", "-m", "First commit")
        return repo

    def sync(self, *, commit=True, story="acme/widgets#7", archived=None):
        with mock.patch.object(cmd_fleet, "_private_repos", return_value={"alpha": self.fleet / "alpha"}), \
                mock.patch.object(cmd_fleet._repo_state, "archived", return_value=archived), \
                mock.patch.dict(os.environ, git_env(), clear=True):
            return quiet(launcher.command_sync_hooks, self.oc, commit=commit, story=story)

    def test_a_changed_hook_is_committed_by_path_and_an_unrelated_staged_file_stays_staged(self):
        repo = self.repo()
        (repo / "other.txt").write_text("staged for another reason\n")
        git(repo, "add", "other.txt")
        code, out = self.sync()
        self.assertEqual(0, code, out)
        self.assertRegex(out, r"alpha: committed [0-9a-f]{7,}")
        self.assertEqual("A  other.txt", git(repo, "status", "--porcelain").stdout.strip())
        self.assertEqual({".githooks/commit-msg", ".githooks/pre-commit", ".githooks/pre-push"},
                         set(git(repo, "show", "--name-only", "--format=", "HEAD").stdout.split()))
        message = git(repo, "log", "-1", "--format=%B").stdout
        self.assertTrue(message.startswith("Sync the managed hook files from OliverCode (acme/widgets#7)\n"))
        self.assertIn("\nNo test: managed hook files copied from OliverCode\n", message)
        self.assertEqual("Size: XS", message.strip().splitlines()[-1])

    def test_a_commit_without_a_story_asks_for_one(self):
        repo = self.repo()
        code, out = self.sync(story=None)
        self.assertEqual(1, code)
        self.assertIn("needs --story", out)
        self.assertEqual(1, len(git(repo, "log", "--format=%H").stdout.split()))

    def test_a_hook_with_local_edits_before_sync_makes_the_repo_skip(self):
        repo = self.repo()
        self.sync()
        (repo / ".githooks" / "pre-push").write_text("local edit\n")
        head = git(repo, "rev-parse", "HEAD").stdout
        code, out = self.sync()
        self.assertEqual(0, code, out)
        self.assertIn("alpha: not committed, .githooks/pre-push already had uncommitted changes that are not the template", out)
        self.assertEqual(head, git(repo, "rev-parse", "HEAD").stdout)
        self.assertEqual("local edit\n", (repo / ".githooks" / "pre-push").read_text())
        code, out = self.sync()  # a re-run asks again and never commits the template over the edit (#1032)
        self.assertIn("not the template", out)
        self.assertEqual(head, git(repo, "rev-parse", "HEAD").stdout)

    def test_uncommitted_hooks_that_already_match_the_template_are_committed_with_the_story(self):
        repo = self.repo()
        self.sync(commit=False)  # hooks written but left uncommitted, as an earlier update did
        self.assertNotEqual("", git(repo, "status", "--porcelain", "--", ".githooks").stdout)
        code, out = self.sync()
        self.assertEqual(0, code, out)
        self.assertRegex(out, r"alpha: committed [0-9a-f]{7,}")
        self.assertEqual("", git(repo, "status", "--porcelain", "--", ".githooks").stdout)
        self.assertIn("(acme/widgets#7)", git(repo, "log", "-1", "--format=%B").stdout)

    def test_an_archived_repo_is_skipped_and_nothing_is_staged(self):
        repo = self.repo()
        with mock.patch.object(cmd_fleet._repo_state, "archived", return_value="archived"), \
                mock.patch.dict(os.environ, git_env(), clear=True):
            before = cmd_fleet._hook_snapshot(repo)
            cmd_fleet._install_hook_pair(repo, cmd_fleet.repo_gates.hook_templates(REPO_ROOT), False)
            _, out = quiet(cmd_fleet._commit_synced, "alpha", repo, before, "acme/widgets#7")
        self.assertIn("alpha: not committed, archived on GitHub", out)
        self.assertEqual(1, len(git(repo, "log", "--format=%H").stdout.split()))
        self.assertEqual("", git(repo, "diff", "--cached", "--name-only").stdout)

    def test_a_repo_with_no_commits_is_skipped(self):
        repo = scratch_repo(self.fleet / "alpha")
        code, out = self.sync()
        self.assertIn("alpha: not committed, the repo has no commits", out)
        self.assertEqual("", git(repo, "diff", "--cached", "--name-only").stdout)

    def test_without_commit_nothing_is_committed(self):
        repo = self.repo()
        code, out = self.sync(commit=False)
        self.assertEqual(0, code, out)
        self.assertNotIn("committed", out)
        self.assertEqual(1, len(git(repo, "log", "--format=%H").stdout.split()))
        self.assertTrue((repo / ".githooks" / "pre-commit").is_file())

    def test_a_second_run_has_nothing_to_commit(self):
        repo = self.repo()
        self.sync()
        _, out = self.sync()
        self.assertIn("alpha: nothing to commit", out)
        self.assertEqual(2, len(git(repo, "log", "--format=%H").stdout.split()))

    def test_a_commit_the_repo_gates_refuse_is_reported_and_unstaged(self):
        repo = self.repo()
        real = gitfiles._git

        def refuse(path, *args):
            if args[0] == "commit":
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="[commit-msg] BLOCKED: refused\n")
            return real(path, *args)

        with mock.patch.object(gitfiles, "_git", refuse):
            _, out = self.sync()
        self.assertIn("alpha: not committed, the repo's own gates refused it ([commit-msg] BLOCKED: refused)", out)
        self.assertEqual("", git(repo, "diff", "--cached", "--name-only").stdout)


if __name__ == "__main__":
    unittest.main()
