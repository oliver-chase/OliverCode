"""#1195: health, status and the guide say when City is not set up, and stay quiet once it is set up or skipped."""

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_guide, cmd_status  # noqa: E402

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


class CityVisible(unittest.TestCase):
    def config(self, settings):
        path = temp_dir(self) / "olivercode.local.json"
        path.write_text(json.dumps(settings))
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(path)})
        patch.start()
        self.addCleanup(patch.stop)
        return path

    def health(self, path):
        env = {**os.environ, "OLIVERCODE_LOCAL_CONFIG": str(path)}
        return subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), "health"], capture_output=True, text=True, env=env).stdout

    def test_a_city_never_set_up_is_one_health_warning_with_the_fix(self):
        out = self.health(self.config({}))
        warnings = [line for line in out.splitlines() if "City" in line]
        self.assertEqual(1, len(warnings), warnings)
        self.assertIn("[WARN]", warnings[0])
        self.assertIn('say "Set up OliverCode City"', warnings[0])

    def test_status_adds_one_short_line_and_no_walkthrough(self):
        self.config({})
        out = []
        cmd_status.run("o/r", count=lambda s, state: 0, fetch=lambda s, since: [], now=NOW, out=out.append)
        lines = [line for line in out if line.startswith("City:")]
        self.assertEqual(1, len(lines), out)
        self.assertNotIn("phone", lines[0].lower())

    def test_a_declined_city_is_quiet_everywhere(self):
        path = self.config({"cityDeclined": True})
        self.assertEqual("", cmd_guide.city_gap())
        self.assertIn("City: skipped by choice", "\n".join(cmd_guide.city_lines()))
        self.assertNotIn("[WARN] City", self.health(path))
        out = []
        cmd_status.run("o/r", count=lambda s, state: 0, fetch=lambda s, since: [], now=NOW, out=out.append)
        self.assertFalse([line for line in out if line.startswith("City:")])

    def test_a_set_up_city_clears_the_warning_and_the_guide_shows_the_url_with_the_pin_unverified(self):
        path = self.config({"cityArtifact": "https://claude.ai/artifact/abc"})
        self.assertEqual("", cmd_guide.city_gap())
        self.assertIn("https://claude.ai/artifact/abc (pin state unverified)", "\n".join(cmd_guide.city_lines()))
        self.assertNotIn("[WARN] City", self.health(path))

    def test_an_unconfirmed_phone_never_warns(self):
        path = self.config({"cityArtifact": "https://claude.ai/artifact/abc", "cityOnPhone": False})
        self.assertNotIn("[WARN] City", self.health(path))


if __name__ == "__main__":
    unittest.main()
