"""The agent loop and `olivercode run`: scripts/lib/agent_loop.py and cmd_run.py, driven by a scripted Claude Code and a scripted validation."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, git, scratch_repo, temp_dir

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


class TestRoundCheck(unittest.TestCase):
    """#1142: the runner's check after each builder round narrows scripts/validate.sh's smoke gate to the files this
    story's branch changed against origin's default branch. A story's landing (cmd_land.py) validates separately and is
    untouched by this."""

    def test_changed_files_lists_the_branch_diff_against_origin(self):
        repo = scratch_repo(temp_dir(self))
        (repo / "a.py").write_text("a = 1\n")
        git(repo, "add", "a.py")
        git(repo, "commit", "-m", "first")
        git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        (repo / "b.py").write_text("b = 2\n")
        git(repo, "add", "b.py")
        git(repo, "commit", "-m", "second")
        self.assertEqual(["b.py"], agent_loop.changed_files(repo))

    def test_changed_files_is_empty_when_git_has_nothing_to_compare(self):
        self.assertEqual([], agent_loop.changed_files(temp_dir(self)))  # not a git repo at all

    def test_validate_hands_scripts_validate_sh_the_round_and_the_changed_files(self):
        repo = temp_dir(self)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "validate.sh").write_text("exit 0\n")
        seen = {}

        def run(argv, **kw):
            seen["argv"] = argv
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch.object(agent_loop, "changed_files", return_value=["scripts/lib/cmd_land.py"]), \
                mock.patch.object(agent_loop.subprocess, "run", side_effect=run):
            agent_loop.validate(repo)
        self.assertEqual(["--round", "scripts/lib/cmd_land.py"], seen["argv"][-2:])

    def test_validate_does_not_narrow_an_npm_validation_command(self):
        repo = temp_dir(self)
        (repo / "package.json").write_text('{"scripts": {"check": "true"}}')
        seen = {}

        def run(argv, **kw):
            seen["argv"] = argv
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch.object(agent_loop, "changed_files") as changed, \
                mock.patch.object(agent_loop.subprocess, "run", side_effect=run):
            agent_loop.validate(repo)
        changed.assert_not_called()
        self.assertNotIn("--round", seen["argv"])


class TestRunLog(unittest.TestCase):
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
        self.assertEqual([1, 2, 1], [r["round"] for r in rows if "round" in r])  # the reader's own row comes last
        self.assertEqual(("story-878", "pass"), (rows[-1]["story"], rows[-1]["review"]))  # then its verdict, which holds no round
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
        self.assertTrue(out["budget"])  # every turn was spent, so the drain leaves a handoff (#1113)

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

    def test_api_error_is_logged_without_a_round_and_does_not_escalate_the_model(self):
        run = Scripted({**reply("", code=1), "stop": "error_during_execution", "text": "API Error: 529 overloaded_error"})
        out = self.loop(run)
        self.assertTrue(out["api_error"])
        self.assertEqual(0, out["rounds"])
        self.assertEqual("haiku", run.models[0])
        self.assertEqual("haiku", agent_loop.restart_model("story-1", "haiku"))
        rows = [json.loads(line) for line in (self.home / "run-log.jsonl").read_text().splitlines()]
        self.assertEqual(1, len(rows))
        self.assertNotIn("round", rows[0])
        self.assertEqual("api_error", rows[0]["stop"])
        self.assertIn("529 overloaded_error", rows[0]["stderr_tail"])


class TestRunLogUsage(unittest.TestCase):
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

    def test_the_model_follows_the_size_and_only_a_design_label_takes_the_largest(self):
        self.assertEqual(["haiku", "haiku", "sonnet", "sonnet", "opus"],
                         [agent_loop.model_for(s) for s in ("XS", "S", "M", "L")] + [agent_loop.model_for("M", [{"name": "design"}])])

    def test_a_small_story_touching_landing_claims_gates_or_hooks_or_a_p0_starts_on_the_middle_model(self):
        for files, priority in ((["scripts/lib/cmd_land.py"], "P2"), (["scripts/lib/cmd_drain.py"], "P2"), (["scripts/lib/agent_loop.py", "docs/RULES.md"], "P2"),
                                (["scripts/lib/log_action.py"], "P2"), (["skills/backlog/scripts/complete_story.py"], "P2"), (["core/hooks/guard.py"], "P2"),
                                (["scripts/hooks/gh_guard.py"], "P2"), ([], "P0")):
            with self.subTest(files=files, priority=priority):
                self.assertEqual("sonnet", agent_loop.model_for("S", files=files, priority=priority))

    def test_a_small_story_touching_only_docs_tests_or_one_command_starts_on_the_smallest_model(self):
        self.assertEqual("haiku", agent_loop.model_for("XS", files=["docs/RULES.md", "tests/test_cmd_status.py", "scripts/lib/cmd_status.py"], priority="P2"))

    def test_only_medium_or_larger_design_or_risky_stories_get_a_fresh_reader(self):
        self.assertEqual("none", agent_loop.review_mode("S", files=["docs/RULES.md"], priority="P2"))
        self.assertEqual("full", agent_loop.review_mode("S", files=["scripts/hooks/gh_guard.py"], priority="P2"))
        self.assertEqual("none", agent_loop.review_mode("S", priority="P0"))
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

    def test_a_small_story_moves_up_one_level_after_a_second_failed_validation(self):
        run = Scripted(reply(), reply(), reply(), reply("PASS"))
        out = self.loop(run, [(False, "a"), (False, "b"), (True, "")], model_name="haiku", rounds=3)
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

    def test_a_second_finding_holds_the_story_and_nothing_is_pushed(self):
        run = Scripted(reply("built"), reply("scripts/a.py: no test"), reply("fixed"), reply("scripts/b.py: still wrong"))
        out = self.loop(run, [(True, ""), (True, "")])
        self.assertFalse(out["done"])
        self.assertEqual("scripts/b.py: still wrong", out["held"])
        self.assertIn("nothing is pushed", out["reason"])
        self.assertEqual(4, len(run.prompts))

    def test_a_finding_in_the_last_round_still_gets_its_one_fix_session(self):
        run = Scripted(reply("built"), reply("scripts/a.py: no test"), reply("fixed"), reply("PASS"))
        out = self.loop(run, [(True, ""), (True, "")], rounds=1)
        self.assertEqual((True, 4), (out["done"], len(run.prompts)))

    def test_a_finding_after_a_failed_validation_still_gets_one_fix_session(self):
        run = Scripted(reply("built"), reply("fixed"), reply("scripts/a.py: no test"), reply("fixed again"), reply("PASS"))
        out = self.loop(run, [(False, "gate"), (True, ""), (True, "")])
        self.assertEqual((True, 5), (out["done"], len(run.prompts)))
        self.assertIn("scripts/a.py: no test", run.prompts[3])

    def test_an_xs_story_on_any_path_gets_a_fresh_reader_before_it_lands(self):
        run = Scripted(reply("built"), reply("PASS"))
        out = self.loop(run, [(True, "")])
        self.assertEqual((True, 2), (out["done"], len(run.prompts)))

    def test_reader_verdict_accepts_explicit_final_line_and_legacy_pass(self):
        cases = (
            ("PASS", "pass"),
            ("PASS, the diff does what the story says.", "pass"),
            ("All checks line up\nVERDICT: PASS", "pass"),
            ("Confirmed\nVERDICT: PASS", "pass"),
            ("scripts/a.py: wrong\nVERDICT: FINDINGS", "findings"),
            ("PASSING concerns", "findings"),
            ("Passing is not a verdict", "findings"),
            ("scripts/a.py: wrong", "findings"),
            ("VERDICT: MAYBE", "findings"),
        )
        for text, verdict in cases:
            with self.subTest(text=text):
                out = agent_loop.review("the story", self.repo, "s1", "gate", run=Scripted(reply(text)), say=lambda *_: None)
                self.assertEqual(verdict, out["verdict"])

    def test_a_reader_that_fails_once_is_asked_again_and_its_pass_lands_the_story(self):
        run = Scripted(reply("built"), model.ModelError("no reader"), reply("PASS"))
        out = self.loop(run, [(True, "")])
        self.assertEqual((True, 3), (out["done"], len(run.prompts)))

    def test_a_reader_that_gives_no_verdict_twice_holds_the_story_and_nothing_is_pushed(self):
        run = Scripted(reply("built"), reply(""), reply("PASS", code=1))
        out = self.loop(run, [(True, "")])
        self.assertEqual((False, 3), (out["done"], len(run.prompts)))
        self.assertIn("nothing is pushed", out["reason"])
        self.assertEqual("claude exited 1.", out["held"])

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

    def test_a_routine_story_does_not_start_a_second_model_session_after_validation(self):
        run = Scripted(reply("built"))
        out = self.loop(run, [(True, "all green")], review_mode="none")
        self.assertTrue(out["done"])
        self.assertEqual(1, len(run.prompts))

    def test_a_restart_after_three_rounds_starts_the_next_build_one_level_up(self):
        run = Scripted(reply("built"), reply("fixed"), reply("again"))
        out = self.loop(run, [(False, "a"), (False, "b"), (False, "c")], model_name="haiku", rounds=3)
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
            (self.repo / "scripts" / "validate.sh").unlink()
            return reply("Done.")

        out = agent_loop.run_loop("do it", self.repo, "s1", run=deletes, say=lambda *_: None, rounds=1)
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
