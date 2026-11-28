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
Autonomy and user flow: one card needs a mouse, which blocks keyboard users. Next: make every card reachable by keyboard.
Self-containment: nothing found, so no fix is needed for this lens.
Accuracy: one comment is stale and misleads the next reader. Next: correct it with the change in #25.
One home per concept: two copies of one rule drift apart. Next: keep one copy and point to it, in #25.
Over-engineering and unused parts: one file is dead. Next: delete it in #24.
Cost in use: a whole file is read on each call. Next: read only the section needed, in #29.
Voice: contrast framing appears in one reply. Next: rewrite it per the voice rules, in #28.
Documentation coverage: two scripts have no docs. Next: document them in #27.
Functionality gaps: nothing found, so no story is needed for this lens.
Portability and sharing: a personal email sits in history. Next: remove it, in #30.
Test necessity: three tests duplicate one another. Next: cut the duplicates in #24.
Design: nothing found, so no fix is needed for this lens.
| Lens | Finding | Issue |
|---|---|---|
| Autonomy and user flow | cards need a mouse | #26 |
| Self-containment | Checked, nothing found | |
| Accuracy | stale comment | #25 |
| One home per concept | two copies | #25 |
| Unused parts | dead file | #24 |
| Cost in use | whole file read | #29 |
| Voice | contrast framing | #28 |
| Design | Checked, nothing found | |
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
        headings = re.findall(r"^## \d+[a-z]?\. (.+)$",(Path(__file__).parent.parent / "references" / "lenses.md").read_text(), re.M)
        for heading in headings:
            self.assertTrue(any(re.search(rx, heading, re.I) for rx in check_report.LENSES.values()), heading)

    def test_each_gap_in_a_report_fails_with_its_reason(self):
        # A missing section or coverage, a finding with no issue, an unstated lens, silence about what
        # was not checked, and coverage that is not the last section.
        voice_opener = "Voice: contrast framing appears in one reply. Next: rewrite it per the voice rules, in #28.\n"
        for reason, report in (("missing section: goal", GOOD.replace("## 2. Goal\nSmaller.\n", "")),
                               ("coverage", GOOD.split("## 9. Coverage")[0]),
                               ("no issue number", GOOD.replace("| #25 |\n| One", "|  |\n| One")),
                               ("lens: voice", GOOD.replace("| Voice | contrast framing | #28 |\n", "")),
                               ("lens has no opening sentence: voice", GOOD.replace(voice_opener, "")),
                               ("lens has no opening sentence: voice", GOOD.replace(voice_opener, "").replace(
                                   "| Voice | contrast framing | #28 |\n", "| Voice | contrast framing | #28 |\n" + voice_opener)),
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

    def test_an_issue_number_at_the_start_of_a_line_is_not_a_heading(self):
        order, _ = check_report.sections(GOOD.replace("| Voice | contrast framing | #28 |", "#812 holds the voice fix\n| Voice | contrast framing | #28 |"))
        self.assertFalse(any(o.startswith("812") for o in order))

    def test_a_small_route_needs_only_a_findings_list(self):
        import io, sys
        from unittest import mock
        for route in ("plan", "docs", "changes"):
            with mock.patch.object(sys, "stdin", io.StringIO("- plan.md:4 step 2 names a missing file. Fix: add it\n")):
                self.assertEqual(0, check_report.main(["check_report.py", "-", "--route", route]))
        with mock.patch.object(sys, "stdin", io.StringIO("  \n")):
            self.assertEqual(1, check_report.main(["check_report.py", "-", "--route", "plan"]))
        with mock.patch.object(sys, "stdin", io.StringIO("- a finding\n")):
            self.assertEqual(1, check_report.main(["check_report.py", "-"]))

    def test_a_whole_repo_report_fails_while_files_are_pending(self):
        from test_audit_ledger import repo
        import audit_ledger
        root = repo({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        audit_ledger.mark(root, ["a.py"])
        self.assertTrue(any("1 files (1 lines)" in p for p in check_report.unread(root)))
        audit_ledger.mark(root, ["b.py"])
        self.assertEqual(check_report.unread(root), [])

    def test_a_stopped_audit_passes_only_with_every_unread_file_deferred_and_no_full_coverage_claim(self):
        from test_audit_ledger import repo
        import audit_ledger
        root = repo({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        audit_ledger.mark(root, ["a.py"])
        self.assertEqual(check_report.unread(root, "Deferred: b.py, out of budget"), [])
        self.assertTrue(check_report.unread(root, "Deferred: c.py"))
        self.assertTrue(check_report.unread(root, "Deferred: b.py. Full coverage."))
        self.assertTrue(check_report.unread(root, "b.py was not read"))
        self.assertTrue(any("b.py" in p for p in check_report.unread(root, "Deferred: ab.py")))
