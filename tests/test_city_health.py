"""City v2 (#1360): the Health section reads the validation, timing, failure, lesson and hook files and says what is not recorded."""

import json
import os
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import city_health  # noqa: E402


def page(home, github=None):
    with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home), "OLIVERCODE_FAILURE_LOG": ""}), mock.patch("lib.city_health.git", return_value=None):
        return city_health.render({"github": github})


class HealthTests(unittest.TestCase):
    def test_validation_timings_and_gate_blocks(self):
        home = temp_dir(self)
        (home / "validate-runs.jsonl").write_text(json.dumps({"at": 1, "run": 50, "wait": 2}) + "\n" + json.dumps({"at": 1795697603, "run": 67.0, "wait": 3.0}) + "\n")
        (home / "validate-timings.json").write_text(json.dumps({f"t{i}": i for i in range(8)}))
        (home / "failures.log").write_text("2026-11-26T00:00:00Z\tr\tpolicy\ta\n2026-11-26T00:01:00Z\tr\tpolicy\tb\n2026-11-26T00:02:00Z\tr\tCommit message\tc\n")
        out = page(home)
        for part in ("waited 3 s for a slot, then ran for 67 s", "Against a 67 s test run", "t7", "7.0 s", "policy", "Commit message", "policy refused. b"):
            self.assertIn(part, out)
        self.assertIn('<div class="fold" hidden>', out)
        self.assertIn('data-fold="See all 8 slowest test files"', out)
        self.assertIn("By 2 gates", out)

    def test_checks_and_version(self):
        home = temp_dir(self)
        out = page(home, {"read_at": 1795697603, "checks": [{"name": "test", "conclusion": "failure"}, {"name": "lint", "conclusion": "success"}]})
        self.assertIn("Failing: test.", out)
        self.assertIn("Not recorded, because the installed commit", out)
        self.assertIn("Not recorded, because no GitHub reading", page(home))

    def test_hook_firing_age_makes_no_claim_the_hooks_ran(self):
        home = temp_dir(self)
        (home / "hook-fires").mkdir()
        f = home / "hook-fires" / "a.json"
        f.write_text("{}")
        os.utime(f, (1795000000, 1795000000))
        out = page(home)
        self.assertIn("no longer recorded since", out)
        self.assertNotIn("hooks ran", out)

    def test_three_newest_lessons_show_and_the_rest_fold(self):
        home = temp_dir(self)
        (home / "lessons").mkdir()
        (home / "lessons" / "a.jsonl").write_text("".join(json.dumps({"date": f"2026-11-{d:02d}", "what": f"lesson{d}"}) + "\n" for d in (1, 2, 3, 4)))
        out = page(home)
        self.assertIn("See all 4 lessons", out)
        shown, folded = out.split('<div class="fold" hidden>')
        self.assertIn("lesson4", shown)
        self.assertNotIn("lesson1", shown)
        self.assertIn("lesson1", folded)

    def test_the_lead_names_the_failing_checks(self):
        home = temp_dir(self)
        out = page(home, {"read_at": 1795697603, "checks": [{"name": "test", "conclusion": "failure"}]})
        self.assertIn('<p class="read">1 failing check on main.', out)

    def test_the_section_uses_the_mockups_tiles_bars_and_rows(self):
        home = temp_dir(self)
        (home / "validate-runs.jsonl").write_text(json.dumps({"at": 1795697603, "run": 107, "wait": 600}) + "\n")
        (home / "validate-timings.json").write_text(json.dumps({"t1": 2.0}))
        (home / "failures.log").write_text("2026-11-26T00:00:00Z\tr\tpolicy\ta\n")
        out = page(home)
        for part in ('class="tiles"', 'class="bm"', 'class="bullet"', 'class="hbar"', 'class="stack"', 'class="row"', 'class="read"', 'class="grid2"'):
            self.assertIn(part, out)

if __name__ == "__main__":
    unittest.main()
