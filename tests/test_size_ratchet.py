"""The size ratchet (#78): the gate in every pre-commit variant, `olivercode size`, and the
baseline that `olivercode bootstrap` ships.

Offline: scratch repos from _support, no network, no gh.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, git, git_env, scratch_repo, temp_dir
from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401

LAUNCHER = REPO_ROOT / "scripts" / "olivercode"
SIZE_SH = REPO_ROOT / "skills" / "audit" / "scripts" / "size.sh"
BASELINE = "docs/SIZE-BASELINE.json"


def baseline_text(lines, percent=5):
    return json.dumps({"lines": lines, "allowancePercent": percent, "updated": "2026-11-02"}, indent=2) + "\n"


def total_of(repo, *flags):
    return int(subprocess.run(["bash", str(SIZE_SH), "--total", *flags, str(repo)], env=git_env(),
                              capture_output=True, text=True, check=True).stdout)


class RatchetSetup:
    """A scratch repo holding a hook, the counter and a baseline equal to its total (mixed into a GateHarness)."""

    def setUp(self):
        super().setUp()
        self.stage("scripts/size.sh", SIZE_SH.read_text())
        self.stage("base.txt", "line\n" * 200)
        self.stage(BASELINE, baseline_text(1))
        self.recorded = total_of(self.tmp, "--staged")
        self.stage(BASELINE, baseline_text(self.recorded))
        git(self.tmp, "commit", "-q", "--no-verify", "-m", "base")
        # The 200-line file gives the 5% allowance room for the cases below.
        self.allowance = self.recorded * 5 // 100


class RatchetGate(RatchetSetup):
    """Every rule of the gate, run against OliverCode's own hook. The two templates are built from the same gate
    source (build-hooks --check fails on drift), so they get one wiring test."""

    def test_a_commit_inside_the_allowance_passes(self):
        self.stage("small.txt", "x\n" * (self.allowance - 1))
        self.assertRegex(self.assertAllowed().stdout, r"Gate \d+ passed \(\d+ lines, baseline")

    def test_growth_past_the_allowance_blocks_and_names_the_three_biggest(self):
        for name, size in (("a.txt", 30), ("b.txt", 20), ("c.txt", 12), ("d.txt", 3)):
            self.stage(name, "x\n" * size)
        out = self.assertBlocked("size ratchet").stdout
        self.assertIn("three files that grew most", out)
        listed = [l.split()[-1] for l in out.splitlines() if l.strip().startswith("+")]
        self.assertEqual(["a.txt", "b.txt", "c.txt"], listed)
        # The allowance comes from the committed baseline, so the same commit cannot widen it.
        self.stage(BASELINE, baseline_text(self.recorded, 100))
        self.assertIn("5% allowance", self.assertBlocked("size ratchet").stdout)

    def test_a_one_line_baseline_reads_the_same_as_the_shipped_layout(self):
        """A hand-written {"lines": N, "allowancePercent": 5} used to read 5 as the line count and block every commit."""
        self.stage(BASELINE, json.dumps({"lines": self.recorded, "allowancePercent": 5}) + "\n")
        self.stage("small.txt", "x\n" * (self.allowance - 1))
        out = self.assertAllowed().stdout
        self.assertIn(f"baseline {self.recorded})", out)

    def test_the_block_names_the_repos_baseline_script_when_it_has_one(self):
        self.stage("big.txt", "x\n" * 100)
        self.assertNotIn("size_baseline.py", self.assertBlocked("size ratchet").stdout)
        self.stage("scripts/size_baseline.py", "# the repo's own baseline writer\n")
        out = self.assertBlocked("size ratchet").stdout
        self.assertIn("size_baseline.py", out)

    def test_a_cleanup_never_blocks(self):
        git(self.tmp, "rm", "-q", "base.txt")
        self.assertAllowed()

    def test_raising_the_baseline_in_the_same_commit_passes(self):
        self.stage("big.txt", "x\n" * 100)
        self.assertBlocked("size ratchet")
        total = total_of(self.tmp, "--staged")
        # A raise to a number the files do not count to, such as a round figure, is refused.
        self.stage(BASELINE, baseline_text(total + 37))
        self.assertIn("counted total", self.assertBlocked("size ratchet").stdout)
        self.stage(BASELINE, baseline_text(total))
        self.assertIn("is trusted", self.assertAllowed().stdout)

    def test_a_raise_inside_the_cap_passes_and_is_printed(self):
        raised = self.recorded + 2
        self.stage("small.txt", "x\n" * 2)
        self.stage(BASELINE, baseline_text(raised))
        self.assertIn("raises the baseline by 2 lines", self.assertAllowed().stdout)

    def test_a_raise_over_the_cap_is_printed_for_the_commit_msg_hook_to_judge(self):
        self.stage("big.txt", "x\n" * 100)
        self.stage(BASELINE, baseline_text(total_of(self.tmp, "--staged")))
        out = self.assertAllowed().stdout
        self.assertIn("without an L or XL story", out)

    def test_an_unset_baseline_skips(self):
        self.stage(BASELINE, '{\n  "lines": null,\n  "allowancePercent": 5,\n  "updated": null\n}\n')
        self.stage("big.txt", "x\n" * 500)
        self.assertIn("skipped", self.assertAllowed().stdout)

    def test_no_baseline_file_skips(self):
        git(self.tmp, "rm", "-q", "-f", BASELINE)
        self.stage("big.txt", "x\n" * 500)
        self.assertIn("skipped", self.assertAllowed().stdout)

    def test_a_baseline_with_no_counter_blocks(self):
        git(self.tmp, "rm", "-q", "-f", "scripts/size.sh")
        self.assertIn("no scripts/size.sh", self.assertBlocked("counter").stdout)

    def test_the_gate_counts_the_staged_tree_not_the_working_copy(self):
        self.write("base.txt", "line\n" * 5000)  # unstaged growth does not count
        self.stage("small.txt", "x\n")
        self.assertAllowed()


class TestRatchetOliverCodeHook(RatchetGate, GateHarness):
    HOOK_FILE = ".githooks/pre-commit"


class RatchetWired(RatchetSetup):
    def test_growth_past_the_allowance_blocks(self):
        self.stage("big.txt", "x\n" * (self.allowance + 5))
        self.assertBlocked("size ratchet")


class TestRatchetPrivateTemplateHook(RatchetWired, GateHarness):
    HOOK_FILE = "core/templates/project/pre-commit-private"


if __name__ == "__main__":
    unittest.main()
