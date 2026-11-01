"""Tests for core/templates/project/ste-lint-joined.py's line joining (STE-JOIN-1).

The vendor ste-lint.py splits sentences one physical line at a time, so the clarity
gate never saw a sentence longer than one wrapped line. These tests pin the join
itself, with no vendor install needed. The wrapper's own --selftest runs the same
cases through the real linter where it is installed.
"""

import importlib.util
import unittest
from pathlib import Path

WRAPPER = Path(__file__).resolve().parent.parent / "core" / "templates" / "project" / "ste-lint-joined.py"
spec = importlib.util.spec_from_file_location("ste_lint_joined", WRAPPER)
joined = importlib.util.module_from_spec(spec)
spec.loader.exec_module(joined)
join = joined.join_soft_wraps


class TestJoinSoftWraps(unittest.TestCase):
    def test_paragraph_joins_onto_first_line_and_keeps_line_count(self):
        text = "one two\nthree four.\n\nnext.\n"
        out = join(text)
        self.assertEqual(out.splitlines(), ["one two three four.", "", "", "next."])

    def test_list_continuation_joins_but_new_item_does_not(self):
        out = join("- a b\n  c d.\n- e.\n").splitlines()
        self.assertEqual(out, ["- a b c d.", "", "- e."])

    def test_heading_fence_rule_and_html_never_join(self):
        for text in ("# Title\nbody.\n", "body\n```\ncode\n```\n", "```\na\nb\n```\n",
                     "body\n---\nmore\n", "body\n<div>\n"):
            self.assertEqual(join(text), text, text)

    def test_table_rows_never_join(self):
        text = "| a | b |\n| --- | --- |\n| c | d |\ntrailing\n"
        self.assertEqual(join(text, frozenset({0, 1, 2})), text)

    def test_indented_code_block_after_blank_line_is_left_alone(self):
        text = "para.\n\n    code line\n    more code\n"
        self.assertEqual(join(text), text)

    def test_blockquote_joins_and_bare_marker_breaks(self):
        self.assertEqual(join("> a\n> b.\n").splitlines(), ["> a b.", ""])
        text = "> a.\n>\n> b.\n"
        self.assertEqual(join(text), text)

    def test_frontmatter_keys_stay_separate_and_folded_value_joins(self):
        out = join("---\nname: x\ndescription: >\n  a b\n  c.\n---\n").splitlines()
        self.assertEqual(out, ["---", "name: x", "description: > a b c.", "", "", "---"])


if __name__ == "__main__":
    unittest.main()
