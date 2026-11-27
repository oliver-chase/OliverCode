"""#1000: a status-only message is blocked with the digest lines as the reason, a mixed one goes through with context, and "ask:" passes unchanged."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, load_script, quiet, temp_dir

hint = load_script("scripts/hooks/status_hint.py")
from lib import cmd_handoff  # noqa: E402  (the hint's load puts scripts/ on the path)

DIGEST = """# Status digest
Written 2026-11-23 13:00 UTC.
Board: owner/repo: 3 open stories.

## Open, 2 in priority order
- #991 P1 The guide teaches efficient use
- #979 P1 Stories build one at a time

## Landed, the last five
- #985 A new thread starts from the digest
"""


class StatusOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self)
        self.digest = self.tmp / "status-digest.md"
        self.digest.write_text(DIGEST, encoding="utf-8")

    def run_hook(self, prompt):
        script = str(REPO_ROOT / "scripts" / "hooks" / "status_hint.py")
        env = dict(os.environ, OLIVERCODE_HOME=str(self.tmp))
        return subprocess.run([sys.executable, script], input=json.dumps({"prompt": prompt}), capture_output=True, text=True, env=env)

    def test_a_status_only_message_is_status_only(self):
        for prompt in ("what's building right now?", "when will it finish?", "what's the status?", "status?"):
            self.assertTrue(hint.is_status_only(prompt), prompt)
        self.assertFalse(hint.is_status_only("what's building and also fix the parser"))

    def test_a_mixed_message_goes_through_with_the_status_lines_as_context(self):
        prompt = "what's building right now? and fix the parser bug in cmd_land"
        self.assertFalse(hint.is_status_only(prompt))
        self.assertIn("Board: owner/repo: 3 open stories.", hint.context(prompt, self.digest))

    def test_a_digest_older_than_an_hour_says_how_old_it_is_and_points_to_olivercode_status(self):
        now = self.digest.stat().st_mtime
        self.assertEqual("", hint.age_note(self.digest, now + 600))
        self.assertIn("5 hours old. Run `olivercode status`", hint.age_note(self.digest, now + 5 * 3600 + 60))
        self.assertIn("3 days old", hint.age_note(self.digest, now + 3 * 86400))
        os.utime(self.digest, (now - 7200, now - 7200))
        stale = hint.context("what is building?", self.digest)
        self.assertIn("2 hours old", stale)
        self.assertIn("Run `olivercode status` before answering", stale)
        self.assertNotIn("Board:", stale)

    def test_a_fresh_digest_is_added_with_its_time_and_never_says_to_skip_a_check(self):
        text = hint.context("what is building?", self.digest)
        self.assertIn("Board: owner/repo: 3 open stories.", text)
        self.assertRegex(text, r"written \d{4}-\d\d-\d\d \d\d:\d\d UTC")
        self.assertIn("Confirm any figure", text)
        self.assertNotIn("no tool call", text)

    def test_a_status_only_prompt_over_a_stale_digest_goes_through(self):
        old = self.digest.stat().st_mtime - 7200
        os.utime(self.digest, (old, old))
        out = json.loads(self.run_hook("what is building?").stdout)
        self.assertNotIn("decision", out)
        self.assertIn("stale", out["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("Board:", out["hookSpecificOutput"]["additionalContext"])

    def test_an_ask_prefix_passes_a_status_question_through_unchanged(self):
        for prompt in ("ask: what is building?", "Ask: status?"):
            self.assertFalse(hint.is_status_only(prompt), prompt)
            self.assertEqual("", hint.context(prompt, self.digest), prompt)

    def test_the_hook_blocks_a_status_only_message_and_adds_context_for_a_mixed_one(self):
        status = self.run_hook("what is building?")
        self.assertEqual(0, status.returncode)
        blocked = json.loads(status.stdout)
        self.assertEqual("block", blocked["decision"])
        self.assertIn("Board: owner/repo: 3 open stories.", blocked["reason"])
        self.assertIn("additionalContext", self.run_hook("what is building? and fix the parser").stdout)
        self.assertEqual("", self.run_hook("ask: what is building?").stdout)
        self.assertEqual("", self.run_hook("fix the parser bug").stdout)


def fake_claude(folder, signed_in=True):
    """A `claude` in `folder` that answers `auth status`."""
    path = folder / "claude"
    path.write_text(f"#!/bin/sh\necho '{json.dumps({'loggedIn': signed_in})}'\nexit {0 if signed_in else 1}\n", encoding="utf-8")
    path.chmod(0o755)


class NextThread(unittest.TestCase):
    """#1476: writing the handoff starts the next thread with Remote Control on, or says in one line why it cannot."""

    def setUp(self):
        self.tmp = temp_dir(self, resolve=True)
        self.draft = self.tmp / "draft.md"
        self.draft.write_text("Next steps: read the board.", encoding="utf-8")
        self.records = self.tmp / "config" / "sessions"
        self.records.mkdir(parents=True)
        env = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.tmp / "home"), "CLAUDE_CONFIG_DIR": str(self.tmp / "config"),
                                           "PATH": f"{self.tmp}{os.pathsep}{os.environ['PATH']}"})
        env.start()
        self.addCleanup(env.stop)
        cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, cwd)

    def terminal(self, connects=True, status=0):
        """A fake osascript: it logs its arguments and, when the session connects, writes the record Claude Code would."""
        path = self.tmp / "osascript"
        path.write_text(f"""#!{sys.executable}
import json, sys
open({str(self.tmp / "argv.json")!r}, "w").write(json.dumps(sys.argv[1:]))
if {status}:
    sys.exit("not allowed to control Terminal")
if {connects}:
    record = {{"sessionId": sys.argv[-1].split()[-1], "bridgeSessionId": "session_abc"}}
    open({str(self.records / "7.json")!r}, "w").write(json.dumps(record))
""", encoding="utf-8")
        path.chmod(0o755)

    def write(self):
        code, out = quiet(cmd_handoff.write, "Shop", self.draft, self.tmp)
        self.assertEqual(0, code)
        return out

    def test_it_opens_terminal_with_remote_control_in_the_same_folder_and_prints_the_link(self):
        fake_claude(self.tmp)
        self.terminal()
        out = self.write()
        argv = json.loads((self.tmp / "argv.json").read_text(encoding="utf-8"))
        self.assertIn("do script (item 1 of argv)", argv)
        words = shlex.split(argv[-1])
        self.assertEqual(["cd", str(self.tmp), "&&", "claude", "--remote-control", "Shop 1"], words[:6])
        self.assertIn(f"{REPO_ROOT / 'scripts' / 'olivercode'} handoff read Shop in {self.tmp}", words[6])
        self.assertIn("https://claude.ai/code/session_abc", out)
        self.assertFalse((self.tmp / "home" / cmd_handoff.THREAD_NUMBERS).exists())

    def test_a_session_that_never_connects_is_said_to_have_no_link(self):
        fake_claude(self.tmp)
        self.terminal(connects=False)
        with mock.patch.object(cmd_handoff, "LINK_WAIT", 0):
            out = self.write()
        self.assertIn("showed no /rc active", out)
        self.assertNotIn("claude.ai/code", out)

    def test_a_machine_that_cannot_start_it_gets_one_line_with_the_reason_and_the_prompt(self):
        self.terminal(status=1)
        which = shutil.which
        cases = (("not on PATH", True, lambda name: None if name == "claude" else which(name)),
                 ("not signed in", False, which), ("not allowed to control Terminal", True, which))
        for reason, signed_in, found in cases:
            fake_claude(self.tmp, signed_in)
            self.draft.write_text("Next steps: read the board.", encoding="utf-8")
            with mock.patch.object(cmd_handoff.shutil, "which", side_effect=found):
                lines = [line for line in self.write().splitlines() if "not started" in line]
            self.assertEqual(1, len(lines), reason)
            self.assertIn(reason, lines[0])
            self.assertIn("Paste this into a new session: Run ", lines[0])
            self.assertIn("handoff read Shop", lines[0])


class LongThread(unittest.TestCase):
    """#1319: a thread past 250,000 tokens of context is flagged once per session, and never in a headless builder."""

    def setUp(self):
        self.tmp = temp_dir(self)
        self.transcript = self.tmp / "t.jsonl"

    def write(self, tokens):
        usage = {"input_tokens": 10, "cache_read_input_tokens": tokens - 10, "cache_creation_input_tokens": 0}
        self.transcript.write_text(json.dumps({"message": {"usage": {"input_tokens": 1}}}) + "\n"
                                   + json.dumps({"message": {"usage": usage}}) + "\n", encoding="utf-8")

    def run_hook(self, session="s1", headless=False, signed_in=True):
        script = str(REPO_ROOT / "scripts" / "hooks" / "status_hint.py")
        fake_claude(self.tmp, signed_in)
        env = dict(os.environ, OLIVERCODE_HOME=str(self.tmp), PATH=f"{self.tmp}{os.pathsep}{os.environ['PATH']}")
        env.pop("OLIVERCODE_HEADLESS", None)
        if headless:
            env["OLIVERCODE_HEADLESS"] = "1"
        data = {"prompt": "fix the parser", "session_id": session, "transcript_path": str(self.transcript)}
        return subprocess.run([sys.executable, script], input=json.dumps(data), capture_output=True, text=True, env=env).stdout

    def test_a_long_thread_is_flagged_once_per_session(self):
        self.write(260_000)
        self.assertIn("olivercode handoff write", self.run_hook())
        self.assertEqual("", self.run_hook())
        self.assertIn("olivercode handoff write", self.run_hook(session="s2"))

    def test_the_line_says_handoff_write_starts_the_next_thread(self):
        self.write(260_000)
        self.assertIn("`olivercode handoff write PROJECT FILE`, which starts the next thread", self.run_hook())

    def test_on_a_machine_that_cannot_start_it_the_line_gives_the_reason_and_the_prompt(self):
        self.write(260_000)
        out = self.run_hook(signed_in=False)
        self.assertIn("the claude CLI is not signed in", out)
        self.assertIn("handoff read PROJECT in ", out)

    def test_a_short_thread_and_a_headless_builder_get_nothing(self):
        self.write(200_000)
        self.assertEqual("", self.run_hook())
        self.write(400_000)
        self.assertEqual("", self.run_hook(headless=True))

    def test_an_unreadable_transcript_counts_as_short(self):
        self.assertEqual(0, hint.context_tokens(self.tmp / "absent.jsonl"))


if __name__ == "__main__":
    unittest.main()
