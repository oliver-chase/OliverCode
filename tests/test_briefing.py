"""#1177: status and City share one plain-language layer: attention first, no engineering words, the terminal commands kept."""

import sys
import unittest
from datetime import datetime, timezone

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import briefing  # noqa: E402

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
STEPS = [
    {"id": 98, "session": "groom", "step": 'acme-site: approve a new epic on "navigator sale"'},
    {"id": 113, "session": "fleet-sync", "step": "Bring widgets level with origin: validation failed"},
    {"id": 133, "session": "maintain", "step": "maintain branches: OliverCode: 3 unmerged branch(es) older than 24 hours with no worktree"},
    {"id": 157, "session": "maintain", "step": "maintain health: acme/widgets#893 parked on the turn limit and names no split"},
    {"id": 140, "session": "maintain", "step": "maintain health: python3 is 3.9, and OliverCode needs 3.12"},
]


def snap(steps=STEPS, building=0, city=True, ideas=20, cost_days=None):
    return briefing.snapshot(slug="o/r", now=NOW, open_now=7, rows=[], numbers={"tokens_per_closed": 9_115_088, "cost_per_closed": 3.43, "handovers": 9, "threads": 7, "open": 7},
                             steps=steps, today=[{"story": "1209", "title": "City opens on what needs you", "tokens": 100, "cost": 1.0}], ready="P1 #461 Morning run",
                             runner={"building": building, "allowed": 2, "load": "load 11 on 10 cores"}, ideas=ideas, city=city, latest={"number": 1209, "title": "City opens"}, cost_days=cost_days)


class GroupingCase(unittest.TestCase):
    def test_steps_group_by_what_the_owner_would_do_and_a_split_step_is_not_an_approval(self):
        names = {g["name"]: len(g["steps"]) for g in briefing.attention(STEPS)}
        self.assertEqual({"Stories to split": 1, "Approvals": 1, "Failed checks": 1, "Cleanup": 1, "Setup": 1}, names)

    def test_setup_problems_become_one_item_per_area_with_a_fix(self):
        items = briefing.setup_items(STEPS)
        self.assertTrue(items)
        self.assertTrue(all(i["fix"] and i["meaning"] for i in items))

    def test_the_trend_never_promises_a_finish_date(self):
        self.assertEqual("You are keeping up with new work.", briefing.trend(571, 575, 7)[0])
        self.assertEqual("The backlog is shrinking.", briefing.trend(100, 300, 7)[0])
        self.assertIn("rough guess", briefing.trend(100, 300, 7)[1])
        self.assertEqual("New work is arriving faster than it is delivered.", briefing.trend(10, 0, 5)[0])


class TextCase(unittest.TestCase):
    def test_attention_comes_first_and_the_commands_are_named(self):
        out = briefing.text(snap())
        self.assertEqual("YOUR ATTENTION", out[3])
        text = "\n".join(out)
        for want in ("5 things need you.", "olivercode owner list", "olivercode drain REPO", "olivercode candidates", "olivercode health"):
            self.assertIn(want, text)

    def test_no_engineering_words_reach_the_owner(self):
        text = "\n".join(briefing.text(snap())).lower() + briefing.dashboard_html(snap()).lower()
        for word in ("clean-clone", "context budget", "catch-up", "origin lacks", "placement"):
            self.assertNotIn(word, text)


class DashboardCase(unittest.TestCase):
    def test_the_dashboard_answers_the_four_questions_and_keeps_the_terminal_commands_as_plain_text(self):
        page = briefing.dashboard_html(snap())
        for heading in ("What needs your attention", "Work underway", "Delivery pace", "System health"):
            self.assertIn(heading, page)
        self.assertIn("cd ~/.claude/olivercode", page)
        self.assertIn("olivercode status", page)
        self.assertNotIn("oc-term", page)
        self.assertIn("Daily breakdown", page)
        self.assertIn("Benchmark:", page)
        self.assertIn("expansion", page)
        self.assertIn("this week", page)
        self.assertIn("within $6.00 budget", page)
        self.assertIn("--accent:#a9a0b5", briefing.STYLE)
        self.assertIn("--lavender:#f2eff4", briefing.STYLE)
        self.assertIn('font:15px/1.6 Georgia,"Times New Roman",serif', briefing.STYLE)
        self.assertNotIn("-apple-system", briefing.STYLE)
        self.assertNotIn("prefers-color-scheme:dark", briefing.STYLE)
        self.assertIn("Why it matters", page)
        self.assertIn("What to do", page)
        self.assertIn("What the trend says:", page)
        self.assertIn("chart-values", page)
        self.assertIn("Daily stories added and delivered", page)
        self.assertIn('class="city-grid" id="dashboard"', page)
        self.assertIn('class="city-head"', page)
        self.assertIn('class="keep" id="explore"', page)
        self.assertIn('class="work" id="work"', page)
        self.assertIn('class="delivery" id="delivery"', page)
        self.assertIn('grid-template-columns:repeat(12,minmax(0,1fr))', briefing.STYLE)
        self.assertIn("--wash:#f8f7f5", briefing.STYLE)

    def test_a_step_cannot_inject_markup(self):
        page = briefing.dashboard_html(snap(steps=[{"id": 1, "session": "maintain", "step": "<script>steal()</script> approve"}]))
        self.assertNotIn("<script>steal()</script>", page)



class CostTrendCase(unittest.TestCase):
    def test_daily_cost_average_and_outlier_are_shown(self):
        page = briefing.dashboard_html(snap(cost_days=[
            {"day": "Mon", "stories": 2, "cost": 2.0},
            {"day": "Tue", "stories": 1, "cost": 3.0},
            {"day": "Wed", "stories": 1, "cost": 9.0},
        ]))
        self.assertIn("Cost over time", page)
        self.assertIn("$2.00/story", page)
        self.assertIn("$9.00/story · unusually high", page)

    def test_missing_cost_data_is_not_presented_as_zero(self):
        page = briefing.dashboard_html(snap(cost_days=[{"day": "Mon", "stories": 1, "cost": None}]))
        self.assertIn("Cost not recorded", page)

if __name__ == "__main__":
    unittest.main()
