"""The docs state what the code does: gate numbers, listed commands and machine names (#854)."""

import re
import subprocess
import sys
import unittest

from _support import REPO_ROOT, load_script, temp_dir

bh = load_script("scripts/build-hooks.py", "build_hooks_docs")
docs_check = load_script("core/templates/project/scripts/docs_check.py", "docs_check_module")
ROW_NAME = {"Secrets": "secrets", "PII": "pii", "Owner identifiers": "owner-identifiers", "Version files": "version-files"}


def expected(variant: str) -> dict:
    """Each gate's printed number, or 'after N' for an unnumbered one, in a variant's built hook order."""
    numbered = [g for g in bh.VARIANTS[variant]["gates"] if g not in bh.UNNUMBERED]
    out = {g: str(i + 1) for i, g in enumerate(numbered)}
    out["version-files"] = f"after {len(numbered)}"
    return out


class TestDocsAccuracy(unittest.TestCase):
    def test_gate_numbers(self):
        rows = {}
        for line in (REPO_ROOT / "docs" / "GATES.md").read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 5 and cells[0] in ROW_NAME:
                rows[ROW_NAME[cells[0]]] = cells[2:]
        self.assertEqual(set(ROW_NAME.values()), set(rows))
        public, private = expected("core/templates/project/pre-commit"), expected("core/templates/project/pre-commit-private")
        for gate, (oc, adopted, priv) in rows.items():
            self.assertEqual(public[gate], oc, f"{gate} in OliverCode's hook")
            self.assertEqual(public[gate], adopted, f"{gate} in an adopted repo's hook")
            self.assertEqual(private.get(gate, "—"), priv, f"{gate} in the private hook")

    def test_a_listed_command_is_a_valid_command(self):
        listed = set(re.findall(r"`olivercode ([a-z][a-z-]*)", (REPO_ROOT / "README.md").read_text(encoding="utf-8")))
        help_text = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), "--help"], capture_output=True, text=True).stdout
        self.assertEqual([], sorted(w for w in listed if f"olivercode {w}" not in help_text))

    def test_every_command_in_help_is_in_the_readme_table(self):
        """#906: a command the launcher prints must have a row in the README table, so a reader can find it."""
        help_text = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), "--help"], capture_output=True, text=True).stdout
        commands = set(re.findall(r"olivercode ([a-z][a-z-]*)", help_text))
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual([], sorted(c for c in commands if f"`olivercode {c}" not in readme))

    def test_the_audit_ledger_lists_only_tracked_files(self):
        """#906: docs/AUDITED.txt names files that exist in the repo, so a deleted file leaves no stale audit line."""
        tracked = set(subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.splitlines())
        paths = [line.split()[1] for line in (REPO_ROOT / "docs" / "AUDITED.txt").read_text(encoding="utf-8").splitlines()
                 if len(line.split()) == 2 and len(line.split()[0]) == 40]
        self.assertEqual([], [p for p in paths if p not in tracked])

    def test_the_plain_terms_table_sits_after_how_work_runs_and_each_part_it_names_exists(self):
        """#974: the kitchen table in the README names one real file per part, so a reader can find each part it describes."""
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        start, end = text.index("## How work runs"), text.index("## How it works, in plain terms")
        self.assertLess(start, end)
        section = text[end:text.index("A delegated task gets a bounded execution context")]
        rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in section.splitlines()
                if line.startswith("| ") and not line.startswith("| In the kitchen")]
        parts = {
            "Owner-facing front door": ["scripts/lib/cli.py", "scripts/lib/cmd_groom.py"],
            "Durable work queue": ["scripts/lib/story_outbox.py"],
            "Autonomous orchestrator": ["scripts/lib/cmd_dispatch.py", "scripts/lib/agent_loop.py"],
            "Isolated Claude Code session": ["scripts/lib/agent_loop.py"],
            "Workflow and model selection": ["scripts/lib/model.py"],
            "Risk-proportional quality checks": ["scripts/validate.sh"],
            "Review": ["scripts/lib/agent_loop.py"],
            "Safe delivery": ["scripts/lib/cmd_land.py"],
            "Commit gates": ["docs/GATES.md"],
            "Safety and policy controls": ["scripts/hooks/pretool_guard.py"],
            "The candidates list": ["scripts/lib/candidates.py"],
            "Background maintenance": ["scripts/lib/schedules.py"],
            "Rules, voice and design files": ["docs/RULES.md", "docs/VOICE.md", "docs/DESIGN.md"],
            "Skills": ["skills/INDEX.md"],
            "Repository and fleet configuration": ["scripts/lib/local_config.py", "docs/backlog-config.json"],
            "Decisions": ["scripts/lib/decisions.py"],
        }
        self.assertEqual(16, len(rows))
        self.assertEqual(set(parts), {cells[1] for cells in rows})
        self.assertTrue(all(len(cells) == 3 for cells in rows))
        missing = [path for paths in parts.values() for path in paths if not (REPO_ROOT / path).is_file()]
        self.assertEqual([], missing)

    def test_a_doc_that_names_a_command_the_launcher_lacks_fails_the_docs_check(self):
        root = temp_dir(self)
        (root / "scripts" / "lib").mkdir(parents=True)
        (root / "scripts" / "lib" / "cli.py").write_text('COMMANDS = [\n    ("olivercode land WORKTREE STORY", "Land a story"),\n]\n', encoding="utf-8")
        (root / "README.md").write_text("Run `olivercode land WORKTREE STORY`, then `olivercode frobnicate-widget` to do it.\n", encoding="utf-8")
        misses = docs_check.check_named_commands(root)
        self.assertEqual(1, len(misses))
        self.assertIn("frobnicate-widget", misses[0])



if __name__ == "__main__":
    unittest.main()
