"""validate.sh runs the tests under skills/*/scripts, and a failing one fails the gate.

The test copies validate.sh into a scratch checkout, swaps its final `main` call for
`run_smoke_tests`, and runs that against a skill whose test passes or fails. Nothing touches
this checkout.
"""

import subprocess
import shutil
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, git_env

PASSING = "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
FAILING = PASSING.replace("assertTrue(True)", "fail('planted failure')")


class TestSmokeGateRunsSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="olivercode-smokegate-"))
        text = (REPO_ROOT / "scripts" / "validate.sh").read_text(encoding="utf-8")
        assert text.rstrip().endswith('main "$@"')
        cls.script = text.rstrip()[: -len('main "$@"')] + "run_smoke_tests\n"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def smoke(self, skill_test):
        repo = Path(tempfile.mkdtemp(dir=self.base))
        (repo / "scripts" / "lib").mkdir(parents=True)
        (repo / "scripts" / "validate.sh").write_text(self.script, encoding="utf-8")
        shutil.copy(REPO_ROOT / "scripts" / "lib" / "smoke_runner.py", repo / "scripts" / "lib" / "smoke_runner.py")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_stub.py").write_text(PASSING, encoding="utf-8")
        scripts = repo / "skills" / "demo" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "test_demo.py").write_text(skill_test, encoding="utf-8")
        return subprocess.run(["bash", str(repo / "scripts" / "validate.sh")], cwd=repo,
                              env=git_env(), capture_output=True, text=True)

    def test_a_passing_skill_test_runs_and_is_counted(self):
        done = self.smoke(PASSING)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Ran 2 tests across 2 modules", done.stdout)

    def test_a_failing_skill_test_fails_the_gate(self):
        done = self.smoke(FAILING)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("planted failure", done.stdout)
        self.assertIn("python smoke tests FAILED", done.stdout)
