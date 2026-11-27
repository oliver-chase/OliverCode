"""City v2 (#1359): the Cost section sums the run log's round rows and reads the GitHub budget files."""

import json
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import city_cost  # noqa: E402


def stages(n, size, cost, rounds=1, model="sonnet", route="size S", start=1000):
    rows = [{"story": f"story-{n}", "stage": "claimed", "at": "2026-11-20T10:00:00Z", "size": size, "seconds": 0}]
    rows += [{"story": f"story-{n}", "round": i + 1, "model": model, "input": 10, "output": 100, "cache_read": 1000, "cache_write": 50, "cost_usd": cost / rounds,
              "size": size, "start_tokens": start, "route": route, "at": "2026-11-20T10:05:00Z"} for i in range(rounds)]
    rows.append({"story": f"story-{n}", "stage": "landed", "at": "2026-11-20T10:30:00Z", "seconds": 5, "size": size})
    return rows


LOG = stages(1, "XS", 0.20) + stages(2, "S", 0.40, rounds=2, model="haiku", route="size S", start=3000) + stages(3, "L", 3.00, route="Priority P0")


class TestCityCost(unittest.TestCase):
    def test_the_section_shows_spend_by_model_size_route_story_and_tokens(self):
        page = city_cost.render({"log": LOG})
        for part in ("4 rounds cost $3.60 in all", "Sonnet", "2 rounds, $0.40", "XS", "limit $0.50, highest uses 40%", "limit $1.00, highest uses 40%",
                     "no limit is set for this size", "Priority P0", "$1.20", "$0.90", "#3", "$3.00", "Read from cache",
                     "4,000", "2,000 tokens of context on average"):
            self.assertIn(part, page)
        self.assertIn("Cache share", page)
        self.assertIn("86.", page)

    def test_the_five_most_expensive_stories_are_ranked(self):
        log = [r for n in range(1, 8) for r in stages(n, "S", n / 10)]
        page = city_cost.render({"log": log})
        self.assertLess(page.index("#7"), page.index("#3"))
        self.assertNotIn("<b>#2</b>", page)

    def test_a_missing_log_or_empty_log_says_so(self):
        self.assertIn("could not be read", city_cost.render({"log": None}))
        self.assertIn("No round is recorded", city_cost.render({"log": []}))

    def test_the_github_budget_shows_points_calls_reset_and_the_latest_hold(self):
        home = temp_dir(self)
        with mock.patch("lib.gh_budget.home", return_value=home):
            (home / "gh-points.json").write_text(json.dumps({"at": 1795742018, "remaining": 4432, "reset": 1795743310, "rest": 4945}))
            (home / "gh-limit.json").write_text(json.dumps({"graphql": 1795725964, "rest": 1795734303}))
            page = city_cost.render({"log": []})
        for part in ("GraphQL points left: 4,432, resetting at", "REST calls left: 4,945", "Latest hold: GraphQL held until", "Only the latest hold is recorded"):
            self.assertIn(part, page)

    def test_a_missing_budget_file_says_not_recorded(self):
        home = temp_dir(self)
        with mock.patch("lib.gh_budget.home", return_value=home):
            page = city_cost.render({"log": []})
        self.assertIn("not recorded, because no reading has been saved", page)
        self.assertIn("No hold is recorded", page)


if __name__ == "__main__":
    unittest.main()
