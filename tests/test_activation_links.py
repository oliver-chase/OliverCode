"""Tests for _check_activation_links: a dangling ~/.claude link fails health and names the fix."""

import contextlib
import io
import unittest

from _support import load_script, temp_dir

health_checks = load_script("scripts/lib/health_checks.py")


class TestActivationLinks(unittest.TestCase):
    def run_check(self, claude):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = health_checks._check_activation_links(claude)
        return result, out.getvalue()

    def test_broken_rules_link_fails_and_prints_the_fix(self):
        claude = temp_dir(self)
        (claude / "CLAUDE.md").symlink_to(claude / "gone" / "CLAUDE.md")
        (result, text) = self.run_check(claude)
        self.assertEqual(result[1], 1)
        self.assertIn("olivercode install", text)
        self.assertIn("CLAUDE.md", text)

    def test_sound_links_report_no_problem(self):
        claude = temp_dir(self)
        target = claude / "real.md"
        target.write_text("x")
        (claude / "CLAUDE.md").symlink_to(target)
        (claude / "VOICE.md").symlink_to(target)
        (result, _) = self.run_check(claude)
        self.assertEqual(result, (2, 0, 0))

    def test_broken_skill_link_fails(self):
        claude = temp_dir(self)
        target = claude / "real.md"
        target.write_text("x")
        (claude / "CLAUDE.md").symlink_to(target)
        (claude / "skills").mkdir()
        (claude / "skills" / "audit").symlink_to(claude / "nowhere")
        self.assertEqual(self.run_check(claude)[0][1], 1)

    def test_no_install_is_a_skip_and_not_a_failure(self):
        self.assertEqual(self.run_check(temp_dir(self))[0], (0, 0, 1))


if __name__ == "__main__":
    unittest.main()
