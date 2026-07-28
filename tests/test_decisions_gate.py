"""Tests for the decision-record integrity gate.

CODE_INTENT_STANDARD §4 requires the ledger to be gated, and four of six fleet repos
had no gate at all. The adoption problem is what shapes this: a repo turning it on
with 186 undocumented ids cannot fix them in one commit, so ids present at adoption
are baselined and only NEW ones fail.

Each test is a mutation. A gate that cannot fail is the class this repo keeps
rediscovering (scripts/lib/falsifiability_check.py).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core" / "templates" / "project" / "scripts" / "check-decisions.mjs"


class DecisionsGateTests(unittest.TestCase):
    def setUp(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node not available")
        self.tmp = Path(tempfile.mkdtemp())
        for d in ("src", "tests", "docs", "scripts"):
            (self.tmp / d).mkdir()
        (self.tmp / ".decisions.json").write_text(
            json.dumps({"sourceDirs": ["src"], "testDirs": ["tests"], "extensions": [".js"]}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_gate(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["node", str(SCRIPT), *args], cwd=self.tmp, capture_output=True, text=True
        )

    def src(self, body: str) -> None:
        (self.tmp / "src" / "a.js").write_text(body, encoding="utf-8")

    def ledger(self, *ids: str) -> None:
        rows = "".join(f"| `{i}` | why |\n" for i in ids)
        (self.tmp / "docs" / "DECISIONS.md").write_text(rows, encoding="utf-8")

    def test_a_recorded_decision_passes(self):
        self.src("// CACHE-POLICY-1: keeps the TTL.\n")
        self.ledger("CACHE-POLICY-1")
        self.assertEqual(self.run_gate().returncode, 0)

    def test_an_undocumented_decision_fails(self):
        self.src("// CACHE-POLICY-1: nothing records this.\n")
        self.ledger()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("has no entry", result.stdout)

    def test_baselining_accepts_existing_debt(self):
        self.src("// CACHE-POLICY-1: adopted as debt.\n")
        self.ledger()
        self.run_gate("--write-baseline")
        self.assertEqual(self.run_gate().returncode, 0)

    def test_a_new_id_still_fails_after_baselining(self):
        # The ratchet. Baselining must accept what was there, never what arrives next.
        self.src("// CACHE-POLICY-1: adopted as debt.\n")
        self.ledger()
        self.run_gate("--write-baseline")
        self.src("// CACHE-POLICY-1: adopted.\n// ARRIVED-LATER-2: new.\n")
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("ARRIVED-LATER-2", result.stdout)

    def test_a_row_describing_deleted_code_fails(self):
        self.src("const a = 1;\n")
        self.ledger("GONE-ROW-9")
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("nowhere in the code", result.stdout)

    def test_a_test_inventing_an_id_fails(self):
        self.src("const a = 1;\n")
        self.ledger()
        (self.tmp / "tests" / "t.js").write_text("// GHOST-ID-4 invented\n", encoding="utf-8")
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("GHOST-ID-4", result.stdout)

    def test_an_id_inside_a_quoted_string_is_not_a_reference(self):
        self.src('const note = "see CACHE-POLICY-1 in the docs";\n')
        self.ledger()
        self.assertEqual(self.run_gate().returncode, 0)

    def test_malformed_config_exits_nonzero(self):
        (self.tmp / ".decisions.json").write_text("{ not json", encoding="utf-8")
        result = self.run_gate()
        self.assertEqual(result.returncode, 2)
        self.assertIn("not valid JSON", result.stderr)


if __name__ == "__main__":
    unittest.main()
