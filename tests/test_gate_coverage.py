"""Tests for per-repo gate-coverage consistency.

Gate coverage is not uniform across OliverCode, an adopted repo and the private
variant, and tracked documents once stated OliverCode's own total as though it were
universal, promising forkers two gates the template does not ship.
GATE-COUNT-1 in docs/DECISIONS.md records why the checker passed through all of it.

Each test is a mutation: it breaks one thing and asserts the checker fails. A
consistency check that cannot fail is the class this repo keeps rediscovering (see
scripts/lib/falsifiability_check.py), so these are written to prove it can.
"""

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, git, load_script, scratch_repo

cc = load_script("scripts/lib/consistency_check.py", "cc")


def _sandbox(dest: Path) -> Path:
    """Copy the WORKING TREE's tracked files into a throwaway git repo.

    A `git clone` would test HEAD, so the sandbox copies files directly. The checker reads
    git ls-files, and a clone would stay green on uncommitted work.
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
        template = "core/templates/project/pre-commit"
        total = int(re.search(r"Gate 1/(\d+)", (self.sandbox / template).read_text()).group(1))
        self.assertTrue(self._fails_after(template, f"Gate 1/{total}", f"Gate 1/{total + 1}"))

    def test_catches_a_doc_overstating_coverage_for_adopted_repos(self):
        """A claim names its hook on its own line and is compared with that hook's count."""
        self.assertTrue(self._fails_after(
            "README.md", "## What runs automatically\n",
            "## What runs automatically\n\nIn every adopted repo, "
            f"{cc._hook_totals(REPO_ROOT)[0]['template-private']} pre-commit gates run.\n"))

    def test_catches_the_word_form_of_a_wrong_claim(self):
        self.assertTrue(self._fails_after(
            "docs/SETUP.md", "### Commits are passing gates",
            "All six gates run here.\n\n### Commits are passing gates"))

    def test_catches_a_stale_coverage_table(self):
        row = re.search(r"\| \*\*(\d+)\*\* \| \*\*(\d+)\*\* \| \*\*(\d+)\*\* \|",
                        (self.sandbox / "docs/GATES.md").read_text())
        a, b, c = row.groups()
        self.assertTrue(self._fails_after("docs/GATES.md", row.group(0), f"| **{a}** | **{int(b) + 2}** | **{c}** |"))

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
