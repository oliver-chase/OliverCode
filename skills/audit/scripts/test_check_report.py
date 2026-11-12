import unittest

import check_report

GOOD = """# Audit
## 1. What it is
A thing.
## 2. Goal
Smaller.
## 3. Size today
100 lines.
## 4. Findings
| Lens | Finding | Issue |
|---|---|---|
| Autonomy and user flow | cards need a mouse | #26 |
| Self-containment | Checked, nothing found | |
| Accuracy | stale comment | #25 |
| One home per concept | two copies | #25 |
| Unused parts | dead file | #24 |
| Cost in use | whole file read | #29 |
| Voice | contrast framing | #28 |
| Documentation coverage | two scripts undocumented | #27 |
| Functionality gaps | Checked, nothing found | |
| Portability and sharing | personal email in history | #30 |
| Test necessity | three duplicates | #24 |
## 5. Cuts and simplifications
| Cut | Lines | Issue |
|---|---|---|
| audit script | 39 | #24 |
## 6. Outcomes
Smaller.
## 7. Added to the board
| #23 | epic |
## 8. Read and unknown
Read all files. Not checked: screen widths.
## 9. Coverage
- Stale comment: #25
"""


def problems(text):
    return check_report.check(text)


class ReportCheckTest(unittest.TestCase):
    def test_a_complete_report_passes(self):
        self.assertEqual(problems(GOOD), [])

    def test_a_missing_section_fails(self):
        self.assertTrue(any("missing section: goal" in p for p in problems(GOOD.replace("## 2. Goal\nSmaller.\n", ""))))

    def test_missing_coverage_fails(self):
        self.assertTrue(any("coverage" in p for p in problems(GOOD.split("## 9. Coverage")[0])))

    def test_a_finding_with_no_issue_fails(self):
        self.assertTrue(any("no issue number" in p for p in problems(GOOD.replace("| #25 |\n| One", "|  |\n| One"))))

    def test_an_unstated_lens_fails(self):
        self.assertTrue(any("lens: voice" in p for p in problems(GOOD.replace("| Voice | contrast framing | #28 |\n", ""))))

    def test_silence_about_what_was_not_checked_fails(self):
        self.assertTrue(any("read and unknown" in p for p in problems(GOOD.replace("Not checked: screen widths.", ""))))

    def test_coverage_not_last_fails(self):
        self.assertTrue(any("not the last" in p for p in problems(GOOD + "## 10. Extra\ntext\n")))


if __name__ == "__main__":
    unittest.main()
