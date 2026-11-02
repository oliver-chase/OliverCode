"""The test harness keeps every run off the owner's real ~/.claude and real local config."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _support

_support.load_script("scripts/olivercode")   # puts scripts/ on sys.path
from lib import local_config  # noqa: E402


class HarnessIsolation(unittest.TestCase):
    def test_home_is_a_temporary_directory_and_not_the_real_one(self):
        self.assertNotEqual(Path.home(), Path(_support.REAL_HOME or "/nonexistent"))
        self.assertEqual(Path.home(), Path(_support.TEST_HOME))

    def test_the_install_command_writes_only_under_the_test_home(self):
        launcher = _support.load_script("scripts/olivercode")
        with contextlib.redirect_stdout(io.StringIO()):
            launcher.command_install(_support.REPO_ROOT)
        self.assertTrue((Path(_support.TEST_HOME) / ".claude" / "CLAUDE.md").is_symlink())

    def test_reading_the_real_local_config_fails_the_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "olivercode.local.json"
            real.write_text("{}")
            env = {k: v for k, v in os.environ.items() if k != "OLIVERCODE_LOCAL_CONFIG"}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(local_config, "LOCAL_FILE", real), \
                    mock.patch.object(local_config, "REAL_LOCAL_FILE", real):
                with self.assertRaises(RuntimeError):
                    local_config.load_local()


class DiscoverySurvivesNestedSuites(unittest.TestCase):
    def test_the_backlog_suite_leaves_the_callers_loader_untouched(self):
        import test_backlog_skill
        loader = unittest.TestLoader()
        loader._top_level_dir = str(_support.REPO_ROOT / "tests")
        test_backlog_skill.load_tests(loader, None, "test_*.py")
        self.assertEqual(loader._top_level_dir, str(_support.REPO_ROOT / "tests"))


if __name__ == "__main__":
    unittest.main()
