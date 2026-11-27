"""Tests for scripts/lib/placement.py, scripts/hooks/placement_guard.py and the place and clean commands."""

import json
import os
import shlex
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_land, placement, repo_gates  # noqa: E402

GUARD = REPO_ROOT / "scripts" / "hooks" / "pretool_guard.py"


def make_config(root, watch, allow=()):
    return placement.Config(root=root, worktrees=root / "_worktrees", archive=root / "_archive",
                            watch=list(watch), allow=list(allow))


class TestWorktreeHooks(unittest.TestCase):
    """#786: a new story worktree accepts its first commit with hooks set."""

    def setUp(self):
        self.root = temp_dir(self, resolve=True) / "Repos"
        self.repo = scratch_repo(self.root / "app")
        hook = self.repo / ".githooks" / "pre-commit"
        hook.parent.mkdir()
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "gates")
        git(self.repo, "config", "extensions.worktreeConfig", "true")
        git(self.repo, "config", "--worktree", "core.hooksPath", ".githooks")
        self.cfg = make_config(self.root, [])

    def test_a_hand_made_worktree_is_named_with_the_fix_and_the_fix_makes_it_commit(self):
        wt = self.cfg.worktrees / "app-1"
        git(self.repo, "worktree", "add", "-q", str(wt), "-b", "story/1")
        git(wt, "config", "--worktree", "--unset", "core.hooksPath")  # git copies the main checkout's setting into a new worktree only on some setups
        (found,) = placement.findings(self.cfg)
        self.assertEqual(("worktree-hooks", wt), (found.kind, found.path))
        self.assertIn(f'olivercode worktree fix "{wt}"', found.fix)
        self.assertEqual([], cmd_land.prepare_worktree(wt))
        self.assertEqual("", repo_gates.gate_problem(wt))
        self.assertEqual([], placement.findings(self.cfg))

    def test_the_sanctioned_command_makes_a_worktree_that_is_ready_to_commit(self):
        wt = self.cfg.worktrees / "app-2"
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertEqual([], cmd_land.add_worktree(self.repo, wt, "2"))
        self.assertEqual(".githooks", git(wt, "config", "--get", "core.hooksPath").stdout.strip())
        self.assertEqual("", repo_gates.gate_problem(wt))

    def test_a_worktree_that_cannot_be_made_names_why(self):
        (problem,) = cmd_land.add_worktree(self.repo, self.cfg.worktrees / "app-3", "3", "origin/nothing")
        self.assertIn("was not created", problem)


class TestResumeWorktree(unittest.TestCase):
    """#877: a story whose first headless session stopped is restarted on the same branch."""

    def setUp(self):
        self.root = temp_dir(self, resolve=True) / "Repos"
        self.repo = scratch_repo(self.root / "app", branch="main")
        git(self.repo, "commit", "--allow-empty", "-q", "-m", "start")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.wt = self.root / "_worktrees" / "app-5"

    def test_a_fresh_story_gets_a_new_branch_and_no_resume_note(self):
        self.assertEqual(([], ""), cmd_land.resume_worktree(self.repo, self.wt, "5"))
        self.assertEqual("story/5", git(self.wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip())

    def test_an_existing_branch_with_its_worktree_keeps_commits_and_uncommitted_work(self):
        cmd_land.add_worktree(self.repo, self.wt, "5")
        (self.wt / "done.txt").write_text("partial\n")
        git(self.wt, "add", "done.txt")
        git(self.wt, "commit", "-q", "-m", "Partial (#5)")
        (self.wt / "wip.txt").write_text("unsaved\n")
        git(self.repo, "commit", "--allow-empty", "-q", "-m", "main moves")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        problems, note = cmd_land.resume_worktree(self.repo, self.wt, "5")
        self.assertEqual([], problems)
        self.assertIn("git status", note)
        self.assertIn("git log", note)
        self.assertIn("rebased onto origin/main", note)
        self.assertTrue((self.wt / "wip.txt").exists())
        self.assertIn("Partial (#5)", git(self.wt, "log", "--format=%s").stdout)
        self.assertIn("main moves", git(self.wt, "log", "--format=%s").stdout)

    def test_an_existing_branch_without_its_worktree_is_attached_with_its_commits(self):
        cmd_land.add_worktree(self.repo, self.wt, "5")
        (self.wt / "done.txt").write_text("partial\n")
        git(self.wt, "add", "done.txt")
        git(self.wt, "commit", "-q", "-m", "Partial (#5)")
        git(self.repo, "worktree", "remove", "--force", str(self.wt))
        problems, note = cmd_land.resume_worktree(self.repo, self.wt, "5")
        self.assertEqual([], problems)
        self.assertIn("git status", note)
        self.assertTrue((self.wt / "done.txt").exists())
        self.assertEqual(".githooks", git(self.wt, "config", "--get", "core.hooksPath").stdout.strip())

    def test_a_branch_that_conflicts_with_the_default_branch_is_left_alone_and_says_so(self):
        cmd_land.add_worktree(self.repo, self.wt, "5")
        (self.wt / "f.txt").write_text("mine\n")
        git(self.wt, "add", "f.txt")
        git(self.wt, "commit", "-q", "-m", "Mine (#5)")
        (self.repo / "f.txt").write_text("theirs\n")
        git(self.repo, "add", "f.txt")
        git(self.repo, "commit", "-q", "-m", "Theirs")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        before = git(self.wt, "rev-parse", "HEAD").stdout
        problems, note = cmd_land.resume_worktree(self.repo, self.wt, "5")
        self.assertEqual([], problems)
        self.assertIn("conflicts with origin/main", note)
        self.assertEqual(before, git(self.wt, "rev-parse", "HEAD").stdout)
        self.assertEqual("", git(self.wt, "status", "--porcelain").stdout.strip())


class TestFindings(unittest.TestCase):
    def setUp(self):
        base = temp_dir(self, resolve=True)
        self.root = base / "Repos"
        self.root.mkdir()
        self.other = base / "Developer"
        self.other.mkdir()
        self.cfg = make_config(self.root, [self.other])

    def test_a_clean_machine_reports_nothing(self):
        scratch_repo(self.root / "app")
        self.assertEqual([], placement.findings(self.cfg))

    def test_a_repo_outside_the_root_is_reported_with_its_destination(self):
        scratch_repo(self.other / "stray")
        (found,) = placement.findings(self.cfg)
        self.assertEqual(("repo", self.other / "stray"), (found.kind, found.path))
        self.assertIn(str(self.root / "stray"), found.fix)

    def test_an_allowed_checkout_outside_the_root_passes(self):
        scratch_repo(self.other / "vault")
        self.cfg.allow = [self.other / "vault"]
        self.assertEqual([], placement.findings(self.cfg))

    def test_a_backup_folder_in_the_root_is_reported(self):
        (self.root / "app-backup-1106").mkdir()
        (found,) = placement.findings(self.cfg)
        self.assertEqual("backup", found.kind)

    def test_the_archive_folder_is_the_home_for_backups(self):
        (self.root / "_archive" / "app-backup-1106").mkdir(parents=True)
        self.assertEqual([], placement.findings(self.cfg))

    def test_a_worktree_outside_the_worktree_folder_is_reported(self):
        repo = scratch_repo(self.root / "app")
        git(repo, "commit", "--allow-empty", "-q", "-m", "x")
        git(repo, "worktree", "add", "-q", str(self.root / "app-wt"), "-b", "side")
        kinds = [(f.kind, f.path.name) for f in placement.findings(self.cfg)]
        self.assertIn(("worktree", "app-wt"), kinds)

    def test_a_subagent_worktree_under_the_repos_claude_folder_is_not_reported(self):
        repo = scratch_repo(self.root / "app")
        git(repo, "commit", "--allow-empty", "-q", "-m", "x")
        (repo / ".claude" / "worktrees").mkdir(parents=True)
        git(repo, "worktree", "add", "-q", str(repo / ".claude" / "worktrees" / "agent-1"), "-b", "agent")
        kinds = [(f.kind, f.path.name) for f in placement.findings(self.cfg)]
        self.assertNotIn(("worktree", "agent-1"), kinds)

    def test_a_worktree_in_the_worktree_folder_passes(self):
        repo = scratch_repo(self.root / "app")
        git(repo, "commit", "--allow-empty", "-q", "-m", "x")
        (self.root / "_worktrees").mkdir()
        git(repo, "worktree", "add", "-q", str(self.root / "_worktrees" / "app-wt"), "-b", "side")
        self.assertEqual([], placement.findings(self.cfg))


class TestClean(unittest.TestCase):
    def setUp(self):
        base = temp_dir(self, resolve=True)
        self.cfg = make_config(base / "Repos", [])
        self.repo = scratch_repo(self.cfg.root / "app", branch="main")
        git(self.repo, "commit", "--allow-empty", "-q", "-m", "x")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.cfg.worktrees.mkdir()

    def add(self, name, branch=None, age_hours=3):
        """A worktree from origin/main with no commit. Its folder, its .git file and its index are dated age_hours back, so no
        builder has used it lately (#1045)."""
        path = self.cfg.worktrees / name
        git(self.repo, "worktree", "add", "-q", str(path), "-b", branch or name)
        old = time.time() - age_hours * 3600
        for stamped in (path, path / ".git", self.repo / ".git" / "worktrees" / name / "index"):
            os.utime(stamped, (old, old))
        return path

    def claims(self, claims):
        home = temp_dir(self)
        (home / "dispatch-claims.json").write_text(json.dumps(claims))
        return mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)})

    def test_a_fresh_worktree_with_no_commit_is_kept_by_apply(self):
        path = self.add("fresh", age_hours=0)
        lines = placement.clean(self.cfg, apply=True)
        self.assertTrue(path.exists())
        self.assertTrue(any(line.startswith(f"KEEP   {path}") and "used in the last" in line for line in lines))

    def test_a_worktree_whose_builder_ran_git_lately_is_kept_though_its_folder_is_old(self):
        path = self.add("active")
        os.utime(self.repo / ".git" / "worktrees" / "active" / "index")  # a git command just rewrote the index
        lines = placement.clean(self.cfg, apply=True)
        self.assertTrue(path.exists())
        self.assertTrue(any(line.startswith(f"KEEP   {path}") and "used in the last" in line for line in lines))

    def test_a_worktree_whose_story_has_a_live_dispatch_claim_is_kept(self):
        path = self.add("story-77", branch="story/77")
        with self.claims({"OliverCode#77": {"agent": "builder", "at": time.time()}}):
            lines = placement.clean(self.cfg, apply=True)
        self.assertTrue(path.exists())
        self.assertTrue(any("dispatch claim holds story #77" in line for line in lines))

    def test_an_expired_dispatch_claim_does_not_keep_its_worktree(self):
        path = self.add("story-78", branch="story/78")
        with self.claims({"OliverCode#78": {"agent": "builder", "at": time.time() - 3 * 3600}}):
            placement.clean(self.cfg, apply=True)
        self.assertFalse(path.exists())

    def test_a_merged_clean_worktree_is_listed_and_kept_without_apply(self):
        path = self.add("done")
        self.assertIn(f"REMOVE {path}", " ".join(placement.clean(self.cfg)))
        self.assertTrue(path.exists())
        # An ignored .env exists nowhere else, so a worktree holding one is kept.
        common = Path(subprocess.run(["git", "-C", str(path), "rev-parse", "--git-common-dir"], capture_output=True, text=True).stdout.strip())
        exclude = (common if common.is_absolute() else path / common) / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(".env\n")
        (path / ".env").write_text("TOKEN=local\n")
        self.assertIn(f"KEEP   {path}", " ".join(placement.clean(self.cfg)))

    def test_apply_removes_a_merged_clean_worktree(self):
        path = self.add("done")
        placement.clean(self.cfg, apply=True)
        self.assertFalse(path.exists())

    def test_uncommitted_work_is_kept(self):
        path = self.add("busy")
        (path / "note.txt").write_text("work\n")
        lines = placement.clean(self.cfg, apply=True)
        self.assertTrue(path.exists())
        self.assertTrue(any(line.startswith("KEEP") and "uncommitted" in line for line in lines))

    def test_unmerged_commits_are_kept(self):
        path = self.add("ahead")
        git(path, "commit", "--allow-empty", "-q", "-m", "more work (#656)")
        lines = placement.clean(self.cfg, apply=True)
        self.assertTrue(path.exists())
        self.assertTrue(any(line.startswith("KEEP") and "not on origin/main" in line and "finish or discard story #656" in line for line in lines))


class TestRemoteBranches(unittest.TestCase):
    """#1045: only a merged story/* branch is pruned, and never one with an open pull request."""

    def setUp(self):
        base = temp_dir(self, resolve=True)
        self.cfg = make_config(base / "Repos", [])
        self.repo = scratch_repo(self.cfg.root / "app", branch="main")
        git(self.repo, "commit", "--allow-empty", "-q", "-m", "x")
        for ref in ("refs/remotes/origin/main", "refs/remotes/origin/story/7", "refs/remotes/origin/feature-x"):
            git(self.repo, "update-ref", ref, "HEAD")

    def test_only_a_merged_story_branch_is_listed(self):
        with mock.patch.object(placement, "_open_pr", return_value=False):
            self.assertEqual(["REMOVE app: origin/story/7 (merged into origin/main; run with --apply)"], placement.remote_branches(self.cfg))

    def ask_github(self, stdout="0\n", returncode=0, refused=""):
        """The real _open_pr with GitHub's answer faked. Returns its verdict and the mock that stood in for gh."""
        with mock.patch.object(placement, "_origin_slug", return_value="acme/app"), \
                mock.patch.object(placement.gh_budget, "reserve_call", return_value=refused), \
                mock.patch.object(placement.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], returncode, stdout, "")) as run:
            verdict = placement._open_pr(self.repo, "story/7")
        return verdict, run

    def test_no_open_pull_request_lets_the_story_branch_go(self):
        verdict, run = self.ask_github("0\n")
        self.assertFalse(verdict)
        self.assertIn("head=acme%3Astory/7", " ".join(run.call_args[0][0]))

    def test_an_open_pull_request_keeps_the_branch(self):
        verdict, _ = self.ask_github("1\n")
        self.assertTrue(verdict)

    def test_a_refused_or_failed_check_keeps_the_branch(self):
        verdict, run = self.ask_github(refused="Try again in 30 seconds.")
        self.assertTrue(verdict)
        run.assert_not_called()
        self.assertTrue(self.ask_github("", returncode=1)[0])

    def test_a_story_branch_with_an_open_pull_request_is_kept(self):
        with mock.patch.object(placement, "_open_pr", return_value=True):
            self.assertEqual([], placement.remote_branches(self.cfg))


class TestViolation(unittest.TestCase):
    def setUp(self):
        base = temp_dir(self, resolve=True)
        self.cfg = make_config(base / "Repos", [])
        self.cfg.root.mkdir()
        self.cwd = self.cfg.root / "app"

    def check(self, line):
        return placement.violation(shlex.split(line), self.cwd, self.cfg)

    def test_a_worktree_under_the_worktree_folder_is_allowed(self):
        self.assertEqual("", self.check(f"git worktree add {self.cfg.worktrees}/x -b x"))

    def test_a_worktree_elsewhere_is_refused_and_names_the_right_path(self):
        why = self.check("git worktree add /tmp/x -b x")
        self.assertIn("_worktrees/x", why)  # the folder name, not the absolute path, keeps the message under 200 characters

    def test_a_relative_worktree_beside_the_repo_is_refused(self):
        self.assertTrue(self.check("git worktree add ../app-wt main"))

    def test_a_clone_into_the_root_is_allowed(self):
        self.assertEqual("", self.check(f"git clone https://github.com/o/r.git {self.cfg.root}/r"))

    def test_a_clone_into_the_current_folder_outside_the_root_is_refused(self):
        self.cwd = self.cfg.root.parent / "Downloads"
        self.assertIn("clone it as r", self.check("git clone https://github.com/o/r.git"))

    def test_other_git_commands_are_ignored(self):
        self.assertEqual("", self.check("git worktree list"))
        self.assertEqual("", self.check("git status"))


class TestGuardScript(unittest.TestCase):
    def run_guard(self, command, cwd):
        payload = json.dumps({"tool_input": {"command": command}, "cwd": str(cwd)})
        done = subprocess.run([sys.executable, str(GUARD)], input=payload, capture_output=True, text=True)
        return done.returncode, done.stdout

    def test_an_unrelated_command_prints_nothing(self):
        self.assertEqual((0, ""), self.run_guard("ls -la", "/tmp"))


class TestOtherDevice(unittest.TestCase):
    """A repo that belongs to another device stays out of every fleet walk and is refused here (#637)."""

    def setUp(self):
        base = temp_dir(self, resolve=True)
        self.root = base / "Repos"
        self.root.mkdir()
        self.cfg = make_config(self.root, [])
        local = base / "local.json"
        local.write_text(json.dumps({"otherDeviceRepos": ["Work-Assets"], "otherDeviceOwners": ["Work-Org"]}))
        old = os.environ.get("OLIVERCODE_LOCAL_CONFIG")
        os.environ["OLIVERCODE_LOCAL_CONFIG"] = str(local)
        self.addCleanup(lambda: os.environ.__setitem__("OLIVERCODE_LOCAL_CONFIG", old) if old is not None else os.environ.pop("OLIVERCODE_LOCAL_CONFIG"))

    def test_a_clone_by_name_or_owner_is_found_by_health_with_its_fix(self):
        by_name = scratch_repo(self.root / "work-assets")
        by_owner = scratch_repo(self.root / "thing")
        git(by_owner, "remote", "add", "origin", "https://github.com/work-org/thing.git")
        scratch_repo(self.root / "fine")
        found = {f.path.name: f for f in placement.findings(self.cfg) if f.kind == "other-device"}
        self.assertEqual({"work-assets", "thing"}, set(found))
        self.assertIn("move it out of the repo root or remove it", found["thing"].fix)
        self.assertTrue(by_name.exists())

    def test_a_clone_of_another_devices_repo_is_refused(self):
        why = placement.violation(shlex.split(f"git clone https://github.com/work-org/thing.git {self.root}/thing"), self.root, self.cfg)
        self.assertIn("belongs to another device", why)
        self.assertEqual("", placement.violation(shlex.split(f"git clone https://github.com/me/thing.git {self.root}/thing"), self.root, self.cfg))

    def test_no_agent_creates_a_github_repo_for_a_folder_without_an_origin(self):
        bare = self.root / "bare"
        scratch_repo(bare)
        why = placement.repo_create_violation(shlex.split("gh repo create --private --source=. --push"), bare)
        self.assertIn("report the folder to the owner", why)
        self.assertIn("report the folder", placement.repo_create_violation(shlex.split("gh repo create --source ../bare"), self.root / "x"))
        git(bare, "remote", "add", "origin", "https://github.com/me/bare.git")
        self.assertEqual("", placement.repo_create_violation(shlex.split("gh repo create --source=. --push"), bare))
        self.assertEqual("", placement.repo_create_violation(shlex.split("gh repo create newthing --private"), bare))
        self.assertEqual("", placement.repo_create_violation(shlex.split("gh repo view"), bare))
