"""Tests for per-repo gate-coverage consistency.

Gate coverage is not uniform: OliverCode runs 8 gates on itself, a repo that adopts
the framework runs 6, the vault's private variant runs 2. Five tracked documents
stated 8 as though it were universal, telling forkers their repos would get contract
integrity and token policy -- two gates the template does not ship.

The consistency checker was in place the whole time and passed, for two independent
reasons, both fixed here and pinned by the tests below:

  1. it compared every claim against OliverCode's own hook, skipping core/templates/
     outright with the comment "the template hook has its own, smaller gate count" --
     the discrepancy was known to the checker and deliberately unexamined
  2. its claim pattern required the number adjacent to the noun, so README's headline
     "8 pre-commit gates" was never even matched

Meanwhile the template disagreed with itself: banners read "Gate 1/5" through
"Gate 5/5" and then "Gate 6/6". Nothing checked a hook other than OliverCode's.

Each test is a mutation: it breaks one thing and asserts the checker fails. A
consistency check that cannot fail is the defect class this repo keeps rediscovering
(see scripts/lib/falsifiability_check.py), so these are written to prove it can.
"""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "cc", REPO_ROOT / "scripts" / "lib" / "consistency_check.py"
)
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


def _sandbox(dest: Path) -> Path:
    """Copy the WORKING TREE's tracked files into a throwaway git repo.

    Deliberately not `git clone`: the checker reads git ls-files, and a clone would
    test HEAD rather than the tree under test -- silently green on uncommitted work.
    """
    dest.mkdir(parents=True, exist_ok=True)
    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.split("\0")
    for rel in filter(None, listing):
        src = REPO_ROOT / rel
        if not src.is_file():
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(src.read_bytes())
    subprocess.run(["git", "init", "-q", "."], cwd=dest, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, capture_output=True, check=True)
    return dest


class TestShippedTree(unittest.TestCase):
    def test_repo_is_consistent(self):
        self.assertEqual(cc.check_all(REPO_ROOT), [])

    def test_hook_totals_are_the_documented_ones(self):
        totals, problems = cc._hook_totals(REPO_ROOT)
        self.assertEqual(problems, [])
        self.assertEqual(
            totals, {"olivercode": 8, "template": 6, "template-private": 2},
            "gate coverage changed -- update the table in docs/governance.md, which is "
            "its single home, and every doc that points there",
        )

    def test_oliveronly_gates_are_absent_from_the_template(self):
        """The two gates a fleet repo does not get, asserted against the files."""
        template = (REPO_ROOT / "core/templates/project/pre-commit").read_text()
        for gate in ("Contract integrity", "Token policy"):
            self.assertNotIn(
                gate, template,
                f"'{gate}' now ships in the template; it was OliverCode-only, so the "
                f"coverage table and the README's summary both need updating",
            )


class TestMutations(unittest.TestCase):
    """Break one thing; the checker must notice."""

    def _fails_after(self, rel: str, old: str, new: str) -> list[str]:
        with tempfile.TemporaryDirectory(prefix="olivercode-gates-") as tmp:
            work = _sandbox(Path(tmp) / "oc")
            target = work / rel
            text = target.read_text(encoding="utf-8")
            self.assertIn(old, text, f"mutation anchor missing from {rel}")
            target.write_text(text.replace(old, new, 1), encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=work, capture_output=True, check=True)
            return cc.check_all(work)

    def test_catches_template_disagreeing_with_itself(self):
        # The real bug: "Gate 1/5" ... "Gate 5/5" then "Gate 6/6".
        self.assertTrue(self._fails_after(
            "core/templates/project/pre-commit", "Gate 1/6", "Gate 1/5"))

    def test_catches_a_gate_removed_without_updating_the_total(self):
        self.assertTrue(self._fails_after(
            "core/templates/project/pre-commit",
            'echo "[pre-commit] Gate 3/6: PII scan..."',
            'echo "[pre-commit] PII scan..."'))

    def test_catches_a_doc_overstating_coverage_for_adopted_repos(self):
        # The exact false claim, in the exact shape the old pattern could not match.
        self.assertTrue(self._fails_after(
            "README.md", "| Doc/code consistency",
            "| 8 pre-commit gates in every adopted repo | x | y |\n| Doc/code consistency"))

    def test_catches_the_word_form_of_a_wrong_claim(self):
        self.assertTrue(self._fails_after(
            "docs/troubleshooting.md", "## Commits are passing gates",
            "All six gates run here.\n\n## Commits are passing gates"))

    def test_catches_a_stale_coverage_table(self):
        self.assertTrue(self._fails_after(
            "docs/governance.md", "| **8** | **6** | **2** |", "| **8** | **8** | **2** |"))

    def test_catches_the_coverage_table_going_missing(self):
        """Other docs defer to that table, so losing it must not be silent."""
        self.assertTrue(self._fails_after(
            "docs/governance.md", "| **Total** |", "| Total |"))

    def test_unmutated_sandbox_passes(self):
        """Guards the harness: if the sandbox failed on its own, every test above
        would 'pass' without testing anything."""
        with tempfile.TemporaryDirectory(prefix="olivercode-gates-") as tmp:
            self.assertEqual(cc.check_all(_sandbox(Path(tmp) / "oc")), [])


if __name__ == "__main__":
    unittest.main()
