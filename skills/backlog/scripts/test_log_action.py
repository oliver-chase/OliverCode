"""Test the action logger with an injected gh runner. No network and no gh.
Run: python3 -m unittest discover -p "test_*.py"   (from this folder)
"""
import io
import json
import subprocess
import tempfile
import unittest
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


def run(argv, runner):
    out, err = io.StringIO(), io.StringIO()
    code = la.main(argv, runner=runner, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


class LogAction(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
