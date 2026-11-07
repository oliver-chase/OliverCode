"""The secret gate in every pre-commit variant and its reading of staged content, split from test_precommit_gates so the gate tests run in parallel."""

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


class SecretGateEveryVariant:
    """A staged fake key blocks the commit in every shipped hook. The key is built at run time."""

    def test_a_staged_fake_key_blocks_at_the_secret_gate(self):
        self.stage("config.py", 'KEY = "' + "sk-" + "z" * 32 + '"\n')
        out = self.assertBlocked("gate 1").stdout
        self.assertIn("Secret scan", out)
        self.assertIn("matches secret pattern", out)
        self.assertNotIn("Gate 2/", out)  # Gate 1 stops the commit itself, before any later gate runs

    def test_a_clean_file_passes_the_secret_gate(self):
        self.stage("notes.txt", "Plain notes.\n")
        self.assertIn("Secret scan", self.assertAllowed().stdout)


class StagedContent:
    """The gates read what the commit records: the staged content, under the file's real name.

    Git prints a name with an accent or an em dash quoted, and a gate that reads the staged list as
    plain text never opens the file. A gate that reads the working copy sees only what the file holds
    now, so a value staged and then edited out of the working copy still lands in the commit.
    It runs on OliverCode's own hook: the templates are built from the same gate source, and
    build-hooks --check fails on any drift."""

    def test_a_secret_in_a_name_with_an_em_dash_blocks(self):
        self.stage("Notes \u2014 Plan.txt", 'KEY = "' + "sk-" + "z" * 32 + '"\n')
        self.assertIn("matches secret pattern", self.assertBlocked("gate 1").stdout)

    def test_a_secret_in_a_name_with_an_accent_blocks(self):
        self.stage("caf\u00e9.txt", "TOKEN=ghp_" + "b" * 36 + "\n")
        self.assertBlocked("gate 1")

    def test_a_staged_secret_blocks_after_the_working_copy_is_cleaned(self):
        self.stage("config.py", 'KEY = "' + "sk-" + "z" * 32 + '"\n')
        self.write("config.py", "KEY = os.environ['KEY']\n")
        self.assertIn("matches secret pattern", self.assertBlocked("gate 1").stdout)

    def test_an_emoji_in_a_name_with_an_accent_blocks(self):
        self.stage("caf\u00e9.txt", "party \U0001F600\n")
        self.assertBlocked("gate 2")

    def test_a_staged_emoji_blocks_after_the_working_copy_is_cleaned(self):
        self.stage("notes.txt", "party \U0001F600\n")
        self.write("notes.txt", "party\n")
        self.assertBlocked("gate 2")

    def test_the_block_message_does_not_suggest_a_way_around_the_gate(self):
        self.stage("config.py", 'KEY = "' + "sk-" + "z" * 32 + '"\n')
        out = self.assertBlocked("gate 1").stdout
        self.assertNotIn("rename", out)
        self.assertNotIn("skip patterns", out)

    def test_a_clean_file_with_an_em_dash_name_passes(self):
        self.stage("Notes \u2014 Clean.txt", "Plain notes.\n")
        self.assertAllowed()


class TestLiveHookBlocksASecret(SecretGateEveryVariant, GateHarness):
    pass


class TestTemplateHookBlocksASecret(SecretGateEveryVariant, GateHarness):
    HOOK_SOURCE = TEMPLATE_HOOK


class TestPrivateHookBlocksASecret(SecretGateEveryVariant, GateHarness):
    HOOK_SOURCE = REPO_ROOT / "core" / "templates" / "project" / "pre-commit-private"


class TestLiveHookReadsStagedContent(StagedContent, GateHarness):
    pass


if __name__ == "__main__":
    unittest.main()
