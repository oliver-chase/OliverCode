import json
import os
import tempfile
import unittest
from pathlib import Path

import audit_mode


class AuditModeTest(unittest.TestCase):
    def setUp(self):
        self.file = Path(tempfile.mkdtemp()) / "olivercode.local.json"
        self.old = os.environ.get("OLIVERCODE_LOCAL_CONFIG")
        os.environ["OLIVERCODE_LOCAL_CONFIG"] = str(self.file)

    def tearDown(self):
        if self.old is None:
            os.environ.pop("OLIVERCODE_LOCAL_CONFIG", None)
        else:
            os.environ["OLIVERCODE_LOCAL_CONFIG"] = self.old

    def test_an_unset_mode_stops_at_the_report_and_the_opt_ins_run_the_to_done_phase(self):
        self.assertEqual(("skip", None), audit_mode.next_step(audit_mode.get_mode()))
        self.assertEqual(("run", None), audit_mode.next_step(None, fix=True))
        self.assertEqual(("skip", None), audit_mode.next_step(None, report_only=True, fix=True))

    def test_the_mode_is_stored_beside_other_settings(self):
        self.file.write_text(json.dumps({"retroEpic": 7}))
        audit_mode.set_mode("gated")
        self.assertEqual("gated", audit_mode.get_mode())
        self.assertEqual({"retroEpic": 7, "auditMode": "gated"}, json.loads(self.file.read_text()))

    def test_the_gated_path_asks_once_for_approval_and_shows_the_reminder(self):
        action, reminder = audit_mode.next_step("gated")
        self.assertEqual("approve", action)
        self.assertIn("olivercode audit-mode full", reminder)

    def test_the_full_path_runs_with_no_prompt_and_no_reminder(self):
        self.assertEqual(("run", None), audit_mode.next_step("full"))

    def test_report_only_skips_the_to_done_phase_in_every_mode(self):
        for mode in (None, "full", "gated"):
            self.assertEqual(("skip", None), audit_mode.next_step(mode, report_only=True))

    def test_the_mode_can_change_at_any_time_and_a_bad_value_is_refused(self):
        audit_mode.set_mode("gated")
        audit_mode.set_mode("full")
        self.assertEqual("full", audit_mode.get_mode())
        with self.assertRaises(ValueError):
            audit_mode.set_mode("auto")
        self.assertEqual("full", audit_mode.get_mode())

    def test_a_stored_junk_value_counts_as_unset(self):
        self.file.write_text(json.dumps({"auditMode": "maybe"}))
        self.assertIsNone(audit_mode.get_mode())

    def test_the_command_line_prints_the_action(self):
        self.assertEqual(0, audit_mode.main(["set", "full"]))
        self.assertEqual(0, audit_mode.main(["next"]))
        self.assertEqual(0, audit_mode.main(["next", "--fix"]))
        self.assertEqual(1, audit_mode.main(["set", "bogus"]))

    def test_the_skill_text_no_longer_promises_the_fix_loop(self):
        skill = (Path(__file__).parent.parent / "SKILL.md").read_text()
        self.assertNotIn("fix them in order, audit again", skill)


if __name__ == "__main__":
    unittest.main()
