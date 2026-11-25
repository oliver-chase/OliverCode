"""#1209: City opens on what needs the owner, and the history and spend stay below it."""

import sys
import time
import unittest
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import status_report  # noqa: E402


class OwnerFirst(unittest.TestCase):
    DASH = "<h2>What needs your attention</h2>"

    def page(self, steps):
        with mock.patch.object(status_report, "_owner_steps", return_value=steps):
            return status_report.render({"o/r": status_report._idle()}, [], time.time(), panel=self.DASH)

    def test_the_dashboard_leads_and_every_repo_section_sits_under_details(self):
        html = self.page([{"id": 7, "step": "approve the new epic"}])
        self.assertLess(html.index(self.DASH), html.index("Details by project"))
        self.assertLess(html.index("Details by project"), html.index("<h2>o/r</h2>"))
        self.assertLess(html.index("Every step waiting on you"), html.index("approve the new epic"))

    def test_with_nothing_waiting_the_details_say_so(self):
        self.assertIn("No owner step is open.", self.page([]))

    def test_the_landed_history_and_spend_stay_below_the_dashboard(self):
        html = self.page([])
        top = html.index(self.DASH)
        self.assertLess(top, html.index("Landed in the last seven days"))
        self.assertLess(top, html.index("Spend by day"))

    def test_without_a_dashboard_the_page_still_has_a_title(self):
        self.assertIn("<h1>OliverCode City</h1>", status_report.render({}, [], time.time()))


if __name__ == "__main__":
    unittest.main()
