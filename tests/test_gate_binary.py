"""The content gates skip binary files, so a PNG, font or PDF prints no sed error and never hides a text secret."""

import unittest

from _support import git
from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00\xff\xfe\x80 @ sk-" + b"a" * 40 + b"\n"
ERRORS = ("sed:", "illegal byte", "Binary file", "Malformed")


class BinaryFiles(GateHarness):
    def stage_bytes(self, relpath, data):
        path = self.tmp / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        git(self.tmp, "add", relpath)

    def assertNoErrors(self, result):
        text = result.stdout + result.stderr
        for marker in ERRORS:
            self.assertNotIn(marker, text)


class TestBinarySkipped(BinaryFiles):
    def test_a_secret_blocks_beside_a_png_with_no_sed_error(self):
        self.stage_bytes("logo.png", PNG)
        self.stage("config.py", 'KEY = "sk-' + "b" * 32 + '"\n')
        result = self.assertBlocked("secret")
        self.assertIn("secret pattern", result.stdout)
        self.assertNoErrors(result)

    def test_a_commit_of_only_a_binary_file_passes_every_gate_quietly(self):
        self.stage_bytes("logo.png", PNG)
        self.stage_bytes("fonts/a.ttf", b"\x00\x01\x00\x00\xff\xfe" + b"person" + bytes([64]) + b"example.com\n")
        result = self.assertAllowed()
        self.assertNoErrors(result)

    def test_a_secret_in_a_text_file_after_many_binary_files_is_found(self):
        for number in range(200):
            self.stage_bytes(f"img/{number:03d}.png", PNG)
        self.stage("zz.py", 'KEY = "sk-' + "c" * 32 + '"\n')
        result = self.assertBlocked("secret after binaries")
        self.assertIn("zz.py matches secret pattern", result.stdout)
        self.assertNoErrors(result)

    def test_two_hundred_binary_files_print_no_error_in_a_tree_scan(self):
        for number in range(200):
            self.stage_bytes(f"img/{number:03d}.png", PNG)
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "images")
        result = self.run_hook(OLIVERCODE_SCAN_TREE="1")
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertNoErrors(result)


if __name__ == "__main__":
    unittest.main()
