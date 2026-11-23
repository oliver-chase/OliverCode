import atexit
import contextlib
import io
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import done_check


def fake(outputs):
    """A runner that answers by the script name in the command."""
    def run(cmd, cwd):
        key = " ".join(map(str, cmd)) if isinstance(cmd, list) else cmd
        for needle, (rc, text) in outputs.items():
            if needle in key:
                return rc, text
        return 0, ""
    return run


def repo(readme="", accepted=""):
    root = Path(tempfile.mkdtemp())
    atexit.register(shutil.rmtree, root, True)
    (root / "docs").mkdir()
    (root / "README.md").write_text(readme)
    if accepted:
        (root / "docs/AUDIT-ACCEPTED.md").write_text(accepted)
    return root


class DoneCheckTest(unittest.TestCase):
    def names(self, results):
        return {n for n, ok, _ in results if not ok}

    def test_all_clear_with_a_recorded_verdict_is_done(self):
        results = done_check.checks(repo("Sharing: portable\n"), run=fake({}))
        self.assertEqual(self.names(results), set())

    def test_missing_verdict_and_a_failing_validation_fail(self):
        results = done_check.checks(repo(), run=fake({"validate": (1, "boom\n")}))
        self.assertEqual(self.names(results), {"validation", "sharing verdict recorded"})

    def test_voice_and_sweep_rows_fail(self):
        out = {"fleet_check": (0, "voice: 2 contrast framing\n"),
               "sweep.py": (0, "unused-def  a.py:3  dead\n")}
        self.assertEqual(self.names(done_check.checks(repo("Sharing: portable\n"), run=fake(out))), {"tests, voice and board", "sweep"})

    def test_a_helper_crash_or_an_unread_board_fails_its_check(self):
        trace = "Traceback (most recent call last):\n  File x\nKeyError: 'k'\n"
        out = {"fleet_check": (1, "board: not checked (gh failed)\n"), "sweep.py": (1, trace), "portability.py": (1, trace)}
        self.assertEqual(self.names(done_check.checks(repo("Sharing: portable\n"), run=fake(out))),
                         {"tests, voice and board", "sweep", "portability"})

    def test_a_sweep_traceback_ending_in_a_bare_exception_name_still_fails(self):
        out = {"sweep.py": (0, "Traceback (most recent call last):\n  File x\nStopIteration\n")}
        self.assertIn("sweep", self.names(done_check.checks(repo("Sharing: portable\n"), run=fake(out))))

    def test_a_sweep_row_for_a_path_with_a_space_matches_its_accepted_row(self):
        out = {"sweep.py": (0, 'orphan      "my dir/a.py"  nothing names it\n')}
        self.assertEqual({"sweep"}, self.names(done_check.checks(repo("Sharing: portable\n"), run=fake(out))))
        root = repo("Sharing: portable\n", 'Accepted: orphan "my dir/a.py" - kept\n')
        self.assertEqual(set(), self.names(done_check.checks(root, run=fake(out))))

    def test_an_accepted_sweep_row_survives_a_line_number_change(self):
        out = {"sweep.py": (0, "unused-def  lib/mod.py:5  dead\n")}
        root = repo("Sharing: portable\n", "Accepted: unused-def lib/mod.py:4 - kept for a hook\n")
        self.assertEqual(set(), self.names(done_check.checks(root, run=fake(out))))

    def test_an_accepted_row_needs_its_reason_and_a_missing_backlog_skill_fails_the_board_check(self):
        out = {"sweep.py": (0, "unused-def  a.py:3  dead\n")}
        self.assertEqual({"sweep"}, self.names(done_check.checks(repo("Sharing: portable\n", "Accepted: unused-def a.py:3\n"), run=fake(out))))
        root = repo("Sharing: portable\n")
        (root / "docs/backlog-config.json").write_text("{}")
        with unittest.mock.patch.object(done_check, "HYGIENE", root / "gone.py"):
            self.assertEqual({"board hygiene"}, self.names(done_check.checks(root, run=fake({}))))

    def test_an_issue_with_both_owner_action_and_program_labels_is_listed_once_as_an_owner_action(self):
        out = {"gh api": (0, "7\towner-action,program\n")}
        detail = dict((n, d) for n, _, d in done_check.checks(repo("Sharing: portable\n"), run=fake(out)))["no open issue"]
        self.assertIn("1 owner action(s)", detail)
        self.assertNotIn("program item", detail)

    def test_a_path_with_a_space_is_one_row_and_one_accepted_where(self):
        self.assertEqual([("home-path", "my dir/notes.md")], done_check.rows('home-path       "my dir/notes.md"  names x\n'))

    def test_a_failing_test_file_in_the_fleet_check_fails_the_tests_row(self):
        out = {"fleet_check": (1, "failing test files: test_x\n")}
        self.assertEqual(self.names(done_check.checks(repo("Sharing: portable\n"), run=fake(out))), {"tests, voice and board"})

    def test_a_prose_line_is_not_a_sharing_verdict(self):
        self.assertIn("sharing verdict recorded", self.names(done_check.checks(repo("Sharing portable tools are easy to clone.\n"), run=fake({}))))

    def test_a_missing_helper_fails_its_check(self):
        gone = (2, "python3: can't open file 'x.py'\n")
        out = {"fleet_check": gone, "sweep.py": gone, "portability.py": gone}
        self.assertEqual(self.names(done_check.checks(repo("Sharing: portable\n"), run=fake(out))),
                         {"tests, voice and board", "sweep", "portability"})

    def test_a_personal_verdict_needs_its_reason(self):
        self.assertIn("sharing verdict recorded", self.names(done_check.checks(repo("Sharing: personal\n"), run=fake({}))))
        self.assertIn("sharing verdict recorded", self.names(done_check.checks(repo("Sharing: personal -\n- next line\n"), run=fake({}))))
        self.assertNotIn("sharing verdict recorded",
                         self.names(done_check.checks(repo("Sharing: personal - my own notes\n"), run=fake({}))))

    def test_a_package_with_only_a_check_script_runs_it(self):
        root = repo("Sharing: portable\n")
        (root / "package.json").write_text('{"scripts": {"check": "x"}}')
        self.assertEqual("npm run check", done_check.default_validation(root))

    def test_the_clean_voice_line_that_fleet_check_prints_passes(self):
        out = {"fleet_check": (0, "== Voice\nvoice: no violations found\n== Board\nboard: matches the baseline\n")}
        self.assertEqual(self.names(done_check.checks(repo("Sharing: portable\n"), run=fake(out))), set())

    def test_an_accepted_row_is_not_counted(self):
        out = {"sweep.py": (0, "unused-def  a.py:3  dead\n")}
        root = repo("Sharing: portable\n", "Accepted: unused-def a.py:3 - runtime entry\n")
        self.assertEqual(self.names(done_check.checks(root, run=fake(out))), set())

    def test_personal_verdict_only_counts_secrets(self):
        out = {"portability.py": (1, "personal-email  1-addresses  x\nhistory-secret  2-commits  y\nsignals: none\nportability: 2 blocker(s)\n")}
        personal = done_check.checks(repo("Sharing: personal - uses my own notes\n"), run=fake(out))
        portable = done_check.checks(repo("Sharing: portable\n"), run=fake(out))
        self.assertIn("portability", self.names(personal))
        self.assertIn("portability", self.names(portable))
        only_email = {"portability.py": (1, "personal-email  1-addresses  x\nportability: 1 blocker(s)\n")}
        self.assertEqual(self.names(done_check.checks(repo("Sharing: personal - mine\n"), run=fake(only_email))), set())

    def test_an_accepted_count_row_hides_only_that_count(self):
        accepted = "Accepted: history-secret 2-commits - revoked\n"
        for printed, hidden in (("2-commits", True), ("3-commits", False)):
            out = {"portability.py": (1, f"history-secret  {printed}  y\n")}
            root = repo("Sharing: personal - mine\n", accepted)
            self.assertEqual("portability" not in self.names(done_check.checks(root, run=fake(out))), hidden, printed)

    def test_epic_must_be_closed(self):
        out = {"issue view": (0, '{"state": "OPEN", "body": ""}'), "issue list": (0, "2\n")}
        results = done_check.checks(repo("Sharing: portable\n"), epics=[5], run=fake(out))
        self.assertEqual(self.names(results), {"epic #5 closed", "no open story under epic #5"})

    def test_an_open_issue_fails_and_an_owner_action_passes_with_its_number(self):
        open_one = {"gh api": (0, "12\tstory\n")}
        self.assertEqual(self.names(done_check.checks(repo("Sharing: portable\n"), run=fake(open_one))), {"no open issue"})
        owner = {"gh api": (0, "150\towner-action,story\n")}
        results = done_check.checks(repo("Sharing: portable\n"), run=fake(owner))
        self.assertEqual(self.names(results), set())
        self.assertIn("#150", dict((n, d) for n, _, d in results)["no open issue"])

    def test_a_program_issue_is_skipped_by_number_and_an_unlabeled_one_still_fails(self):
        program = {"gh api": (0, "418\tprogram,epic\n419\tprogram\n")}
        results = done_check.checks(repo("Sharing: portable\n"), run=fake(program))
        self.assertEqual(self.names(results), set())
        self.assertIn("#418, #419", dict((n, d) for n, _, d in results)["no open issue"])
        mixed = {"gh api": (0, "418\tprogram\n12\tstory\n")}
        self.assertEqual(self.names(done_check.checks(repo("Sharing: portable\n"), run=fake(mixed))), {"no open issue"})

    def test_a_flag_with_no_value_prints_usage(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(2, done_check.main(["done_check.py", "--epic"]))
        self.assertIn("Usage", out.getvalue())

    def test_a_board_hygiene_finding_fails_when_the_repo_has_a_backlog_config(self):
        root = repo("Sharing: portable\n")
        (root / "docs/backlog-config.json").write_text("{}")
        out = {"check_board_hygiene": (1, "1 finding(s):\n  - [required-fields] #7 has no Size\n")}
        results = done_check.checks(root, run=fake(out))
        self.assertEqual(self.names(results), {"board hygiene"})
        self.assertIn("#7 has no Size", dict((n, d) for n, _, d in results)["board hygiene"])
