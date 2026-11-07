"""Tests for scripts/lib/reference_check.py: a backtick repo path that names nothing must fail.

A `$OC/...` path names a file in this repo, so a broken one must fail too.
"""
import unittest
from pathlib import Path

from _support import load_script, scratch_repo, temp_dir

reference_check = load_script("scripts/lib/reference_check.py", "reference_check")
check_references = reference_check.check_references

# Built at runtime so this file holds no backtick-quoted path for the checker to read.
BT = chr(96)


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.repo = temp_dir(self, "reference-check-")
        scratch_repo(self.repo)
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "REAL.md").write_text("# Real\n")


class TestOcPaths(RepoCase):
    def check(self, text):
        (self.repo / "CLAUDE.md").write_text(text)
        return check_references(self.repo)[1]

    def test_a_broken_oc_path_fails(self):
        self.assertEqual(1, len(self.check(f"Read {BT}$OC/docs/MISSING.md{BT} first.\n")))

    def test_a_real_oc_path_passes(self):
        self.assertEqual([], self.check(f"Read {BT}$OC/docs/REAL.md{BT} first.\n"))

    def test_a_skills_test_fixture_path_is_not_a_claim_about_this_repo(self):
        test = self.repo / "skills" / "audit" / "scripts" / "test_audit.py"
        test.parent.mkdir(parents=True)
        test.write_text(f"FIXTURE = {BT}docs/MISSING.md{BT}\n")
        self.assertEqual([], self.check("Nothing here.\n"))

    def test_the_same_path_in_a_skills_own_script_still_fails(self):
        script = self.repo / "skills" / "audit" / "scripts" / "audit.py"
        script.parent.mkdir(parents=True)
        script.write_text(f"READ = {BT}docs/MISSING.md{BT}\n")
        self.assertEqual(1, len(self.check("Nothing here.\n")))

    def test_another_variable_stays_a_placeholder(self):
        self.assertEqual([], self.check(f"Set {BT}$HOME/docs/anything.md{BT} yourself.\n"))


class TestWhatCounts(unittest.TestCase):
    """Which tokens are references, which files are read, and which paths are exempt."""

    def setUp(self):
        self.repo = temp_dir(self, "reference-check-")
        scratch_repo(self.repo)
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "REAL.md").write_text("# Real\n")

    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_counts_every_checked_reference_and_names_the_broken_one(self):
        self.write("docs/GUIDE.md", f"See {BT}docs/REAL.md{BT} and {BT}scripts/gone.sh{BT}.\n")
        checked, failures = check_references(self.repo)
        self.assertEqual(2, checked)
        self.assertEqual([f"  [BROKEN REF] docs/GUIDE.md -> {BT}scripts/gone.sh{BT} (not found on disk)"], failures)

    def test_tokens_outside_the_tracked_roots_are_not_references(self):
        self.write("docs/GUIDE.md", f"Run {BT}npm test{BT} on {BT}lib/missing.ts{BT} and {BT}README.md{BT}.\n")
        self.assertEqual((0, []), check_references(self.repo))

    def test_trailing_punctuation_and_arguments_are_dropped(self):
        self.write("docs/GUIDE.md", f"{BT}docs/REAL.md,{BT} {BT}docs/REAL.md --flag{BT} {BT}docs/REAL.md(1){BT}\n")
        self.assertEqual((3, []), check_references(self.repo))

    def test_a_directory_reference_must_name_a_directory(self):
        self.write("docs/GUIDE.md", f"Look in {BT}docs/{BT}, not {BT}docs/REAL.md/{BT}.\n")
        checked, failures = check_references(self.repo)
        self.assertEqual(2, checked)
        self.assertEqual(1, len(failures))
        self.assertIn("docs/REAL.md/", failures[0])

    def test_exempt_paths_are_neither_counted_nor_failed(self):
        self.write(
            "docs/GUIDE.md",
            f"{BT}docs/<name>.md{BT} {BT}docs/repo-structure-contract.md{BT} {BT}.claude-optimization/memory/MEMORY.md{BT}\n",
        )
        self.assertEqual((0, []), check_references(self.repo))

    def test_templates_and_plans_are_not_read(self):
        broken = f"{BT}docs/MISSING.md{BT}\n"
        self.write("core/templates/CLAUDE.md", broken)
        self.write("docs/plans/next.md", broken)
        self.assertEqual((0, []), check_references(self.repo))

    def test_only_source_and_doc_files_are_read(self):
        self.write("docs/notes.txt", f"{BT}docs/MISSING.md{BT}\n")
        self.assertEqual((0, []), check_references(self.repo))

    def test_a_gitignored_file_is_not_read_but_an_untracked_one_is(self):
        self.write(".gitignore", "local.md\n")
        self.write("local.md", f"{BT}docs/MISSING.md{BT}\n")
        self.assertEqual((0, []), check_references(self.repo))
        self.write("new.md", f"{BT}docs/MISSING.md{BT}\n")
        self.assertEqual(1, len(check_references(self.repo)[1]))


if __name__ == "__main__":
    unittest.main()


class TestMarkdownLinks(RepoCase):
    def links(self, text):
        (self.repo / "CLAUDE.md").write_text(text)
        return reference_check.check_markdown_links(self.repo)

    def test_a_link_to_a_missing_file_fails_and_a_link_to_a_real_one_passes(self):
        checked, failures = self.links("[ok](docs/REAL.md) [gone](docs/GONE.md) [web](https://example.com/a.md) [top](#x)\n")
        self.assertEqual(checked, 2)
        self.assertEqual(len(failures), 1)
        self.assertIn("docs/GONE.md", failures[0])

    def test_links_into_the_local_runtime_layer_pass_and_archived_docs_are_skipped(self):
        (self.repo / "docs" / "archive").mkdir()
        (self.repo / "docs" / "archive" / "OLD.md").write_text("[dead](NOPE.md)\n")
        checked, failures = self.links("[local](runtime/control-plane/README.md)\n")
        self.assertEqual((checked, failures), (1, []))

    def test_report_exits_zero_when_clean_and_one_when_a_link_is_broken(self):
        self.links("[ok](docs/REAL.md)\n")
        self.assertEqual(reference_check.report(self.repo, quiet=True), 0)
        self.links("[gone](docs/GONE.md)\n")
        self.assertEqual(reference_check.report(self.repo, quiet=True), 1)
