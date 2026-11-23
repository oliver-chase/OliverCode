"""The scratch folders and config the maintain tests share."""

import os
import unittest
from unittest import mock

from _support import load_script, temp_dir

launcher = load_script("scripts/olivercode", "olivercode_launcher")
from lib import maintain, placement  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        self.root = temp_dir(self)
        self.claude = temp_dir(self)
        for target, value in (
            (os.environ, {"OLIVERCODE_HOME": str(self.home), "OLIVERCODE_FAILURE_LOG": str(self.home / "failures.log")}),
        ):
            p = mock.patch.dict(target, value); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(maintain, "claude_dir", return_value=self.claude); p.start(); self.addCleanup(p.stop)
        self.cfg = placement.Config(root=self.root, worktrees=self.root / "_worktrees", archive=self.root / "_archive", watch=[], allow=[])
