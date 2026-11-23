"""A recorded standing push approval lets a blocked push go through; with none, the push stays blocked and the owner is asked once (#738)."""

import os
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_owner, push_approval, relay  # noqa: E402


class TestPushApproval(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(temp_dir(self))})
        patcher.start()
        self.addCleanup(patcher.stop)

    def record(self, **changes):
        args = dict(words="Yes, approve", decision_id=push_approval.DECISION, options=["approve", "deny"], thread_id="738", choice="approve", by="owner")
        relay.record(**{**args, **changes})

    def test_a_recorded_approval_names_the_one_rule_and_asks_nobody(self):
        self.record()
        allowed, message = push_approval.handle_block("s1")
        self.assertTrue(allowed)
        self.assertIn("Allow this one rule", message)
        self.assertIn("git push origin HEAD:main", message)
        self.assertIn("Yes, approve", message)
        self.assertEqual([], cmd_owner.items())

    def test_with_no_record_the_push_stays_blocked_and_the_owner_is_asked_once(self):
        allowed, message = push_approval.handle_block("s1")
        self.assertFalse(allowed)
        self.assertIn("stays blocked", message)
        push_approval.handle_block("s2")
        push_approval.handle_block("s1")
        asked = [i for i in cmd_owner.items() if i["status"] == "open"]
        self.assertEqual(1, len(asked))
        self.assertEqual(push_approval.ASK, asked[0]["step"])

    def test_a_record_the_owner_did_not_make_or_that_denies_does_not_count(self):
        self.record(by="s1")
        self.assertFalse(push_approval.handle_block("s1")[0])
        self.record(choice="deny")
        self.assertFalse(push_approval.handle_block("s1")[0])
        self.record(words="  ")
        self.assertFalse(push_approval.handle_block("s1")[0])

    def test_an_incomplete_record_does_not_count(self):
        self.record(options=["approve"], choice="deny")
        self.assertIsNone(push_approval.approval())

    def test_the_command_exits_by_the_answer_and_refuses_bad_input(self):
        out = []
        self.assertEqual(1, push_approval.command_push_blocked([], out=out.append))
        self.assertEqual(1, push_approval.command_push_blocked(["--session", "s1"], out=out.append))
        self.record()
        self.assertEqual(0, push_approval.command_push_blocked(["--session", "s1"], out=out.append))


if __name__ == "__main__":
    unittest.main()
