"""#1000: a status-only message is blocked with the digest lines as the reason, a mixed one goes through with context, and "ask:" passes unchanged."""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, git, load_script, quiet, scratch_repo, temp_dir

hint = load_script("scripts/hooks/status_hint.py")
from lib import cmd_handoff, cmd_owner  # noqa: E402  (the hint's load puts scripts/ on the path)

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


class NewThread(unittest.TestCase):
    """#1488: a new OliverCode chat takes the next thread number and the pin, once, however it starts."""

    def setUp(self):
        self.tmp = temp_dir(self, resolve=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        (self.home / cmd_handoff.THREAD_NUMBERS).write_text('{"OliverCode": 8}', encoding="utf-8")
        (self.home / cmd_handoff.THREAD_SESSIONS).write_text(
            json.dumps({"sessions": {"A": {"OliverCode": 8}}, "pinned": {"OliverCode": "A"}}), encoding="utf-8")
        env = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("OLIVERCODE_HEADLESS", None)  # restored with the patch

    def run_hook(self, prompt="we need to go back to olivercode", session="B", cwd=None, transcript="absent.jsonl"):
        script = str(REPO_ROOT / "scripts" / "hooks" / "status_hint.py")
        data = {"prompt": prompt, "session_id": session, "cwd": str(cwd or self.tmp), "transcript_path": str(self.tmp / transcript)}
        done = subprocess.run([sys.executable, script], input=json.dumps(data), capture_output=True, text=True)
        self.assertEqual((0, ""), (done.returncode, done.stderr))
        return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"] if done.stdout else ""

    def state(self):
        return json.loads((self.home / cmd_handoff.THREAD_SESSIONS).read_text(encoding="utf-8"))

    def last_number(self):
        return json.loads((self.home / cmd_handoff.THREAD_NUMBERS).read_text(encoding="utf-8"))["OliverCode"]

    def test_a_chat_opened_by_hand_that_names_olivercode_is_numbered_and_pinned(self):
        out = self.run_hook()
        self.assertIn('call set_session_title for B with "OliverCode 9"', out)
        self.assertIn("call set_pinned for B with pinned=true", out)
        self.assertIn("call set_pinned for A with pinned=false", out)
        self.assertEqual({"OliverCode": 9}, self.state()["sessions"]["B"])
        self.assertEqual("B", self.state()["pinned"]["OliverCode"])

    def test_a_chat_in_the_olivercode_repo_is_numbered_whatever_the_prompt_says(self):
        for session, cwd in (("B", REPO_ROOT), ("C", REPO_ROOT / "scripts")):
            self.assertIn(f"call set_pinned for {session} with pinned=true", self.run_hook("fix the parser", session, cwd))
        self.assertEqual(10, self.last_number())

    def test_the_main_checkout_counts_when_the_hook_runs_from_a_worktree(self):
        main, worktree = scratch_repo(self.tmp / "OC", branch="main"), self.tmp / "oc-staging"
        git(main, "commit", "-q", "--allow-empty", "-m", "first")
        git(main, "worktree", "add", "-q", str(worktree))
        with mock.patch.object(hint, "OC_ROOT", worktree):
            out = hint.new_thread_note({"prompt": "fix the parser", "session_id": "B", "cwd": str(main)})
        self.assertIn("call set_pinned for B with pinned=true", out)

    def test_a_chat_about_something_else_is_left_alone(self):
        self.assertEqual("", self.run_hook("fix the parser"))
        self.assertEqual(8, self.last_number())

    def test_a_session_is_numbered_once(self):
        self.run_hook()
        self.assertEqual("", self.run_hook("more olivercode work"))
        self.assertEqual({"OliverCode": 9}, self.state()["sessions"]["B"])
        self.assertEqual(9, self.last_number())

    def test_a_later_prompt_of_an_unnumbered_chat_takes_no_pin(self):
        (self.tmp / "t.jsonl").write_text(json.dumps({"message": {"usage": {"input_tokens": 50}}}) + "\n", encoding="utf-8")
        self.assertEqual("", self.run_hook(transcript="t.jsonl"))
        self.assertEqual(8, self.last_number())

    def test_a_handoff_thread_holds_the_one_number_handoff_read_gives_it(self):
        prompt = cmd_handoff.read_prompt("OliverCode", self.tmp)
        quoted = "Run '/a b/scripts/olivercode' handoff read OliverCode in /tmp"
        for text in (prompt, quoted):
            self.assertEqual("", self.run_hook(text, cwd=REPO_ROOT), text)
        (self.tmp / "OliverCode-handoff-2026-11-27.md").write_text("next", encoding="utf-8")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "B"}):
            quiet(cmd_handoff.read, "OliverCode", self.tmp)
        self.assertEqual("", self.run_hook())
        self.assertEqual({"OliverCode": 9}, self.state()["sessions"]["B"])
        self.assertEqual(9, self.last_number())

    def test_an_open_owner_item_keeps_the_old_pin(self):
        cmd_owner.add("A", "approve the deploy")
        out = self.run_hook()
        self.assertNotIn("pinned=false", out)
        self.assertIn("names A, so leave it pinned", out)

    def test_the_title_call_keeps_the_owner_prefix(self):
        self.assertIn(f'keeping an "{cmd_owner.OWNER_PREFIX}" prefix in front', self.run_hook())

    def test_a_headless_builder_and_a_message_from_another_session_are_left_alone(self):
        self.assertEqual("", self.run_hook("<cross-session-message>olivercode</cross-session-message>"))
        os.environ["OLIVERCODE_HEADLESS"] = "1"
        self.assertEqual("", self.run_hook(cwd=REPO_ROOT))
        self.assertEqual(8, self.last_number())

    def test_the_session_map_keeps_its_newest_twenty(self):
        for number in range(25):
            cmd_handoff.claim_thread("OliverCode", f"s{number}")
        self.assertEqual([f"s{n}" for n in range(5, 25)], list(self.state()["sessions"]))


class LongThread(unittest.TestCase):
    """#1319: a thread past 250,000 tokens of context is flagged once per session, and never in a headless builder."""

    def setUp(self):
        self.tmp = temp_dir(self)
        self.transcript = self.tmp / "t.jsonl"

    def write(self, tokens):
        usage = {"input_tokens": 10, "cache_read_input_tokens": tokens - 10, "cache_creation_input_tokens": 0}
        self.transcript.write_text(json.dumps({"message": {"usage": {"input_tokens": 1}}}) + "\n"
                                   + json.dumps({"message": {"usage": usage}}) + "\n", encoding="utf-8")

    def run_hook(self, session="s1", headless=False):
        script = str(REPO_ROOT / "scripts" / "hooks" / "status_hint.py")
        env = dict(os.environ, OLIVERCODE_HOME=str(self.tmp))
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

    def test_the_line_says_handoff_write_gives_the_calls_that_start_the_next_thread(self):
        self.write(260_000)
        out = self.run_hook()
        self.assertIn("`olivercode handoff write PROJECT FILE` and make the calls it prints, which start the next thread in the desktop app", out)
        self.assertNotIn("Remote Control", out)

    def test_a_short_thread_and_a_headless_builder_get_nothing(self):
        self.write(200_000)
        self.assertEqual("", self.run_hook())
        self.write(400_000)
        self.assertEqual("", self.run_hook(headless=True))

    def test_an_unreadable_transcript_counts_as_short(self):
        self.assertEqual(0, hint.context_tokens(self.tmp / "absent.jsonl"))


if __name__ == "__main__":
    unittest.main()
