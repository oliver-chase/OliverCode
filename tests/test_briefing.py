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


def snap(steps=STEPS, building=0, city=True, ideas=20):
    return briefing.snapshot(slug="o/r", now=NOW, open_now=7, rows=[], numbers={"tokens_per_closed": 9_115_088, "cost_per_closed": 3.43, "handovers": 9, "threads": 7, "open": 7},
                             steps=steps, today=[{"story": "1209", "title": "City opens on what needs you", "tokens": 100, "cost": 1.0}], ready="P1 #461 Morning run",
                             runner={"building": building, "allowed": 2, "load": "load 11 on 10 cores"}, ideas=ideas, city=city, latest={"number": 1209, "title": "City opens"})


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
        self.assertIn("within $6.00 budget", page)\n        self.assertIn("--accent:#a99be8", briefing.STYLE)\n        self.assertIn("--lavender:#f0edff", briefing.STYLE)\n        self.assertNotIn("prefers-color-scheme:dark", briefing.STYLE)\n        self.assertIn("Why it matters", page)\n        self.assertIn("What to do", page)

    def test_a_step_cannot_inject_markup(self):
        page = briefing.dashboard_html(snap(steps=[{"id": 1, "session": "maintain", "step": "<script>steal()</script> approve"}]))
        self.assertNotIn("<script>steal()</script>", page)


if __name__ == "__main__":
    unittest.main()
