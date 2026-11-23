"""`validate.sh --check-repo`: the bloat and code quality checks (scripts/lib/repo_checks.py), run on a scratch repo."""

import subprocess
import unittest

from _support import REPO_ROOT, git, git_env, scratch_repo, temp_dir

VALIDATE = REPO_ROOT / "scripts" / "validate.sh"


class ScratchCheck(unittest.TestCase):
    """Runs `validate.sh FLAG` on a scratch repo. It holds no tests, so it runs none under either flag."""
    FLAG = "--check-repo"

    def setUp(self):
        self.repo = scratch_repo(temp_dir(self, "olivercode-check-"))

    def add(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        git(self.repo, "add", rel)

    def run_check(self):
        return subprocess.run(["bash", str(VALIDATE), self.FLAG, str(self.repo)],
                              capture_output=True, text=True, env=git_env())


class CheckRepo(ScratchCheck):

    def test_a_clean_repo_passes(self):
        self.add("README.md", "# Fine\n")
        self.add("tool.py", "print('ok')\n")
        # Untracked folders such as a virtualenv or a build output are not the repo's files.
        for rel in (".venv/lib/bad.py", "dist/big.ts"):
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / ".venv/lib/bad.py").write_text("def (:\n", encoding="utf-8")
        (self.repo / "dist/big.ts").write_text("x\n" * 500, encoding="utf-8")
        self.assertEqual(0, self.run_check().returncode)

    def test_a_folder_that_is_not_a_repo_is_skipped(self):
        plain = temp_dir(self, "olivercode-plain-")
        done = subprocess.run(["bash", str(VALIDATE), self.FLAG, str(plain)], capture_output=True, text=True, env=git_env())
        self.assertEqual(0, done.returncode)
        self.assertIn("[SKIP]", done.stdout)

    def test_a_tracked_archive_directory_fails(self):
        self.add("archive/old.md", "# Old\n")
        result = self.run_check()
        self.assertEqual(1, result.returncode)
        self.assertIn("archive/old.md", result.stdout)

    def test_a_file_that_marks_itself_historical_fails(self):
        self.add("notes.md", "Status: SUPERSEDED\n\nOld text.\n")
        self.assertIn("notes.md", self.run_check().stdout)

    def test_a_python_syntax_error_fails(self):
        self.add("broken.py", "def (:\n")
        result = self.run_check()
        self.assertEqual(1, result.returncode)
        self.assertIn("syntax error in", result.stdout)

    def test_a_lib_module_no_test_mentions_fails(self):
        self.add("scripts/lib/orphan.py", "X = 1\n")
        self.add("tests/test_other.py", "import unittest\n")
        self.assertIn("scripts/lib/orphan.py", self.run_check().stdout)

    def test_a_typescript_file_over_400_lines_fails_unless_it_is_a_test_file(self):
        self.add("big.ts", "x\n" * 401)
        self.add("big.test.ts", "x\n" * 900)
        out = self.run_check().stdout
        self.assertIn("big.ts has 401 lines (limit 400)", out)
        self.assertNotIn("big.test.ts", out)

    def test_a_lib_module_a_test_mentions_passes(self):
        self.add("scripts/lib/covered.py", "X = 1\n")
        self.add("tests/test_covered.py", "import covered\n")
        self.assertEqual(0, self.run_check().returncode)


class UnknownOption(unittest.TestCase):
    def test_an_unknown_flag_exits_2_with_usage_and_runs_no_validation(self):
        done = subprocess.run(["bash", str(VALIDATE), "--nonsense"], capture_output=True, text=True, env=git_env())
        self.assertEqual(2, done.returncode)
        self.assertIn("Unknown option: --nonsense", done.stderr)
        self.assertNotIn("=== validate", done.stdout)

    def test_the_help_names_the_docs_and_size_gates(self):
        done = subprocess.run(["bash", str(VALIDATE), "--help"], capture_output=True, text=True, env=git_env())
        self.assertIn("docs and size limit checks", done.stdout)


class DocsRatio(ScratchCheck):
    def test_a_ratio_just_over_the_threshold_warns_before_rounding(self):
        self.add("README.md", "x\n" * 604)
        self.add("scripts/lib/big.py", "x = 1\n" * 396)
        self.assertIn("[WARN] docs are 0.60", self.run_check().stdout)
