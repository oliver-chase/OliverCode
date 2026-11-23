"""With autoCoverLessons on, a lesson gets its story at once and nothing runs when the setting is off or no lesson waits (#659)."""

import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import candidates, gh_budget, lesson_cover, lessons, retro  # noqa: E402


class TestAutoCover(unittest.TestCase):
    def test_lessons_cover_themselves_only_when_the_setting_is_on(self):
        home = temp_dir(self)
        cfg = home / "local.json"
        cfg.write_text(json.dumps({"autoCoverLessons": True}))
        calls = []

        def runner(args):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout="https://github.com/o/r/issues/900\n", stderr="")

        env = {"OLIVERCODE_HOME": str(home), "OLIVERCODE_LOCAL_CONFIG": str(cfg)}
        with mock.patch.dict(os.environ, env), mock.patch.object(gh_budget, "refusal", return_value=""), \
                mock.patch.object(gh_budget, "reserve_write", return_value=""), \
                mock.patch.object(retro, "sources", return_value=[("structure", None)]), \
                mock.patch.object(retro, "open_story_count", return_value=0), \
                mock.patch.object(retro, "slug", return_value="o/r"), \
                mock.patch.object(lesson_cover, "own_backlog", return_value=True):
            self.assertEqual(0, retro.auto_cover(runner, out=lambda s: None))
            self.assertEqual(0, candidates.count())
            lessons.add("a thing broke", "no check", "check it", None, None)
            retro.auto_cover(runner, out=lambda s: None)
            self.assertEqual(1, candidates.count())
            self.assertEqual([], calls, "nothing is filed on the board")
            self.assertEqual([], lessons.uncovered(None))
            cfg.write_text(json.dumps({}))
            lessons.add("another", "no check", "check that", None, None)
            retro.auto_cover(runner, out=lambda s: None)
            self.assertEqual(1, candidates.count())

    def setup_auto(self):
        home = temp_dir(self)
        cfg = home / "local.json"
        cfg.write_text(json.dumps({"autoCoverLessons": True}))
        calls = []

        def runner(args):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout=f"https://github.com/o/r/issues/{900 + len(calls)}\n", stderr="")

        env = {"OLIVERCODE_HOME": str(home), "OLIVERCODE_LOCAL_CONFIG": str(cfg)}
        for p in (mock.patch.dict(os.environ, env), mock.patch.object(gh_budget, "refusal", return_value=""),
                  mock.patch.object(gh_budget, "reserve_write", return_value=""),
                  mock.patch.object(retro, "sources", return_value=[("structure", None)]),
                  mock.patch.object(retro, "slug", return_value="o/r"),
                  mock.patch.object(lesson_cover, "own_backlog", return_value=True)):
            p.start()
            self.addCleanup(p.stop)
        return runner, calls

    def test_one_run_files_at_most_the_per_run_cap_and_the_rest_wait_for_the_next_run(self):
        runner, calls = self.setup_auto()
        for i in range(5):
            lessons.add(f"thing {i} broke", "no check", f"check rule {i}", None, None)
        with mock.patch.object(retro, "open_story_count", return_value=0):
            retro.auto_cover(runner, out=lambda s: None)
            self.assertEqual(3, candidates.count())
            self.assertEqual(2, len(lessons.uncovered(None)))
            retro.auto_cover(runner, out=lambda s: None)
        self.assertEqual(5, candidates.count())
        self.assertEqual([], lessons.uncovered(None))

    def test_a_lesson_that_names_an_auto_filed_story_files_nothing(self):
        runner, calls = self.setup_auto()
        first = lessons.add("a thing broke", "no check", "check it", None, None)
        lessons.cover(first["id"], "#901", None)
        lessons.add("story #901 came back wrong", "the filer looped", "stop it", None, None)
        lessons.add("a real new problem", "no check", "check the other thing", None, None)
        with mock.patch.object(retro, "open_story_count", return_value=0):
            retro.auto_cover(runner, out=lambda s: None)
        self.assertEqual(1, candidates.count())
        self.assertIn("check the other thing", candidates.items()[0]["title"])

    def test_nothing_is_filed_while_the_repo_holds_more_than_the_open_story_cap(self):
        runner, calls = self.setup_auto()
        lessons.add("a thing broke", "no check", "check it", None, None)
        with mock.patch.object(retro, "open_story_count", return_value=21):
            retro.auto_cover(runner, out=lambda s: None)
        self.assertEqual(0, candidates.count())
        self.assertEqual(1, len(lessons.uncovered(None)))
        with mock.patch.object(retro, "open_story_count", return_value=20):
            retro.auto_cover(runner, out=lambda s: None)
        self.assertEqual(1, candidates.count())


if __name__ == "__main__":
    unittest.main()
