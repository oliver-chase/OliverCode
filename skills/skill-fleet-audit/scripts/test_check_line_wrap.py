"""Fixture tests for check_line_wrap.py: a hard-wrapped paragraph is flagged; a one-line
paragraph, a list, a table, a fenced block, frontmatter, a rule plus HTML comment, and a quoted
list are not. main() is advisory and always exits 0, so the red/green signal is the report text.
The scan root is pointed at a temp folder.

Run from this scripts/ folder: python3 -m unittest test_check_line_wrap
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import check_line_wrap as lw


def hits(text):
    """1 when reflow would change the text, else 0."""
    return int(lw.reflow(text) != text)


def run_main(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        saved = lw.SKILLS_ROOT
        lw.SKILLS_ROOT = root
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                lw.main([])
        finally:
            lw.SKILLS_ROOT = saved
    return out.getvalue()


class Count(unittest.TestCase):
    def test_wrapped_paragraph_is_flagged(self):
        self.assertEqual(hits("First half of a sentence\nsecond half of it.\n"), 1)

    def test_one_line_paragraphs_are_clean(self):
        self.assertEqual(hits("One line.\n\nAnother line.\n"), 0)

    def test_list_is_clean(self):
        self.assertEqual(hits("- a\n- b\n  - c\n1. d\n2) e\n"), 0)

    def test_table_is_clean(self):
        self.assertEqual(hits("| a | b |\n|---|---|\n| 1 | 2 |\n"), 0)

    def test_fenced_code_is_clean(self):
        self.assertEqual(hits("```\nline one\nline two\n```\n"), 0)

    def test_frontmatter_is_clean(self):
        self.assertEqual(hits("---\nname: x\ndescription: y\n---\n\nBody.\n"), 0)

    def test_rule_then_html_comment_is_clean(self):
        self.assertEqual(hits("---\n<!-- end vendored -->\n"), 0)

    def test_quoted_blank_and_list_are_clean(self):
        self.assertEqual(hits("> Opening line\n>\n> - one\n> - two\n"), 0)

    def test_quoted_wrapped_paragraph_is_flagged(self):
        self.assertEqual(hits("> part one\n> part two\n"), 1)

    def test_heading_splits_runs(self):
        self.assertEqual(hits("Line.\n# Head\nLine.\n"), 0)


class Main(unittest.TestCase):
    def test_bad_file_is_reported(self):
        out = run_main({"fam/a.md": "wrap a\nwrap b\n", "fam/b.md": "Fine.\n"})
        self.assertIn("1 file(s) hold a hard-wrapped paragraph", out)
        self.assertIn("a.md", out)
        self.assertNotIn("b.md", out)

    def test_clean_tree_reports_none(self):
        out = run_main({"fam/b.md": "Fine.\n"})
        self.assertIn("No hard-wrapped paragraphs found.", out)

    def test_non_skill_dirs_skipped(self):
        out = run_main({"docs/a.md": "wrap a\nwrap b\n"})
        self.assertIn("No hard-wrapped paragraphs found.", out)


class ReflowTests(unittest.TestCase):
    def test_joins_a_wrapped_paragraph_and_list_item(self):
        text = "# T\n\nOne sentence that was wrapped at the\nright margin and goes on.\n\n- an item that wraps\n  onto a second line\n- next item\n"
        self.assertEqual(
            lw.reflow(text),
            "# T\n\nOne sentence that was wrapped at the right margin and goes on.\n\n- an item that wraps onto a second line\n- next item\n")

    def test_leaves_code_tables_hard_breaks_and_bold_labels(self):
        text = ("---\nname: x\ndescription: a\n  b\n---\n\n```\ncode line\nmore code\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
                "Line with a hard break  \nnext line\n\nA finished sentence.\n**Needs:** a thing\n")
        self.assertEqual(lw.reflow(text), text)

    def test_is_idempotent_and_clears_the_check(self):
        text = "Para one wraps\nacross lines.\n\nPara two wraps\nas well.\n"
        once = lw.reflow(text)
        self.assertEqual(lw.reflow(once), once)
        self.assertEqual(hits(once), 0)

    def test_key_value_lines_stay_separate(self):
        text = "Owner: Acme\nKind: Notes\nProject: A long project line\nthat wraps here.\n"
        self.assertEqual(lw.reflow(text), "Owner: Acme\nKind: Notes\nProject: A long project line that wraps here.\n")


class BlockingTests(unittest.TestCase):
    def test_blocking_fails_a_wrapped_file_and_passes_a_clean_one(self):
        with tempfile.TemporaryDirectory() as d:
            bad, good = Path(d) / "bad.md", Path(d) / "good.md"
            bad.write_text("One sentence wrapped\nacross two lines.\n")
            good.write_text("One sentence on one line.\n")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(lw.blocking([str(good)]), 0)
                self.assertEqual(lw.blocking([str(bad), str(good)]), 1)


if __name__ == "__main__":
    unittest.main()
