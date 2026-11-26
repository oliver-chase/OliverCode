"""City (#1335): the page tells the story of the work from the figures `olivercode status` uses, with no model call."""

import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import city, cmd_status  # noqa: E402

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
DONE = {"story": "story-7", "repo": "r", "at": NOW.timestamp() - 600, "total": 300, "cost": 0.14}


def data(**kw):
    base = {"slug": "o/r", "now": NOW, "open": 3, "waiting": [], "building": ["Runner idle: no story is building. Start it with `olivercode drain REPO`."],
            "warnings": [], "busy": False, "landed": [], "pace": "o/r: 3 open. 0.0 stories landed per day."}
    return {**base, **kw}


class TestCity(unittest.TestCase):
    def test_the_page_leads_with_the_owner_then_building_then_landed_then_pace(self):
        page = city.render(data(waiting=["- #9 Approve the change"], busy=True, building=["#5 in r: building for 3 minutes, 4 minutes in all."], landed=[DONE]))
        order = [page.index(f"<h2>{h}</h2>") for h in ("Needs you", "Building", "Landed today", "Pace")]
        self.assertEqual(order, sorted(order))
        self.assertIn("#7 in r landed at 11:50 UTC, 5 minutes, $0.14", page)
        self.assertIn("1 landed for $0.14 today", page)

    def test_idle_and_running_look_distinct_and_commands_are_purple(self):
        idle, busy = city.render(data()), city.render(data(busy=True))
        self.assertIn('class="idle"', idle)
        self.assertIn('class="pill idle">Idle', idle)
        self.assertIn('class="run"', busy)
        self.assertIn('class="pill running">Running', busy)
        self.assertIn("<code>olivercode drain REPO</code>", idle)

    def test_a_figure_that_was_not_read_is_unknown_and_text_is_escaped(self):
        page = city.render(data(open=None, landed=None, waiting=["<script>x</script>"]))
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertIn("Unknown", page)
        self.assertIn('<div class="big">unknown</div>', page)

    def test_the_page_has_one_file_and_no_sideways_scroll(self):
        page = city.render(data())
        self.assertIn("width=device-width", page)
        self.assertIn("overflow-x:hidden", page)
        self.assertNotIn("http", page)

    def write(self, open_now, rows):
        home = temp_dir(self)
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}), mock.patch.object(cmd_status, "run_log", return_value=[]), \
                mock.patch.object(cmd_status, "live_claims", return_value={}), mock.patch.object(cmd_status, "runner_alive", return_value=False), \
                mock.patch("lib.gh_budget.refusal", return_value=""):
            code = city.write("o/r", count=lambda s, state: open_now, fetch=lambda s, since: rows, now=NOW, out=lambda t: None, waiting=lambda: [])
        return code, (home / "city.html").read_text(encoding="utf-8")

    def test_write_reads_the_status_functions_and_writes_one_file(self):
        code, text = self.write(2, [])
        self.assertEqual(code, 0)
        self.assertIn("2 open", text)
        self.assertIn("Nothing has landed today.", text)

    def test_write_exits_1_when_github_could_not_be_read(self):
        code, text = self.write(None, None)
        self.assertEqual(code, 1)
        self.assertIn("unknown", text)


if __name__ == "__main__":
    unittest.main()
