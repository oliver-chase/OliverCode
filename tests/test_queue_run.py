"""`olivercode queue run` and the pretool guard that routes validation commands through it (#519) and render commands through the render queue (#524)."""

import os
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from _support import REPO_ROOT, load_script, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
import validate_queue  # noqa: E402
import queue_guard  # noqa: E402

pretool = load_script("scripts/hooks/pretool_guard.py", "pretool_guard_queue_test")


def bash(command):
    return {"tool_name": "Bash", "tool_input": {"command": command, "description": "d"}, "cwd": "/tmp"}


class TestQueueGuard(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("OLIVERCODE_VALIDATE_SLOT", None)
        os.environ.pop("VALIDATE_QUEUE_SLOT", None)

    def test_a_matching_command_is_rewritten_through_the_queue(self):
        for command in queue_guard.QUEUED_COMMANDS:
            self.assertEqual(f"{queue_guard.LAUNCHER} queue run -- {command}", queue_guard.rewrite(command), command)
        self.assertEqual(f"{queue_guard.LAUNCHER} queue run -- pytest -q tests/x.py", queue_guard.rewrite("pytest -q tests/x.py"))

    def test_land_sh_is_rewritten_through_the_queue(self):
        self.assertEqual(f"{queue_guard.LAUNCHER} queue run -- bash scripts/land.sh --pr 5", queue_guard.rewrite("bash scripts/land.sh --pr 5"))
        self.assertEqual(f"{queue_guard.LAUNCHER} queue run -- ./scripts/land.sh", queue_guard.rewrite("./scripts/land.sh"))
        self.assertIsNone(queue_guard.rewrite("bash scripts/land.sh.bak"))

    def test_a_cd_prefix_stays_outside_the_wrapper(self):
        self.assertEqual(f"cd /r && {queue_guard.LAUNCHER} queue run -- npm test", queue_guard.rewrite("cd /r && npm test"))

    def test_the_hook_builds_updated_input_that_keeps_the_other_fields(self):
        out = pretool.updated_input(bash("npm run validate"))
        self.assertEqual(f"{queue_guard.LAUNCHER} queue run -- npm run validate", out["command"])
        self.assertEqual("d", out["description"])

    def test_a_command_that_only_contains_a_match_is_left_alone(self):
        for command in ["echo npm test", "grep pytest file", 'git commit -m "npm test"', "npm testing", "pytest-cov x",
                        "ls && pytest", "cat x | pytest", "npm run build", "olivercode queue run -- npm test",
                        "bash scripts/validate.sh.bak", "FOO=1 npm test", ""]:
            self.assertIsNone(queue_guard.rewrite(command), command)

    def test_the_words_queue_run_in_a_comment_or_an_argument_do_not_skip_the_queue(self):
        """#899: only an `olivercode queue run` command is already queued."""
        for command in ("npm test # queue run later", 'pytest -k "queue run"', "npm test --grep 'queue run'"):
            self.assertTrue(queue_guard.rewrite(command).startswith(f"{queue_guard.LAUNCHER} queue run -- "), command)
        for command in ("olivercode queue run -- npm test", f"{queue_guard.LAUNCHER} queue run -- npm test", "cd /r && olivercode queue run -- pytest"):
            self.assertIsNone(queue_guard.rewrite(command), command)

    def test_a_nested_run_passes_through(self):
        os.environ["OLIVERCODE_VALIDATE_SLOT"] = "/x/slot-1.json"
        self.assertIsNone(queue_guard.rewrite("npm test"))
        self.assertIsNone(pretool.updated_input(bash("npm test")))

    def test_a_run_inside_the_neutral_slot_variable_passes_through(self):
        os.environ["VALIDATE_QUEUE_SLOT"] = "/x/slot-1.json"
        self.assertIsNone(queue_guard.rewrite("npm test"))

    def test_a_chained_command_wraps_only_the_first_command(self):
        self.assertEqual(f"{queue_guard.LAUNCHER} queue run -- npm test && echo ok", queue_guard.rewrite("npm test && echo ok"))


class TestQueueRun(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("OLIVERCODE_VALIDATE_SLOT", "VALIDATE_QUEUE_SLOT"):
            os.environ.pop(name, None)

    def slots(self):
        folder = validate_queue.slots_dir()
        return list(folder.glob("slot-*.json")) if folder.exists() else []

    def test_the_exit_code_comes_back_and_the_slot_is_freed_on_failure(self):
        self.assertEqual(0, validate_queue.run([sys.executable, "-c", "pass"]))
        self.assertEqual(3, validate_queue.run([sys.executable, "-c", "raise SystemExit(3)"]))
        self.assertEqual([], self.slots())

    def test_the_child_sees_the_slot_so_a_nested_run_skips_the_queue(self):
        code = "import os,sys; sys.exit(0 if os.environ.get('OLIVERCODE_VALIDATE_SLOT','').endswith('.json') else 9)"
        self.assertEqual(0, validate_queue.run([sys.executable, "-c", code]))

    def test_the_child_sees_the_slot_under_the_neutral_name_too(self):
        code = "import os,sys; sys.exit(0 if os.environ.get('VALIDATE_QUEUE_SLOT','').endswith('.json') else 9)"
        self.assertEqual(0, validate_queue.run([sys.executable, "-c", code]))

    def test_acquire_inside_a_held_slot_takes_no_second_one(self):
        with mock.patch.dict(os.environ, {"VALIDATE_QUEUE_SLOT": "/x/slot-1.json"}), mock.patch("sys.stdout") as out:
            self.assertEqual(0, validate_queue.main(["acquire", "--pid", "1"]))
        self.assertEqual("none", "".join(c.args[0] for c in out.write.call_args_list).strip())
        self.assertEqual([], self.slots())

    def test_a_queue_error_fails_open_with_one_stderr_line(self):
        with mock.patch.object(validate_queue, "acquire", side_effect=OSError("disk")), \
                mock.patch("sys.stderr") as err:
            self.assertEqual(0, validate_queue.run([sys.executable, "-c", "pass"]))
        self.assertEqual(1, sum(1 for c in err.write.call_args_list if "queue skipped" in c.args[0]))

    def test_a_missing_command_returns_127_and_frees_the_slot(self):
        self.assertEqual(127, validate_queue.run(["no-such-command-519"]))
        self.assertEqual([], self.slots())


RENDER = f"{queue_guard.LAUNCHER} queue run --render --"


class TestRenderGuard(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("OLIVERCODE_VALIDATE_SLOT", "VALIDATE_QUEUE_SLOT", "OLIVERCODE_RENDER_SLOT"):
            os.environ.pop(name, None)

    def test_a_render_command_is_rewritten_with_render(self):
        for command in ["ffmpeg -i in.mp4 out.mp4", "/opt/homebrew/bin/ffmpeg -y -i a.mp4 b.mp4",
                        "python3 scripts/render_video.py batch", "python3 scripts/render_new.py --limit 3",
                        "python3 scripts/page_render.py", "./scripts/dashboard_render.py"]:
            self.assertEqual(f"{RENDER} {command}", queue_guard.rewrite(command), command)
        self.assertEqual(f"cd /r && {RENDER} ffmpeg -i a b", queue_guard.rewrite("cd /r && ffmpeg -i a b"))

    def test_the_hook_builds_updated_input_for_a_render(self):
        self.assertEqual(f"{RENDER} ffmpeg -i a b", pretool.updated_input(bash("ffmpeg -i a b"))["command"])

    def test_a_non_render_or_already_queued_command_is_left_alone(self):
        for command in ["ffprobe -i a.mp4", "echo ffmpeg", "ls && ffmpeg -i a b", "python3 scripts/flow.py post", "cat render_video.py",
                        "ffmpeg2 -x", "grep render scripts/x.py", f"{RENDER} ffmpeg -i a b",
                        "olivercode queue run --render -- ffmpeg -i a b"]:
            self.assertIsNone(queue_guard.rewrite(command), command)
        os.environ["OLIVERCODE_RENDER_SLOT"] = "/x/slot-1.json"
        self.assertIsNone(queue_guard.rewrite("ffmpeg -i a b"))

    def test_a_validation_command_still_uses_the_validation_queue(self):
        self.assertEqual(f"{queue_guard.LAUNCHER} queue run -- pytest", queue_guard.rewrite("pytest"))


class TestRenderQueue(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("OLIVERCODE_VALIDATE_SLOT", "OLIVERCODE_RENDER_SLOT", "OLIVERCODE_RENDER_SLOTS"):
            os.environ.pop(name, None)

    def test_the_render_queue_has_its_own_folder_and_one_slot(self):
        self.assertNotEqual(validate_queue.slots_dir("render"), validate_queue.slots_dir())
        self.assertEqual("render-slots", validate_queue.slots_dir("render").name)
        self.assertEqual(1, validate_queue.slot_count("render"))
        os.environ["OLIVERCODE_RENDER_SLOTS"] = "3"  # #1072: the render queue is one slot, with no setting to change it
        self.assertEqual(1, validate_queue.slot_count("render"))

    def test_a_second_render_run_waits_while_one_holds_the_slot(self):
        first = validate_queue.acquire(os.getpid(), "a", queue="render")
        self.assertIsNotNone(first)
        self.assertIsNone(validate_queue.try_acquire(os.getpid(), "b", queue="render"))
        self.assertIsNotNone(validate_queue.try_acquire(os.getpid(), "c"), "the validation queue is separate")
        result = {}
        thread = threading.Thread(target=lambda: result.update(code=validate_queue.run(
            [sys.executable, "-c", "pass"], queue="render", poll=0.05)))
        thread.start()
        time.sleep(0.4)
        self.assertTrue(thread.is_alive(), "the second render run should still be waiting")
        validate_queue.release(first)
        thread.join(10)
        self.assertEqual(0, result.get("code"))
        self.assertEqual([], list(validate_queue.slots_dir("render").glob("slot-*.json")))

    def test_the_render_run_applies_nice_and_hands_the_child_the_render_slot(self):
        code = "import os,sys; sys.exit(0 if os.environ.get('OLIVERCODE_RENDER_SLOT','').endswith('.json') else 9)"
        self.assertEqual(0, validate_queue.run([sys.executable, "-c", code], queue="render"))
        base = os.nice(0)
        out = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), "queue", "run", "--render", "--",
                              sys.executable, "-c", "import os; print(os.nice(0))"], capture_output=True, text=True, env=os.environ)
        self.assertEqual(str(min(19, base + 10)), out.stdout.strip(), out.stderr)

    def test_a_stale_render_slot_is_reaped(self):
        folder = validate_queue.slots_dir("render")
        folder.mkdir(parents=True)
        (folder / "slot-1.json").write_text('{"pid": 999999999, "started": 0}')
        self.assertIsNotNone(validate_queue.try_acquire(os.getpid(), "x", queue="render"))

    def test_queue_show_lists_both_queues(self):
        shown = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), "queue", "show"],
                               capture_output=True, text=True, env={**os.environ, "OLIVERCODE_VALIDATE_SLOTS": "2"}).stdout
        self.assertIn("Validation slots: 0 of 2 held.", shown)
        self.assertIn("Render slots: 0 of 1 held.", shown)


if __name__ == "__main__":
    unittest.main()
