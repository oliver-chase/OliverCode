"""The retro builds one valid story per uncovered lesson, files within the budget, covers what it files and records the retro date."""

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

from _support import REPO_ROOT, quiet, scratch_repo, temp_dir, git

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "backlog" / "scripts"))
import check_story_format  # noqa: E402
from lib import candidates, gh_budget, launchd, lessons, retro  # noqa: E402
from lib.cmd_health import command_health  # noqa: E402

NOW = datetime(2026, 11, 19, 12, 0, 0).astimezone()


def stamp(delta):
    return (NOW - delta).strftime("%Y-%m-%dT%H:%M:%S%z")


class Fake:
    """A gh runner that records its calls and answers each create with the next issue number."""

    def __init__(self, fail=False):
        self.calls, self.fail, self.n = [], fail, 600

    def __call__(self, args):
        self.calls.append(args)
        self.n += 1
        if self.fail:
            return subprocess.CompletedProcess(args, 1, "", "boom")
        return subprocess.CompletedProcess(args, 0, f"https://github.com/acme/widget/issues/{self.n}\n", "")


class Base(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        self.fleet = temp_dir(self)
        self.oc = temp_dir(self)
        env = {"OLIVERCODE_HOME": str(self.home), "OLIVERCODE_GH_POINTS_FLOOR": "0"}
        p = mock.patch.dict(os.environ, env); p.start(); self.addCleanup(p.stop)
        self.widget = scratch_repo(self.fleet / "widget")
        git(self.widget, "remote", "add", "origin", "https://github.com/acme/widget.git")
        scratch_repo(self.oc)
        git(self.oc, "remote", "add", "origin", "https://github.com/acme/OliverCode.git")
        p = mock.patch.object(retro, "load_repo_profiles", return_value=({"widget": {}}, self.fleet)); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(retro, "OC_ROOT", self.oc); p.start(); self.addCleanup(p.stop)
        self.repo = lessons.add("The deploy skipped the tests.", "Nothing ran them first.", "Deploys wait for green tests.", repo=self.widget)
        self.struct = lessons.add("Two sessions edited one file.", "No lock existed.", "One session owns a file at a time.")

    def reqs(self):
        return retro.requests(self.fleet, self.oc)


class TestRetro(Base):
    def test_an_uncovered_lesson_yields_one_valid_story_and_a_covered_one_none(self):
        reqs = self.reqs()
        self.assertEqual(sorted(r["lesson"] for r in reqs), sorted([self.repo["id"], self.struct["id"]]))
        by = {r["lesson"]: r for r in reqs}
        self.assertEqual(by[self.repo["id"]]["repo"], "acme/widget")
        self.assertEqual(by[self.struct["id"]]["repo"], "acme/OliverCode")
        for r in reqs:
            self.assertEqual([x[0] for x in check_story_format.check_body(r["body"])], ["Epic link"])
            self.assertNotIn("Epic:", r["body"], "no retroEpic is configured, so no Epic line is written")
        for value, line in ((504, "Epic: #504"), ("#12", "Epic: #12"), ("acme/board#7", "Epic: acme/board#7")):
            with mock.patch("lib.local_config.load_local", return_value={"retroEpic": value}):
                for r in self.reqs():
                    self.assertIn(line + "\nPriority: P1. Size: S. Work type: Story.", r["body"])
                    self.assertEqual(check_story_format.check_body(r["body"]), [])
        lessons.cover(self.repo["id"], "#9", self.widget)
        lessons.cover(self.struct["id"], "scripts/hooks/x.py")
        self.assertEqual(self.reqs(), [])
        out = quiet(retro.command_retro, ["--root", str(self.fleet)])[1]
        self.assertIn("Every lesson has a check or a story.", out)

    def test_filing_adds_candidates_covers_the_lessons_and_a_second_retro_adds_nothing(self):
        fake = Fake()
        code, out = quiet(retro.command_retro, ["--file", "--root", str(self.fleet)], runner=fake, now=NOW)
        self.assertEqual(code, 0)
        self.assertEqual(fake.calls, [], "retro files nothing on the board")
        self.assertEqual(sorted(i["repo"] for i in candidates.items()), ["acme/OliverCode", "acme/widget"])
        self.assertEqual({i["source"] for i in candidates.items()}, {"retro"})
        self.assertEqual(lessons.uncovered(self.widget), [])
        self.assertEqual(lessons.uncovered(), [])
        self.assertEqual(lessons.read(self.widget)[0]["covered_by"], "candidates")
        self.assertEqual(json.loads((self.home / "retro.json").read_text())["last"], retro.date.today().isoformat())
        quiet(retro.command_retro, ["--file", "--root", str(self.fleet)], runner=Fake(), now=NOW)
        self.assertEqual(candidates.count(), 2)
        # without --file nothing is added and no date is recorded
        lessons.add("a", "b", "c", repo=self.widget)
        (self.home / "retro.json").unlink()
        quiet(retro.command_retro, ["--root", str(self.fleet)], runner=fake, now=NOW)
        self.assertEqual(candidates.count(), 2)
        self.assertFalse((self.home / "retro.json").exists())
        self.assertEqual(len(lessons.uncovered(self.widget)), 1)

    def test_a_held_budget_does_not_stop_a_candidate_from_being_added(self):
        gh_budget.note_limit(600, who="test")
        fake = Fake()
        quiet(retro.command_retro, ["--file", "--root", str(self.fleet)], runner=fake, now=NOW)
        self.assertEqual(fake.calls, [])
        self.assertEqual(candidates.count(), 2)

    def test_health_counts_the_uncovered_lessons_and_a_late_retro(self):
        def lines():
            out = quiet(command_health, self.fleet)[1]
            return [l for l in out.splitlines() if "lesson" in l.lower() or "retro" in l.lower()]
        self.assertEqual(retro.uncovered_count(self.fleet, self.oc), len(self.reqs()))
        got = lines()
        self.assertTrue(any("[WARN] 2 lesson(s) have no check" in l for l in got), got)
        self.assertTrue(any("[WARN] no retro has run" in l for l in got), got)
        lessons.cover(self.repo["id"], "#1", self.widget)
        lessons.cover(self.struct["id"], "#2")
        retro.record_retro()
        got = lines()
        self.assertTrue(any("[OK] 0 lessons without a check" in l for l in got), got)
        self.assertTrue(any("[OK] a retro ran" in l for l in got), got)
        (self.home / "retro.json").write_text(json.dumps({"last": (retro.date.today() - timedelta(days=9)).isoformat()}))
        self.assertTrue(any("[WARN] the last retro ran 9 days ago" in l for l in lines()))

    def test_the_retro_reads_olivercodes_own_log_as_well_as_the_structure_log(self):
        oc = temp_dir(self)
        labels = [label for label, _repo in retro.sources(fleet_root=temp_dir(self), oc_root=oc)]
        self.assertEqual((labels[0], labels[-1]), (oc.name, "structure"))


class TestSchedulePath(unittest.TestCase):
    def test_the_hourly_job_path_holds_the_folder_with_gh(self):
        import plistlib
        from pathlib import Path
        home = temp_dir(self)
        with mock.patch.object(launchd.shutil, "which", return_value="/opt/homebrew/bin/gh"), \
                mock.patch.object(retro.subprocess, "run") as run, mock.patch.object(Path, "home", return_value=home):
            run.return_value.returncode = 0
            quiet(retro.schedule, True)
        job = plistlib.loads((home / "Library" / "LaunchAgents" / "com.olivercode.lessons.plist").read_bytes())
        self.assertEqual("/opt/homebrew/bin", job["EnvironmentVariables"]["PATH"].split(":")[0])


if __name__ == "__main__":
    unittest.main()
