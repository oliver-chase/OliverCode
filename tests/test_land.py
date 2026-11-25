"""`olivercode land` pushes a worktree to main and keeps the main checkout level with it (#608)."""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from _support import git, git_env, load_script, quiet, scratch_repo, temp_dir

launcher = load_script("scripts/olivercode", "olivercode_launcher")
session_check = load_script("scripts/hooks/session_check.py", "session_check_land")
from lib import cmd_drain, cmd_land, maintain, validated  # noqa: E402

REAL_STORY_BODY, REAL_STORY_COMMENT, REAL_STORY_SLUG = cmd_land.story_body, cmd_land._story_comment, cmd_land._story_slug  # the Base class patches these, so keep the real ones (#1073)

_TEMPLATE: Path | None = None  # the one origin/main/wt fixture every Base subclass in this module shares (#1143)


def setUpModule():
    """One origin, main checkout and story worktree for the whole module; each test copies them and repoints their absolute paths."""
    global _TEMPLATE
    root = Path(tempfile.mkdtemp(prefix="olivercode-land-template-")).resolve()
    origin = root / "origin.git"
    scratch_repo(origin, bare=True, branch="main")
    seed = scratch_repo(root / "seed", branch="main")
    git(seed, "remote", "add", "origin", str(origin))
    (seed / "scripts").mkdir()
    (seed / "scripts" / "validate.sh").write_text("exit 0\n")
    (seed / "a.txt").write_text("a")
    git(seed, "add", "."); git(seed, "commit", "-q", "-m", "one"); git(seed, "push", "-q", "origin", "main")
    git(root, "clone", "-q", str(origin), str(root / "main"))
    git(root / "main", "config", "user.email", "t@example.invalid"); git(root / "main", "config", "user.name", "T")
    git(root / "main", "worktree", "add", "-q", "-b", "story/9", str(root / "wt"), "origin/main")
    (root / "wt" / "b.txt").write_text("b")
    git(root / "wt", "add", "."); git(root / "wt", "commit", "-q", "-m", "Add b (#9)")
    _TEMPLATE = root


def tearDownModule():
    if _TEMPLATE is not None:
        shutil.rmtree(_TEMPLATE, ignore_errors=True)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._template = _TEMPLATE

    def setUp(self):
        self.root = temp_dir(self, resolve=True)
        p = mock.patch.dict(os.environ, git_env(), clear=True); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(cmd_land, "LOG_DIR", self.root / "logs"); p.start(); self.addCleanup(p.stop)
        for name in ("origin.git", "seed", "main", "wt"):
            shutil.copytree(self._template / name, self.root / name, symlinks=True)
        self.main, self.wt = self.root / "main", self.root / "wt"
        git(self.main, "remote", "set-url", "origin", str(self.root / "origin.git"))
        git(self.main, "worktree", "repair", str(self.wt))
        p = mock.patch.object(cmd_land, "OC_ROOT", self.main); p.start(); self.addCleanup(p.stop)
        self.body = ""  # the story's body, read over REST: no Files area, so the scope check stays out of these landing tests (#1073)
        p = mock.patch.object(cmd_land, "story_body", side_effect=lambda wt, story: self.body); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(cmd_land, "_story_comment"); self.comment = p.start(); self.addCleanup(p.stop)

    def land(self):
        return quiet(cmd_land.command_land, [str(self.wt), "9"])


class TestLandResumes(Base):
    """A land resumes after an interruption, keeps retrying while main moves, and runs once per story and repo (#784)."""

    def test_a_land_retries_past_four_attempts_and_names_the_reason_when_the_budget_ends(self):
        calls = []
        real = cmd_land._run
        def moving(wt, log, *cmd, env=None):
            if cmd[:2] == ("git", "push"):
                calls.append(cmd)
                (self.main / f"m{len(calls)}.txt").write_text("m")
                git(self.main, "add", "."); git(self.main, "commit", "-q", "-m", "Main moves (#1)"); git(self.main, "push", "-q", "origin", "HEAD:main")
                return False
            return real(wt, log, *cmd, env=env)
        with mock.patch.object(cmd_land, "_run", moving), mock.patch.object(cmd_land, "PAUSE", 0), mock.patch.object(cmd_land, "BUDGET", 3), \
                mock.patch.object(cmd_land.time, "monotonic", side_effect=iter(range(100)).__next__):
            code, out = self.land()
        self.assertEqual(1, code)
        self.assertGreater(len(calls), cmd_land.TRIES)
        self.assertIn("RESULT main-kept-moving", out)
        self.assertNotIn("gave-up", out)

    def test_a_push_that_fails_while_main_stands_still_reports_the_push_error_at_once(self):
        calls = []
        real = cmd_land._run
        def refuse(wt, log, *cmd, env=None):
            if cmd[:2] == ("git", "push"):
                calls.append(cmd)
                log.write("remote: Permission to push denied\n")
                return False
            return real(wt, log, *cmd, env=env)
        with mock.patch.object(cmd_land, "_run", refuse), mock.patch.object(cmd_land, "PAUSE", 0):
            code, out = self.land()
        self.assertEqual(1, code)
        self.assertEqual(1, len(calls))
        self.assertIn("RESULT push-failed", out)
        self.assertIn("Permission to push denied", (self.root / "logs" / "land-main-9.log").read_text())

    def test_a_second_land_for_a_running_story_refuses_and_names_the_log(self):
        logs = self.root / "logs"
        logs.mkdir()
        (logs / "land-main-9.lock").write_text(str(os.getppid()))
        code, out = self.land()
        self.assertEqual(1, code)
        self.assertIn("already running", out)
        self.assertIn("land-main-9.log", out)

    def test_a_land_waits_while_another_run_holds_the_story_and_names_its_commit(self):
        held = iter(["held by drain", "held by drain", ""])
        with mock.patch.object(cmd_land, "_story_slug", return_value="o/r"), mock.patch.object(cmd_land, "PAUSE", 0), \
                mock.patch.dict(os.environ, {cmd_land.LAND_AS: "dispatch"}), mock.patch("lib.cmd_dispatch._local_claim", side_effect=lambda *a, **k: next(held)):
            code, out = self.land()
        self.assertIn("is held by drain, so commit", out)
        self.assertIn(str(self.wt), out)

    def test_a_land_stops_after_five_minutes_on_a_claim_and_names_the_run(self):
        ticks = iter(range(0, 10000, 200))
        with mock.patch.object(cmd_land, "_story_slug", return_value="o/r"), mock.patch.object(cmd_land, "PAUSE", 0), \
                mock.patch.dict(os.environ, {cmd_land.LAND_AS: ""}), mock.patch("lib.cmd_dispatch._local_claim", return_value="held by drain"), \
                mock.patch.object(cmd_land.time, "monotonic", side_effect=lambda: next(ticks)):
            code, out = self.land()
        self.assertEqual(1, code)
        self.assertIn("stays held by drain after 5 minutes", out)

    def test_the_holder_lands_its_own_story_without_waiting(self):
        class NoWaitClock:
            """cmd_land's clock, whose sleep fails. The global time.sleep stays real, since a subprocess poll under load calls it (#1106)."""
            def __getattr__(self, name):
                return getattr(time, name)

            def sleep(self, _):
                raise AssertionError("waited")

        for agent in ("drain", "dispatch"):
            with self.subTest(agent=agent), mock.patch.object(cmd_land, "_story_slug", return_value="o/r"), mock.patch.dict(os.environ, {cmd_land.LAND_AS: agent}), \
                    mock.patch("lib.cmd_dispatch._local_claim", return_value=f"held by {agent}"), mock.patch.object(cmd_land, "time", NoWaitClock()):
                code, out = self.land()
            self.assertNotIn("waits for that run", out)

    def test_the_drain_and_dispatch_tell_the_land_their_agent(self):
        io = cmd_drain.Io(self.wt, "o/r", "dispatch")
        with mock.patch.object(cmd_drain.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            io.land(self.wt, 9)
        self.assertEqual(run.call_args.kwargs["env"][cmd_land.LAND_AS], "dispatch")

    def test_a_second_claim_fails_while_the_first_holds_and_succeeds_after_release_or_when_the_holder_is_gone(self):
        lock = self.root / "claim.lock"
        holder = os.getppid()
        with mock.patch.object(cmd_land.os, "getpid", return_value=holder):
            self.assertIsNone(cmd_land._claim(lock))
        self.assertEqual(str(holder), lock.read_text())
        self.assertEqual(holder, cmd_land._claim(lock))
        self.assertEqual(str(holder), lock.read_text(), "a refused claim leaves the holder's file alone")
        lock.unlink()
        self.assertIsNone(cmd_land._claim(lock))
        self.assertEqual(str(os.getpid()), lock.read_text())
        lock.write_text("999999999")
        self.assertIsNone(cmd_land._claim(lock))
        self.assertEqual(str(os.getpid()), lock.read_text())

    def test_the_claim_file_is_created_exclusively(self):
        lock = self.root / "claim.lock"
        flags = []
        real = os.open
        def spy(path, flag, *rest):
            flags.append(flag)
            return real(path, flag, *rest)
        with mock.patch.object(cmd_land.os, "open", spy):
            cmd_land._claim(lock)
        self.assertEqual([os.O_CREAT | os.O_EXCL | os.O_WRONLY], flags)

    def test_only_one_of_two_simultaneous_claims_wins(self):
        import subprocess, sys
        lock = self.root / "race.lock"
        code = ("import sys; sys.path.insert(0, %r); from pathlib import Path; from lib import cmd_land; "
                "print(cmd_land._claim(Path(%r)), flush=True); sys.stdin.read()" % (str(__import__('_support').REPO_ROOT / "scripts"), str(lock)))
        procs = [subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) for _ in range(6)]
        results = [p.stdout.readline().strip() for p in procs]  # each claimer stays alive until its stdin closes, so a winner never looks stale
        for p in procs:
            p.communicate()
        self.assertEqual(1, results.count("None"), results)

    def test_a_stale_lock_does_not_block_and_is_removed_after_the_land(self):
        logs = self.root / "logs"
        logs.mkdir()
        (logs / "land-main-9.lock").write_text("999999999")
        code, out = self.land()
        self.assertEqual(0, code, out)
        self.assertFalse((logs / "land-main-9.lock").exists())

    def test_a_land_waits_for_a_running_version_cut_then_continues(self):
        logs = self.root / "logs"
        logs.mkdir()
        lock = logs / cmd_land.CUT_LOCK
        lock.write_text(str(os.getppid()))
        sleeps = []
        def sleep(_):
            sleeps.append(1)
            # the cut finishes during the first wait; the patch is the global time.sleep, so a slow
            # subprocess poll can call it again after the lock is gone
            lock.unlink(missing_ok=True)
        with mock.patch.object(cmd_land.time, "sleep", sleep):
            code, out = self.land()
        self.assertEqual(0, code, out)
        self.assertGreaterEqual(len(sleeps), 1)
        self.assertEqual(1, sleeps[0])

    def test_a_cut_that_is_this_process_does_not_block_its_own_land(self):
        logs = self.root / "logs"
        logs.mkdir()
        (logs / cmd_land.CUT_LOCK).write_text(str(os.getpid()))
        self.assertIsNone(cmd_land.cut_running(logs))

    def test_the_log_name_carries_the_repo_so_two_repos_do_not_share_one(self):
        self.land()
        self.assertTrue((self.root / "logs" / "land-main-9.log").is_file())


class TestLandLimits(Base):
    """The size ceiling only warns, so a large growth diff lands and land never commits to docs/LIMITS.json (#879, #882)."""

    def add_big_growth(self):
        (self.wt / "docs").mkdir(exist_ok=True)
        (self.wt / "docs" / "LIMITS.json").write_text('{"limit": 5}\n')
        (self.wt / "scripts" / "lib").mkdir(parents=True)
        (self.wt / "scripts" / "lib" / "grown.py").write_text("x = 1\n" * 300)
        git(self.wt, "add", "."); git(self.wt, "commit", "-q", "-m", "Grow a lot (#9)")

    def test_a_large_growth_diff_lands_with_exit_0_and_no_limits_only_commit(self):
        self.add_big_growth()
        code, out = self.land()
        self.assertEqual(0, code, out)
        subjects = git(self.main, "log", "--format=%s", "origin/main").stdout.splitlines()
        self.assertEqual(["Add b (#9)", "one"], subjects)
        only_limits = [c for c in git(self.main, "rev-list", "origin/main").stdout.split()
                       if git(self.main, "show", "--format=", "--name-only", c).stdout.split() == ["docs/LIMITS.json"]]
        self.assertEqual([], only_limits)
        self.assertEqual('{"limit": 5}\n', git(self.main, "show", "origin/main:docs/LIMITS.json").stdout)

    def test_a_land_that_does_not_grow_the_repo_leaves_the_limits_file_unchanged(self):
        (self.main / "docs").mkdir()
        (self.main / "docs" / "LIMITS.json").write_text('{"limit": 5}\n')
        git(self.main, "add", "."); git(self.main, "commit", "-q", "-m", "Seed limits (#1)"); git(self.main, "push", "-q", "origin", "HEAD:main")
        code, out = self.land()
        self.assertEqual(0, code, out)
        self.assertEqual('{"limit": 5}\n', git(self.main, "show", "origin/main:docs/LIMITS.json").stdout)
        self.assertEqual(["b.txt"], git(self.main, "show", "--format=", "--name-only", "origin/main").stdout.split(), "the landed commit holds the story's change only")


class TestLandSquash(Base):
    """A story with several commits lands as one commit named by the story title and number (#898)."""

    def test_several_commits_land_as_one_with_the_title_and_number(self):
        for name in ("c", "d"):
            (self.wt / f"{name}.txt").write_text(name)
            git(self.wt, "add", "."); git(self.wt, "commit", "-q", "-m", f"fix up {name} (#9)")
        code, out = self.land()
        self.assertEqual(0, code, out)
        self.assertEqual(["Add b (#9)", "one"], git(self.main, "log", "--format=%s", "origin/main").stdout.splitlines())
        for name in ("b", "c", "d"):
            self.assertEqual(name, git(self.main, "show", f"origin/main:{name}.txt").stdout)

    def test_several_stories_add_their_own_commit(self):
        """Several, not ten: each land here is the same code path test_a_landing_pushes... already covers once, so a round number buys no extra coverage, only wall time (#1143)."""
        before = int(git(self.main, "rev-list", "--count", "origin/main").stdout)
        stories = 4
        for n in range(stories):
            wt = self.root / f"wt{n}"
            git(self.main, "fetch", "-q", "origin")
            git(self.main, "worktree", "add", "-q", "-b", f"story/1{n}", str(wt), "origin/main")
            for i in range(3):
                (wt / f"s{n}_{i}.txt").write_text("x")
                git(wt, "add", "."); git(wt, "commit", "-q", "-m", f"part {i} of {n} (#1{n})")
            code, out = quiet(cmd_land.command_land, [str(wt), f"1{n}"])
            self.assertEqual(0, code, out)
        git(self.main, "fetch", "-q", "origin")
        self.assertEqual(before + stories, int(git(self.main, "rev-list", "--count", "origin/main").stdout))


class TestLand(Base):
    def test_a_fresh_worktree_gets_the_main_checkouts_venv_before_validation(self):
        (self.main / ".venv").mkdir()
        (self.wt / "scripts" / "validate.sh").write_text('test -d .venv || exit 1\n')
        git(self.wt, "commit", "-qam", "validate needs the venv")
        code, out = self.land()
        self.assertEqual(0, code, out)
        self.assertIn("RESULT pushed", out)

    def _repo_with_gitignore(self, name, text=None):
        from pathlib import Path
        repo = scratch_repo(self.root / name, branch="main")
        (repo / ".gitignore").write_text(text if text is not None else (Path(__file__).resolve().parent.parent / ".gitignore").read_text())
        git(repo, "add", ".gitignore"); git(repo, "commit", "-q", "-m", "ignore")
        return repo

    def test_a_linked_venv_symlink_is_ignored_by_git(self):
        main, wt = self.root / "vmain", self._repo_with_gitignore("vwt")
        (main / ".venv").mkdir(parents=True)
        self.assertTrue(cmd_land.link_venv(main, wt))
        self.assertTrue((wt / ".venv").is_symlink())
        self.assertNotIn(".venv", git(wt, "status", "--porcelain").stdout)
        git(wt, "add", "-A")
        self.assertNotIn(".venv", git(wt, "diff", "--cached", "--name-only").stdout)

    def test_a_real_venv_directory_is_ignored_by_git(self):
        wt = self._repo_with_gitignore("vdir")
        (wt / ".venv").mkdir(); (wt / ".venv" / "x").write_text("x")
        self.assertNotIn(".venv", git(wt, "status", "--porcelain").stdout)

    def test_the_symlink_test_fails_with_only_the_directory_pattern(self):
        main, wt = self.root / "omain", self._repo_with_gitignore("owt", ".venv/\n")
        (main / ".venv").mkdir(parents=True)
        cmd_land.link_venv(main, wt)
        self.assertIn(".venv", git(wt, "status", "--porcelain").stdout)

    def test_a_repo_without_a_venv_links_nothing_and_raises_nothing(self):
        self.assertFalse(cmd_land.link_venv(self.main, self.wt))
        self.assertFalse((self.wt / ".venv").exists())
        code, out = self.land()
        self.assertEqual(0, code, out)

    def test_a_landing_pushes_and_fast_forwards_a_clean_main_checkout(self):
        code, out = self.land()
        self.assertEqual(0, code)
        self.assertIn("RESULT pushed", out)
        self.assertIn("fast-forwarded", out)
        self.assertEqual(git(self.main, "rev-parse", "origin/main").stdout, git(self.main, "rev-parse", "HEAD").stdout)
        self.assertTrue((self.main / "b.txt").exists())
        self.assertIn("RESULT pushed", (self.root / "logs" / "land-main-9.log").read_text().splitlines()[-1])

    def test_the_log_goes_to_the_running_users_own_home_by_default(self):
        home = self.root / "home"
        with mock.patch.object(cmd_land, "LOG_DIR", None), mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            code, out = self.land()
        self.assertEqual(0, code)
        self.assertIn("RESULT pushed", (home / "land" / "land-main-9.log").read_text())

    def test_an_edited_main_checkout_is_left_alone_and_its_lag_is_printed(self):
        (self.main / "a.txt").write_text("local edit")
        code, out = self.land()
        self.assertEqual(0, code)
        self.assertIn("left alone: 1 commit(s) behind origin/main and edited", out)
        self.assertEqual("local edit", (self.main / "a.txt").read_text())

    def test_a_failing_validation_does_not_push_and_the_log_says_so(self):
        (self.wt / "scripts" / "validate.sh").write_text("exit 1\n")
        git(self.wt, "commit", "-qam", "break validation")
        code, out = self.land()
        self.assertEqual(1, code)
        self.assertIn("RESULT validate-failed", out)
        self.assertEqual(git(self.main, "rev-parse", "origin/main").stdout, git(self.main, "rev-parse", "HEAD").stdout)

    def test_gate_progress_prints_on_the_terminal_while_the_full_output_goes_to_the_log(self):
        (self.wt / "scripts" / "validate.sh").write_text("echo \"=== validate: gate 'smoke' started ===\"\necho noisy-detail\nexit 1\n")
        git(self.wt, "commit", "-qam", "talkative validation")
        code, out = self.land()
        self.assertEqual(1, code)
        self.assertEqual(2, out.count("=== validate: gate 'smoke' started ==="))  # once per validation try
        self.assertNotIn("noisy-detail", out)
        log = (self.root / "logs" / "land-main-9.log").read_text()
        self.assertIn("noisy-detail", log)
        self.assertIn("gate 'smoke' started", log)

    def test_the_launcher_refuses_a_bad_argument_list(self):
        self.assertEqual(2, quiet(cmd_land.command_land, ["only-one"])[0])
        self.assertEqual(2, quiet(cmd_land.command_land, [str(self.wt), "x"])[0])


class TestLandReusesAPass(Base):
    """A tree the runner validated and recorded is pushed without a second validation, and a tree the rebase changed is validated again (#910)."""

    def record_pass(self):
        p = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.root / "home")}); p.start(); self.addCleanup(p.stop)
        validated.record(self.wt)

    def move_main(self):
        (self.main / "m.txt").write_text("m")
        git(self.main, "add", "."); git(self.main, "commit", "-q", "-m", "Main moves (#1)"); git(self.main, "push", "-q", "origin", "HEAD:main")

    def test_a_recorded_pass_for_the_same_tree_is_pushed_without_a_second_validation(self):
        self.record_pass()
        with mock.patch.object(cmd_land, "_validates", wraps=cmd_land._validates) as validates:
            code, out = self.land()
        self.assertEqual(0, code, out)
        self.assertIn("RESULT pushed", out)
        validates.assert_not_called()
        log = (self.root / "logs" / "land-main-9.log").read_text()
        self.assertIn("passed validation at", log, "the log names the record land used")

    def test_a_tree_the_rebase_changed_is_validated_again_before_the_push(self):
        self.record_pass()
        self.move_main()
        with mock.patch.object(cmd_land, "_validates", wraps=cmd_land._validates) as validates:
            code, out = self.land()
        self.assertEqual(0, code, out)
        validates.assert_called_once()
        self.assertIn("RESULT pushed", out)


class TestCleanup(Base):
    def setUp(self):
        super().setUp()
        git(self.wt, "push", "-q", "origin", "HEAD:refs/heads/story/9")  # a branch left on origin by an earlier push

    def branches(self, repo, *args):
        return git(repo, "branch", *args, "--list", "story/9").stdout.strip()

    def test_a_landed_story_loses_its_worktree_and_both_branches(self):
        code, out = self.land()
        self.assertEqual(0, code)
        self.assertFalse(self.wt.exists())
        self.assertEqual("", self.branches(self.main))
        git(self.main, "fetch", "-q", "--prune", "origin")
        self.assertEqual("", self.branches(self.main, "-r"))
        self.assertIn("Removed worktree", out)
        self.assertIn("Deleted remote branch story/9", out)

    def test_cleanup_uses_the_story_id_to_remove_runner_branch_even_from_a_non_story_branch(self):
        git(self.main, "push", "-q", "origin", "--delete", "story/9")
        git(self.wt, "branch", "-m", "feature/cleanup")
        git(self.wt, "push", "-q", "origin", "HEAD:refs/heads/feature/cleanup")
        git(self.wt, "push", "-q", "origin", "HEAD:refs/heads/agent/story-9")
        code, out = self.land()
        self.assertEqual(0, code, out)
        self.assertFalse(self.wt.exists())
        git(self.main, "fetch", "-q", "--prune", "origin")
        remote = git(self.main, "branch", "-r").stdout
        self.assertNotIn("origin/feature/cleanup", remote)
        self.assertNotIn("origin/agent/story-9", remote)
        self.assertIn("Deleted remote branch feature/cleanup", out)
        self.assertIn("Deleted remote branch agent/story-9", out)

    def test_a_landed_story_deletes_the_handover_an_earlier_failed_land_left(self):
        """#1035: a handover from a failed attempt is stale once the story lands, so no file is left behind."""
        logs = self.root / "logs"
        logs.mkdir(exist_ok=True)
        stale = [logs / "handover-main-9.md", logs / "handover-9.md"]
        for path in stale:
            path.write_text("validate-failed\n")
        code, _ = self.land()
        self.assertEqual(0, code)
        self.assertEqual([], [p.name for p in stale if p.exists()])

    def test_a_landing_whose_branch_was_never_pushed_still_cleans_up(self):
        git(self.main, "push", "-q", "origin", "--delete", "story/9")
        code, out = self.land()
        self.assertEqual(0, code)
        self.assertFalse(self.wt.exists())
        self.assertNotIn("remote branch", out)

    def test_a_worktree_with_uncommitted_files_is_refused_before_anything_lands_and_names_them(self):
        with mock.patch.object(cmd_land, "_validates", return_value=True):
            (self.wt / "c.txt").write_text("c")
            code, out = self.land()
        self.assertEqual(1, code)
        self.assertTrue(self.wt.exists())
        self.assertIn("RESULT dirty-worktree", out)
        self.assertIn("c.txt", out)
        origin = self.root / "origin.git"
        self.assertNotEqual(git(origin, "rev-parse", "main").stdout, git(self.wt, "rev-parse", "HEAD").stdout)

    def test_a_worktree_with_no_validate_script_is_refused_not_read_as_done(self):
        git(self.wt, "rm", "-q", "scripts/validate.sh")
        git(self.wt, "commit", "-qm", "Drop validate (#9)")
        code, out = self.land()
        self.assertEqual(1, code)
        self.assertIn("RESULT no-validate", out)
        self.assertIn("scripts/validate.sh", out)


class TestLandsOnAnyDefaultBranch(Base):
    """#1012: land reads the repo's default branch and validation, and fast-forwards the story's own repo."""

    def test_a_master_repo_with_an_npm_check_script_lands_on_master_and_leaves_engine_alone(self):
        origin, engine = self.root / "origin.git", self.root / "engine"
        git(self.main, "branch", "-m", "master"); git(self.main, "push", "-q", "origin", "master")
        git(origin, "symbolic-ref", "HEAD", "refs/heads/master"); git(self.main, "remote", "set-head", "origin", "master")
        git(self.main, "push", "-q", "origin", "--delete", "main")
        git(self.wt, "fetch", "-q", "--prune", "origin"); git(self.main, "fetch", "-q", "--prune", "origin")
        git(self.wt, "rm", "-q", "scripts/validate.sh")
        (self.wt / "package.json").write_text('{"scripts": {"check": "exit 0"}}')
        git(self.wt, "add", "."); git(self.wt, "commit", "-qm", "Use npm (#9)")
        shutil.copytree(self.main, engine, symlinks=True, ignore=shutil.ignore_patterns("*.lock"))
        engine_head = git(engine, "rev-parse", "HEAD").stdout
        with mock.patch.object(cmd_land, "OC_ROOT", engine), mock.patch.object(cmd_land, "_validate_once", return_value=True) as ran:
            code, out = self.land()
        self.assertEqual(0, code, out)
        self.assertIn("RESULT pushed", out)
        self.assertEqual(git(origin, "rev-parse", "master").stdout, git(self.main, "rev-parse", "HEAD").stdout, out)
        ran.assert_called()
        self.assertEqual(engine_head, git(engine, "rev-parse", "HEAD").stdout, "the OliverCode checkout was moved")


class TestUnfinishedWork(Base):
    def test_work_that_fails_validation_gets_a_handover_and_no_pushed_branch(self):
        (self.wt / "scripts" / "validate.sh").write_text("exit 1\n")
        git(self.wt, "commit", "-qam", "break validation")
        code, out = self.land()
        self.assertEqual(1, code)
        handover = (self.root / "logs" / "handover-main-9.md").read_text()
        self.assertIn("validate-failed", handover)
        self.assertIn("never pushed", handover)
        self.assertIn("Handover written", out)
        self.assertTrue(self.wt.exists())
        remote = git(self.main, "ls-remote", "--heads", "origin").stdout
        self.assertNotIn("story/9", remote)
        self.assertNotIn("wip-", remote)
        self.assertNotIn("spent-", remote)


class TestHealthListsSpentWorktrees(Base):
    def test_a_clean_merged_worktree_is_listed_with_the_removing_command(self):
        from lib import cmd_health, placement
        with mock.patch.object(cmd_land, "cleanup", return_value=[]):
            self.land()
        git(self.main, "fetch", "-q", "origin")
        spent = placement.Worktree(self.wt, "story/9", False, True, self.main)
        with mock.patch.object(placement, "worktrees", return_value=[spent]):
            lines = cmd_health.spent_worktree_lines()
        self.assertEqual(1, len(lines))
        self.assertIn(f"git -C {self.main} worktree remove {self.wt}", lines[0])
        self.assertIn("maintain --fix", lines[0])
        with mock.patch.object(placement, "worktrees", return_value=[placement.Worktree(self.wt, "story/9", True, True, self.main)]):
            self.assertEqual([], cmd_health.spent_worktree_lines())


class TestSessionStart(Base):
    def push_commit(self):
        with open(os.devnull, "w") as log:
            cmd_land.land(self.wt, "9", log)
        git(self.main, "fetch", "-q", "origin")

    def test_a_clean_lagging_checkout_is_left_alone_at_session_start(self):
        self.push_commit()
        before = git(self.main, "rev-parse", "HEAD").stdout
        with mock.patch.object(maintain, "OC_ROOT", self.main), mock.patch.object(maintain, "fast_forward") as ff:
            session_check.checkout_notes()
        ff.assert_not_called()
        self.assertEqual(before, git(self.main, "rev-parse", "HEAD").stdout)

    def test_session_start_starts_no_groom(self):
        self.assertFalse(hasattr(session_check, "groom_notes"))

    def test_an_edited_checkout_stays_as_it_is_and_is_named_at_session_start(self):
        self.push_commit()
        (self.main / "a.txt").write_text("edit")
        with mock.patch.object(maintain, "OC_ROOT", self.main):
            notes = session_check.checkout_notes()
        self.assertIn("trails origin/main by 1", notes[0])  # a merged fix that cannot reach the checkout is named (#823)
        self.assertEqual("edit", (self.main / "a.txt").read_text())


# Built from pieces so this file never holds the literal the check looks for: the check reads this file's own added lines (#1073).
SKIP_LINE = "@" + "unittest.skip" + "('later')"
OR_TRUE_LINE = "make " + "|" + "| true"


class TestLandStaysInStory(Base):
    """A landing refuses a commit that changes a file outside its story's Files area, or that weakens a test (#1073)."""

    def test_every_test_file_is_inside_the_area_and_an_unlisted_code_file_is_not(self):
        """The rules ask for a test with every change, and a module's test often has another name (cmd_status.py is tested in
        test_status.py) or covers a neighbour, so a test file never counts as scope creep. The weakened-test check still guards it."""
        from lib import intake
        area = ["scripts/lib/cmd_status.py", "skills/audit/scripts/check_report.py", "scripts/hooks/early-stop-guard.py"]
        for path in ("tests/test_status.py", "tests/test_limits.py", "skills/audit/scripts/test_check_report.py",
                     "skills/backlog/scripts/test_board_hygiene.py", "tests/test_early_stop_guard.py", "scripts/lib/cmd_status.py"):
            self.assertTrue(intake.in_area(path, area), path)
        for path in ("scripts/lib/cmd_health.py", "tests/maintain.py", "skills/backlog/SKILL.md"):
            self.assertFalse(intake.in_area(path, area), path)

    def test_a_commit_that_adds_a_test_of_another_name_lands(self):
        self.body = "Files area: b.txt"
        (self.wt / "tests").mkdir()
        (self.wt / "tests" / "test_other.py").write_text("import unittest\n")
        git(self.wt, "add", "."); git(self.wt, "commit", "-q", "-m", "Test b (#9)")
        code, out = self.land()
        self.assertEqual(0, code, out)
        self.assertIn("RESULT pushed", out)
        self.comment.assert_not_called()

    def test_a_commit_outside_the_files_area_lands_and_is_named_on_the_story(self):
        """A refusal made each restart repeat the same edit and burned the story's restarts, so validation and the reader judge the change and
        the story records the extra files."""
        self.body = "Files area: a.txt"
        code, out = self.land()
        self.assertEqual(0, code, out)
        self.assertIn("RESULT pushed", out)
        self.assertIn("b.txt", (self.root / "logs" / "land-main-9.log").read_text())
        self.comment.assert_called_once()
        text = self.comment.call_args.args[2]
        self.assertIn("b.txt", text)
        self.assertIn("outside the Files area", text)
        self.assertEqual("b", git(self.root / "origin.git", "show", "main:b.txt").stdout, "the commit reached main")

    def test_a_commit_inside_its_files_area_lands_and_gets_no_comment(self):
        self.body = "Files area: b.txt, scripts/"
        code, out = self.land()
        self.assertEqual(0, code)
        self.assertIn("RESULT pushed", out)
        self.comment.assert_not_called()

    def test_a_commit_that_adds_a_skip_to_a_test_is_refused_and_names_the_line(self):
        self.body = "Files area: b.txt, tests/"
        (self.wt / "tests").mkdir()
        (self.wt / "tests" / "test_b.py").write_text("import unittest\n" + SKIP_LINE + "\n")
        git(self.wt, "add", "."); git(self.wt, "commit", "-q", "-m", "Skip b (#9)")
        code, out = self.land()
        self.assertEqual(1, code)
        self.assertIn("RESULT weakened-test", out)
        self.assertIn("tests/test_b.py:2 adds a skip", (self.root / "logs" / "land-main-9.log").read_text())

    def test_a_story_that_cannot_be_read_is_refused_rather_than_checked_against_nothing(self):
        self.body = None
        code, out = self.land()
        self.assertEqual(1, code)
        self.assertIn("RESULT scope-unchecked", out)


class TestStoryReads(Base):
    """The REST read, the comment post and the repo slug run for real here; the landing tests above replace them (#1073)."""

    def test_the_slug_comes_from_the_origin_remote(self):
        git(self.main, "remote", "set-url", "origin", "https://github.com/acme/widgets.git")
        self.assertEqual("acme/widgets", REAL_STORY_SLUG(self.wt))

    def test_the_slug_falls_back_to_the_backlog_config_when_origin_names_no_repo(self):
        git(self.main, "remote", "remove", "origin")
        (self.main / "docs").mkdir(exist_ok=True)
        (self.main / "docs" / "backlog-config.json").write_text(json.dumps({"repoOwner": "acme", "repoName": "gadgets"}))
        self.assertEqual("acme/gadgets", REAL_STORY_SLUG(self.wt))

    def test_the_body_is_read_over_rest_with_a_null_body_read_as_empty(self):
        with mock.patch.object(cmd_land, "_story_slug", return_value="acme/widgets"), \
                mock.patch.object(cmd_land.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="Files area: a.txt\n")) as run:
            self.assertEqual("Files area: a.txt\n", REAL_STORY_BODY(self.wt, "9"))
        args = run.call_args.args[0]
        self.assertEqual(["gh", "api", "repos/acme/widgets/issues/9", "--jq", '.body // ""'], args)

    def test_a_failed_rest_read_returns_none_so_the_landing_refuses(self):
        with mock.patch.object(cmd_land, "_story_slug", return_value="acme/widgets"), \
                mock.patch.object(cmd_land.subprocess, "run", return_value=mock.Mock(returncode=1, stdout="")):
            self.assertIsNone(REAL_STORY_BODY(self.wt, "9"))

    def test_no_slug_means_no_body_to_read(self):
        with mock.patch.object(cmd_land, "_story_slug", return_value=""):
            self.assertIsNone(REAL_STORY_BODY(self.wt, "9"))

    def test_the_comment_posts_to_the_story_over_rest(self):
        with mock.patch.object(cmd_land, "_story_slug", return_value="acme/widgets"), \
                mock.patch.object(cmd_land.subprocess, "run") as run:
            REAL_STORY_COMMENT(self.wt, "9", "Landing refused.")
        self.assertEqual(["gh", "api", "repos/acme/widgets/issues/9/comments", "-f", "body=Landing refused."], run.call_args.args[0])


class TestWeakenedTests(unittest.TestCase):
    """The weakening check reads a zero-context diff: a skip, a trailing true and removed assertions (#1073)."""

    def diff(self, path, hunk, *lines):
        return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n{hunk}\n" + "".join(f"{line}\n" for line in lines)

    def test_assertions_removed_from_a_test_with_no_code_removed_are_refused_at_the_first_one(self):
        rows = cmd_land._changed_lines(self.diff("tests/test_a.py", "@@ -5,2 +5,1 @@",
                                                 "-        self.assertEqual(1, f())", "-        self.assertTrue(g())", "+        pass"))
        self.assertEqual(["tests/test_a.py:5 removes 2 assertion(s) without removing the code they cover"], cmd_land.weakened(rows))

    def test_assertions_may_go_when_the_commit_also_removes_the_code_they_cover(self):
        diff = self.diff("tests/test_a.py", "@@ -5,2 +5,1 @@", "-        self.assertEqual(1, f())", "+        pass")
        diff += self.diff("scripts/lib/a.py", "@@ -9,1 +9,0 @@", "-def f(): return 1")
        self.assertEqual([], cmd_land.weakened(cmd_land._changed_lines(diff)))

    def test_a_one_line_code_edit_does_not_excuse_assertions_removed_from_a_test(self):
        diff = self.diff("tests/test_a.py", "@@ -5,2 +5,1 @@", "-        self.assertEqual(1, f())", "+        pass")
        diff += self.diff("scripts/lib/a.py", "@@ -9,1 +9,1 @@", "-def f(): return 1", "+def f(): return 2")
        self.assertEqual(["tests/test_a.py:5 removes 1 assertion(s) without removing the code they cover"],
                         cmd_land.weakened(cmd_land._changed_lines(diff)))

    def test_blank_lines_removed_from_product_code_do_not_excuse_assertions(self):
        diff = self.diff("tests/test_a.py", "@@ -5,1 +5,0 @@", "-        self.assertTrue(g())")
        diff += self.diff("scripts/lib/a.py", "@@ -9,2 +9,0 @@", "-", "-   ")
        self.assertEqual(["tests/test_a.py:5 removes 1 assertion(s) without removing the code they cover"],
                         cmd_land.weakened(cmd_land._changed_lines(diff)))

    def test_an_assertion_moved_to_another_line_is_not_a_loss(self):
        rows = cmd_land._changed_lines(self.diff("tests/test_a.py", "@@ -5,1 +5,1 @@", "-        self.assertEqual(1, f())", "+        self.assertEqual(1, g())"))
        self.assertEqual([], cmd_land.weakened(rows))

    def test_a_skip_added_to_a_test_names_its_line(self):
        rows = cmd_land._changed_lines(self.diff("tests/test_a.py", "@@ -0,0 +7,1 @@", "+    " + SKIP_LINE))
        self.assertEqual(["tests/test_a.py:7 adds a skip"], cmd_land.weakened(rows))

    def test_or_true_added_to_a_validation_script_is_refused_but_not_added_to_product_code(self):
        flagged = cmd_land._changed_lines(self.diff("scripts/validate.sh", "@@ -1,0 +2,1 @@", "+" + OR_TRUE_LINE))
        self.assertEqual(["scripts/validate.sh:2 adds " + "|" + "| true to a test command"], cmd_land.weakened(flagged))
        product = cmd_land._changed_lines(self.diff("scripts/lib/a.py", "@@ -1,0 +2,1 @@", "+" + OR_TRUE_LINE))
        self.assertEqual([], cmd_land.weakened(product))

    def test_a_deleted_test_file_counts_its_assertions_under_its_own_path(self):
        diff = ("diff --git a/tests/test_gone.py b/tests/test_gone.py\n--- a/tests/test_gone.py\n+++ /dev/null\n@@ -1,1 +0,0 @@\n"
                "-        self.assertEqual(1, f())\n")
        self.assertEqual(["tests/test_gone.py:1 removes 1 assertion(s) without removing the code they cover"], cmd_land.weakened(cmd_land._changed_lines(diff)))


if __name__ == "__main__":
    unittest.main()
