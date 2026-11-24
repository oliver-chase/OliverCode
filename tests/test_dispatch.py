"""`olivercode dispatch N` prepares a builder session: brief, refusals, claim and queue. No network, no real load."""

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, quiet, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import gh_budget  # noqa: E402
from lib import cmd_dispatch, cmd_drain  # noqa: E402

NOW = 1_800_000_000.0
STORY = {"number": 77, "title": "Fixture story title", "state": "OPEN", "body": "Do the fixture thing.\nSecond line.\nFiles area: scripts/lib/x.py.",
         "labels": [{"name": "story"}], "comments": []}
FREE = lambda slug: 0  # noqa: E731


def runner_for(story, posted, others=()):
    def run(args):
        if args[:1] == ["api"] and "issues?state=open" in args[1]:
            return subprocess.CompletedProcess(args, 0, json.dumps([[story, *others]]), "")
        if args[:1] == ["api"] and args[1].endswith("/comments") and "--paginate" in args:
            return subprocess.CompletedProcess(args, 0, json.dumps([story.get("comments") or []]), "")
        if args[:1] == ["api"] and len(args) == 2 and "/issues/" in args[1]:
            return subprocess.CompletedProcess(args, 0, json.dumps({k: v for k, v in story.items() if k != "comments"}), "")
        posted.append(args)
        return subprocess.CompletedProcess(args, 0, "https://example.test/c/1\n", "")
    return run


class RunIo:
    """The outside effects of one dispatched story, recorded in order."""

    def __init__(self, land_ok=True, builds=None):
        self.agent, self.land_ok, self.steps, self.on_main, self.ghost_land = "dispatch", land_ok, [], set(), False
        self.builds, self.issue = builds, None
        self.repo = Path("/repo")

    def validation(self): return ["bash", "scripts/validate.sh"]
    def worktree(self, n): return Path(f"/wt/{n}")
    def beat(self, building): pass
    def claim(self, n): self.steps.append("claim")
    def build(self, issue, wt, note):
        self.steps.append("build")
        self.issue = issue
        return self.builds.pop(0) if self.builds else {"done": True, "reason": "ok", "rounds": 1, "tokens": 5, "summary": ""}
    def landed(self, wt, n): return n in self.on_main
    def pending(self, n): return False
    def commits(self, wt): return 1
    def land(self, wt, n):
        self.steps.append("land")
        if self.land_ok and not self.ghost_land:
            self.on_main.add(n)
        return self.land_ok, "pushed abc1234" if self.land_ok else "validate-failed"
    def comment(self, n, body): self.steps.append("comment")
    def close_by_script(self, wt, n, why):
        self.steps.append("close")
        return True, ""
    def release(self, n): self.steps.append("release")
    def keep_open(self, n, reason=""): self.steps.append(f"open:{reason}")
    def policy_stop(self, n, wt): return None  # no policy ask answers this fake's builds (#1058)
    def landed_lead(self, issue): return None


class DispatchCase(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        self.repo = temp_dir(self)
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "backlog-config.json").write_text(json.dumps(
            {"repoOwner": "o", "repoName": "r", "projectId": "P", "fields": {"status": {"id": "F", "options": {"In Progress": "x"}}}}))
        self.root = temp_dir(self)
        local = self.root / "local.json"
        local.write_text(json.dumps({"repoRoot": str(self.root)}))
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home), "OLIVERCODE_LOCAL_CONFIG": str(local)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_dispatch(self, story=STORY, busy=FREE, argv=("77",), others=(), io=None, **kw):
        io = io or RunIo()
        code, out = quiet(cmd_dispatch.command_dispatch, list(argv), runner=runner_for(story, [], others), busy=busy,
                          clock=lambda: NOW, repo=self.repo, io=io, **kw)
        return code, out, io


class TestDispatch(DispatchCase):
    def test_a_ready_story_builds_headless_through_drains_sequence_with_no_run_flag(self):
        code, out, io = self.run_dispatch()
        self.assertEqual((0, ["claim", "build", "land", "close", "release"]), (code, io.steps))
        self.assertIn("Story #77 landed and closed", out)
        self.assertEqual("Fixture story title", io.issue["title"])

    def test_the_story_runs_the_same_work_story_drain_uses(self):
        with mock.patch.object(cmd_drain, "work_story", return_value=(True, 5)) as work:
            code, _, _ = self.run_dispatch()
        self.assertEqual(0, code)
        self.assertEqual(77, work.call_args.args[1]["number"])

    def test_a_dispatch_while_another_run_holds_the_repo_joins_its_queue_and_builds_nothing(self):
        """#992: no second builder starts; the story is appended, and the holder is named."""
        from lib import run_lock
        run_lock.acquire("o/r", "drain r", time.time(), page="/h/status.md", pid=os.getpid() + 1, alive=lambda p: True)
        with mock.patch.object(run_lock, "pid_alive", return_value=True):
            code, out, io = self.run_dispatch()
        self.assertEqual((0, []), (code, io.steps))
        self.assertIn("Story #77 joins its queue", out)
        self.assertIn("drain r", out)
        self.assertEqual([77], run_lock.take_queue("o/r", os.getpid() + 1))

    def test_a_dispatch_works_the_stories_another_thread_queued_before_it_leaves(self):
        from lib import run_lock

        def work(io, story, state):
            if story["number"] == 77:
                run_lock.acquire("o/r", "dispatch 78", time.time(), want=[78], pid=os.getpid() + 1, alive=lambda p: True)
            return True, 1
        with mock.patch.object(cmd_drain, "work_story", side_effect=work) as w, mock.patch.object(cmd_dispatch, "read_story", side_effect=lambda r, s, n: (dict(STORY, number=n), "")):
            code, _, _ = self.run_dispatch()
        self.assertEqual((0, [77, 78]), (code, [c.args[1]["number"] for c in w.call_args_list]))
        self.assertEqual({}, run_lock.active("o/r"))

    def test_dry_run_claims_and_builds_nothing(self):
        code, out, io = self.run_dispatch(argv=("77", "--dry-run"))
        self.assertEqual((0, []), (code, io.steps))
        self.assertIn("Dry run", out)
        self.assertFalse((self.home / "gh-project-queue.json").exists())

    def test_a_dispatch_starts_below_the_machine_limit_and_refuses_at_it(self):
        """#1055: other runs' builders count against maxBuilders; held validation slots and the load average do not."""
        with mock.patch.object(cmd_dispatch.local_config, "max_builders", return_value=4):
            folder = self.home / "validate-slots"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "slot-1.json").write_text(json.dumps({"pid": os.getpid(), "started": time.time(), "label": "held"}))
            code, _out, io = self.run_dispatch(busy=lambda slug: 3)
            self.assertEqual((code, "build" in io.steps), (0, True))
            code, out, io = self.run_dispatch(busy=lambda slug: 4)
        self.assertEqual((code, io.steps), (1, []))
        self.assertIn("limit of 4", out)

    def test_it_refuses_a_story_whose_files_area_names_a_folder(self):
        """#1077: dispatch names the folder to replace with files."""
        (self.repo / "scripts" / "lib").mkdir(parents=True)
        code, out, io = self.run_dispatch(story={**STORY, "body": "Do it.\nFiles area: scripts/lib, tests/test_x.py"})
        self.assertEqual((code, io.steps), (1, []))
        self.assertIn("names the folder scripts/lib", out)

    def test_it_refuses_a_closed_story_and_a_claimed_story(self):
        code, out, io = self.run_dispatch(story={**STORY, "state": "CLOSED"})
        self.assertEqual((code, io.steps), (1, []))
        self.assertIn("closed", out)
        stamp = "2027-01-15T07:59:00Z"  # inside two hours of NOW
        claimed = {**STORY, "comments": [{"body": f"Claim\n- Session: other-session\n- Time: {stamp}"}]}
        code, out, io = self.run_dispatch(story=claimed)
        self.assertEqual((code, io.steps), (1, []))
        self.assertIn("other-session", out)


class TestClaimStart(DispatchCase):
    def test_a_renewed_claim_keeps_its_start(self):
        """#1093: renewal moves the claim's time and never its start."""
        cmd_dispatch._local_claim("o/r", 5, 1000.0, write="drain")
        cmd_dispatch._local_claim("o/r", 5, 1600.0, write="drain")
        entry = json.loads((self.home / "dispatch-claims.json").read_text())["o/r#5"]
        self.assertEqual((1000.0, 1600.0), (entry["since"], entry["at"]))
        cmd_dispatch._local_claim("o/r", 5, 1700.0, clear=True)
        cmd_dispatch._local_claim("o/r", 5, 1800.0, write="drain")
        self.assertEqual(1800.0, json.loads((self.home / "dispatch-claims.json").read_text())["o/r#5"]["since"])


class TestForkOrigin(DispatchCase):
    def with_origin(self, url):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "remote", "add", "origin", url], check=True)

    def seen_reads(self):
        seen = []
        base = runner_for(STORY, [])
        code, out = quiet(cmd_dispatch.command_dispatch, ["77", "--dry-run"], runner=lambda a: (seen.append(a), base(a))[1],
                          busy=FREE, clock=lambda: NOW, repo=self.repo)
        self.assertEqual(0, code, out)
        return seen

    def slug_read(self):
        view = next(a for a in self.seen_reads() if a[:1] == ["api"] and len(a) == 2)
        return view[1].removeprefix("repos/").split("/issues/")[0]

    def test_the_story_is_read_over_rest_and_never_through_gh_issue(self):
        seen = self.seen_reads()
        self.assertTrue(seen)
        self.assertTrue(all(a[0] == "api" and not a[1].startswith("graphql") for a in seen), seen)

    def test_a_config_naming_another_repo_reads_the_origin_remotes_repo(self):
        self.with_origin("git@github.com:me/my-fork.git")
        self.assertEqual("me/my-fork", self.slug_read())

    def test_drain_reads_the_same_fork_slug_as_dispatch(self):
        self.with_origin("git@github.com:me/my-fork.git")
        self.assertEqual("me/my-fork", cmd_dispatch.origin_slug(self.repo, "o/r"))

    def test_a_config_matching_origin_is_used_as_before(self):
        self.with_origin("https://github.com/O/R.git")
        self.assertEqual("o/r", self.slug_read())


class ClaimIo(RunIo):
    """RunIo with drain's real claim, so the claim goes through the injected GitHub runner."""

    def __init__(self, repo, runner):
        super().__init__()
        self.repo, self.slug, self.runner = repo, "o/r", runner
        self.claimed_at = {}

    gh = cmd_drain.Io.gh
    claim = cmd_drain.Io.claim

    def release(self, n): cmd_dispatch._local_claim(self.slug, n, time.time(), clear=True)


class TestOneBuilderPerStory(DispatchCase):
    """#710: a live claim stops a second builder, and the claim is written before the builder starts."""
    STAMP = "2027-01-15T07:59:00Z"  # inside two hours of NOW

    def claimed(self, who="b1"):
        return {**STORY, "comments": [{"body": f"Claim\n- Session: {who}\n- Time: {self.STAMP}"}]}

    def test_a_live_claim_from_another_session_stops_dispatch_and_names_it(self):
        code, out, io = self.run_dispatch(story=self.claimed())
        self.assertEqual((code, io.steps), (1, []))
        self.assertIn("claimed by b1", out)
        self.assertIn("Take the next open story", out)

    def test_a_claim_released_by_comment_frees_the_story_for_the_next_look(self):
        release = "Claim released\n- Session: b1\n- Reason: gone\n- Time: 2027-01-15T07:59:30Z"
        story = {**self.claimed(), "comments": self.claimed()["comments"] + [{"body": release}]}
        code, _out, io = self.run_dispatch(story=story)
        self.assertEqual((code, "claim" in io.steps), (0, True))

    def test_the_claim_is_written_before_the_builder_starts_and_a_second_dispatch_is_refused(self):
        order = []
        story = {**STORY, "comments": []}
        runner = runner_for(story, [])

        def tracking(args):
            if args[0] == "api" and any(a.startswith("body=") for a in args):
                order.append("claim")
                story["comments"].append({"body": "Claim\n- Session: dispatch\n- Time: 2027-01-15T07:59:30Z"})
            return runner(args)

        io = ClaimIo(self.repo, tracking)
        build = io.build
        io.build = lambda *a: order.append("builder") or build(*a)
        code, _ = quiet(cmd_dispatch.command_dispatch, ["77"], runner=tracking, busy=FREE, clock=lambda: NOW, repo=self.repo, io=io)
        self.assertEqual((code, order), (0, ["claim", "builder"]))
        code, out, io2 = self.run_dispatch(story=story)
        self.assertEqual((code, io2.steps), (1, []))
        self.assertIn("claimed by dispatch", out)


def small(number, area="scripts/lib/x.py", size="XS", priority="P2"):
    return {"number": number, "title": f"Small {number}", "state": "open", "labels": [],
            "body": f"Do {number}.\nPriority: {priority}. Size: {size}. Work type: Story.\nFiles area: {area}"}


class TestOneStoryPerBuilder(DispatchCase):
    def test_a_small_story_builds_alone_and_takes_no_mates(self):
        code, _, io = self.run_dispatch(story={**STORY, "body": "Do the lead.\nPriority: P1. Size: XS. Work type: Story.\nFiles area: scripts/lib/x.py"},
                                        others=(small(78),))
        self.assertEqual(code, 0)
        self.assertNotIn("mates", io.issue)

class TestDispatchRun(DispatchCase):
    def test_a_builder_that_never_finishes_comments_the_blocker_returns_the_story_to_ready_and_releases(self):
        dead = [{"done": False, "reason": "no", "rounds": 3, "tokens": 9, "summary": ""} for _ in range(4)]
        code, out, io = self.run_dispatch(io=RunIo(builds=dead))
        self.assertEqual((1, ["claim"] + ["build"] * 4 + ["comment", "open:", "release"]), (code, io.steps))
        self.assertIn("stayed open", out)

    def test_a_refused_landing_leaves_the_story_open_and_releases_the_claim(self):
        code, _, io = self.run_dispatch(io=RunIo(land_ok=False))
        self.assertEqual(1, code)
        self.assertNotIn("close", io.steps)
        self.assertEqual(["comment", "open:", "release"], io.steps[-3:])

    def test_a_story_already_on_the_default_branch_closes_with_no_builder_session(self):
        io = RunIo()
        io.on_main.add(77)  # the commit is on origin's default branch, so no builder starts (#1011)
        io.commits = lambda wt: 0
        code, out, _ = self.run_dispatch(io=io)
        self.assertEqual((0, ["claim", "close", "release"]), (code, io.steps))
        self.assertIn("landed and closed", out)

    def test_a_story_is_never_closed_unless_its_commit_is_on_the_default_branch(self):
        io = RunIo()
        io.ghost_land = True  # land says yes but nothing reaches origin
        code, _, _ = self.run_dispatch(io=io)
        self.assertEqual(1, code)
        self.assertNotIn("close", io.steps)

    def test_a_worktree_that_cannot_be_made_comments_and_builds_nothing(self):
        io = RunIo()
        def refuse(n): raise RuntimeError("no worktree")
        io.worktree = refuse
        code, out, _ = self.run_dispatch(io=io)
        self.assertEqual((1, ["claim", "comment", "open:", "release"]), (code, io.steps))
        self.assertIn("stayed open", out)


class TestFileExcerpts(unittest.TestCase):
    """#887: the brief holds the functions and callers a story's Files area names."""

    def make_repo(self):
        repo = scratch_repo(temp_dir(self))
        (repo / "scripts").mkdir(exist_ok=True)
        (repo / "scripts" / "thing.py").write_text("def build_thing(x):\n    return x + 1\n\n\ndef other():\n    return 0\n", encoding="utf-8")
        (repo / "scripts" / "user.py").write_text("from thing import build_thing\n\nvalue = build_thing(2)\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "fixture")
        return repo

    def test_the_named_function_and_its_callers_are_in_the_excerpts(self):
        repo = self.make_repo()
        out = cmd_dispatch.file_excerpts("Fix build_thing.\n\nFiles area: scripts/thing.py", repo)
        self.assertIn("def build_thing(x):", out)
        self.assertIn("scripts/user.py:3", out)
        self.assertNotIn("def other", out)

    def test_a_story_that_names_no_function_or_file_adds_nothing(self):
        repo = self.make_repo()
        self.assertEqual("", cmd_dispatch.file_excerpts("Files area: scripts/thing.py", repo))
        self.assertEqual("", cmd_dispatch.file_excerpts("Fix build_thing.", repo))


class TestBriefRules(unittest.TestCase):
    """#1069: the builder brief tells a builder to reuse before it writes, and to mark a shortcut as a decision."""

    def test_the_brief_carries_the_reuse_ladder_and_the_shortcut_comment(self):
        brief = cmd_dispatch.headless_brief(77, STORY, "dispatch")
        self.assertIn("Reuse before you write", brief)
        self.assertIn("already exists here, is in the standard library", brief)
        self.assertIn("`shortcut: <limit>, <when to upgrade>`", brief)


if __name__ == "__main__":
    unittest.main()
