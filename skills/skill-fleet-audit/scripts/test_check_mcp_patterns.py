"""Fixture tests for check_mcp_patterns.py: each rule fires on text that has the anti-pattern and
stays quiet on the fixed wording (negated per-field, a pick-one rule, a dry-run step, and so on),
and main() exits 1 on a bad skill and 0 on a clean one. The fleet root is pointed at a temp folder.

Run from this scripts/ folder: python3 -m unittest test_check_mcp_patterns
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import check_mcp_patterns as mp


def rules(text):
    return {r for r, _ in mp.check_text(text)}


class Rules(unittest.TestCase):

    def test_per_field_search_loop(self):
        self.assertIn("per-field-search-loop", rules("Run one search per field."))

    def test_negated_per_field_is_clean(self):
        self.assertNotIn("per-field-search-loop", rules("Do not run one search per field."))

    def test_connector_setup_instruction_flagged(self):
        for bad in ("Connect via /mcp.", "Edit ~/.claude/settings.json.", "Run npx -y @scope/server-github.",
                    "Open Settings > Connectors.", "Add a `mcpServers.github` entry."):
            self.assertIn("connector-setup-instruction", rules(bad), bad)

    def test_standard_connector_missing_line_is_clean(self):
        self.assertNotIn("connector-setup-instruction", rules(
            "Slack is unavailable. Ask your admin to enable the Slack connector. Paste the thread instead."))






    def test_parallel_subagents(self):
        self.assertIn("no-2-subagents-at-once", rules("Run the agents in parallel."))
        self.assertIn("no-2-subagents-at-once", rules("Spawn a subagent concurrently."))

    def test_parallel_structure_is_clean(self):
        self.assertEqual(rules("Use parallel structure in lists."), set())


class Gather(unittest.TestCase):
    def test_references_are_scanned_with_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "s"
            (d / "references").mkdir(parents=True)
            (d / "SKILL.md").write_text("Body.")
            (d / "references" / "r.md").write_text("Run one search per field.")
            self.assertIn("per-field-search-loop", rules(mp.gather_text(d)))


def run_main(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        out = io.StringIO()
        with mock.patch.object(mp, "SKILLS_ROOT", root):
            with contextlib.redirect_stdout(out):
                try:
                    mp.main([])
                    code = 0
                except SystemExit as e:
                    code = e.code
    return code, out.getvalue()


class Main(unittest.TestCase):
    def test_bad_skill_goes_red(self):
        code, out = run_main({"fam/bad/SKILL.md": "Run one search per field.\n"})
        self.assertEqual(code, 1, out)
        self.assertIn("bad: 1 likely finding(s)", out)

    def test_clean_skill_goes_green(self):
        code, out = run_main({"fam/ok/SKILL.md": "Batch by entity.\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("No mechanical MCP-efficiency findings", out)

    def test_only_the_bad_skill_is_named(self):
        code, out = run_main({"fam/bad/SKILL.md": "Run one search per field.\n",
                              "fam/ok/SKILL.md": "Batch by entity.\n"})
        self.assertEqual(code, 1, out)
        self.assertNotIn("ok:", out)

    def test_a_fleet_folder_passed_as_the_target_is_scanned_skill_by_skill(self):
        # audit-fleet passes a skills folder that holds no SKILL.md of its own
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "fam" / "bad"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("Run one search per field.\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                try:
                    mp.main([tmp])
                    code = 0
                except SystemExit as e:
                    code = e.code
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("bad: 1 likely finding(s)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
