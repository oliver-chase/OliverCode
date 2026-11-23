"""`olivercode audit-mode` (scripts/lib/cmd_audit_mode.py) shows and stores the audit mode in the local config."""

import contextlib
import io
import json
import os
import unittest
from unittest import mock

from _support import load_script, temp_dir

load_script("scripts/olivercode", "olivercode_launcher_audit_mode")  # puts scripts/ on the path
from lib import cmd_audit_mode  # noqa: E402


class AuditModeCommand(unittest.TestCase):
    def setUp(self):
        self.cfg = temp_dir(self) / "olivercode.local.json"
        self.cfg.write_text("{}")
        self.enterContext(mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(self.cfg)}))

    def run_cmd(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cmd_audit_mode.command_audit_mode(list(argv))
        return code, out.getvalue()

    def test_unset_by_default(self):
        self.assertEqual(self.run_cmd(), (0, "mode: unset\n"))

    def test_sets_and_shows_the_mode_in_the_local_file(self):
        self.assertEqual(self.run_cmd("gated")[0], 0)
        self.assertEqual(json.loads(self.cfg.read_text())["auditMode"], "gated")
        self.assertEqual(self.run_cmd(), (0, "mode: gated\n"))

    def test_rejects_an_unknown_mode(self):
        code, out = self.run_cmd("sometimes")
        self.assertEqual(code, 1)
        self.assertIn("Usage", out)
        self.assertEqual(json.loads(self.cfg.read_text()), {})


if __name__ == "__main__":
    unittest.main()
