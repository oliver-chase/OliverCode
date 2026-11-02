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
