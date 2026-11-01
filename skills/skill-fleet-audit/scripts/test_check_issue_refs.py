"""Tests for check_issue_refs.py. Run: python3 -m unittest test_check_issue_refs (from this folder)."""
import os
import tempfile
import unittest
from unittest import mock

import check_issue_refs as C


class Citations(unittest.TestCase):
    def test_a_citation_needs_two_to_four_digits_and_no_word_before_the_hash(self):
        n = "#" + "443"
        text = f"See issue {n} and (#" + "12).\nColor #123456, a#99, word#77, path/#88, x#abc.\n##55 skip"
        self.assertEqual([c for _, c in C.citations(text)], [443, 12])

    def test_the_line_number_is_reported(self):
        self.assertEqual(C.citations("one\nfixes #" + "1234.")[0], (2, 1234))


class FilesUnder(unittest.TestCase):
    def test_a_hidden_folder_is_skipped(self):
        # Guards a peer's .pytest_cache appearing mid-scan and failing the walk.
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".pytest_cache"))
            for rel in ("a.md", os.path.join(".pytest_cache", "README.md")):
                open(os.path.join(tmp, rel), "w").close()
            self.assertEqual([os.path.basename(f) for f in C.files_under([tmp])], ["a.md"])


class RepoNamed(unittest.TestCase):
    def test_no_repo_variable_skips_the_check_and_passes(self):
        saved = os.environ.pop(C.REPO_ENV, None)
        try:
            with mock.patch.object(C.subprocess, "run", side_effect=AssertionError("gh must not run")):
                self.assertEqual(C.main(), 0)
        finally:
            if saved is not None:
                os.environ[C.REPO_ENV] = saved


if __name__ == "__main__":
    unittest.main()
