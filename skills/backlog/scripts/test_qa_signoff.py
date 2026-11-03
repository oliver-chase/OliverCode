"""Test the QA sign-off checker against fixtures. No network and no gh.
Run: python3 -m unittest discover -p "test_*.py"   (from this folder)
"""
import io
import json
import subprocess
import unittest
from pathlib import Path

import check_qa_signoff as qa

FIX = Path(__file__).parent / "fixtures"
BODY = str(FIX / "qa-story.body")


def run(name, **kw):
    out, err = io.StringIO(), io.StringIO()
    code = qa.main(["--story", "54", "--comments", str(FIX / name), "--body", BODY],
                   out=out, err=err, **kw)
    return code, out.getvalue()


class QaSignoff(unittest.TestCase):
    def test_an_independent_pass_is_accepted_and_lists_each_scenario(self):
        code, text = run("qa-pass.json")
        self.assertEqual(code, 0)
        self.assertIn("confirmed by qa-1: Work is finished", text)
        self.assertIn("confirmed by qa-1: Work fails", text)

    def test_no_qa_comment_is_refused(self):
        code, text = run("qa-none.json")
        self.assertEqual(code, 1)
        self.assertIn("no QA comment", text)

    def test_the_builder_cannot_qa_its_own_work_even_with_different_case(self):
        code, text = run("qa-self.json")
        self.assertEqual(code, 1)
        self.assertIn("QA agent is a builder", text)

    def test_a_fail_result_is_refused(self):
        code, text = run("qa-fail.json")
        self.assertEqual(code, 1)
        self.assertIn("not PASS", text)

    def test_an_unconfirmed_scenario_is_named(self):
        code, text = run("qa-unconfirmed.json")
        self.assertEqual(code, 1)
        self.assertIn("scenario unconfirmed by qa-1: Work fails", text)

    def test_a_lone_qa_comment_with_no_builder_comment_is_refused(self):
        code, text = run("qa-only.json")
        self.assertEqual(code, 1)
        self.assertIn("no builder comment", text)

    def test_a_scenario_name_must_match_whole_not_as_a_substring(self):
        code, text = run("qa-substring.json")
        self.assertEqual(code, 1)
        self.assertIn("scenario unconfirmed by qa-1: Work is finished", text)

    def test_matching_ignores_case_and_surrounding_space(self):
        body = "Scenario: Work is finished\n"
        comments = [
            "Agent action\n- Agent: b\n- Role: builder\n- Result: x",
            "Agent action\n- Agent: q\n- Role: qa\n- Result: PASS; Confirmed:  WORK IS FINISHED ",
        ]
        self.assertTrue(qa.check(comments, body)[0])

    def test_a_pass_with_no_confirmed_list_confirms_nothing(self):
        body = "Scenario: Work is finished\n"
        comments = [
            "Agent action\n- Agent: b\n- Role: builder\n- Result: x",
            "Agent action\n- Agent: q\n- Role: qa\n- Result: PASS; Work is finished",
        ]
        self.assertFalse(qa.check(comments, body)[0])

    def test_a_trailing_note_is_tolerated_but_a_longer_name_is_not(self):
        body = "Scenario: A full run\nScenario: Validation passes on a clean main\n"
        b = "Agent action\n- Agent: b\n- Role: builder\n- Result: x"

        def ok(conf):
            return qa.check([b, f"Agent action\n- Agent: q\n- Role: qa\n- Result: PASS; confirmed: {conf}"], body)[0]
        self.assertTrue(ok("A full run; Validation passes on a clean main. Tested on main 74a99fb"))
        self.assertTrue(ok("A full run (note); Validation passes on a clean main - fine"))
        self.assertTrue(ok("A full run, ok; Validation passes on a clean main: yes"))
        self.assertFalse(ok("A full run leaves X unchanged; Validation passes on a clean main"))
        longer = "Scenario: Login\nScenario: Login - admin\n"
        self.assertFalse(qa.check([b, "Agent action\n- Agent: q\n- Role: qa\n- Result: PASS; confirmed: Login - admin"], longer)[0])
        self.assertTrue(qa.check([b, "Agent action\n- Agent: q\n- Role: qa\n- Result: PASS; confirmed: Login; Login - admin"], longer)[0])

    def test_mechanical_story_needs_builder_proof_else_normal_path(self):
        b = "Agent action\n- Agent: b\n- Role: builder\n- Result: %s"
        q = "Agent action\n- Agent: q\n- Role: qa\n- Result: PASS; confirmed: Work is finished"
        mech, plain = "Scenario: Work is finished\n  qa: Mechanical \n", "Scenario: Work is finished\n"
        ok, lines = qa.check([b % "Validate.sh exits 0"], mech)
        self.assertTrue(ok)
        self.assertEqual(lines, ["mechanical: proof from b: Validate.sh exits 0"])
        ok, lines = qa.check([b % "done"], mech)
        self.assertFalse(ok)
        self.assertIn('mechanical proof missing: the builder comment must say "validate.sh exits 0"', lines)
        self.assertTrue(qa.check([b % "done", q], mech)[0])
        ok, lines = qa.check([b % "validate.sh exits 0"], plain)
        self.assertFalse(ok)
        self.assertIn("no QA comment", lines[0])
        self.assertEqual(len(lines), 1)
        fenced = "Scenario: Work is finished\n```\nQA: mechanical\n```\n"
        self.assertFalse(qa.check([b % "validate.sh exits 0"], fenced)[0])
        self.assertFalse(qa.check([b % "validate.sh exits 01 failed"], mech)[0])

    def test_a_later_fail_overrides_an_earlier_pass(self):
        pages = json.loads((FIX / "qa-pass.json").read_text())
        pages.append(json.loads((FIX / "qa-fail.json").read_text())[1])
        ok, _ = qa.check(qa.flatten([pages]), Path(BODY).read_text())
        self.assertFalse(ok)

    def test_fetch_uses_the_injected_runner(self):
        data = (FIX / "qa-pass.json").read_text()
        calls = []

        def runner(args):
            calls.append(args)
            text = data if "--slurp" in args else Path(BODY).read_text()
            return subprocess.CompletedProcess([], 0, text if "--slurp" not in args else json.dumps([json.loads(data)]), "")

        out = io.StringIO()
        code = qa.main(["--story", "54", "--repo", "o/r"], runner=runner, out=out, err=io.StringIO())
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)

    def test_missing_repo_is_a_usage_error(self):
        self.assertEqual(qa.main(["--story", "54"], out=io.StringIO(), err=io.StringIO()), 2)


if __name__ == "__main__":
    unittest.main()
