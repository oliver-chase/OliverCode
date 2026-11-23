"""olivercode decisions import turns a markdown decisions log into decision records, once."""

import os
import re
import sys
import unittest
from datetime import date, timedelta
from unittest import mock

from _support import REPO_ROOT, quiet, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import relay  # noqa: E402
from lib import decisions  # noqa: E402


def _log(today):
    old = (today - timedelta(days=200)).isoformat()
    new = (today - timedelta(days=5)).isoformat()
    return (f"# Decisions\n\n## {new} Use pm2\nRun the bot under pm2.\n\n## {new} Keep the database local\nThe database is 42 GB database size.\n\n"
            f"## {old} Weekly backups\nBack up on Sundays.\n\n## {new} Pin Python\nUse 3.12.\n\n"
            f"## {new} Move the database\nThe database is now 65 GB database size.\n")


class TestDecisionsImport(unittest.TestCase):
    def setUp(self):
        home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.file = temp_dir(self) / "decisions.md"
        self.file.write_text(_log(date.today()), encoding="utf-8")
        self.before = self.file.read_bytes()

    def test_five_entries_become_five_records_and_two_are_flagged_and_the_file_is_unchanged(self):
        code, out = quiet(decisions.command_decisions, ["import", str(self.file)])
        self.assertEqual(code, 0)
        recs = relay.records()
        self.assertEqual(len(recs), 5)
        flagged = [r for r in recs if r.get("flag") == "reconfirm"]
        self.assertEqual(sorted(r["title"].split(" ", 1)[1] for r in flagged), ["Keep the database local", "Weekly backups"])
        self.assertIn("more than 90 days", out)
        self.assertIn("65", out)
        self.assertTrue(all(re.search(r":\d+$", r["source"]) and str(self.file.resolve()) in r["source"] for r in recs))
        self.assertEqual(self.file.read_bytes(), self.before)

    def test_a_second_run_adds_no_duplicates(self):
        quiet(decisions.command_decisions, ["import", str(self.file)])
        code, out = quiet(decisions.command_decisions, ["import", str(self.file)])
        self.assertEqual(code, 0)
        self.assertEqual(len(relay.records()), 5)
        self.assertIn("Imported 0", out)

    def test_bullets_import_when_there_are_no_headings_and_a_missing_or_empty_file_fails(self):
        self.file.write_text("- Use pm2\n- Pin Python\n", encoding="utf-8")
        self.assertEqual(quiet(decisions.command_decisions, ["import", str(self.file)])[0], 0)
        self.assertEqual(len(relay.records()), 2)
        self.file.write_text("nothing here\n", encoding="utf-8")
        self.assertEqual(quiet(decisions.command_decisions, ["import", str(self.file)])[0], 1)
        self.assertEqual(quiet(decisions.command_decisions, ["import", str(self.file) + ".none"])[0], 1)
        self.assertEqual(quiet(decisions.command_decisions, [])[0], 1)


if __name__ == "__main__":
    unittest.main()
