"""The lesson logs append one line per add, refuse an incomplete line, cover by rewrite and load their seeds."""

import json
import os
import pathlib
import sys
import unittest
from datetime import date
from unittest import mock

from _support import REPO_ROOT, quiet, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import lessons  # noqa: E402
from lib.cmd_lesson import command_lesson  # noqa: E402

FIELDS = ("id", "date", "scope", "what", "why", "rule", "covered_by")


class Isolated(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        self.repo = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def lines(self, repo=None):
        return lessons.path(repo).read_text(encoding="utf-8").splitlines()


class TestLessons(Isolated):
    def test_a_file_written_through_record_is_mode_600(self):
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        lessons.add("a", "b", "c")
        self.assertEqual(lessons.path().stat().st_mode & 0o777, 0o600)

    def test_add_appends_exactly_one_line_and_refuses_a_missing_field(self):
        lessons.add("a", "b", "c", repo=self.repo)
        self.assertEqual(len(self.lines(self.repo)), 1)
        rec = lessons.add("d", "e", "f", "#513", repo=self.repo)
        self.assertEqual(len(self.lines(self.repo)), 2)
        self.assertEqual(sorted(json.loads(self.lines(self.repo)[1])), sorted(FIELDS))
        self.assertEqual((rec["scope"], rec["covered_by"]), ("repo", "#513"))
        for kwargs in ({"what": ""}, {"why": " "}, {"rule": ""}):
            with self.assertRaises(ValueError):
                lessons.add(**{"what": "a", "why": "b", "rule": "c", **kwargs}, repo=self.repo)
        self.assertEqual(len(self.lines(self.repo)), 2)
        lessons.add("s", "t", "u")
        self.assertEqual(json.loads(self.lines()[0])["scope"], "structure")
        self.assertEqual(lessons.path(), self.home / "structure-lessons.jsonl")

    def test_cover_sets_covered_by_and_keeps_the_other_lines(self):
        first = lessons.add("a", "b", "c", repo=self.repo)
        second = lessons.add("d", "e", "f", repo=self.repo)
        before = self.lines(self.repo)
        lessons.cover(second["id"], "#514", repo=self.repo)
        after = self.lines(self.repo)
        self.assertEqual(after[0], before[0])
        self.assertEqual(json.loads(after[1]), {**second, "covered_by": "#514", "covered_on": date.today().isoformat()})
        self.assertEqual(len(after), 2)
        self.assertEqual([p.name for p in lessons.path(self.repo).parent.iterdir() if p.suffix != ".lock"], [lessons.path(self.repo).name])
        with self.assertRaises(ValueError):
            lessons.cover("L-nope", "#1", repo=self.repo)
        self.assertEqual(first["covered_by"], None)

    def test_uncovered_lists_only_lessons_without_covered_by(self):
        lessons.add("a", "b", "c", "#1", repo=self.repo)
        open_one = lessons.add("d", "e", "f", repo=self.repo)
        self.assertEqual([r["id"] for r in lessons.uncovered(self.repo)], [open_one["id"]])
        code, out = quiet(command_lesson, ["list", "--repo", str(self.repo), "--uncovered"])
        self.assertEqual(code, 0)
        self.assertIn(open_one["id"], out)
        self.assertNotIn("covered by #1", out)

    def test_cli_adds_covers_and_refuses_an_incomplete_line(self):
        r = str(self.repo)
        code, _ = quiet(command_lesson, ["add", "--repo", r, "--what", "w", "--why", "y"])
        self.assertEqual(code, 1)
        self.assertFalse(lessons.path(self.repo).exists())
        code, out = quiet(command_lesson, ["add", "--repo", r, "--what", "w", "--why", "y", "--rule", "z"])
        self.assertEqual(code, 0)
        lid = lessons.read(self.repo)[0]["id"]
        with mock.patch("lib.lesson_flags.story_state", return_value="OPEN"):
            self.assertEqual(quiet(command_lesson, ["cover", lid, "#9", "--repo", r])[0], 0)
        self.assertEqual(lessons.read(self.repo)[0]["covered_by"], "#9")


class TestSeeds(Isolated):
    def test_the_seeds_have_every_field_and_seed_copies_them_once(self):
        seeds = [json.loads(x) for x in lessons.SEED_FILE.read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertEqual(len(seeds), 6)
        for s in seeds:
            self.assertEqual(sorted(s), sorted(FIELDS))
            self.assertTrue(all(s[k].strip() for k in ("what", "why", "rule")), s["id"])
            self.assertEqual(s["scope"], "structure")
        self.assertEqual(len({s["id"] for s in seeds}), len(seeds))
        self.assertEqual(lessons.seed(), len(seeds))
        self.assertEqual(lessons.seed(), 0)
        self.assertEqual(len(self.lines()), len(seeds))
        self.assertEqual(len(lessons.uncovered()), len([s for s in seeds if not s["covered_by"]]))

    def test_a_seeded_log_is_mode_600(self):
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        lessons.seed()
        self.assertEqual(lessons.path().stat().st_mode & 0o777, 0o600)

    def test_a_seed_line_with_no_id_does_not_stop_seed(self):
        seed = pathlib.Path(self.repo) / "seed.jsonl"
        seed.write_text('{"what": "no id"}\n', encoding="utf-8")
        with mock.patch.object(lessons, "SEED_FILE", seed):
            self.assertEqual(lessons.seed(), 1)


if __name__ == "__main__":
    unittest.main()
