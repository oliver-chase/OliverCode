"""A `$OC/...` path names a file in this repo, so a broken one must fail the reference check."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib.reference_check import check_references  # noqa: E402

# Built at runtime so this file holds no backtick-quoted path for the checker to read.
BT = chr(96)


class TestOcPaths(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="reference-check-"))
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "REAL.md").write_text("# Real\n")

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


if __name__ == "__main__":
    unittest.main()
