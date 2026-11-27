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
        self.assertEqual(chart["twoh"]["spend"][-4], 0.5)
        self.assertEqual(chart["week"]["tokens"][-1], 2.0)
        self.assertIn("1 rounds have no timestamp", html)

    def test_the_figures_count_landed_rows_and_the_lead_is_built_from_them(self):
        log = story(1, 30) + story(2, 20, rounds=3, review="findings") + [{"story": "run-r", "stage": "run-end", "at": at(1), "landed": 99, "stopped": 0},
                                                                         {"story": "story-3", "stage": "stopped", "at": at(10), "reason": "out of money"}]
        html = page(log)
        lead = re.search(r'<p class="read">(.*?)</p>', html).group(1)
        self.assertEqual(lead, "2 stories landed on 2026-11-22, the most in a day so far, and 2 in the last 7 days. 50% of 2 reviewed stories passed review first time, and 1 stopped.")
        for part in ("Best day so far", "Backlog flow", "Passed review first time", "1 of 2 reviews", "The other 1 went back", '<div class="bullet">', "4 or more",
                     '<div class="row"><span class="t">out of money</span><b>1</b></div>', '<span class="n">#2</span>', "Run summaries", "The run summaries show 99 landed, but 2 stories landed."):
            self.assertIn(part, html)
        self.assertEqual(re.search(r'id="d0">Delivery</h2>.*?Best day so far</span><span class="num">(\d+)', html, re.S).group(1), "2")
        self.assertLess(html.index('id="activity"'), html.index('id="delivery"'))

    def test_the_rounds_chart_counts_each_story_once_in_its_column(self):
        log = story(1, 30) + story(2, 20, rounds=3) + story(3, 10, rounds=6)
        self.assertEqual(city_delivery.histogram(log, city_delivery.cmd_status.landings(log)), [("1 round", 1), ("2", 0), ("3", 1), ("4 or more", 1)])
        self.assertIn("Stories by rounds: 1 round 1, 2 0, 3 1, 4 or more 1", page(log))

    def test_long_lists_fold_and_nothing_raw_shows_outside_the_fold(self):
        log = []
        for n in range(1, 11):
            log += story(n, 100 - n * 5)
        for i in range(7):
            log.append({"story": f"story-{20 + i}", "stage": "stopped", "at": at(1), "reason": f"Kind {chr(65 + i)} failed in scripts/lib/x{i}.py at abc1234def: Traceback boom"})
        log += [{"story": "run-r", "stage": "run-end", "at": at(i), "landed": 0, "stopped": 0} for i in range(1, 13)]
        html = page(log)
        for label in ("See all 10 landings", "See all 7 kinds", "See all 12 runs"):
            self.assertIn(f'data-fold="{label}"', html)
        outside = re.sub(r'<div class="fold" hidden>.*?</div></div>|<div class="fold" hidden>.*?</div>', "", html, flags=re.S)
        for raw in ("scripts/lib", "abc1234def", "Traceback", ".py"):
            self.assertNotIn(raw, re.sub(r"<script.*?</script>", "", outside, flags=re.S))

    def test_backlog_flow_names_the_read_time_or_the_command(self):
        self.assertIn("run <code>olivercode status page --fetch</code>".replace("run", "Run"), page([]))
        read = {"opened": 4, "closed": 6, "read_at": NOW.timestamp()}
        self.assertIn("6 closed as completed against 4 opened in the last 7 days. Read from GitHub at 12:00 UTC", page([], read))

    def test_an_unreadable_log_is_named(self):
        self.assertIn("unknown, because the run log could not be read", page(None))

    def test_activity_and_delivery_use_only_the_mockups_classes_in_its_order(self):
        mockup = (REPO_ROOT / "docs" / "city" / "Main.dc.html").read_text()
        log = []
        for n in range(1, 11):
            log += story(n, 100 - n * 5, review="findings")
        log += [{"story": f"story-{20 + i}", "stage": "stopped", "at": at(1), "reason": f"Kind {chr(65 + i)}"} for i in range(7)]
        log += [{"story": "run-r", "stage": "run-end", "at": at(i), "landed": 0, "stopped": 0} for i in range(1, 13)]
        github = {"opened": 4, "closed": 6, "read_at": NOW.timestamp()}
        mine = page(log, github)

        def classes(markup):
            return [c for m in re.findall(r'class="([^"]*)"', markup) for c in m.split()]

        for ms, ps in (('<section class="card" aria-labelledby="act"', '<section class="card" id="activity"'), ('<section class="chap" id="delivery"', '<section class="chap" id="delivery"')):
            theirs, ours = mockup[mockup.index(ms):], mine[mine.index(ps):]
            theirs, ours = theirs[:theirs.index("</section>")], ours[:ours.index("</section>")]
            seen = iter(classes(theirs))
            for c in dict.fromkeys(classes(ours)):
                if c not in ("fold", "more"):
                    self.assertTrue(any(c == m for m in seen), f"{c} is not in the mockup's order")


if __name__ == "__main__":
    unittest.main()
