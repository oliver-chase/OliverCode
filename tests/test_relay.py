"""The decision ledger keeps one decision, verify fails an incomplete record, and `olivercode decisions` records, verifies and shows it."""

import os
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, quiet, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import relay  # noqa: E402
from lib import decisions  # noqa: E402

GOOD = {"words": "Option A", "decision_id": "513", "options": ["A", "B"], "thread_id": "T1", "choice": "A", "by": "owner"}


class Isolated(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)


class TestVerify(Isolated):
    def test_a_record_missing_a_required_field_fails_and_names_it(self):
        for changes, missing in (({"decision_id": ""}, "the decision id"), ({"options": []}, "the options"),
                                 ({"thread_id": ""}, "the thread id"), ({"choice": ""}, "the choice")):
            relay.record(**{**GOOD, **changes})
            with self.assertRaises(ValueError) as caught:
                relay.verify(changes.get("decision_id", GOOD["decision_id"]))
            self.assertIn(missing, str(caught.exception))

    def test_a_choice_outside_the_options_fails_and_an_unknown_decision_fails(self):
        relay.record(**{**GOOD, "choice": "C"})
        with self.assertRaises(ValueError):
            relay.verify("513")
        with self.assertRaises(ValueError):
            relay.verify("unknown")

    def test_a_complete_record_verifies_and_round_trips(self):
        relay.record(**GOOD)
        rec = relay.verify("513")
        self.assertEqual((rec["choice"], rec["words"], rec["by"]), ("A", "Option A", "owner"))
        self.assertEqual(len(relay.records()), 1)


class TestCommand(Isolated):
    def test_record_verify_and_show_through_the_command(self):
        code, out = quiet(decisions.command_decisions, ["record", "--decision", "7", "--thread", "T", "--words", "go", "--option", "A", "--option", "B", "--choice", "A", "--by", "owner"])
        self.assertEqual(code, 0)
        self.assertIn("Recorded decision 7", out)
        code, out = quiet(decisions.command_decisions, ["verify", "7"])
        self.assertEqual(code, 0)
        self.assertIn("choice A of ['A', 'B']", out)
        code, out = quiet(decisions.command_decisions, ["show"])
        self.assertEqual(code, 0)
        self.assertIn("words: go", out)

    def test_verify_exits_1_for_an_unknown_decision_and_a_bad_record_prints_the_usage(self):
        code, out = quiet(decisions.command_decisions, ["verify", "nope"])
        self.assertEqual(code, 1)
        self.assertIn("No record for decision", out)
        code, out = quiet(decisions.command_decisions, ["record", "--decision", "7"])
        self.assertEqual(code, 1)
        self.assertIn("Usage", out)
        code, _ = quiet(decisions.command_decisions, ["show"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
