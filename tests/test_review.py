"""The recurring review reads its settings from the fleet repo (#821). No test reaches GitHub or a real fleet."""

import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _support import temp_dir, quiet  # noqa: E402
from lib import cmd_review  # noqa: E402


class Review(unittest.TestCase):
    def fleet(self, config):
        root = temp_dir(self) / "fleet"
        root.mkdir()
        (root / "repo-profiles.json").write_text("{}")
        (root / "review-config.json").write_text(json.dumps(config))
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_FLEET_REGISTRY": str(root / "repo-profiles.json")})
        patch.start()
        self.addCleanup(patch.stop)
        return root

    def run_review(self):
        calls = []

        def runner(args, **kw):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout="0\n", stderr="")
        rc, out = quiet(cmd_review.command_review, [], runner)
        return rc, out, [a[-1] if "olivercode" in a[1] else " ".join(a) for a in calls]

    def test_settings_come_from_the_fleet_repo(self):
        self.fleet({"schedule": {"cadence": "daily"}, "conform": True, "boardSweep": False, "updateCheck": True, "alwaysUpToDate": False})
        self.assertEqual(cmd_review.review_config()["schedule"]["cadence"], "daily")
        rc, out, steps = self.run_review()
        self.assertEqual(rc, 0, out)
        self.assertIn("conform", steps)
        self.assertNotIn("sync", steps)
        self.assertNotIn("update", steps)
        self.assertTrue(any("fetch" in s for s in steps), steps)

    def test_always_up_to_date_runs_update(self):
        self.fleet({"conform": False, "boardSweep": False, "updateCheck": False, "alwaysUpToDate": True})
        self.assertEqual(self.run_review()[2], ["update"])

    def test_no_fleet_config_says_how_to_make_one(self):
        root = temp_dir(self)
        with mock.patch.dict(os.environ, {"OLIVERCODE_FLEET_REGISTRY": str(root / "repo-profiles.json")}):
            rc, out = quiet(cmd_review.command_review, [], lambda *a, **k: None)
        self.assertEqual(rc, 1)
        self.assertIn("olivercode init-fleet", out)

    def test_the_template_carries_every_setting(self):
        text = json.loads((cmd_review.TEMPLATE / "review-config.json").read_text())
        self.assertTrue({"schedule", "conform", "boardSweep", "updateCheck", "alwaysUpToDate"} <= set(text))


if __name__ == "__main__":
    unittest.main()
