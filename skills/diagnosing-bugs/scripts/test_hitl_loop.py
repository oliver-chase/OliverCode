"""Test the manual repro walker by running it with piped answers. No network, no real secrets.
Run: python3 -m unittest discover -p "test_*.py"   (from this folder)
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "hitl_loop.sh"
SECRET = "sk-test-0123456789abcdef"


def run(steps_text, answers, env_extra=None):
    with tempfile.TemporaryDirectory() as tmp:
        steps = Path(tmp) / "steps.txt"
        steps.write_text(steps_text)
        env = {k: v for k, v in os.environ.items() if k != "HITL_REDACT"}
        env.update(env_extra or {})
        proc = subprocess.run(["bash", str(SCRIPT), str(steps)], input=answers, capture_output=True, text=True, env=env)
        return proc.returncode, proc.stdout, proc.stderr


class HitlLoop(unittest.TestCase):
    def test_no_arguments_is_a_usage_error(self):
        proc = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Usage", proc.stderr)

    def test_missing_steps_file_is_a_usage_error(self):
        proc = subprocess.run(["bash", str(SCRIPT), "/nonexistent/steps.txt"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)

    def test_red_when_the_symptom_shows(self):
        code, out, _ = run("open the form\nsubmit it\n", "\n\ny\n")
        self.assertEqual(code, 1)
        self.assertIn("Step 1: open the form", out)
        self.assertIn("Step 2: submit it", out)
        self.assertIn("red: symptom reproduced", out)

    def test_green_when_the_symptom_is_absent(self):
        code, out, _ = run("open the form\n", "\nn\n")
        self.assertEqual(code, 0)
        self.assertIn("green: symptom absent", out)

    def test_blank_lines_and_comments_are_not_steps(self):
        code, out, _ = run("# setup\n\nopen the form\n", "\nn\n")
        self.assertEqual(code, 0)
        self.assertIn("Step 1: open the form", out)
        self.assertNotIn("Step 2", out)

    def test_a_secret_named_in_the_step_text_is_redacted(self):
        code, out, _ = run(f"paste {SECRET} into the box\n", "\ny\n", {"API_KEY": SECRET, "HITL_REDACT": "API_KEY"})
        self.assertIn("paste <REDACTED> into the box", out)
        self.assertNotIn(SECRET, out)

    def test_quitting_stops_with_usage_code(self):
        code, out, _ = run("open the form\nsubmit it\n", "\nq\n")
        self.assertEqual(code, 2)
        self.assertIn("Stopped at step 2", out)

    def test_no_verdict_is_not_a_result(self):
        code, _, err = run("open the form\n", "\nmaybe\n")
        self.assertEqual(code, 2)
        self.assertIn("no verdict", err)

    def test_empty_steps_file_is_a_usage_error(self):
        code, _, err = run("# nothing here\n\n", "")
        self.assertEqual(code, 2)
        self.assertIn("no steps", err)


if __name__ == "__main__":
    unittest.main()
