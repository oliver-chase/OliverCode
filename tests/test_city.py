"""#1097, #1177: City's dashboard is cached with no model call, carries the two terminal commands in plain text and has no terminal-styled panel."""

import os
import sys
import tempfile
import unittest
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import city, status_report  # noqa: E402

T0 = 1732460000.0


def fake_read(when):
    return "<p>2 open, 0 building.</p>"


class PanelCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": self.tmp.name})
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_second_read_inside_the_ttl_reuses_the_cached_dashboard_with_no_second_read(self):
        calls = []

        def counting(when):
            calls.append(1)
            return fake_read(when)

        first = city.panel_html(T0, runner=counting)
        second = city.panel_html(T0 + 60, runner=counting)
        self.assertEqual(first, second)
        self.assertEqual(1, len(calls))

    def test_a_stale_renderer_version_is_rebuilt_even_inside_the_ttl(self):
        calls = []
        city.failure_log.write_atomic(city.cache_path(), json.dumps({"version": city.PANEL_VERSION - 1, "at": T0, "html": "old dashboard"}))
        body = city.panel_html(T0 + 60, runner=lambda when: calls.append(when) or fake_read(when))
        self.assertIn("<p>2 open, 0 building.</p>", body)
        self.assertEqual(1, len(calls))

    def test_a_read_past_the_ttl_reads_again(self):
        calls = []

        def counting(when):
            calls.append(1)
            return fake_read(when)

        city.panel_html(T0, runner=counting)
        city.panel_html(T0 + city.PANEL_TTL + 1, runner=counting)
        self.assertEqual(2, len(calls))

    def test_the_cached_dashboard_is_written_to_the_home_folder_and_holds_what_was_read(self):
        body = city.panel_html(T0, runner=fake_read)
        self.assertIn("<p>2 open, 0 building.</p>", body)
        self.assertIn(f'href="{status_report.page_path().as_uri()}"', body)
        self.assertIn("refreshes every 60 seconds", body)
        cached = city._load_cache()
        self.assertEqual(body, cached["html"])
        self.assertIn("Open the live local page", cached["html"])
        self.assertEqual(T0, cached["at"])
        self.assertEqual({"version", "at", "html"}, set(cached))
        self.assertEqual(city.PANEL_VERSION, cached["version"])

    def test_portfolio_lists_multiple_registered_repositories_and_qualifies_the_metrics(self):
        state = {
            "org/alpha": {"active": True, "builders": 1, "building": {"1": {"at": T0, "n": 1, "title": "Building"}}, "queue": [{"n": 2, "title": "Queued"}], "held": [], "waiting": []},
            "org/beta": {"active": False, "builders": 1, "building": {}, "queue": [], "held": [], "waiting": []},
        }
        with mock.patch.object(status_report, "fleet_repos", return_value=[("org/alpha", Path("/alpha")), ("org/beta", Path("/beta"))]), \
             mock.patch.object(status_report, "load_state", return_value=state), \
             mock.patch.object(city.cmd_status, "run_log", return_value=[]), \
             mock.patch.object(status_report, "history", return_value=[]):
            page = city._portfolio_html(T0)
        self.assertIn("org/alpha", page)
        self.assertIn("org/beta", page)
        self.assertIn("Building across projects", page)
        self.assertIn("not GitHub backlog counts", page)
        self.assertIn("1 building", page)
        self.assertIn("1 queued", page)

    def test_each_repository_expands_into_its_own_story_and_history(self):
        state = {"org/alpha": {"active": False, "builders": 1, "building": {}, "queue": [], "held": [], "waiting": []}}
        log = [{"repo": "org/alpha", "story": "story-9", "landed": True, "title": "Alpha delivery", "at": "2026-11-25T10:00:00Z", "minutes": 12, "model": "haiku"}]
        with (
            mock.patch.object(status_report, "fleet_repos", return_value=[("org/alpha", Path("/alpha"))]),
            mock.patch.object(status_report, "load_state", return_value=state),
            mock.patch.object(city.cmd_status, "run_log", return_value=log),
        ):
            page = city._portfolio_html(1795600000.0)
        self.assertIn('<details class="repo-card">', page)
        self.assertIn("org/alpha", page)
        self.assertIn("Alpha delivery", page)
        self.assertIn("12 min/story", page)

    def test_a_dashboard_that_could_not_read_github_says_so_in_plain_words(self):
        with mock.patch.object(city.cmd_status, "recent", return_value=None), mock.patch.object(city.repo_state, "origin", return_value="o/r"):
            body = city.panel_html(T0)
        self.assertIn("could not read GitHub", body)
        self.assertNotIn("oc-term", body)
        self.assertNotIn("Traceback", body)


if __name__ == "__main__":
    unittest.main()
