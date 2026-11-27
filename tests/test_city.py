"""City v2 (#1356): the page's frame is drawn from local files, and only `--fetch` calls GitHub."""

import json
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import city, city_cost, city_delivery, city_health, cmd_status  # noqa: E402

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
DONE = {"story": "story-7", "repo": "r", "at": NOW.timestamp() - 600, "total": 300, "cost": 0.14}


def data(**kw):
    base = {"slug": "o/r", "now": NOW, "steps": [], "building": ["Runner idle: no story is building."], "warnings": [], "busy": False, "builders": 0,
            "landed": [], "ready": 0, "github": None, "log": [], "until": 0}
    return {**base, **kw}


class TestCity(unittest.TestCase):
    def test_the_frame_has_the_nav_and_a_status_band_that_reloads_every_minute(self):
        page = city.render(data(steps=[{"id": 9, "step": "Approve"}, {"id": 10, "step": "Decline"}], busy=True, builders=2))
        for name in ("Today", "Delivery", "Cost", "Health"):
            self.assertIn(f">{name}</a>", page)
        self.assertIn('<meta http-equiv="refresh" content="60">', page)
        for part in ("2 builders", "2 need you", "Updated 12:00 UTC", ">Refresh</button>"):
            self.assertIn(part, page)

    def test_the_band_shows_each_states_word_and_sentence(self):
        cases = {
            "Building": (data(busy=True, builders=2), "2 builders are working"),
            "Idle": (data(ready=7), "7 stories are Ready, so starting the drain would take them in priority order"),
            "Stopped": (data(warnings=["Warning: #5 stopped"]), "#5 stopped"),
            "Waiting": (data(until=NOW.timestamp() + 600), "paused until about 12:10 UTC and will carry on by itself"),
        }
        for word, (d, sentence) in cases.items():
            page = city.render(d)
            self.assertIn(f"<i></i>{word}</span>", page)
            self.assertIn(sentence, page)
        self.assertIn("no story is Ready. The drain has nothing to take until a story is marked Ready", city.render(data()))
        self.assertIn("Nothing waits on you.", city.render(data()))
        self.assertNotIn("need you</a>", city.render(data()))

    def test_an_old_page_says_so_and_how_old(self):
        page = city.render(data())
        self.assertIn(f'data-written="{int(NOW.timestamp())}"', page)
        self.assertIn("age>600", page)
        self.assertIn("Out of date", page)
        self.assertIn("minutes", page)

    def test_the_phone_order_is_status_needs_you_building_then_the_sections(self):
        page = city.render(data())
        self.assertIn("max-width:600px", page)
        order = [page.index(x) for x in ('class="band b-idle"', 'id="needs"', 'id="live"', 'id="today"', 'id="delivery"', 'id="cost"', 'id="health"')]
        self.assertEqual(order, sorted(order))

    def test_text_is_escaped_and_the_page_is_one_file(self):
        page = city.render(data(steps=[{"id": 1, "step": "<script>x</script>"}], landed=None))
        self.assertIn("&lt;script&gt;", page)
        self.assertEqual(page.count("<script>"), 1)
        self.assertIn("overflow-x:hidden", page)
        self.assertIn("unknown", page)

    def test_github_figures_show_when_they_were_read(self):
        figures = {"slug": "o/r", "read_at": NOW.timestamp(), "open": 4, "opened": 6, "closed": 9, "checks": []}
        page = city.render(data(github=figures))
        self.assertIn("4 open. In the last 7 days 9 closed as completed and 6 opened.", page)
        self.assertIn("Read from GitHub at 12:00 UTC.", page)
        self.assertIn("not recorded yet", city.render(data()))

    def test_an_unread_open_count_is_never_printed_as_none(self):
        figures = {"slug": "o/r", "read_at": NOW.timestamp(), "open": None, "opened": 6, "closed": 9, "checks": None}
        page = city.render(data(github=figures))
        self.assertNotIn("None", page)
        self.assertIn("9 closed as completed and 6 opened.", page)

    def test_each_section_module_renders_its_own_anchor(self):
        for module, anchor in ((city_delivery, "delivery"), (city_cost, "cost"), (city_health, "health")):
            self.assertIn(f'id="{anchor}"', module.render(data()))

    def write(self, fetch=False, read=None, saved=None):
        home = temp_dir(self)
        root = temp_dir(self)
        if saved:
            (home / "city-github.json").write_text(json.dumps(saved), encoding="utf-8")
        calls = []
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}), mock.patch.object(cmd_status, "run_log", return_value=[]), \
                mock.patch.object(cmd_status, "live_claims", return_value={}), mock.patch.object(cmd_status, "runner_alive", return_value=False), \
                mock.patch("lib.gh_budget.refusal", return_value=""), mock.patch("lib.gh_budget.blocked_until", return_value=0), \
                mock.patch("lib.run_lock.active", return_value=None):
            code = city.write("o/r", root, fetch=fetch, now=NOW, out=lambda t: None, waiting=lambda: [], read=lambda *a: calls.append(a) or read)
        return code, (home / "city.html").read_text(encoding="utf-8"), home, calls

    def test_a_plain_write_makes_no_github_call(self):
        code, text, home, calls = self.write()
        self.assertEqual((code, calls), (0, []))
        self.assertIn("Nothing has landed today.", text)
        self.assertFalse((home / "city-github.json").exists())

    def test_a_plain_write_reads_the_saved_github_figures(self):
        saved = {"slug": "o/r", "read_at": NOW.timestamp(), "open": 2, "opened": 1, "closed": 3, "checks": []}
        _, text, _, calls = self.write(saved=saved)
        self.assertEqual(calls, [])
        self.assertIn("2 open.", text)

    def test_fetch_reads_github_once_and_saves_it_with_the_time(self):
        figures = {"slug": "o/r", "read_at": NOW.timestamp(), "open": 5, "opened": 2, "closed": 1, "checks": [{"name": "ci", "conclusion": "success"}]}
        code, text, home, calls = self.write(fetch=True, read=figures)
        self.assertEqual((code, len(calls)), (0, 1))
        self.assertEqual(json.loads((home / "city-github.json").read_text(encoding="utf-8")), figures)
        self.assertIn("Read from GitHub at 12:00 UTC.", text)

    def test_fetch_exits_1_when_a_figure_could_not_be_read_and_still_writes_the_page(self):
        code, text, _, _ = self.write(fetch=True, read={"slug": "o/r", "read_at": NOW.timestamp(), "open": None, "opened": None, "closed": None, "checks": None})
        self.assertEqual(code, 1)
        self.assertIn("not recorded yet", text)

    def test_read_github_counts_the_week_and_the_checks(self):
        rows = [{"created_at": "2026-11-21T00:00:00Z", "state_reason": "completed", "closed_at": "2026-11-21T01:00:00Z"}, {"created_at": "2026-11-01T00:00:00Z"}]
        done = mock.Mock(returncode=0, stdout=json.dumps({"check_runs": [{"name": "ci", "conclusion": "failure"}]}))
        got = city.read_github("o/r", NOW, count=lambda s, st: 4, fetch=lambda s, since: rows, runner=lambda args: done)
        self.assertEqual((got["open"], got["opened"], got["closed"], got["checks"]), (4, 1, 1, [{"name": "ci", "conclusion": "failure"}]))

    def test_the_ready_count_comes_from_the_board_copy(self):
        home, root = temp_dir(self), temp_dir(self)
        (root / "docs").mkdir()
        (root / "docs" / "backlog-config.json").write_text(json.dumps({"projectOwner": "me", "projectNumber": 3}), encoding="utf-8")
        items = [{"status": "Ready", "content": {"repository": "o/r"}}, {"status": "Ready", "content": {"repository": "o/other"}}, {"status": "Backlog", "content": {}}]
        (home / "board-me-3.json").write_text(json.dumps(items), encoding="utf-8")
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}):
            self.assertEqual(city.board_ready(root, "o/r"), 1)
            self.assertIsNone(city.board_ready(temp_dir(self), "o/r"))


if __name__ == "__main__":
    unittest.main()
