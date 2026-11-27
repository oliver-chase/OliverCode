"""Size and Priority, the filing fit check and the repeated-blocker report. None files a story (#1275)."""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import intake  # noqa: E402


class TestSizeAndPriority(unittest.TestCase):
    def test_the_stated_lines_win_and_the_body_length_sizes_the_rest(self):
        self.assertEqual("S", intake.size_of({"body": "Priority: P1. Size: S. Work type: Story."}))
        self.assertEqual("P1", intake.priority_of({"body": "Priority: P1. Size: S."}))
        self.assertEqual("XS", intake.size_of({"body": "short"}))
        self.assertEqual("XL", intake.size_of({"body": "x" * 5000}))
        self.assertEqual("P0", intake.priority_of({"title": "A leaked secret", "body": ""}))
        self.assertEqual("P1", intake.priority_of({"title": "The run is broken", "body": ""}))
        self.assertEqual("P2", intake.priority_of({"title": "Add a flag", "body": ""}))


class TestFit(unittest.TestCase):
    def test_an_overlapping_open_story_gets_one_related_line_and_a_repeat_keeps_one(self):
        stories = {7: {"body": "Files area: scripts/lib/intake.py"}}
        with mock.patch.object(intake, "tracked", return_value={"scripts", "scripts/lib", "scripts/lib/intake.py"}):
            once, _ = intake.fit("Files area: scripts/lib/intake.py\n", "New", stories, ".")
            twice, _ = intake.fit(once, "New", stories, ".")
        self.assertEqual("Related: #7 (Files area overlaps)", once.splitlines()[-1])
        self.assertEqual(once, twice)

    def test_a_path_not_on_main_and_not_created_is_printed(self):
        with mock.patch.object(intake, "tracked", return_value={"a.py"}):
            _, lines = intake.fit("Files area: a.py, b.py, c.py, word\nCreates: c.py\n", "New", {}, ".")
        self.assertEqual(1, len(lines))
        self.assertIn("names b.py", lines[0])

    def test_git_unable_to_read_main_is_said(self):
        with mock.patch.object(intake, "tracked", return_value=None):
            _, lines = intake.fit("Files area: a.py\n", "New", {}, ".")
        self.assertIn("did not run", lines[0])


class TestRepeatedBlockers(unittest.TestCase):
    """A blocker the failure log holds three times is reported, two are not, and nothing is filed, commented or remembered (#1275)."""

    def setUp(self):
        home = temp_dir(self)
        p = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home), "OLIVERCODE_FAILURE_LOG": str(home / "failures.log")})
        p.start()
        self.addCleanup(p.stop)
        self.home = home

    def test_three_entries_are_reported_and_two_are_not(self):
        from lib import failure_log
        for _ in range(2):
            failure_log.record("gate 4", "land interrupted", "r")
        self.assertEqual([], intake.repeated_blockers())
        failure_log.record("gate 4", "land interrupted", "r")
        with mock.patch("subprocess.run") as gh:
            lines = intake.repeated_blockers()
        self.assertEqual(1, len(lines))
        self.assertIn("gate 4: land interrupted blocked 3 times", lines[0])
        gh.assert_not_called()
        self.assertFalse((self.home / "blocker-seen.json").exists())

    def test_a_refusal_from_a_guard_the_tree_no_longer_has_is_not_reported(self):
        self.assertEqual([], intake.repeated_blockers({("gone_guard", "x"): ["t1", "t2", "t3"]}))


BODY = ("Title: Fix the crash\n**As the owner**, I want the crash fixed, so that drain goes on.\n\n```gherkin\nFeature: x\n  Scenario: y\n    Given a\n    When b\n    Then c\n```\n\n"
        "Root cause: scripts/lib/a.py:1\n\nExisting coverage checked: grep.\n\nFit: reuses.\n\nSize: S. Work type: Story.\n\nFiles area: scripts/lib/a.py\n")


class TestBugIntake(unittest.TestCase):
    def setUp(self):
        from lib import failure_log
        self.log = failure_log
        home = temp_dir(self)
        p = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home), "OLIVERCODE_FAILURE_LOG": str(home / "failures.log")})
        p.start()
        self.addCleanup(p.stop)
        self.home = home
        self.calls = []
        self.prompts = []

    def stop(self, reason, at="2999-01-01T00:00:00Z", stage="stopped"):
        with open(self.home / "run-log.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"story": "story-9", "stage": stage, "reason": reason, "at": at}) + "\n")

    def gh(self, args):
        self.calls.append(args)
        out = {"number": 50 + len(self.calls)} if "POST" in args and any(a.endswith("/issues") for a in args) else {}
        return mock.Mock(returncode=0, stdout=json.dumps(out))

    def run_bugs(self, answer, opened=None):
        def read(task, *a, **k):
            self.prompts.append((task, k))
            return {"verdict": "findings", "text": answer}
        with mock.patch.object(intake.open_issues, "fetch", return_value=opened or []), \
                mock.patch.object(intake, "backlog_config", return_value={"repoOwner": "o", "repoName": "r"}), \
                mock.patch.object(intake, "file_story", side_effect=lambda slug, root, t, b, gh: 77), \
                mock.patch.object(intake, "ci_candidate", return_value=None):
            return intake.bugs(Path("."), gh=self.gh, read=read, say=lambda *_: None)

    def test_only_a_crash_a_fatal_stop_or_a_refused_close_is_a_candidate(self):
        rows = [{"stage": "stopped", "reason": r} for r in ("Drain blocked: the worker crashed with ValueError()", "Drain blocked: the landing queue crashed with x.",
                                                            "Close refused: no commit", "Drain blocked: The model finished, but nothing checked the result.")]
        rows += [{"stage": "stopped", "reason": r} for r in ("Drain stopped: the story spent its ceiling", "Held by the fresh reader", "tests failed", "usage limit")]
        self.assertEqual(4, len(intake.run_candidates(rows)))

    def test_candidates_that_differ_in_hex_numbers_or_worktree_paths_share_a_signature(self):
        a = intake.signature("drain", "crash 12 at /x/_worktrees/oc-1/f.py in deadbeef01")
        b = intake.signature("drain", "crash 345 at /y/_worktrees/oc-9/f.py in cafebabe99")
        self.assertEqual(a, b)

    def test_a_hook_crash_is_recorded_when_a_guard_raises(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
        import pretool_guard

        def boom():
            raise ValueError("bad")
        self.assertIsNone(pretool_guard._safely(boom))
        self.assertEqual("hook-crash", self.log.entries()[-1][2])
        self.assertIn("ValueError", self.log.entries()[-1][3])
        self.assertEqual(1, len(intake.hook_candidates()))

    def test_a_bug_is_filed_once_and_its_signature_is_never_read_again(self):
        self.run_bugs("")  # makes bug-seen.json, so older rows are not read
        self.stop("Close refused: no commit")
        self.assertEqual(1, self.run_bugs("BUG\n" + BODY))
        self.assertIn("The open stories", self.prompts[0][0])
        self.assertEqual(0, self.run_bugs("BUG\n" + BODY))
        self.assertEqual(1, len(self.prompts))

    def test_not_a_bug_is_recorded_and_files_nothing(self):
        self.run_bugs("")
        self.stop("Close refused: no commit")
        self.assertEqual(0, self.run_bugs("NOT A BUG\nIt is a feature."))
        self.assertEqual("not a bug", json.loads((self.home / "bug-seen.json").read_text())["seen"][intake.signature("drain", "Close refused: no commit")]["verdict"])

    def test_a_covered_failure_comments_on_the_open_story(self):
        self.run_bugs("")
        self.stop("Close refused: no commit")
        self.run_bugs("COVERED #12\nOpen story 12 covers it.", opened=[{"number": 12, "title": "t"}])
        self.assertIn(["-X", "POST", "repos/o/r/issues/12/comments"], [c[:3] for c in self.calls])

    def test_rows_older_than_bug_seen_json_are_never_read_and_a_run_reads_three(self):
        self.stop("Close refused: old", at="2000-01-01T00:00:00Z")
        self.run_bugs("NOT A BUG\nx")
        self.assertEqual([], self.prompts)
        for i in "abcde":
            self.stop(f"Close refused: reason {i}x")
        self.run_bugs("NOT A BUG\nx")
        self.assertEqual(3, len(self.prompts))

    def test_a_fourth_bug_waits_for_the_next_day_and_the_owner_queue_gets_nothing(self):
        self.run_bugs("")
        for i in "abcd":
            self.stop(f"Close refused: reason {i}x")
        now = intake.datetime.datetime(2999, 1, 1, tzinfo=intake.datetime.timezone.utc)
        with mock.patch.object(intake.open_issues, "fetch", return_value=[]), mock.patch.object(intake, "ci_candidate", return_value=None), \
                mock.patch.object(intake, "backlog_config", return_value={"repoOwner": "o", "repoName": "r"}), \
                mock.patch.object(intake, "file_story", return_value=77) as filed:
            read = lambda *a, **k: {"verdict": "findings", "text": "BUG\n" + BODY}
            self.assertEqual(3, intake.bugs(Path("."), gh=self.gh, read=read, now=now, say=print))
            self.assertEqual(1, intake.bugs(Path("."), gh=self.gh, read=read, now=now.replace(day=2), say=print))
        self.assertEqual(4, filed.call_count)

    def test_a_staging_ci_story_is_p1_and_others_p2(self):
        self.assertIn("Priority: P1.", intake.story_text(BODY, {"branch": "staging", "sig": "s", "text": "t"})[1])
        self.assertIn("Priority: P2.", intake.story_text(BODY, {"branch": "", "sig": "s", "text": "t"})[1])


if __name__ == "__main__":
    unittest.main()
