import tempfile
import unittest
from pathlib import Path

import design_check

DIRTY = """<p class="eyebrow">Features</p>
<h2 style="background-clip: text">Title</h2>
"""
CLEAN = """<!doctype html>
<style>:root { --ink: #111; } body { color: var(--ink); }</style>
<h1>Plain page</h1>
<form action="/send" method="post"><button>Send</button></form>
"""


def run(body, name="page.html"):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / name
        p.write_text(body)
        return design_check.check_file(p)


class DesignCheckTest(unittest.TestCase):
    def test_finds_eyebrow_and_gradient_text_with_lines(self):
        rows = {(line, rule) for line, rule, _, _ in run(DIRTY)}
        self.assertEqual(rows, {(1, "eyebrow"), (2, "gradient-text")})

    def test_clean_page_has_no_findings(self):
        self.assertEqual(run(CLEAN), [])

    def test_floor_tells(self):
        rows = {(rule, tier) for _, rule, tier, _ in run('<form><input></form><p>Lorem ipsum</p><span class="live-dot"></span>')}
        self.assertEqual(rows, {("dead-form", "floor"), ("placeholder-copy", "floor"), ("pulsing-live-dot", "floor")})

    def test_a_form_with_a_handler_passes(self):
        self.assertEqual(run('<form onSubmit={go}>x</form><form action={save}>y</form>', "a.tsx"), [])

    def test_a_non_ui_file_is_skipped(self):
        self.assertEqual(run("Lorem ipsum", "notes.md"), [])

    def test_main_exit_codes_and_output(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.css").write_text("h1 { letter-spacing: -0.02em; }")
            (Path(d) / "b.html").write_text(CLEAN)
            self.assertEqual(design_check.main([str(Path(d) / "b.html")]), 0)
            self.assertEqual(design_check.main([d]), 1)


if __name__ == "__main__":
    unittest.main()
