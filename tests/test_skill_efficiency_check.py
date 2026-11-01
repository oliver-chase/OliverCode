"""Tests for scripts/lib/skill_efficiency_check.py. GATE-SKILL-EFFICIENCY-1 in docs/DECISIONS.md.

Every check has a block case and a pass case on a throwaway skills/ tree. The ablation
tests turn one check's threshold or guard off and show its block case stops blocking, so
each block case is proven to depend on the check it names.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
# The module imports `lib.duplication_check`, so scripts/ must be importable first.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "skill_efficiency_check", REPO_ROOT / "scripts" / "lib" / "skill_efficiency_check.py"
)
sec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sec)

FRONTMATTER = "---\nname: {name}\ndescription: A fixture skill.\n---\n\n"


def filler(n: int, seed: str) -> str:
    """n distinct words, so a long file never reads as a duplicate of another."""
    return " ".join(f"{seed}{i}" for i in range(n))


# A 40-word rule and a reworded restatement of it (same rule, a few words swapped).
RULE = (
    "Before any write to the shared workbook the agent copies the file to a scratch path, "
    "runs the full update against that copy, compares the row counts before and after, "
    "and only then repeats the same update against the real shared workbook on disk."
)
RULE_REWORDED = (
    "Before every write to the shared workbook the agent copies the file to a scratch folder, "
    "runs the whole update against that copy, compares the row totals before and after, "
    "and only then repeats the same update against the real shared workbook on disk."
)
OTHER = (
    "The weekly report lists each open item with its owner and its due date, sorts the "
    "list by the date the item last changed, and links each row to the issue on the board "
    "so a reader can open the full history in one click from the report."
)


class Fixture:
    """A temporary repo root holding skills/<name>/SKILL.md and optional references."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="olivercode-skilleff-")
        self.root = Path(self._tmp.name)

    def skill(self, name: str, body: str, refs: dict[str, str] | None = None) -> Path:
        d = self.root / "skills" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(FRONTMATTER.format(name=name) + body, encoding="utf-8")
        for fname, text in (refs or {}).items():
            (d / "references").mkdir(exist_ok=True)
            (d / "references" / fname).write_text(text, encoding="utf-8")
        return d

    def findings(self) -> list[str]:
        return sec.check_all(self.root)

    def close(self):
        self._tmp.cleanup()


class SkillEfficiencyTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)

    def rules(self) -> list[str]:
        return [f.split(": ", 1)[1].split(" ", 1)[0] for f in self.fx.findings()]


class TestShippedTree(unittest.TestCase):
    def test_repo_skills_pass(self):
        # The gate validate.sh runs on this repo must stay green on its own skills.
        self.assertEqual(sec.check_all(REPO_ROOT), [])

    def test_empty_tree_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = sec.check_all(Path(tmp))
        self.assertEqual(len(found), 1)
        self.assertIn("nothing was checked", found[0])


class TestMonolith(SkillEfficiencyTest):
    def test_blocks_a_long_skill_with_no_references(self):
        self.fx.skill("big", filler(sec.MONOLITH_WORD_CAP + 50, "w"))
        self.assertEqual(self.rules(), ["monolith-without-references"])

    def test_passes_a_long_skill_with_a_references_split(self):
        self.fx.skill("big", filler(sec.MONOLITH_WORD_CAP + 50, "w"), {"branch.md": "One branch."})
        self.assertEqual(self.fx.findings(), [])

    def test_passes_a_skill_under_the_cap(self):
        self.fx.skill("small", filler(sec.MONOLITH_WORD_CAP - 50, "w"))
        self.assertEqual(self.fx.findings(), [])

    def test_ablation_raising_the_cap_lets_the_monolith_through(self):
        self.fx.skill("big", filler(sec.MONOLITH_WORD_CAP + 50, "w"))
        with mock.patch.object(sec, "MONOLITH_WORD_CAP", 10**6):
            self.assertEqual(self.fx.findings(), [])


class TestDuplicateParagraph(SkillEfficiencyTest):
    def test_blocks_a_reworded_paragraph_across_two_skills(self):
        self.fx.skill("one", RULE + "\n")
        self.fx.skill("two", RULE_REWORDED + "\n")
        found = self.fx.findings()
        self.assertEqual(len(found), 1)
        self.assertIn("duplicate-paragraph (cross-skill)", found[0])

    def test_blocks_a_paragraph_restated_in_a_skills_own_reference(self):
        self.fx.skill("one", RULE + "\n", {"detail.md": RULE + "\n"})
        found = self.fx.findings()
        self.assertEqual(len(found), 1)
        self.assertIn("duplicate-paragraph (within-skill)", found[0])

    def test_passes_two_different_paragraphs(self):
        self.fx.skill("one", RULE + "\n")
        self.fx.skill("two", OTHER + "\n")
        self.assertEqual(self.fx.findings(), [])

    def test_passes_the_declared_opening_message_convention(self):
        # Every skill carries this line (duplication_check.DECLARED_MARKERS). The rest of
        # each paragraph is too short to compare, so it is not a duplicate.
        line = ("Send this first, in one turn, exactly as written, with no other opening line "
                "and no closing recap. A request that names its {} skips the message.\n")
        self.fx.skill("one", line.format("config path"))
        self.fx.skill("two", line.format("own dimension or target"))
        self.assertEqual(self.fx.findings(), [])

    def test_ablation_without_declared_markers_the_convention_line_blocks(self):
        line = ("Send this first, in one turn, exactly as written, with no other opening line "
                "and no closing recap. A request that names its {} skips the message, and the "
                "agent then starts the first step of the skill at once.\n")
        self.fx.skill("one", line.format("config path"))
        self.fx.skill("two", line.format("own dimension or target"))
        self.assertEqual(self.fx.findings(), [])
        with mock.patch.object(sec, "DECLARED_MARKERS", {}):
            self.assertIn("duplicate-paragraph", " ".join(self.fx.findings()))

    def test_ablation_an_unreachable_threshold_lets_the_duplicate_through(self):
        self.fx.skill("one", RULE + "\n")
        self.fx.skill("two", RULE_REWORDED + "\n")
        with mock.patch.object(sec, "SIMILARITY_THRESHOLD", 1.01):
            self.assertEqual(self.fx.findings(), [])


# Per MCP rule: (rule, text that trips it, the same text with the fix that clears it).
MCP_CASES = [
    ("no-concise-mode",
     "Call `crm_search` with the company name. Follow the cursor to the last page.",
     "Call `crm_search` with the company name in concise mode. Follow the cursor to the last page."),
    ("no-pagination",
     "Call `crm_search` with the company name in concise mode.",
     "Call `crm_search` with the company name in concise mode. Follow the cursor to the last page."),
    ("per-field-search-loop",
     "Run one search per field until the record is full.",
     "Do not run one search per field. Search once per record."),
    ("fuzzy-search-only",
     "Find the deck with sharepoint_search and open the first hit.",
     "Find the deck with sharepoint_search, or read it by direct path when the path is known."),
    ("no-dry-run-first",
     "Save the tracker with wb.save when the rows are filled.",
     "Do a dry run on a copy first, then save the tracker with wb.save when the rows are filled."),
    ("no-pick-one-rule",
     "Two methods exist to load the sheet: the export or the API.",
     "Two methods exist to load the sheet: the export or the API. Pick one and finish it first."),
]


class TestMcpPatterns(SkillEfficiencyTest):
    def test_every_named_rule_has_a_case(self):
        self.assertEqual(sorted(r for r, _, _ in MCP_CASES), sorted(sec.MCP_RULES))

    def test_each_rule_blocks_its_pattern(self):
        for rule, bad, _good in MCP_CASES:
            with self.subTest(rule=rule):
                self.assertEqual([r for r, _ in sec.mcp_findings(bad)], [rule])

    def test_each_rule_passes_the_fixed_text(self):
        for rule, _bad, good in MCP_CASES:
            with self.subTest(rule=rule):
                self.assertEqual(sec.mcp_findings(good), [])

    def test_a_pattern_in_a_reference_file_blocks_the_skill(self):
        # The scan covers references/, the files an invocation loads after SKILL.md.
        self.fx.skill("crm", "Route to the reference.\n", {"lookup.md": MCP_CASES[2][1]})
        self.assertEqual(self.rules(), ["per-field-search-loop"])

    def test_ablation_a_disabled_pattern_stops_blocking(self):
        disabled = {
            "no-concise-mode": ("SEARCH_TOOL_RE", r"(?!x)x"),
            "per-field-search-loop": ("PER_FIELD_RE", r"(?!x)x"),
            "fuzzy-search-only": ("FUZZY_SEARCH_RE", r"(?!x)x"),
            "no-dry-run-first": ("DESTRUCTIVE_RE", r"(?!x)x"),
            "no-pick-one-rule": ("STRATEGY_FLIP_RE", r"(?!x)x"),
        }
        import re
        for rule, bad, _good in MCP_CASES:
            if rule not in disabled:
                continue  # no-pagination shares SEARCH_TOOL_RE with no-concise-mode
            name, never = disabled[rule]
            with self.subTest(rule=rule), mock.patch.object(sec, name, re.compile(never)):
                self.assertNotIn(rule, [r for r, _ in sec.mcp_findings(bad)])


if __name__ == "__main__":
    unittest.main()
