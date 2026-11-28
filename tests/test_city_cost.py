"""City v2 (#1359): the Cost section sums the run log's round rows and reads the GitHub budget files."""

import json
import re
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import city_cost  # noqa: E402

MOCKUP = (REPO_ROOT / "docs" / "city" / "Main.dc.html").read_text()


def stages(n, size, cost, rounds=1, model="sonnet", route="size S", start=1000):
    rows = [{"story": f"story-{n}", "stage": "claimed", "at": "2026-11-20T10:00:00Z", "size": size, "seconds": 0}]
    rows += [{"story": f"story-{n}", "round": i + 1, "model": model, "input": 10, "output": 100, "cache_read": 1000, "cache_write": 50, "cost_usd": cost / rounds,
              "size": size, "start_tokens": start, "route": route, "at": "2026-11-20T10:05:00Z"} for i in range(rounds)]
    rows.append({"story": f"story-{n}", "stage": "landed", "at": "2026-11-20T10:30:00Z", "seconds": 5, "size": size})
    return rows


LOG = stages(1, "XS", 0.20) + stages(2, "S", 0.40, rounds=2, model="haiku", route="size S", start=3000) + stages(3, "L", 3.00, route="Priority P0")


class TestCityCost(unittest.TestCase):
    def test_the_section_opens_with_the_mockups_lead_and_shows_its_tiles_and_bars(self):
        page = city_cost.render({"log": LOG})
        for part in ("rounds cost $3.60, or $1.20 for each landed story", "Caching kept it low: 86.2% of tokens came from cache",
                     "Cost per landed story", "$1.20", "$3.60 over 3 landings", "Cache share", "Highest XS story against its limit",
                     "Cost per round", "$0.90", "Against Sonnet at $1.60", "Haiku rounds cost $0.20 each"):
            self.assertIn(part, page)
        self.assertEqual(page.count('<div class="bullet">'), 4)

    def test_the_model_card_splits_rounds_and_spend_and_names_the_most_used_model(self):
        page = city_cost.render({"log": LOG})
        for part in ("Sonnet did 50% of the rounds and 89% of the spend.", "Sonnet 2 rounds, $3.20", "Haiku 2 rounds, $0.40", 'aria-label="Rounds by model"', 'aria-label="Spend by model"'):
            self.assertIn(part, page)

    def test_the_size_lanes_show_median_highest_and_the_limit_mark(self):
        page = city_cost.render({"log": LOG})
        for part in ("XS highest story used 20% of its limit", "S highest story used 20% of its limit", 'aria-label="XS: median $0.20, highest $0.20, limit $1.00"',
                     'class="lim"', "Median", "Highest", "Limit"):
            self.assertIn(part, page)

    def test_the_reasons_and_tokens_are_shown_as_bars(self):
        page = city_cost.render({"log": LOG})
        for part in ("The most rounds, 3 of 4, were routed by size S.", "Priority P0", "Read from cache", "4,000", "2,000 tokens of context on average",
                     'class="stack"'):
            self.assertIn(part, page)

    def test_the_five_most_expensive_stories_are_ranked(self):
        log = [r for n in range(1, 8) for r in stages(n, "S", n / 10)]
        page = city_cost.render({"log": log})
        self.assertLess(page.index("#7"), page.index("#3"))
        self.assertNotIn("<b>#2</b>", page)

    def test_a_size_with_no_limit_shows_its_median_and_highest_with_no_mark_and_no_line_about_the_limit(self):
        page = city_cost.render({"log": LOG})
        lane = page[page.index('aria-label="L:'):]
        lane = lane[:lane.index("</div></div>")]
        self.assertIn("$3.00", lane)
        self.assertNotIn('class="lim"', lane)
        self.assertNotIn("limit", lane)
        self.assertNotIn("no limit", page)

    def test_the_cost_section_uses_only_classes_its_mockup_section_has(self):
        page = city_cost.render({"log": LOG})
        section = lambda markup: markup[markup.index('<section class="chap" id="cost"'):markup.index("</section>", markup.index('<section class="chap" id="cost"'))]
        mine = set(re.findall(r'class="([^"]*)"', section(page)))
        theirs = {c for m in re.findall(r'class="([^"]*)"', section(MOCKUP)) for c in m.split()}
        extra = {c for m in mine for c in m.split()} - theirs
        self.assertEqual(extra, set(), "the Cost section uses classes its mockup section lacks")

    def unpriced(self, n, size):
        rows = stages(n, size, 0, model="opus")
        del rows[1]["cost_usd"]
        return rows

    def test_a_landing_with_no_recorded_cost_leaves_every_cost_figure_as_it_was(self):
        """#1533: a chat build's rows hold tokens and no price."""
        page = city_cost.render({"log": LOG + self.unpriced(8, "XL") + self.unpriced(9, "S")})
        for part in ("rounds cost $3.60, or $1.20 for each landed story", "$3.60 over 3 landings", "Sonnet did 50% of the rounds and 89% of the spend.",
                     'aria-label="S: median $0.40, highest $0.40, limit $2.00"'):
            self.assertIn(part, page)
        for part in ("Opus", 'aria-label="XL:', "<b>$0.00</b>"):
            self.assertNotIn(part, page)

    def test_a_log_with_only_unpriced_rounds_says_no_cost_is_recorded_and_still_shows_tokens(self):
        page = city_cost.render({"log": self.unpriced(9, "L")})
        for part in ("No round in the run log has a cost recorded.", "No round has a cost recorded.", "No landed story has a cost recorded.", "Read from cache"):
            self.assertIn(part, page)
        self.assertNotIn("$0.00", page)

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
