"""`olivercode board groom` flags an identifier that differs from its README heading, from fixtures only (#840), the Name check."""

import subprocess
import sys
import unittest

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import name_drift  # noqa: E402


def repo_with(readme: str):
    root = temp_dir(unittest.TestCase())
    (root / "README.md").write_text(readme, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
    return root


class TestNameDrift(unittest.TestCase):
    def test_a_command_that_differs_from_its_heading_is_flagged_with_the_fix(self):
        root = repo_with("# Tool\n\n## Gallery\n\nOne page, built hourly with `olivercode showcase`.\n")
        lines = name_drift.drift(root)
        self.assertEqual(len(lines), 1)
        self.assertIn('"Gallery"', lines[0])
        self.assertIn("`showcase`", lines[0])
        self.assertIn("use one name in both", lines[0])
        self.assertIn("1 name difference(s)", name_drift.summary(lines))

    def test_a_bracketed_name_next_to_a_command_is_compared_with_the_heading(self):
        root = repo_with("## Commands\n\n| Job | `olivercode showcase` (Gallery), `olivercode story` |\n\n## Gallery\n\nOne page.\n")
        self.assertEqual(len(name_drift.drift(root)), 1)

    def test_a_job_label_and_a_file_name_are_compared_too(self):
        self.assertEqual(len(name_drift.mismatches("## Gallery\n\nRuns as `com.oc.showcase`.\n")), 1)
        self.assertEqual(len(name_drift.mismatches("## Gallery\n\nBuilt by `" + "scripts/lib/showcase_page.py" + "`.\n")), 1)

    def test_names_that_match_are_not_flagged(self):
        root = repo_with("## Dispatch planning\n\nRun `olivercode dispatch`.\n\n## Adoption\n\nWrite with `olivercode manager adopt write`.\n"
                         "\n## Many\n\nUse `olivercode a` and `olivercode b`.\n")
        self.assertEqual(name_drift.drift(root), [])


if __name__ == "__main__":
    unittest.main()
