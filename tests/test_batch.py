"""A batch builds one sample and stops until it is approved (#628)."""

import os
import subprocess
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_batch  # noqa: E402


class TestBatch(unittest.TestCase):
    def test_second_item_waits_for_the_sample_approval(self):
        home = temp_dir(self)
        with mock.patch("lib.failure_log.home", return_value=home):
            self.assertFalse(cmd_batch.next_item("posts")[0])
            self.assertEqual(0, cmd_batch.command_batch(["start", "posts", "--count", "3"]))
            self.assertTrue(cmd_batch.next_item("posts")[0])
            allowed, why = cmd_batch.next_item("posts")
            self.assertFalse(allowed)
            self.assertIn("batch approve posts", why)
            self.assertEqual(1, cmd_batch.command_batch(["approve", "nope"]))
            self.assertEqual(0, cmd_batch.command_batch(["approve", "posts"]))
            self.assertTrue(cmd_batch.next_item("posts")[0])
            self.assertEqual(1, cmd_batch.command_batch(["start", "x", "--count", "0"]))

    def test_the_launcher_runs_batch_start_and_prints_no_rule_usage(self):
        home = temp_dir(self)
        env = {**os.environ, "OLIVERCODE_HOME": str(home)}
        out = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), "batch", "start", "posts", "--count", "2"],
                             capture_output=True, text=True, env=env)
        self.assertEqual(0, out.returncode, out.stdout + out.stderr)
        self.assertIn("Batch posts recorded", out.stdout)
        self.assertNotIn("rule add", out.stdout)

    def test_the_launcher_defines_one_batch_import_and_branch(self):
        text = (REPO_ROOT / "scripts" / "olivercode").read_text()
        self.assertEqual(1, text.count("import command_batch"))
        self.assertEqual(1, text.count('cmd == "batch"'))


if __name__ == "__main__":
    unittest.main()
