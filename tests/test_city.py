"""#1097: City's terminal panel -- the commands the owner would type and `olivercode status`'s own live output, cached with no model call."""

import os
import sys
import tempfile
import unittest
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import city  # noqa: E402

T0 = 1732460000.0


def fake_run(slug, out=print, now=None, folder=None, **kw):
    out(f"{slug}: 2 open, 0 building.")
    out("")
    return 0


class PanelCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": self.tmp.name})
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_panel_shows_the_cd_and_status_commands_and_their_output(self):
        html = city.panel_html(T0, runner=fake_run)
        self.assertIn('<div class="cmd">cd ~/.claude/olivercode</div>', html)
        self.assertIn('<div class="cmd">olivercode status</div>', html)
        self.assertIn("2 open, 0 building.", html)

    def test_the_stamp_under_the_panel_is_the_time_of_that_read(self):
        html = city.panel_html(T0, runner=fake_run)
        self.assertIn("oc-term-stamp", html)

    def test_a_second_read_inside_the_ttl_reuses_the_cached_panel_with_no_second_run(self):
        calls = []

        def counting(slug, out=print, now=None, folder=None, **kw):
            calls.append(1)
            return fake_run(slug, out=out, now=now, folder=folder, **kw)

        first = city.panel_html(T0, runner=counting)
        second = city.panel_html(T0 + 60, runner=counting)
        self.assertEqual(first, second)
        self.assertEqual(1, len(calls))

    def test_a_read_past_the_ttl_runs_again(self):
        calls = []

        def counting(slug, out=print, now=None, folder=None, **kw):
            calls.append(1)
            return fake_run(slug, out=out, now=now, folder=folder, **kw)

        city.panel_html(T0, runner=counting)
        city.panel_html(T0 + city.PANEL_TTL + 1, runner=counting)
        self.assertEqual(2, len(calls))

    def test_output_is_escaped(self):
        def xss(slug, out=print, now=None, folder=None, **kw):
            out("<script>steal()</script>")
            return 0

        html = city.panel_html(T0, runner=xss)
        self.assertNotIn("<script>steal()</script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
