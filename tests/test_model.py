"""The model-call layer: scripts/lib/model.py runs Claude Code headless."""

import json
import os
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import model  # noqa: E402

REPLY = json.dumps({"result": "ok", "session_id": "abc", "total_cost_usd": 0.0123,
                    "usage": {"input_tokens": 3, "output_tokens": 4, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 50}})


class TestRunCli(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home), "OLIVERCODE_PROJECT_SETTINGS": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, stdout=REPLY, code=0, **kw):
        ran = mock.Mock(returncode=code, stdout=stdout, stderr="")
        with mock.patch("shutil.which", return_value="/bin/claude"), mock.patch("subprocess.run", return_value=ran) as run:
            out = model.run_cli("task", str(self.home), session="s1", **kw)
        return run, out

    def test_the_reply_session_and_tokens_come_back_and_enter_the_trace(self):
        _, out = self.call()
        self.assertEqual(("ok", "abc", 57, 0), (out["text"], out["session_id"], out["tokens"], out["code"]))

    def test_cli_call_writes_durable_start_and_end_session_records(self):
        _, out = self.call()
        rows = [json.loads(line) for line in (self.home / "model-sessions.jsonl").read_text().splitlines()]
        self.assertEqual(["session_start", "session_end"], [row["event"] for row in rows])
        self.assertTrue(rows[0]["session_id"])
        self.assertEqual(rows[0]["session_id"], rows[1]["session_id"])
        self.assertEqual("", rows[0]["model"])
        self.assertIn("started_at", out)
        self.assertIn("duration_s", out)
        self.assertEqual(1, out["session_cap"])
        self.assertEqual(1, out["session_attempt"])
        self.assertEqual(0.0123, rows[1]["cost_usd"])

    def test_no_api_key_is_read_or_passed(self):
        run, _ = self.call()
        self.assertNotIn("api", " ".join(run.call_args_list[0][0][0]).lower())
        self.assertEqual(["claude", "-p", "task"], run.call_args_list[0][0][0][:3])

    def test_resume_system_and_model_reach_the_command(self):
        run, _ = self.call(resume="abc", system="be brief", model="m-1", allowed_tools="Bash")
        argv = run.call_args_list[0][0][0]
        for flag, value in (("--resume", "abc"), ("--append-system-prompt", "be brief"), ("--model", "m-1"), ("--allowedTools", "Bash")):
            self.assertEqual(value, argv[argv.index(flag) + 1])

    def test_no_connector_loads_and_the_six_tools_are_allowed(self):
        run, _ = self.call()
        argv = run.call_args_list[0][0][0]
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual({"mcpServers": {}}, json.loads(argv[argv.index("--mcp-config") + 1]))
        self.assertEqual("Read,Edit,Write,Bash,Grep,Glob", argv[argv.index("--allowedTools") + 1])

    def test_the_built_in_tool_set_is_narrowed_and_skills_are_disabled(self):
        run, _ = self.call()
        argv = run.call_args_list[0][0][0]
        self.assertIn("--disable-slash-commands", argv)
        self.assertEqual("Read,Edit,Write,Bash,Grep,Glob", argv[argv.index("--tools") + 1])

    def test_every_token_kind_and_the_cost_come_back(self):
        _, out = self.call()
        self.assertEqual({"input": 3, "output": 4, "cache_read": 100, "cache_write": 50}, out["usage"])
        self.assertEqual(0.0123, out["cost_usd"])

    def test_a_reply_with_no_cost_or_usage_reports_zeros_and_no_cost(self):
        _, out = self.call(stdout=json.dumps({"result": "ok"}))
        self.assertEqual({"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}, out["usage"])
        self.assertIsNone(out["cost_usd"])

    def test_a_non_json_reply_is_kept_as_text(self):
        _, out = self.call(stdout="plain words", code=2)
        self.assertEqual(("plain words", 0, 2), (out["text"], out["tokens"], out["code"]))

    def test_a_new_session_gets_an_id_we_chose_and_a_resumed_one_keeps_its_own(self):
        run, _ = self.call()
        argv = run.call_args_list[0][0][0]
        self.assertEqual(36, len(argv[argv.index("--session-id") + 1]))
        run, _ = self.call(resume="abc")
        self.assertNotIn("--session-id", run.call_args_list[0][0][0])

    def test_the_stop_reason_and_the_stderr_tail_come_back_on_a_failed_call(self):
        capped = json.dumps({"subtype": "error_max_turns", "terminal_reason": "max_turns", "is_error": True, "session_id": "abc", "errors": ["Reached maximum number of turns (30)"]})
        ran = mock.Mock(returncode=1, stdout=capped, stderr="x" * 2000 + "warn")
        with mock.patch("shutil.which", return_value="/bin/claude"), mock.patch("subprocess.run", return_value=ran):
            out = model.run_cli("task", str(self.home))
        self.assertEqual((1, "max_turns", "abc"), (out["code"], out["stop"], out["session_id"]))
        self.assertIn("maximum number of turns", out["text"])
        self.assertEqual((model.STDERR_TAIL, True), (len(out["stderr"]), out["stderr"].endswith("warn")))

    def test_api_error_flag_from_claude_json_is_preserved(self):
        payload = json.dumps({"result": "API Error: 529 overloaded_error", "is_error": True, "subtype": "error_during_execution"})
        out = self.call(stdout=payload, code=1)[1]
        self.assertTrue(out["is_error"])
        self.assertIn("529 overloaded_error", out["text"])

    def test_a_timeout_names_the_session_it_stopped(self):
        import subprocess
        with mock.patch("shutil.which", return_value="/bin/claude"), mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 1)):
            with self.assertRaises(model.ModelTimeout) as caught:
                model.run_cli("task", str(self.home), resume="abc")
        self.assertEqual("abc", caught.exception.session_id)

    def test_a_project_only_run_takes_the_project_sources_and_only_olivercodes_hooks(self):
        settings = {"model": "x", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": 'python3 "/oc/scripts/hooks/pretool_guard.py"'},
            {"type": "command", "command": "my-own-notifier"}]}]}}
        path = self.home / "settings.json"
        path.write_text(json.dumps(settings))
        with mock.patch.object(model, "user_settings", return_value=path):
            run, out = self.call(project_only=True)
        argv = run.call_args_list[0][0][0]
        self.assertEqual("project,local", argv[argv.index("--setting-sources") + 1])
        hooks = json.loads(argv[argv.index("--settings") + 1])["hooks"]
        self.assertEqual({"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": 'python3 "/oc/scripts/hooks/pretool_guard.py"'}]}]}, hooks)
        self.assertEqual("project", out["settings"])

    def test_a_project_only_run_refuses_to_start_when_no_olivercode_hook_is_installed(self):
        path = self.home / "settings.json"
        path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}]}}))
        with mock.patch.object(model, "user_settings", return_value=path), mock.patch("shutil.which", return_value="/bin/claude"), mock.patch("subprocess.run") as run:
            with self.assertRaisesRegex(model.ModelError, "install"):
                model.run_cli("task", str(self.home), project_only=True)
        run.assert_not_called()

    def test_the_project_setup_is_the_default_and_the_env_switch_set_to_0_opts_back_in_and_every_call_marks_itself_headless(self):
        path = self.home / "settings.json"
        path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": 'python3 "/oc/scripts/hooks/wip_save.py"'}]}]}}))
        with mock.patch.object(model, "user_settings", return_value=path), mock.patch.dict(os.environ):
            os.environ.pop("OLIVERCODE_PROJECT_SETTINGS", None)
            run, out = self.call()
            self.assertIn("--setting-sources", run.call_args_list[0][0][0])
            self.assertEqual(("project", "1"), (out["settings"], run.call_args_list[0][1]["env"]["OLIVERCODE_HEADLESS"]))
            with mock.patch.dict(os.environ, {"OLIVERCODE_PROJECT_SETTINGS": "0"}):
                run, out = self.call()
            self.assertEqual(("current", "1"), (out["settings"], run.call_args_list[0][1]["env"]["OLIVERCODE_HEADLESS"]))
            self.assertNotIn("--setting-sources", run.call_args_list[0][0][0])

    def test_a_missing_claude_command_says_how_to_get_it(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(model.available())
            with self.assertRaisesRegex(model.ModelError, "sign in"):
                model.run_cli("task", str(self.home))


if __name__ == "__main__":
    unittest.main()
