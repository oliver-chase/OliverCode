"""The duplicate-text gate (#80), run against each shipped pre-commit hook, and the shared check.

Offline: scratch repos from _support. The check script is copied in the way bootstrap ships it.
"""

import json
import subprocess
import sys

from _support import REPO_ROOT, git
from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401

CHECKER = REPO_ROOT / "scripts" / "lib" / "duplication_check.py"
PASSAGE = ("the release owner signs the checklist before any tag is pushed and records the "
           "date beside the signature so the audit trail stays complete")


class DuplicationSetup:
    def setUp(self):
        super().setUp()
        self.write("scripts/duplication_check.py", CHECKER.read_text(encoding="utf-8"))
        self.stage("skills/one/references/a.md", f"# A\n\n{PASSAGE}.\n")
        git(self.tmp, "add", "scripts/duplication_check.py")
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "seed")


class DuplicationGate(DuplicationSetup):
    """Every rule of the gate, run against OliverCode's own hook. The two templates are built from the same gate
    source (build-hooks --check fails on drift), so they get one wiring test."""

    def test_a_staged_file_repeating_a_paragraph_blocks_and_names_both(self):
        self.stage("skills/two/references/b.md", f"# B\n\n{PASSAGE}.\n")
        out = self.assertBlocked("another file already holds").stdout
        self.assertIn("skills/one/references/a.md", out)
        self.assertIn("skills/two/references/b.md", out)

    def test_a_distinct_staged_file_passes(self):
        self.stage("docs/c.md", "# C\n\nNothing here is repeated anywhere else in this small tree.\n")
        self.assertIn("passed (1 staged markdown", self.assertAllowed().stdout)

    def test_no_staged_markdown_passes(self):
        self.stage("a.txt", PASSAGE + "\n")
        self.assertIn("no staged markdown", self.assertAllowed().stdout)

    def test_an_old_duplicate_between_untouched_files_does_not_block(self):
        self.stage("docs/old.md", f"# Old\n\n{PASSAGE}.\n")
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "old duplicate")
        self.stage("docs/new.md", "# New\n\nA fresh and unrelated short note.\n")
        self.assertAllowed()

    def test_the_staged_copy_is_judged_not_the_working_copy(self):
        self.stage("docs/c.md", f"# C\n\n{PASSAGE}.\n")
        self.write("docs/c.md", "# C\n\nrewritten after staging\n")
        self.assertBlocked("another file already holds")

    def test_a_repo_without_the_script_skips(self):
        git(self.tmp, "rm", "-q", "-f", "scripts/duplication_check.py")
        self.stage("skills/two/references/b.md", f"# B\n\n{PASSAGE}.\n")
        self.assertIn("skipped", self.assertAllowed().stdout)


class TestDuplicationOliverCodeHook(DuplicationGate, GateHarness):
    HOOK_FILE = ".githooks/pre-commit"


class DuplicationWired(DuplicationSetup):
    def test_a_staged_file_repeating_a_paragraph_blocks(self):
        self.stage("skills/two/references/b.md", f"# B\n\n{PASSAGE}.\n")
        self.assertBlocked("another file already holds")


class TestDuplicationPrivateTemplateHook(DuplicationWired, GateHarness):
    HOOK_FILE = "core/templates/project/pre-commit-private"


class TestSharedCheck(GateHarness):
    def run_check(self, *args):
        return subprocess.run([sys.executable, str(CHECKER), "--root", str(self.tmp), *args],
                              capture_output=True, text=True)

    def test_two_skill_references_with_the_same_paragraph_fail_naming_both(self):
        self.stage("skills/x/references/one.md", f"{PASSAGE}\n")
        self.stage("skills/y/references/two.md", f"{PASSAGE}\n")
        done = self.run_check()
        self.assertEqual(1, done.returncode)
        self.assertIn("skills/x/references/one.md", done.stdout)
        self.assertIn("skills/y/references/two.md", done.stdout)

    def test_bootstrap_ships_the_check_to_scripts(self):
        manifest = json.loads((REPO_ROOT / "shared" / "project-bootstrap-manifest.json").read_text())
        entries = {e["target"]: e["source"] for e in manifest["templatedFiles"]}
        self.assertEqual("scripts/lib/duplication_check.py", entries["scripts/duplication_check.py"])
