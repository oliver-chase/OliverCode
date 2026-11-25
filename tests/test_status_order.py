"""#1209: City opens on what needs the owner, and the history and spend stay below it."""

import sys
import time
import unittest
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import status_report  # noqa: E402


class OwnerFirst(unittest.TestCase):
    def page(self, steps):
        with mock.patch.object(status_report, "_owner_steps", return_value=steps):
            return status_report.render({"o/r": status_report._idle()}, [], time.time())

    def test_an_open_owner_step_is_listed_before_any_repo_section(self):
        html = self.page([{"id": 7, "step": "approve the new epic"}])
        self.assertLess(html.index("Waits on you, in any repo"), html.index("<h2>o/r</h2>"))
        self.assertLess(html.index("approve the new epic"), html.index("<h2>o/r</h2>"))

    def test_with_nothing_waiting_one_line_at_the_top_says_so(self):
        html = self.page([])
        self.assertLess(html.index("No owner step is open."), html.index("<h2>o/r</h2>"))

    def test_the_landed_history_and_spend_stay_below_the_owner_list(self):
        html = self.page([])
        owner = html.index("Waits on you, in any repo")
        self.assertLess(owner, html.index("Landed in the last seven days"))
        self.assertLess(owner, html.index("Spend by day"))


if __name__ == "__main__":
    unittest.main()
