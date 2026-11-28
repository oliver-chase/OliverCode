"""The agent loop: scripts/lib/agent_loop.py, driven by a scripted Claude Code and a scripted validation."""

import json
import os
import shutil
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # so `-m unittest tests.test_agent_loop` finds _support
from _support import REPO_ROOT, git, scratch_repo, temp_dir  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import agent_loop, cmd_drain, model  # noqa: E402


def reply(text="done", code=0, tokens=10, session_id="c1"):
    return {"code": code, "text": text, "tokens": tokens, "session_id": session_id}


class Scripted:
    """A Claude Code that returns its replies in order and keeps the prompts and resume ids it was given."""

    def __init__(self, *replies):
        self.replies, self.prompts, self.resumes, self.models = list(replies), [], [], []

    def __call__(self, prompt, cwd, **kw):
        self.prompts.append(prompt)
        self.resumes.append(kw.get("resume"))
        self.models.append(kw.get("model"))
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestValidateTimeout(unittest.TestCase):
    """#877: a validation that outruns its limit is a failed result, never an exception out of the loop."""

    def test_a_timed_out_validation_returns_a_failed_result(self):
        repo = temp_dir(self)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "validate.sh").write_text("exit 0\n")
        with mock.patch.object(agent_loop.subprocess, "run", side_effect=agent_loop.subprocess.TimeoutExpired("x", 1)):
            passed, tail = agent_loop.validate(repo)
        self.assertFalse(passed)
        self.assertIn("ran past", tail)


class TestValidateOnce(unittest.TestCase):
    """#1290: the runner's pass is recorded so land never repeats it, and every story runs the repo's --quick validation when it has one."""

    def setUp(self):
        self.repo = temp_dir(self)
        (self.repo / "scripts").mkdir()
        self.script = self.repo / "scripts" / "validate.sh"
        self.script.write_text("exit 0\n")

    def argv(self, code=0):
        ran = agent_loop.subprocess.CompletedProcess([], code, "ok", "")
        with mock.patch.object(agent_loop.subprocess, "run", return_value=ran) as run, mock.patch.object(agent_loop.validated, "record") as record:
            agent_loop.validate(self.repo)
        return run.call_args.args[0], record

    def test_a_pass_is_recorded_for_the_worktree_and_a_failure_is_not(self):
        self.assertEqual(1, self.argv()[1].call_count)
        self.assertEqual(0, self.argv(code=1)[1].call_count)

    def test_the_repo_validation_runs_directly_with_no_queue_in_front(self):
        self.assertEqual(["bash", "scripts/validate.sh"], self.argv()[0][:2])
        self.assertNotIn("queue", self.argv()[0])

    def test_a_timeout_exit_and_a_runner_timeout_both_report_the_timed_out_code(self):
        """#1436: exit 124 from the gates and a runner timeout are the same code, and neither records a pass."""
        ran = agent_loop.subprocess.CompletedProcess([], 124, "", "gate stopped")
        with mock.patch.object(agent_loop.subprocess, "run", return_value=ran), mock.patch.object(agent_loop.validated, "record") as record:
            self.assertEqual(agent_loop.TIMED_OUT, agent_loop.validate_code(self.repo)[0])
        with mock.patch.object(agent_loop.subprocess, "run", side_effect=agent_loop.subprocess.TimeoutExpired("x", 1)):
            self.assertEqual(agent_loop.TIMED_OUT, agent_loop.validate_code(self.repo)[0])
        record.assert_not_called()

    def test_every_story_validates_whatever_its_review(self):
        for mode in ("none", "full"):
            with self.subTest(mode=mode), mock.patch.object(agent_loop, "validate", return_value=(False, "bad")) as check:
                agent_loop.run_loop("do it", self.repo, "s1", run=Scripted(reply("built"), model.ModelError("stop")), say=lambda *_: None, review_mode=mode)
            check.assert_called_once_with(str(self.repo))


class TestValidationCommand(unittest.TestCase):
    """#1012: the repo's own validation runs, whatever it is called."""

    def test_an_npm_script_stands_in_for_validate_sh(self):
        repo = temp_dir(self)
        self.assertIsNone(agent_loop.validation_command(repo))
        (repo / "package.json").write_text('{"scripts": {"check": "true"}}')
        self.assertEqual(["npm", "run", "check"], agent_loop.validation_command(repo))
        (repo / "package.json").write_text('{"scripts": {"check": "true", "verify": "true"}}')
        (repo / "CLAUDE.md").write_text("Before committing run `npm run verify`.")
        self.assertEqual(["npm", "run", "verify"], agent_loop.validation_command(repo))


class TestRunLogRounds(unittest.TestCase):
    """What a headless run costs (docs/SETUP.md), #878: one JSON line per round under the OliverCode home folder."""

    def test_each_round_appends_one_line_with_story_round_model_tokens_and_cost(self):
        home, repo = temp_dir(self), temp_dir(self)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "validate.sh").write_text("exit 0\n")
        usage = {"input": 3, "output": 4, "cache_read": 100, "cache_write": 50}
        replies = Scripted({**reply("one"), "usage": usage, "cost_usd": 0.5}, {**reply("two"), "usage": usage, "cost_usd": None}, reply("PASS"))
        checks = iter([(False, "bad"), (True, "")])
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            agent_loop.run_loop("do it", repo, "story-878", run=replies, check=lambda cwd: next(checks), say=lambda *_: None, model_name="sonnet")
        rows = [json.loads(line) for line in (home / "run-log.jsonl").read_text().splitlines()]
        self.assertEqual([1, 2, 1, None], [r.get("round") for r in rows])  # the reader's own round, then its verdict row
        self.assertEqual(("story-878", "sonnet", 3, 4, 100, 50, 0.5), tuple(rows[0][k] for k in ("story", "model", "input", "output", "cache_read", "cache_write", "cost_usd")))
        self.assertIsNone(rows[1]["cost_usd"])

    def test_a_log_that_cannot_be_written_never_stops_the_loop(self):
        repo = temp_dir(self)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "validate.sh").write_text("exit 0\n")
        with mock.patch.object(agent_loop.failure_log, "home", side_effect=OSError("read-only")):
            out = agent_loop.run_loop("do it", repo, "s", run=Scripted(reply(), reply("PASS")), check=lambda cwd: (True, ""), say=lambda *_: None)
        self.assertTrue(out["done"])


class TestExitOne(unittest.TestCase):
    """#877: a session that stops on the turn cap or the timeout is resumed once, and every non-zero exit records the CLI's own stop reason and stderr."""

    def setUp(self):
        self.repo, self.home = temp_dir(self), temp_dir(self)
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / "validate.sh").write_text("exit 0\n")
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def loop(self, run, **kw):
        return agent_loop.run_loop("do it", self.repo, "story-1", run=run, check=lambda cwd: (True, ""), say=lambda *_: None, model_name="haiku", **kw)

    def rows(self):  # the builder's rounds only, since the reader writes its own rows
        return [r for r in (json.loads(l) for l in (self.home / "run-log.jsonl").read_text().splitlines()) if "round" in r and not r["story"].endswith("-review")]

    def test_the_turn_cap_resumes_the_same_session_once_and_logs_both_calls(self):
        run = Scripted({**reply("", code=1, session_id="sess"), "stop": "max_turns", "stderr": ""}, reply("committed", session_id="sess"), reply("PASS"))
        out = self.loop(run)
        self.assertTrue(out["done"])
        self.assertEqual(["", "sess"], [r or "" for r in run.resumes[:2]])  # the builder's two calls, then the reader's
        self.assertIn("Continue from where you left off", run.prompts[1])
        rows = self.rows()
        self.assertEqual(("max_turns", False, ""), (rows[0]["stop"], rows[0]["resumed"], rows[1]["stop"]))
        self.assertTrue(rows[1]["resumed"])

    def test_a_second_turn_cap_ends_the_round_and_the_reason_names_the_cause(self):
        capped = {**reply("", code=1, session_id="sess"), "stop": "max_turns", "stderr": "boom"}
        run = Scripted(capped, capped)  # the reader never runs, since the story never passed validation
        out = self.loop(run)
        self.assertFalse(out["done"])
        self.assertEqual(2, len(run.prompts))
        self.assertIn("stop reason max_turns after one resume", out["reason"])
        self.assertIn("stderr: boom", out["reason"])

    def test_a_timeout_resumes_the_session_the_run_started(self):
        run = Scripted(model.ModelTimeout("claude -p ran past 900 seconds and was stopped.", "sid-9"), reply("committed", session_id="sid-9"), reply("PASS"))
        out = self.loop(run)
        self.assertTrue(out["done"])
        self.assertEqual(["", "sid-9"], [r or "" for r in run.resumes[:2]])  # the builder's two calls, then the reader's
        self.assertEqual("timeout", self.rows()[0]["stop"])

    def test_a_second_timeout_gives_up(self):
        run = Scripted(model.ModelTimeout("slow", "sid-9"), model.ModelTimeout("slow", "sid-9"))
        out = self.loop(run)
        self.assertFalse(out["done"])
        self.assertIn("resumed once", out["reason"])

    def test_any_other_exit_is_not_resumed_and_keeps_its_stop_reason_and_stderr(self):
        run = Scripted({**reply("", code=1), "stop": "error_during_execution", "stderr": "auth expired"})
        out = self.loop(run)
        self.assertEqual(1, len(run.prompts))
        self.assertEqual("claude exited 1 in round 1, stop reason error_during_execution. stderr: auth expired", out["reason"])
        self.assertEqual(("error_during_execution", "auth expired"), (self.rows()[0]["stop"], self.rows()[0]["stderr_tail"]))

    def test_a_usage_limit_error_is_not_resumed_and_is_flagged(self):  # #1299
        run = Scripted({**reply("Claude AI usage limit reached|1700000000", code=1), "stop": "", "stderr": ""})
        out = self.loop(run)
        self.assertEqual((1, False, True), (len(run.prompts), out["done"], out["usage_limit"]))
        self.assertIn("usage limit", out["reason"])

    def test_another_error_is_not_flagged_as_the_usage_limit(self):  # #1299
        out = self.loop(Scripted({**reply("", code=1), "stop": "error_during_execution", "stderr": "auth expired"}))
        self.assertNotIn("usage_limit", out)


class TestStoryLines(unittest.TestCase):
    """#1552: with several stories building at once, each round and review line says when it was written and which story it is."""

    def setUp(self):
        self.repo = temp_dir(self)
        scratch_repo(self.repo, branch="main")
        (self.repo / "scripts").mkdir(exist_ok=True)
        (self.repo / "scripts" / "validate.sh").write_text("exit 0\n")
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(temp_dir(self))})
        patcher.start()
        self.addCleanup(patcher.stop)

    def said(self, session):
        """Every line of a build that fails validation once, passes and is read, with one reader attempt that says nothing."""
        lines, checks = [], iter([(False, "bad"), (True, "")])
        run = Scripted(reply("built\nin two lines"), reply("fixed"), reply(""), reply("PASS"))
        agent_loop.run_loop("do it", self.repo, session, run=run, check=lambda cwd: next(checks), say=lines.append)
        return "\n".join(lines).splitlines()

    def test_every_line_of_a_round_or_a_review_starts_with_the_time_and_its_story(self):
        for n in (7, 8):
            lines = self.said(f"story-{n}")
            for line in lines:
                self.assertRegex(line, rf"^\d\d:\d\d:\d\d #{n} ")
            self.assertEqual(["Round 1: built", "in two lines", "Round 1: validation failed.", "Round 2: fixed",
                              "Review: no verdict on attempt 1. The reader replied with nothing.", "Review: pass."], [line.split(" ", 2)[2] for line in lines])

    def test_a_session_that_is_no_storys_speaks_with_no_prefix(self):
        self.assertEqual("Round 1: built", self.said("bug-intake")[0])


class TestRunLog(unittest.TestCase):
    """#878, #909, #976: a run-log line holds the CLI's usage, cost and stop reason and the start size, which is the first call's context and never the session's total."""

    def setUp(self):
        self.repo, self.home = temp_dir(self), temp_dir(self)
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / "validate.sh").write_text("exit 0\n")
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        no_transcript = mock.patch.object(agent_loop, "start_size", return_value=None)
        no_transcript.start()
        self.addCleanup(no_transcript.stop)

    def rows(self):  # the builder's rounds only, since the reader writes its own rows
        return [r for r in (json.loads(line) for line in (self.home / "run-log.jsonl").read_text().splitlines()) if "round" in r and not r["story"].endswith("-review")]

    def test_the_first_round_logs_the_first_call_size_and_never_the_session_total(self):
        said = []
        usage = {"input": 3, "output": 4, "cache_read": 0, "cache_write": 99_000}
        with mock.patch.object(agent_loop, "start_size", return_value=31_000) as start:
            out = agent_loop.run_loop("do it", self.repo, "story-1", run=Scripted({**reply(), "usage": usage}, reply("PASS")), check=lambda cwd: (True, ""), say=said.append)
        row = self.rows()[0]
        self.assertEqual(("c1",), start.call_args[0])
        self.assertEqual((31_000, 99_000, 3, 4), (row["start_tokens"], row["cache_write"], row["input"], row["output"]))
        self.assertTrue({"cost_usd", "stop"} <= set(row))
        self.assertFalse({"start_source", "start_over_limit", "calls_before_first_edit"} & set(row))
        self.assertNotIn("start_tokens", out)
        self.assertFalse(any("limit" in line for line in said))

    def test_a_first_round_with_no_transcript_logs_no_start_size_rather_than_a_guess(self):
        agent_loop.run_loop("do it", self.repo, "story-1", run=Scripted({**reply(), "usage": {"cache_write": 99_000}}, reply("PASS")), check=lambda cwd: (True, ""), say=lambda line: None)
        self.assertNotIn("start_tokens", self.rows()[0])

    def test_a_later_round_logs_no_start_size(self):
        run = Scripted({**reply(), "usage": {"cache_write": 900}}, {**reply(), "usage": {"cache_write": 50}}, reply("PASS"))
        with mock.patch.object(agent_loop, "start_size", return_value=900):
            agent_loop.run_loop("do it", self.repo, "story-1", run=run, check=lambda cwd, results=iter([(False, "x"), (True, "")]): next(results), say=lambda line: None)
        self.assertEqual([900, None], [r.get("start_tokens") for r in self.rows()])

    def test_the_run_log_names_which_setup_each_start_ran(self):
        """#911: the two start sizes are told apart by the setup that ran, current or project."""
        with mock.patch.object(agent_loop, "start_size", return_value=900):
            agent_loop.run_loop("do it", self.repo, "story-1", run=Scripted({**reply(), "settings": "project", "usage": {"cache_write": 900}}, reply("PASS")),
                                check=lambda cwd: (True, ""), say=lambda line: None)
        row = self.rows()[0]
        self.assertEqual(("project", 900), (row["settings"], row["start_tokens"]))


class TestStartSize(unittest.TestCase):
    """#976: the start size is the context of the session's first call, read from the first assistant line of its transcript and nothing after it."""

    def setUp(self):
        self.projects = temp_dir(self)
        (self.projects / "-repo").mkdir()
        self.path = self.projects / "-repo" / "s9.jsonl"

    def write(self, *lines):
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_the_first_assistant_line_gives_the_context_and_later_calls_are_ignored(self):
        self.write(json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}),
                   json.dumps({"type": "assistant", "message": {"role": "assistant", "usage": {"input_tokens": 2, "cache_read_input_tokens": 30_000, "cache_creation_input_tokens": 1_000, "output_tokens": 9}}}),
                   json.dumps({"type": "assistant", "message": {"role": "assistant", "usage": {"input_tokens": 5, "cache_read_input_tokens": 60_000}}}),
                   "not json at all")
        self.assertEqual(31_002, agent_loop.start_size("s9", self.projects))

    def test_a_transcript_with_no_assistant_usage_gives_no_start_size(self):
        self.write(json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}))
        self.assertIsNone(agent_loop.start_size("s9", self.projects))

    def test_a_session_with_no_transcript_gives_no_start_size(self):
        self.assertIsNone(agent_loop.start_size("missing", self.projects))
        self.assertIsNone(agent_loop.start_size("", self.projects))


class TestLoop(unittest.TestCase):
    def setUp(self):
        self.repo = temp_dir(self)
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / "validate.sh").write_text("exit 0\n")
        self.home = temp_dir(self)  # the run log goes here, never to the owner's real home
        env = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)

    def loop(self, run, results, **kw):
        checks = iter(results)
        return agent_loop.run_loop("do it", self.repo, "s1", run=run, check=lambda cwd: next(checks), say=lambda *_: None, **kw)

    def test_each_changed_failure_starts_another_fix_session_on_the_same_worktree(self):  # #1513
        seen, replies = [], [reply() for _ in range(5)]

        def run(prompt, cwd, **kw):
            seen.append(cwd)
            return replies.pop(0)

        out = self.loop(run, [(False, "a"), (False, "b"), (False, "a"), (False, "c"), (True, "")], review_mode="none")
        self.assertEqual((True, 5, [str(self.repo)] * 5), (out["done"], out["rounds"], seen))

    def repo_run(self, *effects):
        """A git worktree and a Claude Code whose rounds each run one effect on it, then reply."""
        scratch_repo(self.repo)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "base")
        steps, calls = list(effects), []

        def run(prompt, cwd, **kw):
            calls.append(kw["session"])
            if kw["session"].endswith("-review"):
                return reply("scripts/a.py: no test")
            steps.pop(0)()
            return reply(f"reply {len(calls)}")

        return run, calls

    def nothing(self):
        pass

    def test_two_rounds_in_a_row_that_change_nothing_end_the_story_before_any_check(self):  # #1531
        (self.repo / "half.py").write_text("x = 1\n")  # uncommitted work from an earlier build, left as it is
        run, calls = self.repo_run(self.nothing, self.nothing)
        (self.repo / "half.py").write_text("x = 2\n")
        checks = []
        out = agent_loop.run_loop("do it", self.repo, "s1", run=run, check=lambda cwd: checks.append(cwd) or (False, "a"), say=lambda *_: None)
        self.assertEqual((False, True, True, 2, "reply 2"), (out["done"], out["stuck"], out["idle"], out["rounds"], out["summary"]))
        self.assertIn("rounds 1 and 2 changed nothing", out["reason"])
        self.assertEqual((["s1", "s1"], 1), (calls, len(checks)))  # no third round, and nothing checks the second

    def test_no_reader_is_called_after_the_second_round_that_changed_nothing(self):  # #1531
        run, calls = self.repo_run(self.nothing, self.nothing)
        out = self.loop(run, [(True, "")])
        self.assertTrue(out["idle"])
        self.assertEqual(["s1", "s1-review", "s1"], calls)

    def test_a_round_with_no_commit_on_the_branch_starts_no_reader_and_returns_to_the_drain(self):  # #1547
        run, calls = self.repo_run(lambda: (self.repo / "half.py").write_text("x = 1\n"))  # changed and never committed
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        out = self.loop(run, [(True, "")])
        self.assertEqual((True, 1, ["s1"]), (out["done"], out["rounds"], calls))  # done sends it to the drain's landing step
        self.assertIn("no commit on the branch", out["reason"])

    def test_a_round_with_a_commit_on_the_branch_starts_the_reader(self):  # #1547
        run, calls = self.repo_run(lambda: git(self.repo, "commit", "-qm", "work", "--allow-empty"))  # an empty diff, yet a commit that could land
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        with mock.patch.object(agent_loop, "review", return_value={"verdict": "pass", "text": "PASS"}) as read:
            out = self.loop(run, [(True, "")])
        self.assertEqual((True, 1, ["s1"]), (out["done"], read.call_count, calls))

    def gated(self, refused):
        """One committed round behind a gate that answers `refused`. Returns (outcome, the stubbed reader, sessions run)."""
        run, calls = self.repo_run(lambda: git(self.repo, "commit", "-qm", "work", "--allow-empty"))
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        with mock.patch.object(agent_loop, "review", return_value={"verdict": "pass", "text": "PASS"}) as read:
            out = self.loop(run, [(True, "")], gate=lambda cwd: refused)
        return out, read, calls

    def test_a_refusal_from_the_gate_ends_the_loop_with_no_reader(self):  # #1551
        out, read, calls = self.gated("Refused: weak.")
        self.assertEqual((False, "Refused: weak.", 0, ["s1"]), (out["done"], out["refused"], read.call_count, calls))

    def test_a_commit_the_gate_passes_starts_the_reader(self):  # #1551
        out, read, calls = self.gated("")
        self.assertEqual((True, 1, ["s1"]), (out["done"], read.call_count, calls))

    def test_a_round_that_commits_edits_or_adds_a_file_is_progress_and_resets_the_count(self):  # #1531
        def commit():
            git(self.repo, "commit", "-qm", "more", "--allow-empty")

        def add():
            (self.repo / "new.py").write_text("x = 1\n")

        def edit_untracked():
            (self.repo / "new.py").write_text("x = 2\n")

        def edit_tracked():
            (self.repo / "scripts" / "validate.sh").write_text("exit 1\n")

        run, calls = self.repo_run(self.nothing, commit, self.nothing, add, self.nothing, edit_untracked, self.nothing, edit_tracked, self.nothing, self.nothing)
        out = self.loop(run, [(False, str(i)) for i in "abcdefghi"], review_mode="none")
        self.assertEqual((True, 10, 10), (out["idle"], out["rounds"], len(calls)))
        self.assertIn("rounds 9 and 10 changed nothing", out["reason"])

    def test_the_same_failing_test_names_twice_in_a_row_stop_the_builder_whatever_the_timestamps_and_line_order(self):  # #1513
        first = "2026-11-27T01:00:00Z start\nFAIL: test_b (m.T.test_b)\n  line 4\nERROR: test_a (m.T.test_a)\nRan 2 tests in 0.512s"
        second = "ERROR: test_a (m.T.test_a)\n  line 9, another message\nFAIL: test_b (m.T.test_b)\nRan 3 tests in 12.1s"
        out = self.loop(Scripted(reply(), reply()), [(False, first), (False, second)])
        self.assertEqual((False, True, 2), (out["done"], out["stuck"], out["rounds"]))
        self.assertIn("rounds 1 and 2 failed validation the same way", out["reason"])
        self.assertIn("test_a (m.T.test_a); test_b (m.T.test_b)", out["reason"])
        self.assertNotIn("capped", out)

    def test_output_that_names_no_test_is_compared_by_its_lines_without_timestamps_order_or_gate_progress(self):  # #1513
        first = (f"{agent_loop.PROGRESS}'refs' passed in 3s ===\n10:01:02 BLOCKED: broken link in docs/a.md\n"
                 "log at /var/folders/ab/T/tmp1x/out after 4.2s\nvalidate: gates took 9s in all, load 3.1")
        second = (f"log at /var/folders/cd/T/tmp9z/out after 11s\n2026-11-27 10:09:59 BLOCKED: broken link in docs/a.md\n"
                  f"{agent_loop.PROGRESS}'docs' started (2 running, 1 waiting) ===")
        out = self.loop(Scripted(reply(), reply()), [(False, first), (False, second)])
        self.assertTrue(out["stuck"])
        self.assertIn("BLOCKED: broken link in docs/a.md", out["reason"])

    def test_a_different_test_name_or_a_different_line_is_a_changed_failure(self):  # #1513
        for first, second in (("FAIL: test_a (m.T.test_a)", "FAIL: test_b (m.T.test_b)"), ("FAILED t.py::test_a - boom", "FAILED t.py::test_b - boom"),
                              ("line 4: boom", "line 9: boom")):
            with self.subTest(first=first):
                self.assertNotEqual(agent_loop.failure_key(first), agent_loop.failure_key(second))
        self.assertEqual(agent_loop.failure_key("FAILED t.py::test_a - boom"), agent_loop.failure_key("FAILED t.py::test_a - another"))

    def test_a_failing_test_named_above_the_tail_still_counts_as_a_change(self):  # #1513
        noise = "\n" + "x\n" * agent_loop.TAIL_LINES
        z = "FAIL: test_z (m.T.test_z)" + noise
        first, second = agent_loop.gate_tail("FAIL: test_a (m.T.test_a)\n" + z), agent_loop.gate_tail(z)
        self.assertEqual(first, second)  # the fix session sees the same tail both times
        out = self.loop(Scripted(reply(), reply(), reply()), [(False, first), (False, second), (True, "")], review_mode="none")
        self.assertEqual((True, 3), (out["done"], out["rounds"]))

    def test_a_last_line_longer_than_the_tail_is_compared_whole(self):  # #1513
        long = "x" * agent_loop.TAIL_CHARS
        first, second = agent_loop.gate_tail("boom " + long), agent_loop.gate_tail("bang " + long)
        self.assertNotEqual(first.key, second.key)
        self.assertTrue(first.key)

    def test_lines_cut_by_length_or_shifted_by_gate_progress_compare_the_same(self):  # #1513
        body = "\n".join(f"line {i} " + "x" * 200 for i in range(agent_loop.TAIL_LINES))
        progress = f"\n{agent_loop.PROGRESS}'docs' passed in 3s ==="
        self.assertEqual(agent_loop.gate_tail(body + "\nafter 1s").key, agent_loop.gate_tail(body + "\nafter 12.5s" + progress * 3).key)

    def test_a_story_whose_failures_keep_changing_stops_at_the_backstop_and_names_it(self):  # #1513
        self.assertEqual(3 * agent_loop.COST_CEILING["M"], agent_loop.BACKSTOP)
        self.addCleanup(agent_loop.SPEND.pop, "s1", None)
        agent_loop.SPEND["s1"] = 10.90  # carried from earlier drains
        costly = {**reply(), "cost_usd": 0.60}
        agent = Scripted(costly, costly, costly)
        out = self.loop(agent, [(False, "a"), (False, "b")])
        self.assertEqual((True, 2), (out["capped"], len(agent.prompts)))  # $11.50 is under it, $12.10 has reached it
        self.assertEqual("Spend $12.10 (API-price equivalent, not billed) reached the backstop of $12.00, so no further round starts.", out["reason"])  # #1527
        again = self.loop(agent, [])
        self.assertEqual((True, 0, 2), (again["capped"], again["rounds"], len(agent.prompts)))

    def test_a_stop_under_the_backstop_names_no_backstop(self):  # #1527
        self.addCleanup(agent_loop.SPEND.pop, "s1", None)
        out = self.loop(Scripted({**reply(), "cost_usd": 0.60}, reply()), [(False, "a"), (False, "a")])
        self.assertTrue(out["stuck"])
        self.assertNotIn("backstop", out["reason"])
        self.assertNotIn("API-price", out["reason"])

    def test_the_board_size_sets_no_ceiling_of_its_own(self):  # #1513
        for table in (agent_loop.STORY_SIZE, agent_loop.SPEND):
            self.addCleanup(table.pop, "s1", None)
        agent_loop.STORY_SIZE["s1"], agent_loop.SPEND["s1"] = "XS", 4.60
        out = self.loop(Scripted(reply()), [(True, "")], review_mode="none")
        self.assertTrue(out["done"])

    def test_the_model_follows_the_size_and_only_a_design_label_takes_the_largest(self):
        self.assertEqual(["haiku", "haiku", "sonnet", "sonnet", "opus"],
                         [agent_loop.route(s)[0] for s in ("XS", "S", "M", "L")] + [agent_loop.route("M", [{"name": "design"}])[0]])

    def test_a_small_story_touching_landing_claims_gates_or_hooks_or_a_p0_starts_on_the_middle_model(self):
        for files, priority in ((["scripts/lib/cmd_land.py"], "P2"), (["scripts/lib/cmd_drain.py"], "P2"), (["scripts/lib/agent_loop.py", "docs/RULES.md"], "P2"),
                                (["scripts/lib/log_action.py"], "P2"), (["skills/backlog/scripts/complete_story.py"], "P2"), (["core/hooks/guard.py"], "P2"),
                                (["scripts/hooks/gh_guard.py"], "P2"), ([], "P0")):
            with self.subTest(files=files, priority=priority):
                self.assertEqual("sonnet", agent_loop.route("S", files=files, priority=priority)[0])

    def test_a_small_story_touching_only_docs_tests_or_one_command_starts_on_the_smallest_model(self):
        self.assertEqual("haiku", agent_loop.route("XS", files=["docs/RULES.md", "tests/test_cmd_status.py", "scripts/lib/cmd_status.py"], priority="P2")[0])

    def test_only_medium_or_larger_design_p0_or_risky_stories_get_a_fresh_reader(self):
        self.assertEqual("none", agent_loop.review_mode("S", files=["docs/RULES.md"], priority="P2"))
        self.assertEqual("full", agent_loop.review_mode("S", files=["scripts/hooks/gh_guard.py"], priority="P2"))
        self.assertEqual("full", agent_loop.review_mode("S", priority="P0"))
        self.assertEqual("full", agent_loop.review_mode("M", files=["docs/RULES.md"], priority="P2"))
        self.assertEqual("full", agent_loop.review_mode("S", labels=[{"name": "design"}], priority="P2"))

    def test_the_route_names_the_rule_that_chose_the_model(self):
        self.assertEqual(("sonnet", "its Files area touches scripts/lib/agent_loop.py"), agent_loop.route("XS", files=["scripts/lib/agent_loop.py"]))
        self.assertEqual(("sonnet", "priority P0"), agent_loop.route("S", priority="P0"))
        self.assertEqual(("opus", "labeled design"), agent_loop.route("M", [{"name": "design"}]))
        self.assertEqual(("haiku", "size S with no risky path or P0 priority"), agent_loop.route("S"))

    def test_the_run_log_records_the_rule_that_chose_the_builder(self):
        run = Scripted(reply("built"), reply("PASS"))
        self.loop(run, [(True, "")], model_name="sonnet", why="priority P0")
        rows = [json.loads(l) for l in (self.home / "run-log.jsonl").read_text().splitlines()]
        self.assertEqual(["priority P0"], [r["route"] for r in rows if r.get("story") == "s1" and "route" in r])

    def test_the_review_row_carries_its_time_in_the_stage_row_format(self):  # #1377
        for verdict, text in (("pass", "PASS"), ("findings", "a.py: wrong")):
            with self.subTest(verdict=verdict):
                agent_loop.review("the story", self.repo, "s1", "gate", run=Scripted(reply(text)), say=lambda *_: None)
        rows = [json.loads(l) for l in (self.home / "run-log.jsonl").read_text().splitlines()]
        reviews = [r for r in rows if "review" in r]
        self.assertEqual(2, len(reviews))
        for r in reviews:
            self.assertRegex(r["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_a_small_story_moves_up_one_level_after_a_second_failed_validation(self):
        run = Scripted(reply(), reply(), reply(), reply("PASS"))
        out = self.loop(run, [(False, "a"), (False, "b"), (True, "")], model_name="haiku")
        self.assertTrue(out["done"])
        self.assertEqual(["haiku", "haiku", "sonnet", "sonnet"], run.models)  # three builder rounds, then the Sonnet reader

    def test_the_ladder_stops_at_the_largest_model(self):
        self.assertEqual(("sonnet", "opus", "opus"), (agent_loop.escalate("haiku", 2), agent_loop.escalate("sonnet", 2), agent_loop.escalate("opus", 5)))
        self.assertEqual("haiku", agent_loop.escalate("haiku", 1))

    def test_an_m_story_gets_one_fresh_reader_that_sees_the_story_the_diff_and_the_test_output(self):
        run = Scripted(reply("built"), reply("PASS"))
        with mock.patch.object(agent_loop, "branch_diff", return_value="THE-DIFF"), mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(temp_dir(self))}):
            out = self.loop(run, [(True, "all green")])
        self.assertTrue(out["done"])
        self.assertEqual(2, len(run.prompts))
        for text in ("do it", "THE-DIFF", "all green"):
            self.assertIn(text, run.prompts[1])
        self.assertEqual(["", ""], [r or "" for r in run.resumes])  # the reader resumes nothing

    def test_the_reader_logs_its_findings_on_the_story(self):
        home = temp_dir(self)
        run = Scripted(reply("built"), reply("scripts/a.py: no test"), reply("fixed"), reply("PASS"))
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            self.loop(run, [(True, ""), (True, "")])
        rows = [json.loads(l) for l in (home / "run-log.jsonl").read_text().splitlines()]
        self.assertEqual([("s1", "findings", "scripts/a.py: no test"), ("s1", "pass", "")], [(r["story"], r["review"], r["findings"]) for r in rows if "review" in r])

    def test_a_finding_sends_the_story_back_once_with_the_finding_and_the_reader_reads_again(self):
        run = Scripted(reply("built"), reply("scripts/a.py: no test"), reply("fixed"), reply("PASS"))
        with mock.patch.object(agent_loop, "branch_diff", return_value="THE-DIFF"):
            out = self.loop(run, [(True, ""), (True, "")])
        self.assertEqual((True, 2), (out["done"], out["rounds"]))
        self.assertEqual(4, len(run.prompts))
        for text in ("do it", "THE-DIFF", "scripts/a.py: no test"):
            self.assertIn(text, run.prompts[2])  # the fix session gets the story, the diff and the finding
        self.assertNotIn("held", out)
        self.assertEqual("", run.resumes[2])  # a new session, never the builder's resumed one (#1064)
        self.assertIn("one commit", run.prompts[2])

    def test_a_second_findings_verdict_holds_the_story_in_any_wording_and_the_comment_names_both(self):  # #1548
        for second in ("scripts/a.py: no test", "scripts/b.py: still wrong"):
            with self.subTest(second=second):
                run = Scripted(reply("built"), reply("scripts/a.py: no test"), reply("fixed"), reply(second))
                out = self.loop(run, [(True, ""), (True, "")])
                self.assertEqual((False, True, 2, 4), (out["done"], out["stuck"], out["rounds"], len(run.prompts)))  # no third fix session
                self.assertEqual((second, "scripts/a.py: no test"), (out["held"], out["earlier"]))
                self.assertIn("a second time, so nothing is pushed", out["reason"])
                comment = cmd_drain.held_comment(self.repo, out["held"], out["earlier"])
                self.assertIn("Earlier finding:\nscripts/a.py: no test", comment)
                self.assertEqual(second, comment.partition(cmd_drain.FINDING)[2])  # the next build reads back only the latest

    def test_a_second_findings_verdict_holds_the_story_after_a_failed_validation_between_them(self):  # #1548
        run = Scripted(reply("built"), reply("scripts/a.py: no test"), reply("fixed"), reply("fixed again"), reply("scripts/b.py: wrong"))
        out = self.loop(run, [(True, ""), (False, "gate"), (True, "")])
        self.assertEqual(("scripts/b.py: wrong", 3), (out["held"], out["rounds"]))

    def test_the_same_validation_failure_on_both_sides_of_a_finding_is_not_repeated_in_a_row(self):
        run = Scripted(reply("built"), reply("fixed"), reply("scripts/a.py: no test"), reply("fixed"), reply("fixed again"), reply("PASS"))
        out = self.loop(run, [(False, "gate"), (True, ""), (False, "gate"), (True, "")])
        self.assertEqual((True, 4), (out["done"], out["rounds"]))

    def test_a_finding_after_a_failed_validation_still_gets_one_fix_session(self):
        run = Scripted(reply("built"), reply("fixed"), reply("scripts/a.py: no test"), reply("fixed again"), reply("PASS"))
        out = self.loop(run, [(False, "gate"), (True, ""), (True, "")])
        self.assertEqual((True, 5), (out["done"], len(run.prompts)))
        self.assertIn("scripts/a.py: no test", run.prompts[3])

    def test_an_xs_story_on_any_path_gets_a_fresh_reader_before_it_lands(self):
        run = Scripted(reply("built"), reply("PASS"))
        out = self.loop(run, [(True, "")])
        self.assertEqual((True, 2), (out["done"], len(run.prompts)))

    def test_only_a_pass_verdict_passes(self):
        for text, verdict in (("PASS", "pass"), ("PASS, the diff does what the story says.", "pass"), ("PASSING concerns", "findings"),
                              ("PASS—the diff does what the story says.", "pass"), ("**PASS**—notes", "pass"),
                              ("Passing is not a verdict", "findings"), ("scripts/a.py: wrong", "findings")):
            with self.subTest(text=text):
                out = agent_loop.review("the story", self.repo, "s1", "gate", run=Scripted(reply(text)), say=lambda *_: None)
                self.assertEqual(verdict, out["verdict"])

    def test_a_pass_after_a_progress_note_passes_unless_the_reply_takes_it_back(self):  # #1477
        note = "Still reviewing: I've checked the callers and I'm about to give the verdict."
        for text, verdict in ((f"{note}\n\nPASS\n\n- notes", "pass"), (f"{note}\n**PASS**", "pass"), ("**PASS**", "pass"),
                              ("PASS\n\nI can't pass it because one scenario is unmet.", "findings"),
                              (f"{note}\n\nPASS\n\nOn reflection I can’t pass it because one scenario is unmet.", "findings"),
                              (f"{note}\n\nPASS is not the verdict here.", "findings"), (f"{note}\n\n- a.py: wrong\n\nPASS", "findings")):
            with self.subTest(text=text):
                out = agent_loop.review("the story", self.repo, "s1", "gate", run=Scripted(reply(text)), say=lambda *_: None)
                self.assertEqual(verdict, out["verdict"])

    def test_the_reader_briefs_ask_for_the_verdict_before_any_progress_note(self):  # #1477
        from lib import intake
        for text in (agent_loop.REVIEW_BRIEF, intake.BUG_BRIEF, agent_loop.READER_SYSTEM):
            self.assertIn("first line of your reply, with no progress note before it", text)

    def test_a_brief_swaps_the_question_and_skips_the_diff_it_does_not_name(self):
        run = Scripted(reply("BUG\nroot cause"))
        out = agent_loop.review("the failure", self.repo, "s1", "", run=run, say=lambda *_: None, brief="Read this: {task}{diff}{tail}")
        self.assertEqual("Read this: the failure", run.prompts[0])
        self.assertEqual("findings", out["verdict"])

    def test_a_reader_that_fails_once_is_asked_again_and_its_pass_lands_the_story(self):
        run = Scripted(reply("built"), model.ModelError("no reader"), reply("PASS"))
        out = self.loop(run, [(True, "")])
        self.assertEqual((True, 3), (out["done"], len(run.prompts)))

    def test_a_reader_that_gives_no_verdict_twice_holds_the_story_and_nothing_is_pushed(self):
        run = Scripted(reply("built"), reply(""), reply("PASS", code=1))
        out = self.loop(run, [(True, "")])
        self.assertEqual((False, 3), (out["done"], len(run.prompts)))
        self.assertIn("nothing is pushed", out["reason"])
        self.assertEqual("claude exited 1 in attempt 2.", out["reader_failed"])
        self.assertNotIn("held", out)

    def rows(self):
        return [json.loads(l) for l in (self.home / "run-log.jsonl").read_text().splitlines()]

    def test_a_reader_stopped_on_its_turn_cap_is_asked_again_with_twice_the_turns(self):  # #1489
        replies, turns = [{**reply("", code=1), "stop": "max_turns"}, reply("PASS")], []

        def run(prompt, cwd, **kw):
            turns.append(kw["max_turns"])
            return replies.pop(0)

        out = agent_loop.review("the story", self.repo, "s1", "gate", run=run, say=lambda *_: None)
        self.assertEqual("pass", out["verdict"])
        self.assertEqual([agent_loop.READER_TURNS, 2 * agent_loop.READER_TURNS], turns)

    def test_a_reader_that_failed_for_another_cause_is_asked_again_with_the_same_turns(self):  # #1489
        replies, turns = [{**reply("", code=1), "stop": "error_during_execution"}, reply("PASS")], []

        def run(prompt, cwd, **kw):
            turns.append(kw["max_turns"])
            return replies.pop(0)

        agent_loop.review("the story", self.repo, "s1", "gate", run=run, say=lambda *_: None)
        self.assertEqual([agent_loop.READER_TURNS] * 2, turns)

    def reader_turns(self, diff, *replies):
        """The turns each reader attempt got on `diff`."""
        replies, turns = list(replies), []

        def run(prompt, cwd, **kw):
            turns.append(kw["max_turns"])
            return replies.pop(0)

        with mock.patch.object(agent_loop, "branch_diff", return_value=diff):
            agent_loop.review("the story", self.repo, "s1", "gate", run=run, say=lambda *_: None)
        return turns

    def test_a_cut_diff_gets_twice_the_turns_on_the_first_attempt(self):  # #1550
        cut = agent_loop.cut_diff("y" * (agent_loop.DIFF_LIMIT + 1))
        self.assertEqual([2 * agent_loop.READER_TURNS], self.reader_turns(cut, reply("PASS")))

    def test_a_diff_within_the_limit_keeps_the_first_attempts_turns(self):  # #1550
        whole = agent_loop.cut_diff("y" * agent_loop.DIFF_LIMIT)
        self.assertEqual([agent_loop.READER_TURNS], self.reader_turns(whole, reply("PASS")))

    def test_a_cut_diff_stopped_on_the_turn_cap_doubles_the_turns_of_the_attempt_that_stopped(self):  # #1550
        cut = agent_loop.cut_diff("y" * (agent_loop.DIFF_LIMIT + 1))
        capped = {**reply("", code=1), "stop": "max_turns"}
        self.assertEqual([2 * agent_loop.READER_TURNS, 4 * agent_loop.READER_TURNS], self.reader_turns(cut, capped, reply("PASS")))

    def test_each_failed_reader_attempt_logs_its_stop_reason_stderr_and_cost_and_counts_against_no_ceiling(self):  # #1489
        self.addCleanup(agent_loop.SPEND.pop, "s1", None)
        agent_loop.SPEND.pop("s1", None)
        failed = {**reply("", code=1), "stop": "api_error", "stderr": "rate limited", "cost_usd": 0.4}
        out = agent_loop.review("the story", self.repo, "s1", "gate", run=Scripted(failed, model.ModelTimeout("too slow", "sid")), say=lambda *_: None)
        first, second = [r for r in self.rows() if r["story"] == "s1-review"]
        self.assertEqual((1, "api_error", "rate limited", 0.4), tuple(first[k] for k in ("round", "stop", "stderr_tail", "cost_usd")))
        self.assertEqual((2, "timeout", "too slow"), tuple(second[k] for k in ("round", "stop", "stderr_tail")))
        self.assertEqual(0.0, agent_loop.SPEND.get("s1", 0.0))
        self.assertEqual("too slow", out["text"])

    def test_the_failure_names_the_stop_reason(self):  # #1489
        capped = {**reply("", code=1), "stop": "max_turns", "stderr": "boom"}
        out = agent_loop.review("the story", self.repo, "s1", "gate", run=Scripted(capped, capped), say=lambda *_: None)
        self.assertEqual("claude exited 1 in attempt 2, stop reason max_turns. stderr: boom", out["text"])

    def test_a_build_the_reader_failed_on_steps_no_later_build_up(self):  # #1489
        self.loop(Scripted(reply(), reply(), reply(), reply(code=1), reply(code=1)), [(False, "a"), (False, "b"), (True, "")], model_name="haiku")
        self.assertEqual("haiku", agent_loop.restart_model("s1", "haiku"))

    def test_a_reader_failure_keeps_the_step_up_the_build_before_it_earned(self):  # #1489
        rows = [{"story": "story-7", "round": r} for r in (1, 2, 3, 1)] + [{"story": "story-7", "round": 1, "resumed": True}, {"story": "story-7", "review": "none"}]
        (self.home / "run-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.assertEqual("sonnet", agent_loop.restart_model("story-7", "haiku"))

    def test_a_diff_over_the_limit_is_cut_and_the_marker_names_each_file_the_reader_did_not_see(self):
        full = ("diff --git a/scripts/a.py b/scripts/a.py\n+ok\n" "diff --git a/scripts/b.py b/scripts/b.py\n+" + "y" * agent_loop.DIFF_LIMIT + "\n"
                "diff --git a/scripts/c.py b/scripts/c.py\n+z\n")
        cut = agent_loop.cut_diff(full)
        self.assertTrue(cut.startswith(full[:agent_loop.DIFF_LIMIT]))
        self.assertIn("The reader did not see these files in full: scripts/b.py, scripts/c.py.", cut)
        self.assertEqual(full[:agent_loop.DIFF_LIMIT], agent_loop.cut_diff(full[:agent_loop.DIFF_LIMIT]))

    def test_the_reader_is_never_weaker_than_the_builder_and_the_run_log_names_its_model(self):
        self.assertEqual(["sonnet", "sonnet", "opus"], [agent_loop.reader_for(m) for m in ("haiku", "sonnet", "opus")])
        run = Scripted(reply("built"), reply("PASS"))
        self.loop(run, [(True, "")], model_name="haiku")
        self.assertEqual(["haiku", "sonnet"], run.models)
        rows = [json.loads(l) for l in (self.home / "run-log.jsonl").read_text().splitlines()]
        self.assertEqual(["sonnet"], [r["model"] for r in rows if r.get("story") == "s1-review"])

    def test_the_reader_gets_its_own_system_prompt_and_no_builder_rules(self):
        seen = {}

        def run(prompt, cwd, **kw):
            seen.update(prompt=prompt, **kw)
            return reply("PASS")

        agent_loop.review("the story", self.repo, "s1", "gate", run=run, say=lambda *_: None)
        self.assertEqual(agent_loop.READER_SYSTEM, seen["system"])
        self.assertNotIn("never poll", seen["system"])
        self.assertNotIn("Commit by explicit path", seen["system"])
        self.assertNotIn("Builder rules", seen["prompt"])

    def test_the_reader_can_read_and_search_and_is_told_to_check_a_doubt_first(self):
        """#1079: a one-turn reader with no tool call held #1024 for a helper it could not look up."""
        seen = {}

        def run(prompt, cwd, **kw):
            seen.update(prompt=prompt, **kw)
            return reply("PASS")

        agent_loop.review("the story", self.repo, "s1", "gate", run=run, say=lambda *_: None)
        self.assertGreaterEqual(seen["max_turns"], 10)
        for tool in ("Read", "Grep", "Glob"):
            self.assertIn(tool, seen["allowed_tools"])
        self.assertNotIn("Edit", seen["allowed_tools"])
        self.assertNotIn("make no tool call", seen["system"] + seen["prompt"])
        self.assertIn("not a finding", seen["prompt"])

    def story_commit(self, text):
        """A story's one commit on a branch ahead of origin's default branch."""
        if not (self.repo / ".git").exists():
            scratch_repo(self.repo)
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-qm", "base")
            git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        (self.repo / "a.py").write_text(text)
        git(self.repo, "add", "a.py")
        git(self.repo, "commit", "-qm", "work")

    def read(self, *replies, story="s1"):
        """One call of the reader on the worktree: (its verdict, the readers it started)."""
        run = Scripted(*replies)
        out = agent_loop.review("the story", self.repo, story, "gate", run=run, say=lambda *_: None)
        return out["verdict"], len(run.prompts)

    def test_a_rebuild_with_an_unchanged_diff_reuses_the_pass_and_logs_the_reuse(self):  # #1549
        self.story_commit("x = 1\n")
        first = Scripted(reply("built"), reply("PASS"))
        self.loop(first, [(True, "")])
        git(self.repo, "checkout", "-qb", "moved", "origin/main")  # the default branch moves on, as before a rebase conflict
        (self.repo / "a.py").write_text("x = 2\n")
        git(self.repo, "add", "a.py")
        git(self.repo, "commit", "-qm", "theirs")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(self.repo, "checkout", "-q", "-")
        again = Scripted(reply("nothing to add"))
        out = self.loop(again, [(True, "")])
        self.assertEqual((True, 1), (out["done"], len(again.prompts)))  # the builder only
        reviews = [r for r in self.rows() if "review" in r]
        self.assertEqual([("pass", False), ("pass", True)], [(r["review"], r.get("reused", False)) for r in reviews])
        self.assertEqual(reviews[0]["diff"], reviews[1]["diff"])

    def test_a_changed_diff_starts_a_fresh_reader_whose_verdict_decides(self):  # #1549
        self.story_commit("x = 1\n")
        self.assertEqual(("pass", 1), self.read(reply("PASS")))
        self.story_commit("x = 2\n")
        self.assertEqual(("findings", 1), self.read(reply("a.py: wrong")))

    def test_a_change_past_the_cut_of_a_long_diff_starts_a_fresh_reader(self):  # #1549
        long = "y" * agent_loop.DIFF_LIMIT + "\n"
        self.story_commit(long + "x = 1\n")
        self.assertEqual(("pass", 1), self.read(reply("PASS")))
        self.story_commit(long + "x = 2\n")
        self.assertEqual(("pass", 1), self.read(reply("PASS")))

    def test_a_findings_verdict_is_never_reused_even_after_a_pass_of_the_same_diff(self):  # #1549
        self.story_commit("x = 1\n")
        self.assertEqual(("findings", 1), self.read(reply("a.py: wrong")))
        self.assertEqual(("findings", 1), self.read(reply("a.py: still wrong")))
        rows = [r for r in self.rows() if "review" in r]
        agent_loop.append_run_log({**rows[0], "review": "pass"})
        agent_loop.append_run_log(rows[0])  # the last verdict for this diff is findings
        self.assertEqual(("pass", 1), self.read(reply("PASS")))

    def test_a_pass_is_not_reused_for_another_story_or_another_repos_story_of_the_same_number(self):  # #1549
        self.story_commit("x = 1\n")
        self.addCleanup(agent_loop.STORY_SLUG.pop, "s1", None)
        agent_loop.STORY_SLUG["s1"] = "o/one"
        self.assertEqual(("pass", 1), self.read(reply("PASS")))
        self.assertEqual(("pass", 1), self.read(reply("PASS"), story="s2"))
        agent_loop.STORY_SLUG["s1"] = "o/two"
        self.assertEqual(("pass", 1), self.read(reply("PASS")))
        self.assertEqual(("pass", 0), self.read())

    def stage_rows(self):
        return [r for r in (json.loads(l) for l in (self.home / "run-log.jsonl").read_text().splitlines()) if "stage" in r]

    def test_a_loop_with_a_repo_logs_validating_and_one_building_row_per_fix_round_each_with_the_seconds_of_the_stage_before(self):
        """#1291: stage rows carry story, repo, stage, at and seconds, and the story id is the one the round rows use."""
        agent_loop.STAGE_START["s1"] = 1000.0
        with mock.patch.object(agent_loop.time, "time", return_value=1090.0):
            self.loop(Scripted(reply(), reply()), [(False, "a"), (True, "")], review_mode="none", repo="r")
        rows = self.stage_rows()
        self.assertEqual(["validating", "building", "validating"], [r["stage"] for r in rows])
        self.assertEqual({"s1"}, {r["story"] for r in rows})
        self.assertEqual({"r"}, {r["repo"] for r in rows})
        self.assertEqual(90, rows[0]["seconds"])
        self.assertRegex(rows[0]["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_a_loop_with_no_repo_logs_no_stage_rows(self):
        self.loop(Scripted(reply()), [(True, "")], review_mode="none")
        self.assertEqual([], self.stage_rows())

    def test_a_stopped_stage_row_carries_its_reason_and_a_claimed_row_starts_at_zero_seconds(self):
        agent_loop.log_stage("s2", "r", "claimed")
        agent_loop.log_stage("s2", "r", "stopped", reason="validation failed")
        claimed, stopped = self.stage_rows()
        self.assertEqual(0, claimed["seconds"])
        self.assertEqual("validation failed", stopped["reason"])
        self.assertNotIn("reason", claimed)

    def test_a_routine_story_does_not_start_a_second_model_session_after_validation(self):
        run = Scripted(reply("built"))
        out = self.loop(run, [(True, "all green")], review_mode="none")
        self.assertTrue(out["done"])
        self.assertEqual(1, len(run.prompts))

    def test_a_restart_after_three_rounds_starts_the_next_build_one_level_up(self):
        run = Scripted(reply("built"), reply("fixed"), reply("again"), reply("once more"))
        out = self.loop(run, [(False, "a"), (False, "b"), (False, "c"), (False, "c")], model_name="haiku")
        self.assertFalse(out["done"])
        self.assertEqual(["haiku", "haiku", "sonnet"], run.models[:3])
        self.assertEqual("sonnet", agent_loop.restart_model("s1", "haiku"))

    def test_a_build_that_stopped_before_its_third_round_does_not_escalate_a_restart(self):
        rows = [{"story": "story-7", "round": r, "model": "haiku"} for r in (1, 2, 1)]
        (self.home / "run-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.assertEqual("haiku", agent_loop.restart_model("story-7", "haiku"))
        self.assertEqual("haiku", agent_loop.restart_model("story-8", "haiku"))

    def test_the_brief_names_the_builder_and_reader_the_runner_starts(self):
        from lib import cmd_dispatch
        for size, labels, expect in (("S", [], "Run on Haiku (size S with no risky path or P0 priority), and repository validation and commit gates"),
                                     ("M", [], "Run on Sonnet (size M), and a fresh Sonnet reader"),
                                     ("M", [{"name": "design"}], "Run on Opus (labeled design), and a fresh Opus reader")):
            with self.subTest(size=size, labels=labels):
                brief = cmd_dispatch.headless_brief(9, {"title": "t", "body": f"Size: {size}", "labels": labels}, "dispatch")
                self.assertIn(expect, brief)
                self.assertNotIn("for QA", brief)

    def test_a_builder_that_landed_and_removed_its_worktree_ends_the_loop_without_validation(self):
        def lands(prompt, cwd, **kw):
            shutil.rmtree(self.repo)  # the landed story's worktree is gone
            return reply("Landed.")

        out = agent_loop.run_loop("do it", self.repo, "s1", run=lands, say=lambda *_: None)  # the default check, which needs a command
        self.assertEqual((True, 1, "Landed."), (out["done"], out["rounds"], out["summary"]))
        self.assertEqual((False, agent_loop.NO_VALIDATION), agent_loop.validate(self.repo))

    def test_a_worktree_that_lost_its_validate_script_is_not_read_as_done(self):
        """#1011: the directory is still there, so a missing script means nothing checked the result."""
        def deletes(prompt, cwd, **kw):
            (self.repo / "scripts" / "validate.sh").unlink(missing_ok=True)
            return reply("Done.")

        out = agent_loop.run_loop("do it", self.repo, "s1", run=deletes, say=lambda *_: None)
        self.assertFalse(out["done"])

    def test_a_passing_validation_ends_the_loop_in_one_round(self):
        out = self.loop(Scripted(reply("All done."), reply("PASS")), [(True, "")])
        self.assertEqual((True, 1, 10, "All done."), (out["done"], out["rounds"], out["tokens"], out["summary"]))

    def test_the_loop_runs_on_sonnet_by_default_and_tells_the_model_not_to_poll(self):
        seen = {}

        def run(prompt, cwd, **kw):
            if kw["session"].endswith("-review"):
                return reply("PASS")
            seen.update(kw)
            return reply()

        self.loop(run, [(True, "")])
        self.assertEqual("sonnet", seen["model"])
        self.assertIn("never poll", seen["system"])
        self.assertIn("run neither", seen["system"])
        self.assertIn("run every test file that imports a module you changed and fix any failure", seen["system"])
        with mock.patch.dict(os.environ, {"OLIVERCODE_MODEL": "haiku"}):
            self.loop(run, [(True, "")])
        self.assertEqual("haiku", seen["model"])

    def test_a_failing_gate_starts_one_short_fix_session_with_the_story_the_diff_and_the_last_60_lines(self):
        run = Scripted(reply(session_id="c1"), reply(session_id="c2"), reply("PASS"))
        tail = "\n".join(f"line {i}" for i in range(100))
        with mock.patch.object(agent_loop, "branch_diff", return_value="THE DIFF"):
            out = self.loop(run, [(False, agent_loop.gate_tail(tail)), (True, "")])
        self.assertEqual((True, 2), (out["done"], out["rounds"]))
        self.assertEqual(["", ""], run.resumes[:2])  # the fix session is fresh, so it does not carry the builder's context
        for part in ("do it", "THE DIFF", "line 99", "line 40"):
            self.assertIn(part, run.prompts[1])
        self.assertNotIn("line 39\n", run.prompts[1])

    def test_a_claude_error_exit_stops_the_loop(self):
        out = self.loop(Scripted(reply(code=1)), [])
        self.assertEqual((False, 1), (out["done"], out["rounds"]))
        self.assertIn("exited 1", out["reason"])

    def test_a_refused_call_stops_the_loop_with_its_reason(self):
        out = self.loop(Scripted(model.ModelError("The call was refused. Over its budget.")), [])
        self.assertEqual((False, 0), (out["done"], out["rounds"]))
        self.assertIn("Over its budget", out["reason"])

    def test_a_repo_with_no_validation_script_stops_after_one_round_unverified_and_says_nothing_checked_it(self):
        (self.repo / "scripts" / "validate.sh").unlink()
        out = self.loop(Scripted(reply()), [])
        self.assertFalse(out["done"])
        self.assertIn("nothing checked", out["reason"])


if __name__ == "__main__":
    unittest.main()
