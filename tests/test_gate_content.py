"""The PII gate of the pre-commit hook."""

from _support import git  # noqa: F401
from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401


class TestGate2PII(GateHarness):
    def test_a_home_path_or_an_email_blocks(self):
        for text in ("cd /Users/someone/projects\n", "cd /home/someone/projects\n", "NOTIFY=person@example.com\n"):
            with self.subTest(text=text):
                self.stage("run.sh", text)
                self.assertBlocked("gate 2")

    def test_placeholder_path_passes(self):
        self.stage("run.sh", "cd <vault-root>/projects\n")
        self.assertAllowed()
