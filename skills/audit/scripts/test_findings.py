import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import check_report
import findings


def item(**kw):
    base = {"lens": "Accuracy", "priority": "P1", "where": "a.py:1", "defect": "wrong count",
            "evidence": "wc -l a.py", "fix": "correct it"}
    base.update(kw)
    return base


def confirm(led, fid, priority="P1"):
    findings.verdict(led, "lead", fid, "fresh-reader", "confirmed", priority)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "docs" / "AUDIT-FINDINGS.json")
        self.led = findings.start(self.path, "repo", "lead", ["skills", "scripts"])

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = findings.main(["findings.py", self.path, *args])
        return code, out.getvalue()


class OneLedger(Base):
    def test_every_chunk_writes_one_ledger_with_one_numbering(self):
        self.assertEqual(self.run_cli("add", "--chunk", "skills", "--lens", "Voice", "--priority", "P2",
                                      "--where", "s.md:3", "--defect", "fragment", "--evidence", "line 3",
                                      "--fix", "rewrite")[1].strip(), "F1")
        src = Path(self.tmp.name) / "chunk.json"
        src.write_text(json.dumps([item(), item(where="b.py:2", defect="other")]))
        self.assertEqual(self.run_cli("add", "--chunk", "scripts", "--from", str(src))[1].split(), ["F2", "F3"])
        led = findings.load(self.path)
        self.assertEqual([f["id"] for f in led["findings"]], ["F1", "F2", "F3"])
        self.assertEqual(led["scale"], ["P0", "P1", "P2"])

    def test_second_start_is_refused(self):
        with self.assertRaises(findings.Refused):
            findings.start(self.path, "repo", "other", ["x"])

    def test_off_scale_priority_unknown_lens_and_missing_field_are_refused(self):
        for bad in (item(priority="high"), item(lens="style"), item(fix="")):
            with self.assertRaises(findings.Refused):
                findings.add(self.led, "skills", bad)
        with self.assertRaises(findings.Refused):
            findings.add(self.led, "nowhere", item())


class OneCoordinator(Base):
    def test_only_the_coordinator_crosses_files_and_reports(self):
        findings.add(self.led, "skills", item())
        for c in self.led["chunks"]:
            findings.done(self.led, c)
        with self.assertRaises(findings.Refused):
            findings.cross(self.led, "chunk-session")
        findings.cross(self.led, "lead")
        with self.assertRaises(findings.Refused):
            findings.file_issue(self.led, "chunk-session", "F1", 900)
        confirm(self.led, "F1")
        findings.file_issue(self.led, "lead", "F1", "#900")
        with self.assertRaises(findings.Refused):
            findings.report(self.led, "chunk-session")

    def test_filing_waits_for_the_cross_pass(self):
        findings.add(self.led, "skills", item())
        with self.assertRaises(findings.Refused):
            findings.file_issue(self.led, "lead", "F1", 900)

    def test_cross_waits_for_every_chunk(self):
        findings.done(self.led, "skills")
        with self.assertRaises(findings.Refused):
            findings.cross(self.led, "lead")


class CrossPass(Base):
    def test_duplicates_across_chunks_merge_and_keep_the_higher_priority(self):
        findings.add(self.led, "skills", item(priority="P2", defect="Wrong count."))
        findings.add(self.led, "scripts", item(priority="P0", where="z.py:9", defect="wrong count"))
        findings.add(self.led, "scripts", item(where="b.py:2", defect="other"))
        for c in self.led["chunks"]:
            findings.done(self.led, c)
        merges, _ = findings.cross(self.led, "lead")
        self.assertEqual(merges, [("F2", "F1")])
        f1 = self.led["findings"][0]
        self.assertEqual((f1["priority"], f1["chunks"], f1["where"]), ("P0", ["scripts", "skills"], ["a.py:1", "z.py:9"]))
        confirm(self.led, "F1")
        self.assertEqual(findings.file_issue(self.led, "lead", "F2", 901), "F1")
        with self.assertRaises(findings.Refused):
            findings.add(self.led, "skills", item(defect="late"))

    def test_a_rule_broken_in_two_chunks_becomes_one_finding_and_single_chunk_rules_are_checked(self):
        findings.add(self.led, "skills", item(rule="no contrast framing", defect="contrast in s.md"))
        findings.add(self.led, "scripts", item(rule="No contrast framing", where="c.py:4", defect="contrast in c.py"))
        findings.add(self.led, "skills", item(rule="one home", where="d.md:1", defect="two homes"))
        for c in self.led["chunks"]:
            findings.done(self.led, c)
        merges, checks = findings.cross(self.led, "lead")
        self.assertEqual(merges, [("F2", "F1")])
        self.assertEqual(len(self.led["findings"]), 2)
        self.assertEqual(checks, ['check rule "one home" (F3, found in skills) in scripts'])


class MergeKeepsText(Base):
    def test_two_findings_on_one_line_keep_both_defects_fixes_and_the_higher_priority(self):
        findings.add(self.led, "skills", item(priority="P1", where="a.py:5", defect="drops text", evidence="e1", fix="fix one"))
        findings.add(self.led, "scripts", item(priority="P0", where="a.py:5", defect="wrong id", evidence="e2", fix="fix two"))
        for c in self.led["chunks"]:
            findings.done(self.led, c)
        findings.cross(self.led, "lead")
        (row,) = self.led["findings"]
        self.assertEqual("P0", row["priority"])
        for text in ("drops text", "wrong id", "e1", "e2", "fix one", "fix two"):
            self.assertIn(text, " ".join((row["defect"], row["evidence"], row["fix"])))


class OneReport(Base):
    def test_report_is_one_priority_order_that_passes_the_report_check(self):
        findings.add(self.led, "skills", item(priority="P2", lens="Voice", defect="fragment"))
        findings.add(self.led, "scripts", item(priority="P0", where="k.py:1", defect="leak"))
        for c in self.led["chunks"]:
            findings.done(self.led, c)
        findings.cross(self.led, "lead")
        with self.assertRaises(findings.Refused):
            findings.report(self.led, "lead")
        confirm(self.led, "F1", "P2")
        confirm(self.led, "F2", "P0")
        findings.file_issue(self.led, "lead", "F1", 910)
        findings.file_issue(self.led, "lead", "F2", 911)
        table = findings.report(self.led, "lead")
        rows = table.splitlines()[2:]
        self.assertIn("| P0 | F2 |", rows[0])
        self.assertIn("| P2 | F1 |", rows[1])
        self.assertNotIn("skills", table)
        body = "\n".join(l.strip("| ").split("|")[0] for l in rows)
        for rx in check_report.LENSES.values():
            self.assertRegex(body, "(?i)" + rx)
        self.assertEqual(check_report.rows_without_issue(table.splitlines()), [])


class Verdicts(Base):
    def crossed(self, n=1):
        for i in range(n):
            findings.add(self.led, "skills", item(where=f"a.py:{i}", defect=f"d{i}"))
        for c in self.led["chunks"]:
            findings.done(self.led, c)
        findings.cross(self.led, "lead")

    def test_an_unjudged_or_unconfirmed_finding_is_not_filed_or_reported(self):
        self.crossed()
        with self.assertRaises(findings.Refused):
            findings.file_issue(self.led, "lead", "F1", 900)
        with self.assertRaises(findings.Refused):
            findings.report(self.led, "lead")

    def test_the_writer_of_a_finding_cannot_judge_it(self):
        self.crossed()
        with self.assertRaises(findings.Refused):
            findings.verdict(self.led, "lead", "F1", "skills", "confirmed", "P1")

    def test_unproven_names_its_blocker_carries_no_priority_and_is_reported_unfiled(self):
        self.crossed()
        with self.assertRaises(findings.Refused):
            findings.verdict(self.led, "lead", "F1", "reader", "unproven")
        findings.verdict(self.led, "lead", "F1", "reader", "unproven", blocker="needs the prod log")
        self.assertIsNone(self.led["findings"][0]["priority"])
        with self.assertRaises(findings.Refused):
            findings.file_issue(self.led, "lead", "F1", 900)
        table = findings.report(self.led, "lead")
        self.assertIn("Unproven, no priority", table)
        self.assertIn("needs the prod log", table)
        self.assertEqual(check_report.rows_without_issue(table.splitlines()), [])

    def test_a_rejected_finding_leaves_the_report(self):
        self.crossed(2)
        findings.verdict(self.led, "lead", "F1", "reader", "rejected")
        confirm(self.led, "F2")
        findings.file_issue(self.led, "lead", "F2", 901)
        self.assertNotIn("F1", findings.report(self.led, "lead"))

    def test_a_confirmed_finding_needs_a_priority_and_a_known_status(self):
        self.crossed()
        for status, prio in (("confirmed", ""), ("maybe", "P1")):
            with self.assertRaises(findings.Refused):
                findings.verdict(self.led, "lead", "F1", "reader", status, prio)


if __name__ == "__main__":
    unittest.main()
