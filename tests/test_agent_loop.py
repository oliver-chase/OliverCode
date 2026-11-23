"""The agent loop and `olivercode run`: scripts/lib/agent_loop.py and cmd_run.py, driven by a scripted Claude Code and a scripted validation."""

import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import agent_loop, cmd_run, model  # noqa: E402


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


class TestRunLog(unittest.TestCase):
    """What a headless run costs (docs/SETUP.md), #878: one JSON line per round under the OliverCode home folder."""

    def test_each_round_appends_one_line_with_story_round_model_tokens_and_cost(self):
        home, repo = temp_dir(self), temp_dir(self)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "validate.sh").write_text("exit 0\n")
        usage = {"input": 3, "output": 4, "cache_read": 100, "cache_write": 50}
        replies = Scripted({**reply("one"), "usage": usage, "cost_usd": 0.5}, {**reply("two"), "usage": usage, "cost_usd": None})
        checks = iter([(False, "bad"), (True, "")])
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            agent_loop.run_loop("do it", repo, "story-878", run=replies, check=lambda cwd: next(checks), say=lambda *_: None, model_name="sonnet")
        rows = [json.loads(line) for line in (home / "run-log.jsonl").read_text().splitlines()]
        self.assertEqual([1, 2], [r["round"] for r in rows])
        self.assertEqual(("story-878", "sonnet", 3, 4, 100, 50, 0.5), tuple(rows[0][k] for k in ("story", "model", "input", "output", "cache_read", "cache_write", "cost_usd")))
        self.assertIsNone(rows[1]["cost_usd"])

    def test_a_log_that_cannot_be_written_never_stops_the_loop(self):
        repo = temp_dir(self)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "validate.sh").write_text("exit 0\n")
        with mock.patch.object(agent_loop.failure_log, "home", side_effect=OSError("read-only")):
            out = agent_loop.run_loop("do it", repo, "s", run=Scripted(reply()), check=lambda cwd: (True, ""), say=lambda *_: None)
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

    def rows(self):
        return [json.loads(l) for l in (self.home / "run-log.jsonl").read_text().splitlines()]

    def test_the_turn_cap_resumes_the_same_session_once_and_logs_both_calls(self):
        run = Scripted({**reply("", code=1, session_id="sess"), "stop": "max_turns", "stderr": ""}, reply("committed", session_id="sess"))
        out = self.loop(run)
        self.assertTrue(out["done"])
        self.assertEqual(["", "sess"], [r or "" for r in run.resumes])
        self.assertIn("Continue from where you left off", run.prompts[1])
        rows = self.rows()
        self.assertEqual(("max_turns", False, ""), (rows[0]["stop"], rows[0]["resumed"], rows[1]["stop"]))
        self.assertTrue(rows[1]["resumed"])

    def test_a_second_turn_cap_ends_the_round_and_the_reason_names_the_cause(self):
        capped = {**reply("", code=1, session_id="sess"), "stop": "max_turns", "stderr": "boom"}
        run = Scripted(capped, capped)
        out = self.loop(run)
        self.assertFalse(out["done"])
        self.assertEqual(2, len(run.prompts))
        self.assertIn("stop reason max_turns after one resume", out["reason"])
        self.assertIn("stderr: boom", out["reason"])

    def test_a_timeout_resumes_the_session_the_run_started(self):
        run = Scripted(model.ModelTimeout("claude -p ran past 900 seconds and was stopped.", "sid-9"), reply("committed", session_id="sid-9"))
        out = self.loop(run)
        self.assertTrue(out["done"])
        self.assertEqual(["", "sid-9"], [r or "" for r in run.resumes])
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


class TestRunLog(unittest.TestCase):
    """#878, #909: a run-log line holds the CLI's usage, cost and stop reason and the start size, and no transcript is read to count calls."""

    def setUp(self):
        self.repo, self.home = temp_dir(self), temp_dir(self)
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / "validate.sh").write_text("exit 0\n")
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def rows(self):
        return [json.loads(line) for line in (self.home / "run-log.jsonl").read_text().splitlines()]

    def test_the_first_round_logs_the_cache_write_as_the_start_size_and_no_flag(self):
        said = []
        usage = {"input": 3, "output": 4, "cache_read": 0, "cache_write": 31_000}
        out = agent_loop.run_loop("do it", self.repo, "story-1", run=Scripted({**reply(), "usage": usage}), check=lambda cwd: (True, ""), say=said.append)
        row = self.rows()[0]
        self.assertEqual((31_000, 3, 4), (row["start_tokens"], row["input"], row["output"]))
        self.assertTrue({"cost_usd", "stop"} <= set(row))
        self.assertFalse({"start_source", "start_over_limit", "calls_before_first_edit"} & set(row))
        self.assertNotIn("start_tokens", out)
        self.assertFalse(any("limit" in line for line in said))

    def test_a_later_round_logs_no_start_size(self):
        run = Scripted({**reply(), "usage": {"cache_write": 900}}, {**reply(), "usage": {"cache_write": 50}})
        agent_loop.run_loop("do it", self.repo, "story-1", run=run, check=lambda cwd, results=iter([(False, "x"), (True, "")]): next(results), say=lambda line: None)
        self.assertEqual([900, None], [r.get("start_tokens") for r in self.rows()])

    def test_the_run_log_names_which_setup_each_start_ran(self):
        """#911: the two start sizes are told apart by the setup that ran, current or project."""
        agent_loop.run_loop("do it", self.repo, "story-1", run=Scripted({**reply(), "settings": "project", "usage": {"cache_write": 900}}),
                            check=lambda cwd: (True, ""), say=lambda line: None)
        row = self.rows()[0]
        self.assertEqual(("project", 900), (row["settings"], row["start_tokens"]))


class TestLoop(unittest.TestCase):
    def setUp(self):
        self.repo = temp_dir(self)
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / "validate.sh").write_text("exit 0\n")

    def loop(self, run, results, **kw):
        checks = iter(results)
        return agent_loop.run_loop("do it", self.repo, "s1", run=run, check=lambda cwd: next(checks), say=lambda *_: None, **kw)

    def test_the_model_follows_the_size_and_only_a_design_label_takes_the_largest(self):
        self.assertEqual(["haiku", "haiku", "sonnet", "sonnet", "opus"],
                         [agent_loop.model_for(s) for s in ("XS", "S", "M", "L")] + [agent_loop.model_for("M", [{"name": "design"}])])

    def test_a_small_story_moves_up_one_level_after_a_second_failed_validation(self):
        run = Scripted(reply(), reply(), reply())
        out = self.loop(run, [(False, "a"), (False, "b"), (True, "")], model_name="haiku", rounds=3)
        self.assertTrue(out["done"])
        self.assertEqual(["haiku", "haiku", "sonnet"], run.models)

    def test_the_ladder_stops_at_the_largest_model(self):
        self.assertEqual(("sonnet", "opus", "opus"), (agent_loop.escalate("haiku", 2), agent_loop.escalate("sonnet", 2), agent_loop.escalate("opus", 5)))
        self.assertEqual("haiku", agent_loop.escalate("haiku", 1))

    def test_an_m_story_gets_one_fresh_reader_that_sees_the_story_the_diff_and_the_test_output(self):
        run = Scripted(reply("built"), reply("PASS"))
        with mock.patch.object(agent_loop, "branch_diff", return_value="THE-DIFF"), mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(temp_dir(self))}):
            out = self.loop(run, [(True, "all green")], size="M")
        self.assertTrue(out["done"])
        self.assertEqual(2, len(run.prompts))
        for text in ("do it", "THE-DIFF", "all green"):
            self.assertIn(text, run.prompts[1])
        self.assertEqual(["", ""], [r or "" for r in run.resumes])  # the reader resumes nothing

    def test_the_reader_logs_its_findings_on_the_story(self):
        home = temp_dir(self)
        run = Scripted(reply("built"), reply("scripts/a.py: no test"))
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            self.loop(run, [(True, "")], size="L")
        rows = [json.loads(l) for l in (home / "run-log.jsonl").read_text().splitlines()]
        self.assertEqual([("s1", "findings", "scripts/a.py: no test")], [(r["story"], r["review"], r["findings"]) for r in rows if "review" in r])

    def test_a_small_story_that_touches_no_hook_runs_no_reader(self):
        run = Scripted(reply("built"))
        self.loop(run, [(True, "")], size="S")
        self.assertEqual(1, len(run.prompts))

    def test_which_stories_need_a_reader(self):
        from lib import cmd_land
        self.assertEqual([True, True, True, False, False],
                         [cmd_land.needs_review("M", []), cmd_land.needs_review("S", ["core/hooks/x.py"]), cmd_land.needs_review("XS", ["scripts/hooks/y.py"]),
                          cmd_land.needs_review("S", ["scripts/lib/z.py"]), cmd_land.needs_review("", [])])

    def test_a_builder_that_landed_and_removed_its_worktree_ends_the_loop_without_validation(self):
        def lands(prompt, cwd, **kw):
            (self.repo / "scripts" / "validate.sh").unlink()  # the landed story's worktree is gone
            return reply("Landed.")

        out = agent_loop.run_loop("do it", self.repo, "s1", run=lands, say=lambda *_: None)  # the default check, which needs a command
        self.assertEqual((True, 1, "Landed."), (out["done"], out["rounds"], out["summary"]))
        self.assertEqual((False, "The repo has no validation command to run."), agent_loop.validate(self.repo))

    def test_a_passing_validation_ends_the_loop_in_one_round(self):
        out = self.loop(Scripted(reply("All done.")), [(True, "")])
        self.assertEqual((True, 1, 10, "All done."), (out["done"], out["rounds"], out["tokens"], out["summary"]))

    def test_the_loop_runs_on_sonnet_by_default_and_tells_the_model_not_to_poll(self):
        seen = {}

        def run(prompt, cwd, **kw):
            seen.update(kw)
            return reply()

        self.loop(run, [(True, "")])
        self.assertEqual("sonnet", seen["model"])
        self.assertIn("never poll", seen["system"])
        self.assertIn("run neither", seen["system"])
        with mock.patch.dict(os.environ, {"OLIVERCODE_MODEL": "haiku"}):
            self.loop(run, [(True, "")])
        self.assertEqual("haiku", seen["model"])

    def test_a_failing_gate_starts_one_short_fix_session_with_the_story_the_diff_and_the_last_60_lines(self):
        run = Scripted(reply(session_id="c1"), reply(session_id="c2"))
        tail = "\n".join(f"line {i}" for i in range(100))
        with mock.patch.object(agent_loop, "branch_diff", return_value="THE DIFF"):
            out = self.loop(run, [(False, agent_loop.gate_tail(tail)), (True, "")])
        self.assertEqual((True, 2), (out["done"], out["rounds"]))
        self.assertEqual(["", ""], run.resumes)  # the fix session is fresh, so it does not carry the builder's context
        for part in ("do it", "THE DIFF", "line 99", "line 40"):
            self.assertIn(part, run.prompts[1])
        self.assertNotIn("line 39\n", run.prompts[1])

    def test_validation_that_keeps_failing_stops_after_the_rounds_and_says_so(self):
        out = self.loop(Scripted(reply(), reply()), [(False, "a"), (False, "b")], rounds=2)
        self.assertEqual((False, 2), (out["done"], out["rounds"]))
        self.assertIn("after 2 rounds", out["reason"])

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


class TestRunCommand(unittest.TestCase):
    def run_cmd(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cmd_run.command_run(argv)
        return code, out.getvalue()

    def test_a_missing_task_or_flag_prints_the_usage(self):
        for argv in ([], ["--bogus"], ["task", "--max-turns", "x"], ["task", "--max-turns", "0"]):
            code, out = self.run_cmd(argv)
            self.assertEqual((1, True), (code, out.startswith("Usage")), argv)

    def test_no_claude_command_says_how_to_get_it(self):
        with mock.patch.object(model, "available", return_value=False):
            code, out = self.run_cmd(["do", "it"])
        self.assertEqual(1, code)
        self.assertIn("sign in", out)

    def test_the_loop_outcome_sets_the_exit_code(self):
        done = {"done": True, "reason": "The repo's validation passes.", "rounds": 1, "tokens": 20, "summary": ""}
        with mock.patch.object(model, "available", return_value=True), mock.patch.object(cmd_run.agent_loop, "run_loop", return_value=done) as loop:
            code, out = self.run_cmd(["add", "a", "test", "--max-turns", "5"])
        self.assertEqual(0, code)
        self.assertEqual(("add a test", 5), (loop.call_args[0][0], loop.call_args[1]["max_turns"]))
        self.assertIn("Done:", out)
        with mock.patch.object(model, "available", return_value=True), \
                mock.patch.object(cmd_run.agent_loop, "run_loop", return_value={**done, "done": False}):
            self.assertEqual(1, self.run_cmd(["x"])[0])


if __name__ == "__main__":
    unittest.main()
