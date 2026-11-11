"""The secret gate (Gate 1) of the pre-commit hook in every variant, split from test_precommit_gates so the gate tests run in parallel."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import ISOLATION, REPO_ROOT, git, git_env, scratch_repo
from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401

HOOK = REPO_ROOT / ".githooks" / "pre-commit"
TEMPLATE_HOOK = REPO_ROOT / "core" / "templates" / "project" / "pre-commit"


class TestGate1Secrets(GateHarness):
    def test_github_pat_blocks(self):
        self.stage("deploy.sh", "TOKEN=ghp_" + "b" * 36 + "\n")
        self.assertBlocked("gate 1")
        git(self.tmp, "rm", "-q", "--cached", "deploy.sh")
        # Current credential formats, each built at run time and staged alone.
        modern = {
            "anthropic": "sk-" + "ant-api03-" + "A1b_" * 20,
            "github fine-grained": "github" + "_pat_" + "11ABC" + "Ab3" * 20,
            "github oauth": "gh" + "o_" + "c" * 36,
            "aws secret with slashes": "aws_secret_access_key = " + "Ab/c+De" * 5 + "Ab/c+",
            "slack webhook": "https://hooks." + "slack.com/services/T0ABC/B0DEF/" + "g" * 24,
            "gitlab": "gl" + "pat-" + "h" * 20,
            "hugging face": "h" + "f_" + "i" * 34,
            "sendgrid": "S" + "G." + "j" * 22 + "." + "k" * 43,
            "webhook secret": "wh" + "sec_" + "m" * 32,
            "google oauth": "ya" + "29." + "n" * 40,
        }
        for name, value in modern.items():
            with self.subTest(name):
                self.stage("cred.txt", value + "\n")
                self.assertBlocked("gate 1")
                git(self.tmp, "rm", "-q", "--cached", "cred.txt")

    def test_private_key_header_blocks(self):
        self.stage("id.txt", "-----BEGIN RSA " + "PRIVATE KEY-----\n")
        self.assertBlocked("gate 1")

    def test_a_secret_in_a_large_file_blocks(self):
        # A pipeline that exits early fails open on big files under pipefail.
        self.stage("big.py", ('KEY = "sk-' + "d" * 32 + '"\n') * 2000)
        self.assertBlocked("gate 1")

    def test_no_path_is_exempt_and_a_placeholder_is_exempt_by_its_value_or_line(self):
        key = "sk-" + "c" * 32
        for path in ("tests/t.txt", "src/mock_client.py", ".env.example"):
            with self.subTest(path):
                self.stage(path, f'API_KEY="{key}"\n')
                self.assertBlocked("gate 1")
                git(self.tmp, "rm", "-q", "--cached", path)
        # A placeholder word elsewhere on the line does not excuse a real key.
        for line in (f'curl https://api.example.com -H "Authorization: Bearer {key}"',
                     f"OPENAI_KEY={key}  # paste your_token here"):
            with self.subTest(line):
                self.stage("run.sh", line + "\n")
                self.assertBlocked("gate 1")
                git(self.tmp, "rm", "-q", "--cached", "run.sh")
        self.stage(".env.example", 'API_KEY="sk-' + "EXAMPLE" + "0" * 20 + '"\n'
                   f'TOKEN="{key}"  # secret-scan: allow\n')
        self.assertAllowed()

    def test_ordinary_prose_passes(self):
        self.stage("notes.md", "This file mentions a token conceptually.\n")
        self.assertAllowed()


if __name__ == "__main__":
    unittest.main()
