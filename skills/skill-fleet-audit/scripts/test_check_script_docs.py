"""Fixture tests for check_script_docs.py: an undocumented subcommand fails, a documented command that does not exist
fails, and a matching set passes.

Run from this scripts/ folder: python3 -m unittest test_check_script_docs
"""
import tempfile
import unittest
from pathlib import Path

import check_script_docs as csd

SCRIPT = 'sub.add_parser("add")\nsub.add_parser("verify")\n'


class ScriptDocs(unittest.TestCase):
    def skill(self, doc):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        skill = Path(self.tmp.name) / "fixture"
        (skill / "scripts").mkdir(parents=True)
        (skill / "scripts" / "tool.py").write_text(SCRIPT)
        (skill / "SKILL.md").write_text(doc)
        return skill

    def test_matching_docs_pass(self):
        self.assertEqual([], csd.check(self.skill("Run `tool.py add` then `tool.py --file x.xlsx verify`.")))

    def test_an_undocumented_subcommand_is_flagged(self):
        problems = csd.check(self.skill("Run `tool.py add`."))
        self.assertEqual(1, len(problems))
        self.assertIn("`verify`", problems[0])

    def test_a_documented_command_that_does_not_exist_is_flagged(self):
        problems = csd.check(self.skill("Run `tool.py add`, `tool.py verify` and `tool.py frobnicate`."))
        self.assertEqual(1, len(problems))
        self.assertIn("frobnicate", problems[0])

    def test_a_help_flag_followed_by_prose_is_not_a_command(self):
        self.assertEqual([], csd.check(self.skill("Run `tool.py --help` for every command. `tool.py add` and `tool.py verify`.")))


if __name__ == "__main__":
    unittest.main()
