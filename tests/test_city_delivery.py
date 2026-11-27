"""City v2 (#1358): the Delivery section and Activity chart are drawn from the run log and city-github.json."""

import json
import re
import sys
import unittest
from datetime import datetime, timezone

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import city_delivery  # noqa: E402

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def at(minutes_ago):
    return datetime.fromtimestamp(NOW.timestamp() - minutes_ago * 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def story(n, ago, rounds=1, review="pass"):
    s = f"story-{n}"
    rows = [{"story": s, "repo": "r", "stage": "claimed", "at": at(ago + 5), "seconds": 0}, {"story": s, "repo": "r", "stage": "building", "at": at(ago + 5), "seconds": 0}]
    rows += [{"story": s, "round": i + 1, "input": 1000, "output": 1000, "cost_usd": 0.5, "at": at(ago + 4)} for i in range(rounds)]
    rows += [{"story": s, "repo": "r", "stage": "validating", "at": at(ago + 3), "seconds": 120}, {"story": s, "review": review, "findings": "" if review == "pass" else "bad"},
             {"story": s, "repo": "r", "stage": "landed", "at": at(ago), "seconds": 0}]
    return rows


def page(log, github=None):
    return city_delivery.render({"now": NOW, "log": log, "github": github})


class TestDelivery(unittest.TestCase):
    def test_the_chart_data_is_in_the_page_and_untimed_rounds_are_counted_once(self):
        log = story(1, 30) + [{"story": "story-2", "round": 1, "cost_usd": 1.0}]
        html = page(log)
        chart = json.loads(re.search(r'id="activity-data">(.*?)</script>', html).group(1))
        self.assertEqual(set(chart), {"twoh", "day", "week", "month"})
        self.assertEqual(sum(chart["day"]["landed"]), 1)
        self.assertEqual(chart["twoh"]["spend"][-1], 0.5)
        self.assertEqual(chart["week"]["tokens"][-1], 2.0)
        self.assertIn("1 rounds have no timestamp", html)

    def test_the_figures_count_landed_rows_and_ignore_run_end_rows(self):
        log = story(1, 30) + story(2, 20, rounds=3, review="findings") + [{"story": "run-r", "stage": "run-end", "at": at(1), "landed": 99, "stopped": 0},
                                                                         {"story": "story-3", "stage": "stopped", "at": at(10), "reason": "out of money"}]
        html = page(log)
        for part in ("2 landed on 2026-11-22", "50% of 2 reviewed", "1 × out of money", "#2 in r landed", "bad", "The M ceiling is $2.00", "5 or more"):
            self.assertIn(part, html)
        self.assertNotIn("99", html)

    def test_backlog_flow_names_the_read_time_or_the_command(self):
        self.assertIn("run <code>olivercode status page --fetch</code>".replace("run", "Run"), page([]))
        read = {"opened": 4, "closed": 6, "read_at": NOW.timestamp()}
        self.assertIn("6 closed as completed against 4 opened in the last 7 days. Read from GitHub at 12:00 UTC", page([], read))

    def test_an_unreadable_log_is_named(self):
        self.assertIn("unknown, because the run log could not be read", page(None))


if __name__ == "__main__":
    unittest.main()
