"""Auto-cover files only in the checkout's own backlog, shares a story between lessons with one rule and verifies after thirty days (#662)."""

import json
import os
import sys
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import candidates, gh_budget, lesson_cover, lessons, retro  # noqa: E402


class TestOwnBacklog(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        self.checkout = temp_dir(self)
        (self.checkout / "docs").mkdir()
        self.cfg = self.home / "local.json"
        self.cfg.write_text(json.dumps({"autoCoverLessons": True}))
        self.calls = []
        env = {"OLIVERCODE_HOME": str(self.home), "OLIVERCODE_LOCAL_CONFIG": str(self.cfg)}
        for patcher in (mock.patch.dict(os.environ, env), mock.patch.object(gh_budget, "refusal", return_value=""),
                        mock.patch.object(gh_budget, "reserve_write", return_value=""),
                        mock.patch.object(retro, "sources", return_value=[("structure", None)]),
                        mock.patch.object(retro, "OC_ROOT", self.checkout),
                        mock.patch.object(retro, "open_story_count", return_value=0),
                        mock.patch.object(lesson_cover, "OC_ROOT", self.checkout)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def runner(self, args):
        self.calls.append(args)
        return SimpleNamespace(returncode=0, stdout="https://github.com/o/r/issues/901\n", stderr="")

    def config(self, name):
        (self.checkout / "docs" / "backlog-config.json").write_text(json.dumps({"repoOwner": "o", "repoName": name}))

    def test_a_checkout_without_its_own_backlog_writes_to_the_backlog_file(self):
        lessons.add("it broke", "no check", "check it", None, None)
        with mock.patch.object(retro, "slug", return_value="o/r"):
            retro.auto_cover(self.runner, out=lambda s: None)  # no config at all
            self.config("upstream")  # a config that names another repo
            lessons.add("again", "no check", "check that", None, None)
            retro.auto_cover(self.runner, out=lambda s: None)
        self.assertEqual([], self.calls)
        self.assertEqual([], lessons.uncovered(None))
        self.assertIn("Check for lesson", (self.checkout / "docs" / "BACKLOG.md").read_text())

    def test_a_checkout_with_its_own_backlog_adds_a_candidate_and_files_nothing(self):
        self.config("r")
        lessons.add("it broke", "no check", "check it", None, None)
        with mock.patch.object(retro, "slug", return_value="o/r"):
            retro.auto_cover(self.runner, out=lambda s: None)
        self.assertEqual(([], 1), (self.calls, candidates.count()))
        self.assertFalse((self.checkout / "docs" / "BACKLOG.md").exists())

    def test_lessons_with_the_same_rule_share_one_story(self):
        self.config("r")
        lessons.add("first mistake", "why one", "Check it.", None, None)
        lessons.add("second mistake", "why two", "check  it", None, None)
        with mock.patch.object(retro, "slug", return_value="o/r"):
            retro.auto_cover(self.runner, out=lambda s: None)
        self.assertEqual(([], 1), (self.calls, candidates.count()))
        self.assertEqual([], lessons.uncovered(None))
        self.assertEqual({"candidates"}, {r["covered_by"] for r in lessons.read(None)})

    def test_a_lesson_is_verified_after_thirty_quiet_days(self):
        today = date.today()
        lesson = {"id": "L-1", "rule": "Check it", "covered_by": "#9", "covered_on": (today - timedelta(days=31)).isoformat()}
        self.assertTrue(lesson_cover.verified(lesson, today, rows=[]))
        young = dict(lesson, covered_on=(today - timedelta(days=29)).isoformat())
        self.assertFalse(lesson_cover.verified(young, today, rows=[]))
        self.assertFalse(lesson_cover.verified(dict(lesson, covered_by=None), today, rows=[]))
        later = (today - timedelta(days=5)).isoformat() + "T10:00:00Z"
        self.assertFalse(lesson_cover.verified(lesson, today, rows=[(later, "r", "gate", "again: check it")]))
        before = (today - timedelta(days=40)).isoformat() + "T10:00:00Z"
        self.assertTrue(lesson_cover.verified(lesson, today, rows=[(before, "r", "gate", "check it")]))



if __name__ == "__main__":
    unittest.main()
