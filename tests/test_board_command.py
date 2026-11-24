"""`olivercode board` and the `manager` message subcommands send each job to the module that owns it (#676)."""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_board  # noqa: E402


class TestBoardCommand(unittest.TestCase):
    def test_each_board_job_gets_its_own_flags(self):
        for job, module, fn in (("groom", "cmd_groom", "command_groom"), ("sync", "cmd_boardsweep", "command_board_sweep")):
            with mock.patch.object(getattr(cmd_board, module), fn, return_value=7) as run:
                self.assertEqual(cmd_board.command_board([job, "--schedule"]), 7)
            run.assert_called_once_with(["--schedule"])

    def test_an_unknown_job_prints_the_usage(self):
        for argv in ([], ["sweep"]):
            with mock.patch("builtins.print") as out:
                self.assertEqual(cmd_board.command_board(argv), 1)
            out.assert_called_once_with(cmd_board.USAGE)


GOOD_BODY = """**As the owner**, I want a story filed only when its format check passes, so that nothing is missing.

```gherkin
Feature: Filing stops on a failed check
  Scenario: A complete body files
    Given a body that passes the format check
    When it is filed
    Then the issue is created
```

Epic: #1043
Blocked by: none.
Priority: P1. Size: S. Work type: Story.
Existing coverage checked: searched open stories for the format check, found none.
Files area: scripts/lib/cmd_board.py
"""


class TestBoardFile(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory(prefix="olivercode-test-file-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "docs").mkdir()
        self.config = root / "docs" / "backlog-config.json"
        self.config.write_text('{"repoOwner": "owner", "repoName": "repo"}', encoding="utf-8")

    def file(self, body, gh_out="42\n", batch_code=0):
        body_file = Path(self.tmp.name) / "body.md"
        body_file.write_text(body, encoding="utf-8")
        argv = [str(body_file), "--title", "A title", "--config", str(self.config)]
        with mock.patch.object(cmd_board.cmd_groom, "gh", return_value=gh_out) as gh, \
                mock.patch("batch_project.main", return_value=batch_code) as batch, \
                mock.patch("builtins.print") as out:
            code = cmd_board.command_board(["file", *argv])
        return code, gh, batch, [c.args[0] for c in out.call_args_list]

    def test_a_body_missing_its_epic_link_files_nothing(self):
        code, gh, batch, out = self.file(GOOD_BODY.replace("Epic: #1043\n", ""))
        self.assertEqual(code, 1)
        gh.assert_not_called()
        batch.assert_not_called()
        self.assertTrue(any(line.startswith("MISSING Epic link.") for line in out))

    def test_a_body_naming_a_line_number_files_nothing(self):
        code, gh, batch, out = self.file(GOOD_BODY.replace("Files area: scripts/lib/cmd_board.py",
                                                           "Files area: scripts/lib/cmd_board.py, see scripts/lib/cmd_board.py:12"))
        self.assertEqual(code, 1)
        gh.assert_not_called()
        self.assertTrue(any('Line number "scripts/lib/cmd_board.py:12" in the body' in line for line in out))

    def test_a_complete_body_creates_the_issue_and_sets_its_fields_in_one_batch(self):
        seen = {}

        def batch(argv):
            seen["fields"] = json.loads(Path(argv[argv.index("--input") + 1]).read_text(encoding="utf-8"))
            return 0

        with mock.patch.object(cmd_board.cmd_groom, "gh", return_value="42\n") as gh, \
                mock.patch("batch_project.main", side_effect=batch) as main, \
                mock.patch("builtins.print"):
            code = cmd_board.command_board(["file", str(self._body(GOOD_BODY)), "--title", "A title", "--config", str(self.config)])
        self.assertEqual(code, 0)
        self.assertEqual(gh.call_args.args[0][:4], ["api", "-X", "POST", "repos/owner/repo/issues"])
        self.assertEqual(seen["fields"], {"issues": [{"number": 42, "fields": {
            "status": "Backlog", "priority": "P1", "size": "S", "workType": "Story"}}]})
        self.assertEqual(main.call_args.args[0][:2], ["--config", str(self.config)])

    def test_a_refused_create_names_the_refusal_and_sets_no_fields(self):
        code, gh, batch, out = self.file(GOOD_BODY, gh_out="")
        self.assertEqual(code, 1)
        batch.assert_not_called()
        self.assertIn("A title: not filed, GitHub refused to make the issue", out)

    def _body(self, text):
        path = Path(self.tmp.name) / "good.md"
        path.write_text(text, encoding="utf-8")
        return path
