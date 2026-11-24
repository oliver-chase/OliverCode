"""`missing` names a managed hook whose matcher is out of date (#1039)."""

import json
import sys
import unittest

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import claude_settings  # noqa: E402


class TestMissing(unittest.TestCase):
    def test_missing_names_a_hook_whose_matcher_is_out_of_date(self):
        root = temp_dir(self, "olivercode-matcher-", resolve=True)
        path = root / "settings.json"
        path.write_text(json.dumps(claude_settings.merge({})))
        self.assertEqual(claude_settings.missing(path), [])
        old = json.loads(path.read_text())
        for g in old["hooks"]["PreToolUse"]:
            g["matcher"] = g["matcher"].replace("|Agent|Task", "")
        path.write_text(json.dumps(old))
        self.assertEqual(claude_settings.missing(path), ["pretool_guard.py"])
        path.write_text(json.dumps(claude_settings.merge(old)))
        self.assertEqual(claude_settings.missing(path), [])


if __name__ == "__main__":
    unittest.main()
