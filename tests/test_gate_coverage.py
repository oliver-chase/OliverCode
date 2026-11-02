"""Tests for per-repo gate-coverage consistency.

Gate coverage is not uniform across OliverCode, an adopted repo and the private
variant, and tracked documents once stated OliverCode's own total as though it were
universal, promising forkers two gates the template does not ship.
GATE-COUNT-1 in docs/DECISIONS.md records why the checker passed through all of it.

Each test is a mutation: it breaks one thing and asserts the checker fails. A
consistency check that cannot fail is the class this repo keeps rediscovering (see
scripts/lib/falsifiability_check.py), so these are written to prove it can.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, git, load_script, scratch_repo

cc = load_script("scripts/lib/consistency_check.py", "cc")


def _sandbox(dest: Path) -> Path:
    """Copy the WORKING TREE's tracked files into a throwaway git repo.

    Deliberately not `git clone`: the checker reads git ls-files, and a clone would
    test HEAD rather than the tree under test -- silently green on uncommitted work.
    """
    dest.mkdir(parents=True, exist_ok=True)
    listing = git(REPO_ROOT, "ls-files", "-z").stdout.split("\0")
    for rel in filter(None, listing):
        src = REPO_ROOT / rel
        if not src.is_file():
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(src.read_bytes())
    scratch_repo(dest)
    git(dest, "add", "-A")
    return dest


class TestShippedTree(unittest.TestCase):
    def test_oliveronly_gates_are_absent_from_the_template(self):
        """The gate a fleet repo does not get, asserted against the files."""
        template = (REPO_ROOT / "core/templates/project/pre-commit").read_text()
        self.assertNotIn(
            "Contract integrity", template,
            "'Contract integrity' now ships in the template; it was OliverCode-only, so the "
            "coverage table and the README's summary both need updating",
        )


class TestMutations(unittest.TestCase):
    """Break one thing; the checker must notice. One sandbox serves the class, and each
    mutation is put back before the next test runs."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="olivercode-gates-")
        cls.sandbox = _sandbox(Path(cls._tmp) / "oc")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _fails_after(self, rel: str, old: str, new: str) -> list[str]:
        target = self.sandbox / rel
        text = target.read_text(encoding="utf-8")
        self.assertIn(old, text, f"mutation anchor missing from {rel}")
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        try:
            git(self.sandbox, "add", "-A")
            return cc.check_all(self.sandbox)
        finally:
            target.write_text(text, encoding="utf-8")
            git(self.sandbox, "add", "-A")

    def test_catches_template_disagreeing_with_itself(self):
        # The real bug: a run of banners counting to one total, then a later one
        # counting to another.
        self.assertTrue(self._fails_after(
            "core/templates/project/pre-commit", "Gate 1/9", "Gate 1/5"))

    def test_catches_a_doc_overstating_coverage_for_adopted_repos(self):
        """The original false claim, in the shape the old pattern could not match.

        Exercises all three mechanisms at once: the modifier-tolerant claim pattern
        ("N pre-commit gates"), the cue sitting on the PRECEDING line, and comparison
        against the template's count rather than OliverCode's. The planted number is
        the private variant's total, which matches neither, so the claim is wrong
        whichever hook it resolves to.
        """
        self.assertTrue(self._fails_after(
            "README.md", "## What happens automatically\n",
            "## What happens automatically\n\n**On every commit, in every adopted repo**\n"
            f"{cc._hook_totals(REPO_ROOT)[0]['template-private']} pre-commit gates run.\n"))

    def test_a_cue_in_an_earlier_paragraph_does_not_reattribute(self):
        """Context stops at a blank line.

        Widening it past the paragraph boundary made the checker MISS a planted wrong
        claim: an unrelated "template" two paragraphs up re-attributed an OliverCode
        claim to the private hook, where the wrong number happened to be right. The
        planted number is the private variant's total, so reattribution would hide it.
        """
        self.assertTrue(self._fails_after(
            "docs/SETUP.md", "### Commits are passing gates",
            "The private variant is unrelated to what follows.\n\n"
            f"All {cc._hook_totals(REPO_ROOT)[0]['template-private']} gates run in this repo.\n\n"
            "### Commits are passing gates"))

    def test_catches_the_word_form_of_a_wrong_claim(self):
        self.assertTrue(self._fails_after(
            "docs/SETUP.md", "### Commits are passing gates",
            "All six gates run here.\n\n### Commits are passing gates"))

    def test_catches_a_stale_coverage_table(self):
        self.assertTrue(self._fails_after(
            "docs/GATES.md", "| **9** | **9** | **4** |", "| **9** | **11** | **4** |"))

    def test_catches_the_coverage_table_going_missing(self):
        """Other docs defer to that table, so losing it must not be silent."""
        self.assertTrue(self._fails_after(
            "docs/GATES.md", "| **Total** |", "| Total |"))

    def test_unmutated_sandbox_passes(self):
        """Guards the harness: if the sandbox failed on its own, every test above
        would 'pass' without testing anything."""
        self.assertEqual(cc.check_all(self.sandbox), [])


if __name__ == "__main__":
    unittest.main()
