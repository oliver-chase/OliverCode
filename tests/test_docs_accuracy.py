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
