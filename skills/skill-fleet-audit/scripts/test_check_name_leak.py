"""Fixture tests for check_name_leak.py. A fake .env.local holds a fake name and email (none are
real); a tracked file repeating the full name or the email goes red, a first-name-only mention
passes, and a clean tree goes green. The filename-example heuristic flags an unknown
name next to a filename cue and skips the three established placeholder names. NON_NAME keys are
not read as names. The scan root is pointed at a temp folder, so no real .env.local is read.

Run from this scripts/ folder: python3 -m unittest test_check_name_leak
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import check_name_leak as nl

# Built at run time so this file holds no name-shaped string next to a filename cue.
UNKNOWN = "Rex" + " Plume"
# Built at runtime so the commit gate's PII scan sees no literal email or home path in this file.
EMAIL = "zelda.quux" + "@" + "example.test"
HOME_WORK = "/" + "Users/someone/work"
ENV = f"TEAM_STAFF=Zelda Quux:{EMAIL}:lead\nNOTE=x\n"


def run_gate(files):
    """Write {relative path: text} under a temp skills root (fam/...), run main()."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        saved = nl.SKILLS_ROOT
        nl.SKILLS_ROOT = root
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                try:
                    nl.main([])
                    code = 0
                except SystemExit as e:
                    code = e.code
        finally:
            nl.SKILLS_ROOT = saved
    return code, out.getvalue()


class KnownIdentity(unittest.TestCase):
    def test_full_name_in_tracked_file_goes_red(self):
        code, out = run_gate({"fam/.env.local": ENV, "fam/a.md": "Ask Zelda Quux about it.\n"})
        self.assertEqual(code, 1, out)
        self.assertIn("'Zelda Quux'", out)

    def test_email_in_tracked_file_goes_red(self):
        code, out = run_gate({"fam/.env.local": ENV, "fam/a.py": f"x = '{EMAIL}'\n"})
        self.assertEqual(code, 1, out)
        self.assertIn(EMAIL, out)

    def test_first_name_only_passes(self):
        code, out = run_gate({"fam/.env.local": ENV, "fam/a.md": "Email Zelda with the file.\n"})
        self.assertEqual(code, 0, out)
        self.assertNotIn("first-name", out)

    def test_clean_tree_is_green(self):
        code, out = run_gate({"fam/.env.local": ENV, "fam/a.md": "Nothing personal here.\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("Known-identity leak check: clean", out)

    def test_no_env_file_is_green(self):
        code, out = run_gate({"fam/a.md": "Ask Zelda Quux about it.\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("0 real .env.local", out)

    def test_env_file_itself_is_not_scanned(self):
        code, out = run_gate({"fam/.env.local": ENV})
        self.assertEqual(code, 0, out)

    def test_example_files_are_not_scanned(self):
        code, out = run_gate({"fam/.env.local": ENV, "fam/.env.local.example": "Zelda Quux\n"})
        self.assertEqual(code, 0, out)

    def test_a_sheet_style_key_is_not_a_name(self):
        env = "SHEET_NAME=Budget Plan\n"
        code, out = run_gate({"fam/.env.local": env, "fam/a.md": "Budget Plan ships.\n"})
        self.assertEqual(code, 0, out)

    def test_name_key_with_plain_name_is_read(self):
        env = "OWNER_NAME=Zelda Quux\n"
        code, out = run_gate({"fam/.env.local": env, "fam/a.md": "Zelda Quux\n"})
        self.assertEqual(code, 1, out)


class FilenameExamples(unittest.TestCase):
    def test_unknown_name_against_filename_is_flagged(self):
        code, out = run_gate({"fam/a.md": f"Save as 2510 - {UNKNOWN}_Resume.pdf\n"})
        self.assertEqual(code, 0, out)  # advisory only
        self.assertIn(f"possible real name '{UNKNOWN}'", out)

    def test_established_placeholders_are_skipped(self):
        code, out = run_gate({"fam/a.md": "Jane Doe_Resume.pdf, John Smith.docx, Sally May.pdf\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("no two-capitalized-word sequence", out)

    def test_name_without_filename_cue_is_clean(self):
        code, out = run_gate({"fam/a.md": "Rex Plume wrote this.\n"})
        self.assertIn("no two-capitalized-word sequence", out)

    def test_py_files_are_scanned(self):
        code, out = run_gate({"fam/a.py": f"# {UNKNOWN}_Resume.pdf\n"})
        self.assertIn(f"possible real name '{UNKNOWN}'", out)


class MachineLeaks(unittest.TestCase):
    def test_home_path_in_a_skill_file_goes_red(self):
        code, out = run_gate({"fam/skill/SKILL.md": "x\n", "fam/skill/a.sh": f"cd {HOME_WORK}\n"})
        self.assertEqual(code, 1, out)
        self.assertIn("home path", out)

    def test_machine_account_name_goes_red(self):
        code, out = run_gate({"fam/skill/SKILL.md": f"owner: {sorted(nl.account_names())[0]}\n"})
        self.assertEqual(code, 1, out)

    def test_a_test_file_may_hold_a_sample_path(self):
        code, out = run_gate({"fam/skill/SKILL.md": "x\n", "fam/skill/scripts/test_a.py": f"P = '{HOME_WORK}'\n"})
        self.assertEqual(code, 0, out)

    def test_a_file_outside_a_skill_folder_is_not_swept(self):
        code, out = run_gate({"fam/skill/SKILL.md": "x\n", "fam/notes.md": f"cd {HOME_WORK}\n"})
        self.assertEqual(code, 0, out)

    def test_clean_tree_is_green(self):
        code, out = run_gate({"fam/skill/SKILL.md": "Nothing here.\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("Machine-leak check: clean", out)


if __name__ == "__main__":
    unittest.main()
