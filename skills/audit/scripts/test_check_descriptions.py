"""Tests for check_descriptions.py. Run from this scripts/ folder: python3 -m unittest test_check_descriptions"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import check_descriptions as cd

DESC = "---\nname: {n}\ndescription: {d}\n---\n\nBody.\n"


def run_main(files):
    with tempfile.TemporaryDirectory() as tmp:
        fleet = Path(tmp).resolve()
        for rel, text in files.items():
            (fleet / rel).parent.mkdir(parents=True, exist_ok=True)
            (fleet / rel).write_text(text, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                cd.main([str(fleet)])
                code = 0
            except SystemExit as e:
                code = e.code
    return code, out.getvalue()


class Descriptions(unittest.TestCase):
    def test_a_description_over_the_cap_fails(self):
        long = " ".join(["word"] * (cd.DESCRIPTION_WORD_LIMIT + 1))
        code, out = run_main({"s/SKILL.md": DESC.format(n="s", d=long), "t/SKILL.md": DESC.format(n="t", d="short")})
        self.assertEqual(code, 1, out)
        self.assertIn("s/SKILL.md", out)
        self.assertNotIn("t/SKILL.md", out)

    def test_descriptions_within_the_cap_pass(self):
        code, out = run_main({"s/SKILL.md": DESC.format(n="s", d="short")})
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
