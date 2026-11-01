"""Fixture tests for check_clarity.py: the description word-count flag, skill and references
discovery, and main() exit codes against a stub linter and a stub joined-lint wrapper. Every root
is pointed at a temp folder.

Not covered: the real asd-ste100 rules. They need the installed linter; the stubs only prove this
script's own wiring (which files reach the linter, how a hard violation sets the exit code).

Run from this scripts/ folder: python3 -m unittest test_check_clarity
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import check_clarity as cc

# Stub wrapper: argv = [wrapper, <ste-lint>, <file>]. Exits 1 when the file text holds BADWORD.
# The stub linter takes the same shape, argv = [linter, <file>], so one body serves both.
WRAPPER = (
    "import sys\n"
    "text = open(sys.argv[-1], encoding='utf-8').read()\n"
    "sys.exit(1 if 'BADWORD' in text else 0)\n"
)
DESC = "---\nname: {n}\ndescription: {d}\n---\n\nBody.\n"


def run_main(files, with_lint=True, with_wrapper=True):
    """Build a temp fleet tree, run main(), return (exit code, stdout)."""
    with tempfile.TemporaryDirectory() as tmp:
        git = fleet = Path(tmp).resolve() / "fleet"
        for rel, text in files.items():
            p = fleet / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        (git / ".githooks").mkdir(parents=True, exist_ok=True)
        if with_wrapper:
            (git / ".githooks" / "ste-lint-joined.py").write_text(WRAPPER)
        lint = git / "ste-lint.py"
        lint.write_text(WRAPPER)
        saved = {k: getattr(cc, k) for k in ("SKILLS_ROOT", "FLEET_ROOT", "STE_LINT_CANDIDATES", "STE_JOIN_WRAPPER")}
        cc.SKILLS_ROOT = cc.FLEET_ROOT = fleet
        cc.STE_LINT_CANDIDATES = [lint] if with_lint else [git / "absent.py"]
        cc.STE_JOIN_WRAPPER = git / ".githooks" / "ste-lint-joined.py"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                try:
                    cc.main([])
                    code = 0
                except SystemExit as e:
                    code = e.code
        finally:
            for k, v in saved.items():
                setattr(cc, k, v)
    return code, out.getvalue()


class Description(unittest.TestCase):
    def test_long_description_is_advisory_only(self):
        long = " ".join(["word"] * (cc.DESCRIPTION_WORD_LIMIT + 5))
        code, out = run_main({"fam/s/SKILL.md": DESC.format(n="s", d=long)})
        self.assertEqual(code, 0, out)
        self.assertIn("description is", out)

    def test_short_description_has_no_flag(self):
        code, out = run_main({"fam/s/SKILL.md": DESC.format(n="s", d="short")})
        self.assertEqual(code, 0, out)
        self.assertNotIn("description is", out)


class Discovery(unittest.TestCase):
    def test_references_are_linted_and_non_skill_dirs_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fam/s/references").mkdir(parents=True)
            (root / "fam/s/SKILL.md").write_text("x")
            (root / "fam/s/references/r.md").write_text("x")
            (root / "docs/d").mkdir(parents=True)
            (root / "docs/d/SKILL.md").write_text("x")
            saved = cc.SKILLS_ROOT
            cc.SKILLS_ROOT = root
            try:
                skills, lint = cc.find_skills()
            finally:
                cc.SKILLS_ROOT = saved
        self.assertEqual([p.name for p in skills], ["SKILL.md"])
        self.assertEqual(sorted(p.name for p in lint), ["SKILL.md", "r.md"])


class Main(unittest.TestCase):
    CLEAN = {"fam/s/SKILL.md": DESC.format(n="s", d="fine")}
    BAD = {"fam/s/SKILL.md": DESC.format(n="s", d="fine") + "BADWORD\n"}

    def test_clean_is_green(self):
        code, out = run_main(self.CLEAN)
        self.assertEqual(code, 0, out)
        self.assertIn("All skills clean", out)

    def test_hard_violation_goes_red(self):
        code, out = run_main(self.BAD)
        self.assertEqual(code, 1, out)
        self.assertIn("fam/s/SKILL.md: asd-ste100 hard violation(s)", out)

    def test_violation_in_references_goes_red(self):
        code, out = run_main({**self.CLEAN, "fam/s/references/r.md": "BADWORD\n"})
        self.assertEqual(code, 1, out)
        self.assertIn("references/r.md", out)

    def test_missing_wrapper_lints_the_file_directly(self):
        self.assertEqual(run_main(self.CLEAN, with_wrapper=False)[0], 0)
        code, out = run_main(self.BAD, with_wrapper=False)
        self.assertEqual(code, 1, out)
        self.assertIn("asd-ste100 hard violation", out)

    def test_missing_linter_skips_lint_pass(self):
        code, out = run_main(self.BAD, with_lint=False)
        self.assertEqual(code, 0, out)
        self.assertIn("asd-ste100 not found", out)


if __name__ == "__main__":
    unittest.main()
