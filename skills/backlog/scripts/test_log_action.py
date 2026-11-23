"""Test the action logger with an injected gh runner. No network and no gh.
Run: python3 -m unittest discover -p "test_*.py"   (from this folder)
"""
import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import log_action as la

ARGS = ["--repo", "o/r", "--story", "53", "--agent", "builder-1", "--role", "builder",
        "--commit", "abc1234", "--files", "4", "--result", "tests pass"]


class Recorder:
    def __init__(self, returncode=0, stdout="https://example.invalid/c/1\n", stderr=""):
        self.calls = []
        self.reply = subprocess.CompletedProcess([], returncode, stdout, stderr)

    def __call__(self, args):
        self.calls.append(args)
        return self.reply


def run(argv, runner, names=None):
    out, err = io.StringIO(), io.StringIO()
    code = la.main(argv, runner=runner, out=out, err=err, pushed=lambda commit: None, names=names, names_story=lambda commit, story: None)
    return code, out.getvalue(), err.getvalue()


def run_unpushed(argv, runner):
    out, err = io.StringIO(), io.StringIO()
    code = la.main(argv, runner=runner, out=out, err=err, pushed=lambda commit: f"commit {commit} is not on origin/main; push it first")
    return code, out.getvalue(), err.getvalue()


class LogAction(unittest.TestCase):
    def test_a_close_names_its_own_commit(self):
        """#1011: a commit whose message lacks #N for the story is refused, and one that names it posts."""
        with tempfile.TemporaryDirectory() as tmp:
            who = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t", "GIT_AUTHOR_EMAIL": "t-at-test", "GIT_COMMITTER_EMAIL": "t-at-test"}
            git = lambda *a: subprocess.run(["git", "-C", tmp, *a], capture_output=True, text=True, check=True, env=who)
            git("init", "-q")
            git("commit", "--allow-empty", "-qm", "Fix the other thing (#6)")
            other = git("rev-parse", "HEAD").stdout.strip()
            git("commit", "--allow-empty", "-qm", "Fix this thing (#5)")
            mine = git("rev-parse", "HEAD").stdout.strip()
            self.assertIn("does not name #5", la.commit_names_story(other, 5, tmp))
            self.assertIn("does not name #5", la.commit_names_story(mine, 55, tmp))
            self.assertIsNone(la.commit_names_story(mine, 5, tmp))
        argv = ["--repo", "o/r", "--story", "5", "--agent", "b", "--role", "builder", "--commit", "abc1234", "--files", "1", "--result", "ok"]
        out, err = io.StringIO(), io.StringIO()
        code = la.main(argv, runner=Recorder(), out=out, err=err, pushed=lambda c: None, names_story=lambda c, s: "commit abc1234 does not name #5 in its message")
        self.assertEqual(2, code)
        self.assertIn("does not name #5", err.getvalue())

    def test_a_builder_entry_for_an_unpushed_commit_is_refused_and_a_pushed_one_posts(self):
        argv = ["--repo", "o/r", "--story", "5", "--agent", "b", "--role", "builder", "--commit", "abc1234", "--files", "1", "--result", "ok"]
        posted = []
        runner = lambda a: (posted.append(a), subprocess.CompletedProcess([], 0, "https://x/1", ""))[1]
        code, _, err = run_unpushed(argv, runner)
        self.assertEqual((2, []), (code, posted))
        self.assertIn("not on origin/main", err)
        self.assertEqual(0, run(argv, runner)[0])
        self.assertEqual(1, len(posted))

    def test_an_olivercode_comment_naming_another_repo_is_refused_before_the_post(self):
        rec = Recorder()
        argv = ["--repo", "o/OliverCode", "--story", "5", "--agent", "b", "--role", "builder", "--commit", "abc1234",
                "--files", "1", "--result", "synced zz-example-repo"]
        code, _, err = run(argv, rec, names=["zz-example-repo"])
        self.assertEqual((1, []), (code, rec.calls))
        self.assertIn("another repo", err)
        self.assertNotIn("zz-example-repo", err)
        argv[1] = "o/r"
        self.assertEqual(0, run(argv, rec, names=["zz-example-repo"])[0])

    def test_the_comment_names_agent_role_commit_files_and_result(self):
        body = la.build_comment("builder-1", "builder", "abc1234", 4, "tests pass")
        for part in ("Agent: builder-1", "Role: builder", "Commit: abc1234",
                     "Files changed: 4", "Result: tests pass"):
            self.assertIn(part, body)

    def test_posting_calls_the_issue_comments_endpoint(self):
        rec = Recorder()
        code, out, _ = run(ARGS, rec)
        self.assertEqual(0, code)
        self.assertEqual("repos/o/r/issues/53/comments", rec.calls[0][0])
        self.assertTrue(any(a.startswith("body=Agent action") for a in rec.calls[0]))
        self.assertIn("o/r#53", out)

    def test_dry_run_prints_the_comment_and_calls_nothing(self):
        rec = Recorder()
        code, out, _ = run(ARGS + ["--dry-run"], rec)
        self.assertEqual(0, code)
        self.assertEqual([], rec.calls)
        self.assertIn("- Role: builder", out)

    def test_a_failed_post_exits_one_and_says_so(self):
        code, _, err = run(ARGS, Recorder(returncode=1, stderr="HTTP 404"))
        self.assertEqual(1, code)
        self.assertIn("not posted", err)
        self.assertIn("HTTP 404", err)

    def test_the_repo_comes_from_the_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "c.json"
            cfg.write_text(json.dumps({"repoOwner": "own", "repoName": "name"}))
            argv = [a for a in ARGS if a not in ("--repo", "o/r")] + ["--config", str(cfg)]
            rec = Recorder()
            self.assertEqual(0, run(argv, rec)[0])
            self.assertEqual("repos/own/name/issues/53/comments", rec.calls[0][0])

    def test_bad_input_exits_two_and_posts_nothing(self):
        rec = Recorder()
        bad_commit = [a if a != "abc1234" else "not-a-hash" for a in ARGS]
        no_repo = [a for a in ARGS if a not in ("--repo", "o/r")]
        for argv in (bad_commit, no_repo):
            with self.subTest(argv=argv):
                self.assertEqual(2, run(argv, rec)[0])
        self.assertEqual([], rec.calls)

    def test_an_unknown_role_is_refused(self):
        with self.assertRaises(SystemExit):
            la.parse_args([a if a != "builder" else "lead" for a in ARGS])

    def test_agent_from_commit_takes_the_commit_author(self):
        pre = ["--repo", "o/r", "--story", "5", "--role", "builder", "--commit", "abc1234",
               "--files", "1", "--result", "ok", "--agent-from-commit", "--dry-run"]
        out = io.StringIO()
        self.assertEqual(0, la.main(pre, out=out, git=lambda commit: "Dana"))
        self.assertIn("- Agent: Dana", out.getvalue())
        self.assertEqual(2, la.main(pre, out=out, err=io.StringIO(), git=lambda commit: ""))
        self.assertEqual(2, la.main(pre + ["--agent", "x"], out=out, err=io.StringIO(), git=lambda c: "D"))

    def test_a_claim_comment_names_the_session_and_the_time(self):
        rec = Recorder()
        base = ["--repo", "o/r", "--story", "9", "--agent", "sess-a", "--role", "claim"]
        self.assertEqual(0, run(base, rec)[0])
        body = rec.calls[0][2]
        self.assertRegex(body, r"^body=Claim\n- Session: sess-a\n- Time: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        with self.assertRaises(SystemExit):
            run(["--repo", "o/r", "--story", "9", "--role", "claim"], rec)

    def test_claim_status_reads_the_comments(self):
        now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)

        def status(*bodies, at=now):
            lines = "\n".join(json.dumps({"body": b}) for b in bodies)
            return la.claim_status("o/r", 9, Recorder(stdout=lines), now=at)

        claim = la.build_claim("sess-a", datetime(2026, 11, 17, 11, 0, tzinfo=timezone.utc))
        self.assertEqual("claimed by sess-a at 2026-11-17T11:00:00Z", status("hello", claim))
        later = datetime(2026, 11, 17, 13, 1, tzinfo=timezone.utc)
        self.assertEqual("free", status(claim, at=later))
        self.assertEqual("free", status("hello"))
        self.assertEqual("free", status("Claim\n- Session: sess-a\n- Time: 2026-13-45T99:00:00Z"))
        built = la.build_comment("sess-a", "builder", "abc1234", 2, "ok")
        self.assertEqual("free", status(claim, built))
        code, out, _ = run(["--repo", "o/r", "--story", "9", "--check-claim"], Recorder(stdout=""))
        self.assertEqual((0, "free\n"), (code, out))
        self.assertEqual(1, run(["--repo", "o/r", "--story", "9", "--check-claim"], Recorder(returncode=1))[0])
