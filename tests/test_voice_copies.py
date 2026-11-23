"""A suite's docs/VOICE.md copy drifting from OliverCode's must fail health."""
import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import _support  # noqa: E402,F401  (isolates the local config and HOME)
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
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def check(self, skills=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return _check_voice_copies(self.oc, skills or self.skills)

    def test_matching_copy_passes(self):
        (self.suite / "docs" / "VOICE.md").write_text("voice\n")
        self.assertEqual(self.check(), (1, 0, 0))
        (self.suite / "docs" / "VOICE.md").write_text("voice\n\n## The dashboard\n")
        self.assertEqual(self.check(), (1, 0, 0))

    def test_drifted_copy_fails(self):
        (self.suite / "docs" / "VOICE.md").write_text("old voice\n")
        self.assertEqual(self.check(), (0, 1, 0))
        # the design copy is checked beside the voice copy
        (self.oc / "docs" / "DESIGN.md").write_text("design\n")
        (self.suite / "docs" / "DESIGN.md").write_text("design\n\n## Brand\n")
        self.assertEqual(self.check(), (1, 1, 0))

    def test_suite_without_copy_is_not_checked(self):
        self.assertEqual(self.check(), (0, 0, 0))

    def test_a_missing_canonical_voice_fails(self):
        (self.oc / "docs" / "VOICE.md").unlink()
        (self.suite / "docs" / "VOICE.md").write_text("voice\n")
        self.assertEqual(self.check(), (0, 1, 0))
        (self.suite / "docs" / "VOICE.md").unlink()
        self.assertEqual(self.check(), (0, 1, 0))

    def test_olivercodes_own_skills_are_not_a_suite(self):
        (self.oc / "skills" / "own").mkdir(parents=True)
        (self.skills / "own").symlink_to(self.oc / "skills" / "own")
        self.assertEqual(self.check(), (0, 0, 0))

    def test_a_broken_link_into_a_drifted_suite_is_not_checked(self):
        stale = self.tmp / "stale-suite"
        (stale / "docs").mkdir(parents=True)
        (stale / "docs" / "VOICE.md").write_text("old voice\n")
        (stale / "skills").mkdir()
        (self.skills / "gone").symlink_to(stale / "skills" / "gone")
        self.assertEqual(self.check(), (0, 0, 0))

    def test_a_real_folder_in_the_skills_directory_is_not_a_suite(self):
        # ~/.claude/skills holds real, untracked folders beside the symlinks; only a link
        # names an installed suite.
        home = self.tmp / "claude"
        (home / "skills" / "local-skill").mkdir(parents=True)
        (home / "docs").mkdir()
        (home / "docs" / "VOICE.md").write_text("old voice\n")
        self.assertEqual(self.check(home / "skills"), (0, 0, 0))
