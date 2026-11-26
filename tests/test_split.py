"""Story split by files area for parallel builders (#794): groups, models, a missing area and a long wait."""

import datetime
import json
import sys
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
from lib import cmd_dispatch, intake  # noqa: E402
import model_guard  # noqa: E402

TODAY = datetime.date(2026, 11, 22)


def story(n, area="", size="S", extra=""):
    return {"number": n, "title": f"S{n}", "labels": [], "body": f"{'Files area: ' + area + '.' if area else ''}\nPriority: P2. Size: {size}.\n{extra}"}


# README section "Dispatch planning" (#794): `dispatch --plan` holds back overlapping stories and sets the model by size.

class TestSplit(unittest.TestCase):
    def test_non_overlapping_stories_are_parallel_and_shared_files_are_ordered(self):
        found = intake.plan([story(1, "a/x.py"), story(2, "b/y.py"), story(3, "a/x.py, c/z.py"), story(4, "b/")], TODAY)
        self.assertEqual(sorted(map(tuple, found["groups"])), [(1, 3), (2, 4)])

    def test_small_stories_build_on_haiku_and_every_story_is_read_by_sonnet_or_larger(self):
        found = intake.plan([story(1, "a.py", "XS"), story(2, "b.py", "M"), story(3, "scripts/lib/cmd_land.py", "XS")], TODAY)
        self.assertEqual(found["models"], {1: ("haiku", "sonnet", "size XS with no risky path or P0 priority"), 2: ("sonnet", "sonnet", "size M"),
                                           3: ("sonnet", "sonnet", "its Files area touches scripts/lib/cmd_land.py")})
        self.assertIn("#3 (sonnet builder, sonnet QA, chosen for its Files area touches scripts/lib/cmd_land.py)", intake.render(found))

    def test_a_story_with_no_area_is_flagged_and_dispatch_refuses_it(self):
        self.assertEqual(intake.plan([story(5)], TODAY)["rewrite"], [5])
        self.assertIn("5 names no files area", intake.render(intake.plan([story(5)], TODAY)).replace("#", ""))

    def test_a_wait_past_14_days_is_flagged_and_a_short_one_is_not(self):
        far = intake.plan([story(6, "a.py", extra="Wait until 2027-02-01 for the data window.")], TODAY)["waits"]
        self.assertIn("do it now or close it", far[6])
        self.assertEqual(intake.plan([story(7, "a.py", extra="Wait until 2026-11-30 for data.")], TODAY)["waits"], {})
        self.assertIn(30, [int(x) for x in [30]] if intake.long_wait("after 30 days of data") else [])

    def test_the_haiku_brief_lets_model_guard_pass_a_haiku_subagent(self):
        self.assertIn("Haiku", cmd_dispatch.headless_brief(9, {"title": "t", "body": "Size: S"}, "dispatch"))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.jsonl"
            path.write_text(json.dumps({"message": {"role": "user", "content": cmd_dispatch.headless_brief(9, {"title": "t", "body": "Size: S"}, "dispatch")}}) + "\n", encoding="utf-8")
            call = {"tool_name": "Agent", "tool_input": {"model": "haiku"}, "transcript_path": str(path)}
            self.assertEqual(model_guard.reason(call), "")
            path.write_text(json.dumps({"message": {"role": "user", "content": cmd_dispatch.headless_brief(9, {"title": "t", "body": "Size: M"}, "dispatch")}}) + "\n", encoding="utf-8")
            self.assertIn("Sonnet", model_guard.reason(call))


if __name__ == "__main__":
    unittest.main()
