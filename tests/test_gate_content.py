"""The PII gate of the pre-commit hook."""

from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401
__all__ = ["setUpModule", "tearDownModule"]  # unittest runs them from this module


class TestGate2PII(GateHarness):
    def test_a_home_path_or_an_email_blocks(self):
        for text in ("cd /Users/someone/projects\n", "cd /home/someone/projects\n", "NOTIFY=person@example.com\n"):
            with self.subTest(text=text):
                self.stage("run.sh", text)
                self.assertBlocked("gate 2")

    def test_placeholder_path_passes(self):
        self.stage("run.sh", "cd <vault-root>/projects\n")
        self.assertAllowed()

    def test_a_real_home_path_or_address_in_a_test_file_blocks(self):
        for text in ("HOME = '/" + "Users/janedoe/code'\n", "OWNER = 'jane.doe@" + "corp.test.org'\n"):  # built so this file holds no real-looking value
            with self.subTest(text=text):
                self.stage("tests/test_real.py", text)
                self.assertBlocked("gate 2")

    def test_placeholder_values_in_a_test_file_pass(self):
        self.stage("tests/test_fixture.py", "EMAIL = 't@example.com'\nHOME = '/Users/someone/code'\nREMOTE = 'git@github.com:o/r.git'\n")
        self.assertAllowed()
