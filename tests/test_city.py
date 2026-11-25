"""#1097, #1177: City's dashboard is cached with no model call, carries the two terminal commands in plain text and has no terminal-styled panel."""

import os
import sys
import tempfile
import unittest
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import city  # noqa: E402

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
        self.assertEqual("<p>2 open, 0 building.</p>", body)
        cached = city._load_cache()
        self.assertEqual(body, cached["html"])
        self.assertEqual(T0, cached["at"])
        self.assertEqual({"at", "html"}, set(cached))

    def test_a_dashboard_that_could_not_read_github_says_so_in_plain_words(self):
        with mock.patch.object(city.cmd_status, "recent", return_value=None), mock.patch.object(city.repo_state, "origin", return_value="o/r"):
            body = city.panel_html(T0)
        self.assertIn("could not read GitHub", body)
        self.assertNotIn("oc-term", body)
        self.assertNotIn("Traceback", body)


if __name__ == "__main__":
    unittest.main()
