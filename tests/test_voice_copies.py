"""A suite's docs/VOICE.md copy drifting from OliverCode's must fail health."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib.health_checks import _check_voice_copies  # noqa: E402


class TestVoiceCopies(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="voice-copies-"))
        self.oc = self.tmp / "OliverCode"
        (self.oc / "docs").mkdir(parents=True)
        (self.oc / "docs" / "VOICE.md").write_text("voice\n")
        self.suite = self.tmp / "suite"
        (self.suite / "skills" / "one").mkdir(parents=True)
        (self.suite / "docs").mkdir()
        self.skills = self.tmp / "home-skills"
        self.skills.mkdir()
        (self.skills / "one").symlink_to(self.suite / "skills" / "one")

    def test_matching_copy_passes(self):
        (self.suite / "docs" / "VOICE.md").write_text("voice\n")
        self.assertEqual(_check_voice_copies(self.oc, self.skills), (1, 0, 0))

    def test_drifted_copy_fails(self):
        (self.suite / "docs" / "VOICE.md").write_text("old voice\n")
        self.assertEqual(_check_voice_copies(self.oc, self.skills), (0, 1, 0))

    def test_suite_without_copy_is_not_checked(self):
        self.assertEqual(_check_voice_copies(self.oc, self.skills), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
