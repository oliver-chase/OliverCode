import re
import unittest
from pathlib import Path

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
| Story | Title | Why |
|---|---|---|
| #23 | epic | The audit found waste |
| #24 | cut | Dead files cost reads |
## 8. Read and unknown
Read all files. Not checked: screen widths.
## 9. Coverage
- Stale comment: #25
## 10. Engine parts to cut or merge
| Part | Issue |
|---|---|
| audit script | #24 |
"""


def problems(text):
    return check_report.check(text)


class ReportCheckTest(unittest.TestCase):
    def test_a_complete_report_passes(self):
        self.assertEqual(problems(GOOD), [])
        # Each lens in references/lenses.md has its own pattern here, so a renamed or added lens fails this test.
        headings = re.findall(r"^## \d+\. (.+)$", (Path(__file__).parent.parent / "references" / "lenses.md").read_text(), re.M)
        for heading in headings:
            self.assertTrue(any(re.search(rx, heading, re.I) for rx in check_report.LENSES.values()), heading)

    def test_each_gap_in_a_report_fails_with_its_reason(self):
        # A missing section or coverage, a finding with no issue, an unstated lens, silence about what
        # was not checked, and coverage that is not the last section.
        for reason, report in (("missing section: goal", GOOD.replace("## 2. Goal\nSmaller.\n", "")),
                               ("coverage", GOOD.split("## 9. Coverage")[0]),
                               ("no issue number", GOOD.replace("| #25 |\n| One", "|  |\n| One")),
                               ("lens: voice", GOOD.replace("| Voice | contrast framing | #28 |\n", "")),
                               ("read and unknown", GOOD.replace("Not checked: screen widths.", "")),
                               ("not the last", GOOD + "## 11. Extra\ntext\n"),
                               ("no Why column", GOOD.replace(" | Why |", " | Note |")),
                               ("empty Why", GOOD.replace("| The audit found waste |", "|  |")),
                               ("engine parts", GOOD.split("## 10.")[0])):
            with self.subTest(reason=reason):
                self.assertTrue(any(reason in p for p in problems(report)))

    def test_the_empty_why_failure_names_the_story(self):
        self.assertTrue(any("#23" in p for p in problems(GOOD.replace("| The audit found waste |", "|  |"))))

    def test_a_report_delivered_as_a_file_fails_and_stdin_passes(self):
        import io, sys
        from unittest import mock
        self.assertEqual(1, check_report.main(["check_report.py", "report.md"]))
        with mock.patch.object(sys, "stdin", io.StringIO(GOOD)):
            self.assertEqual(0, check_report.main(["check_report.py", "-"]))
