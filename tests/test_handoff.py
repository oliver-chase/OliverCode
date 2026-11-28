"""One live handoff per project, deleted once read, and a draft whose command would print a usage error is never filed (#1321)."""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, quiet, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_drain, cmd_handoff, cmd_owner  # noqa: E402


class Handoff(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self)
        self.folder = self.tmp / "Claude"
        self.folder.mkdir()
        self.home = self.tmp / "home"
        self.env = mock.patch.dict(os.environ, {"OLIVERCODE_HANDOFF_DIR": str(self.folder), "OLIVERCODE_HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def put(self, name, text="x"):
        path = self.folder / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_cmd(self, *argv):
        return quiet(cmd_handoff.command_handoff, list(argv))

    def test_a_new_handoff_is_the_only_one_for_its_project(self):
        old = self.put("OliverCode-handoff-2026-11-26.md")
        other = self.put("Pattern-handoff-2026-11-26.md")
        folder = self.folder / "pattern-handoff"
        folder.mkdir()
        (folder / "keep.txt").write_text("project file", encoding="utf-8")
        draft = self.tmp / "draft.md"
        draft.write_text("Next steps: read the board.", encoding="utf-8")
        self.assertEqual(0, self.run_cmd("write", "OliverCode", str(draft))[0])
        left = cmd_handoff.handoffs("OliverCode", self.folder)
        self.assertEqual(1, len(left))
        self.assertEqual("Next steps: read the board.", left[0].read_text(encoding="utf-8"))
        self.assertFalse(old.exists() and old != left[0])
        self.assertTrue(other.exists())
        self.assertTrue((folder / "keep.txt").exists())

    def test_a_handoff_already_in_the_folder_is_kept_and_the_older_one_goes(self):
        old = self.put("OliverCode-handoff-2026-11-25.md")
        new = self.put("OliverCode-handoff-2026-11-26.md", "new")
        self.assertEqual(0, self.run_cmd("write", "OliverCode", str(new))[0])
        self.assertTrue(new.exists())
        self.assertFalse(old.exists())

    def test_read_prints_the_handoff_and_deletes_it(self):
        path = self.put("OliverCode-handoff-2026-11-26.md", "continue here")
        other = self.put("Pattern-handoff-2026-11-26.md")
        code, _ = self.run_cmd("read", "OliverCode")
        self.assertEqual(0, code)
        self.assertFalse(path.exists())
        self.assertTrue(other.exists())
        self.assertEqual([other], list(self.folder.iterdir()))

    def test_read_of_a_handoff_that_names_a_drain_says_to_watch_it(self):
        self.put("OliverCode-handoff-2026-11-26.md", "Run `olivercode drain OliverCode --parallel 2` next.")
        with mock.patch.object(cmd_drain, "resolve_repo", return_value=Path("/r")):
            _, out = self.run_cmd("read", "OliverCode")
        self.assertEqual(1, out.count("olivercode watch OliverCode --until-exit` in the background"))
        self.assertIn("Never use Monitor", out)

    def test_read_of_a_handoff_with_no_drain_prints_no_watch_line(self):
        self.put("OliverCode-handoff-2026-11-26.md", "Next steps: read the board.")
        _, out = self.run_cmd("read", "OliverCode")
        self.assertNotIn("olivercode watch", out)

    def test_read_ignores_a_drain_that_does_not_resolve(self):
        self.put("OliverCode-handoff-2026-11-26.md", "Run `olivercode drain nowhere-repo` next.")
        with mock.patch.object(cmd_drain, "resolve_repo", return_value=None):
            _, out = self.run_cmd("read", "OliverCode")
        self.assertNotIn("olivercode watch", out)

    def test_read_with_no_handoff_says_so(self):
        self.assertEqual(1, self.run_cmd("read", "OliverCode")[0])

    def test_read_with_no_handoff_prints_no_detach_line(self):
        code, out = self.run_cmd("read", "OliverCode")
        self.assertEqual(1, code)
        self.assertNotIn("Detach:", out)

    def test_read_says_to_detach_self_only_when_the_session_nests(self):
        self.put("OliverCode-handoff-2026-11-26.md")
        out = self.read_as("s2")
        self.assertIn('Detach: if this session nests under the session that started it, call detach_session with "self".', out)
        self.assertIn("Skip the call when this session is already at the top level or the owner placed it.", out)

    def test_with_no_folder_set_the_handoff_folder_is_the_working_directory(self):
        os.environ.pop("OLIVERCODE_HANDOFF_DIR")
        cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, cwd)
        self.assertEqual(self.tmp.resolve(), cmd_handoff.handoff_dir().resolve())

    def test_a_folder_that_looks_like_a_handoff_is_untouched(self):
        folder = self.folder / "OliverCode-handoff-2026-11-26.md"
        folder.mkdir()
        self.assertEqual(1, self.run_cmd("read", "OliverCode")[0])
        self.assertTrue(folder.is_dir())

    def test_a_draft_with_an_unresolved_repo_writes_nothing(self):
        old = self.put("OliverCode-handoff-2026-11-25.md")
        draft = self.tmp / "draft.md"
        draft.write_text("ok\nRun `olivercode drain nowhere-repo` next.\n", encoding="utf-8")
        with mock.patch.object(cmd_drain, "resolve_repo", return_value=None) as resolve, \
                mock.patch.object(cmd_drain, "command_drain") as drain, mock.patch("subprocess.run") as run:
            self.assertEqual(1, self.run_cmd("write", "OliverCode", str(draft))[0])
        resolve.assert_called_once_with("nowhere-repo")
        drain.assert_not_called()
        run.assert_not_called()
        self.assertTrue(old.exists())
        self.assertTrue(draft.exists())
        self.assertEqual([old], list(self.folder.iterdir()))

    def test_errors_name_the_line(self):
        with mock.patch.object(cmd_drain, "resolve_repo", return_value=Path("/r")):
            errors = cmd_handoff.command_errors("a\n`olivercode drain` now\n`olivercode dispatch abc`\n`olivercode drain repo --parallel 2`\n`olivercode dispatch 12 --dry-run`")
        self.assertEqual(2, len(errors))
        self.assertTrue(errors[0].startswith("line 2:") and errors[1].startswith("line 3:"))

    def test_prose_that_names_a_command_is_not_checked_but_a_fenced_one_is(self):
        with mock.patch.object(cmd_drain, "resolve_repo", return_value=Path("/r")):
            prose = "run olivercode drain OliverCode to continue\nthe olivercode drain command\nolivercode dispatch 12 next"
            self.assertEqual([], cmd_handoff.command_errors(prose))
            errors = cmd_handoff.command_errors("```\n$ olivercode dispatch abc\n```\nolivercode drain a b")
        self.assertEqual(1, len(errors))
        self.assertTrue(errors[0].startswith("line 2:"))

    def write_draft(self, session="s1"):
        draft = self.tmp / "draft.md"
        draft.write_text("Next steps: read the board.", encoding="utf-8")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": session}):
            return self.run_cmd("write", "OliverCode", str(draft))[1]

    def read_as(self, session):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": session}):
            return self.run_cmd("read", "OliverCode")[1]

    def test_write_prints_the_desktop_calls_and_starts_nothing_itself(self):
        self.home.mkdir()
        (self.home / cmd_handoff.THREAD_NUMBERS).write_text('{"OliverCode": 8}', encoding="utf-8")
        with mock.patch("subprocess.run") as run, mock.patch("subprocess.Popen") as popen:
            out = self.write_draft()
        run.assert_not_called()
        popen.assert_not_called()
        self.assertIn(f"call start_session with this prompt: {cmd_handoff.read_prompt('OliverCode', self.folder)}", out)
        self.assertIn('call set_session_title for the new session with "OliverCode 9"', out)
        self.assertIn("call set_pinned for the new session with pinned=true", out)
        self.assertIn("call set_pinned for s1 with pinned=false", out)
        self.assertNotIn("Remote Control", out)

    def test_write_says_to_detach_the_new_session_right_after_start(self):
        self.home.mkdir()
        out = self.write_draft()
        lines = out.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("Start:"))
        detach = next(i for i, line in enumerate(lines) if line.startswith("Detach:"))
        title = next(i for i, line in enumerate(lines) if line.startswith("Title:"))
        self.assertEqual(start + 1, detach)
        self.assertLess(detach, title)
        self.assertIn("call detach_session for the new session", lines[detach])

    def test_the_new_thread_keeps_the_number_write_gave_it_and_repeats_no_call_it_already_got(self):
        self.home.mkdir()
        (self.home / cmd_handoff.THREAD_NUMBERS).write_text('{"OliverCode": 8}', encoding="utf-8")
        self.write_draft()
        out = self.read_as("s2")
        before, _, if_missing = out.partition('Thread: this one is "OliverCode 9". If its title says so and it is pinned, no rename or pin step is needed.')
        self.assertNotIn("set_session_title", before)
        self.assertNotIn("set_pinned", before)
        self.assertIn("If either is missing, make these calls:", if_missing)
        state = json.loads((self.home / cmd_handoff.THREAD_SESSIONS).read_text(encoding="utf-8"))
        self.assertEqual(({"OliverCode": 9}, "s2", {}), (state["sessions"]["s2"], state["pinned"]["OliverCode"], state["reserved"]))

    def test_a_thread_that_did_not_get_writes_calls_is_given_its_title_and_the_pin(self):
        cmd_handoff.claim_thread("OliverCode", "s1")
        self.write_draft()
        out = self.read_as("pasted")
        self.assertIn('call set_session_title for pasted with "OliverCode 2"', out)
        self.assertIn("call set_pinned for pasted with pinned=true", out)
        self.assertIn("call set_pinned for s1 with pinned=false", out)

    def test_a_chat_opened_between_write_and_read_loses_the_pin(self):
        cmd_handoff.claim_thread("OliverCode", "s1")
        self.write_draft()
        cmd_handoff.claim_thread("OliverCode", "by-hand")
        before, _, if_missing = self.read_as("s2").partition("Thread: this one is")
        self.assertIn("call set_pinned for by-hand with pinned=false", before)
        self.assertNotIn("by-hand", if_missing)

    def test_a_numbered_session_that_reads_a_handoff_gets_no_pin_call(self):
        cmd_handoff.claim_thread("OliverCode", "s2")
        cmd_handoff.claim_thread("OliverCode", "s1")
        self.write_draft()
        out = self.read_as("s2")
        self.assertIn('"OliverCode 1", and no new name is needed', out)
        self.assertNotIn("set_pinned", out)

    def test_write_also_unpins_a_newer_thread_that_took_the_pin(self):
        cmd_handoff.claim_thread("OliverCode", "newer")
        out = self.write_draft()
        self.assertIn("call set_pinned for s1 with pinned=false", out)
        self.assertIn("call set_pinned for newer with pinned=false", out)

    def test_the_old_thread_unpins_itself_unless_the_owner_queue_names_it(self):
        with mock.patch.object(cmd_owner, "open_items", return_value=[{"session": "s1", "status": "open"}]):
            out = self.write_draft()
        self.assertNotIn("pinned=false", out)
        self.assertIn("leave it pinned", out)

    def test_a_thread_write_did_not_name_is_pinned_in_place_of_the_old_one(self):
        cmd_handoff.claim_thread("OliverCode", "s1")
        self.put("OliverCode-handoff-2026-11-26.md")
        out = self.read_as("s2")
        self.assertIn("call set_pinned for s2 with pinned=true", out)
        self.assertIn("call set_pinned for s1 with pinned=false", out)

    def test_the_new_thread_is_numbered_from_the_stored_count(self):
        self.home.mkdir()
        (self.home / cmd_handoff.THREAD_NUMBERS).write_text('{"OliverCode": 2}', encoding="utf-8")
        self.put("OliverCode-handoff-2026-11-26.md", "continue here")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "s2"}):
            _, out = self.run_cmd("read", "OliverCode")
        self.assertIn('call set_session_title for s2 with "OliverCode 3"', out)
        self.assertIn("Owner ·", out)
        self.assertEqual({"OliverCode": 3}, json.loads((self.home / cmd_handoff.THREAD_NUMBERS).read_text(encoding="utf-8")))

    def test_the_number_wraps_after_ten(self):
        self.home.mkdir()
        (self.home / cmd_handoff.THREAD_NUMBERS).write_text('{"Shop": 10}', encoding="utf-8")
        self.put("Shop-handoff-2026-11-26.md")
        _, out = self.run_cmd("read", "Shop")
        self.assertIn('with "Shop 1"', out)

    def test_a_repo_with_no_number_starts_at_one_and_an_overwritten_handoff_uses_none(self):
        self.put("Pattern-handoff-2026-11-26.md")
        for _ in range(2):
            self.assertIn('with "OliverCode 1"', self.write_draft())
        _, out = self.run_cmd("read", "Pattern")
        self.assertIn('with "Pattern 1"', out)

    def test_a_bad_call_prints_the_usage(self):
        self.assertEqual(1, self.run_cmd("write", "OliverCode")[0])


if __name__ == "__main__":
    unittest.main()
