"""`olivercode gap-sweep`: one story per uncovered gap, none on a rerun (#725)."""

import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_gapsweep, conform  # noqa: E402


def feature(fid="hooks", title="the hooks conform row"):
    return SimpleNamespace(id=fid, title=title, enable="olivercode sync-hooks", owner_only=False)


class TestGapSweep(unittest.TestCase):
    def sweep(self, gaps, existing, state=None, now=1e6, closed=None, others=0, made_number=None):
        made, fields, comments = [], [], []
        def make(slug, title, text):
            made.append((title, text))
            return 100 + len(made) if made_number is None else made_number
        issues = "\n".join(f'{{"number": {n}, "state": "open", "body": "{cmd_gapsweep.marker(g)}"}}' for g, n in existing.items())
        issues += "".join(f'\n{{"number": {n}, "state": "closed", "body": "{cmd_gapsweep.marker(g)}"}}' for g, n in (closed or {}).items())
        issues += "".join(f'\n{{"number": {900 + i}, "state": "open", "body": "plain"}}' for i in range(others))
        with mock.patch.object(cmd_gapsweep.candidates, "has", return_value=False):
            got = cmd_gapsweep.sweep_repo("R", "cfg", gaps, "o/R", 722, {} if state is None else state, now, run=lambda a: issues,
                                          make=make, fields=lambda c, n, p: fields.append((n, p)), comment=lambda n, t: comments.append(n))
        return got, made, fields, comments

    def test_a_gap_with_no_open_story_files_one_story_with_all_four_fields_and_a_rerun_files_none(self):
        got, made, fields, _ = self.sweep([feature()], {})
        self.assertEqual(got, (1, 0))
        self.assertIn("Priority: P0. Size: XS. Work type: Story.", made[0][1])
        self.assertIn("Epic: #722", made[0][1])
        self.assertEqual(fields, [(101, "P0")])
        got, made, _, _ = self.sweep([feature()], {"hooks": 101})
        self.assertEqual((got, made), ((0, 1), []))

    def test_a_reminder_is_commented_once_a_week_and_five_stories_is_the_cap(self):
        state = {"o/R#9": 1e6 - 3600}
        self.assertEqual(self.sweep([feature()], {"hooks": 9}, state)[0], (0, 0))
        self.assertEqual(self.sweep([feature()], {"hooks": 9}, {})[0], (0, 1))
        got, made, _, _ = self.sweep([feature(f"f{i}", f"F{i}") for i in range(8)], {})
        self.assertEqual((got[0], len(made)), (5, 5))

    def test_a_closed_gap_story_is_never_filed_again(self):
        got, made, fields, _ = self.sweep([feature()], {}, closed={"hooks": 55})
        self.assertEqual((got, made, fields), ((0, 0), [], []))
        got, made, _, _ = self.sweep([feature(), feature("board-baseline", "Board")], {}, closed={"hooks": 55})
        self.assertEqual((got[0], len(made)), (1, 1))

    def test_a_create_that_returned_nothing_counts_only_when_the_candidates_list_holds_it(self):
        self.assertEqual(self.sweep([feature()], {}, made_number=0)[0], (0, 0))
        queue = []
        def make(slug, title, text):
            queue.append({"repo": slug, "title": title})
        with mock.patch.object(cmd_gapsweep.candidates, "has", side_effect=lambda slug, title: any(q["title"] == title for q in queue)):
            got = cmd_gapsweep.sweep_repo("R", "cfg", [feature()], "o/R", 722, {}, 1e6, run=lambda a: "", make=make,
                                          fields=lambda *a: None, comment=lambda *a: None)
        self.assertEqual((got, len(queue)), ((1, 0), 1))

    def test_no_story_is_filed_while_the_repo_holds_more_than_the_open_story_cap(self):
        cap = cmd_gapsweep.candidates.limits()["openStoryCap"]
        self.assertEqual(cap, 20)
        got, made, _, _ = self.sweep([feature()], {}, others=cap + 1)
        self.assertEqual((got, made), ((0, 0), []))
        got, made, _, _ = self.sweep([feature()], {}, others=cap)
        self.assertEqual(got, (1, 0))
        self.assertEqual(len(made), 1)

    def test_each_failing_conform_row_an_agent_can_repair_is_a_gap_and_owner_rows_are_not(self):
        rows = [conform.Row("hooks", "fail", fix="olivercode sync-hooks"), conform.Row("ignore", "pass"),
                conform.Row("sleep-setting", "fail", fix="caffeinate"), conform.Row("exceptions", "fail")]
        with mock.patch.object(cmd_gapsweep.conform, "check_repo", return_value=rows):
            gaps = cmd_gapsweep.gaps_of(REPO_ROOT)
        self.assertEqual([("hooks", "olivercode sync-hooks")], [(g.id, g.enable) for g in gaps])


if __name__ == "__main__":
    unittest.main()
