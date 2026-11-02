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

from _support import REPO_ROOT, git, git_env, scratch_repo
from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401

LAUNCHER = REPO_ROOT / "scripts" / "olivercode"
SIZE_SH = REPO_ROOT / "skills" / "audit" / "scripts" / "size.sh"
BASELINE = "docs/SIZE-BASELINE.json"


def baseline_text(lines, percent=5):
    return json.dumps({"lines": lines, "allowancePercent": percent, "updated": "2026-11-02"}, indent=2) + "\n"


def total_of(repo, *flags):
    return int(subprocess.run(["bash", str(SIZE_SH), "--total", *flags, str(repo)], env=git_env(),
                              capture_output=True, text=True, check=True).stdout)


class RatchetGate:
    """The gate's four rules, run against each shipped hook (mixed into a GateHarness)."""

    HOOK_FILE = None

    @classmethod
    def setUpClass(cls):
        cls.HOOK_SOURCE = REPO_ROOT / cls.HOOK_FILE
        super().setUpClass()

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

    def test_a_cleanup_never_blocks(self):
        git(self.tmp, "rm", "-q", "base.txt")
        self.assertAllowed()

    def test_raising_the_baseline_in_the_same_commit_passes(self):
        self.stage("big.txt", "x\n" * 100)
        self.assertBlocked("size ratchet")
        self.stage(BASELINE, baseline_text(total_of(self.tmp, "--staged")))
        self.assertIn("is trusted", self.assertAllowed().stdout)

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


class TestRatchetPublicTemplateHook(RatchetGate, GateHarness):
    HOOK_FILE = "core/templates/project/pre-commit"


class TestRatchetPrivateTemplateHook(RatchetGate, GateHarness):
    HOOK_FILE = "core/templates/project/pre-commit-private"


class TestSizeCounter(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-size-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = scratch_repo(self.tmp / "repo")
        (self.repo / "a.txt").write_text("1\n2\n3\n")
        git(self.repo, "add", "a.txt")

    def test_total_is_a_bare_integer_and_agrees_with_the_report(self):
        self.assertEqual(3, total_of(self.repo))
        report = subprocess.run(["bash", str(SIZE_SH), str(self.repo)], env=git_env(),
                                capture_output=True, text=True).stdout
        total_row = next(l for l in report.splitlines() if l.startswith("TOTAL"))
        self.assertEqual("3", total_row.split()[2])

    def test_staged_counts_the_index_copy(self):
        (self.repo / "a.txt").write_text("1\n" * 10)
        self.assertEqual(3, total_of(self.repo, "--staged"))
        self.assertEqual(10, total_of(self.repo))


class TestSizeCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="olivercode-sizecmd-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = scratch_repo(self.tmp / "repo")
        (self.repo / "docs").mkdir()
        (self.repo / "a.txt").write_text("x\n" * 100)
        self.set_baseline(200)

    def set_baseline(self, lines):
        (self.repo / BASELINE).write_text(baseline_text(lines))
        git(self.repo, "add", "-A")

    def size(self, *args):
        return subprocess.run([sys.executable, str(LAUNCHER), "size", *args], cwd=self.repo,
                              env=git_env(), capture_output=True, text=True)

    def recorded(self):
        return json.loads((self.repo / BASELINE).read_text())

    def test_plain_size_prints_total_baseline_and_headroom(self):
        out = self.size().stdout
        self.assertIn("Total lines: 105", out)
        self.assertIn("Baseline: 200 lines, allowance 5% (10 lines)", out)
        self.assertIn("Headroom: 105 lines", out)

    def test_lower_rewrites_the_baseline_to_a_smaller_total(self):
        done = self.size("--lower")
        self.assertEqual(0, done.returncode, done.stdout)
        data = self.recorded()
        self.assertEqual(105, data["lines"])
        self.assertEqual(5, data["allowancePercent"])
        self.assertRegex(data["updated"], r"^\d{4}-\d{2}-\d{2}$")

    def test_lower_accepts_an_equal_total(self):
        self.set_baseline(105)
        self.assertEqual(0, self.size("--lower").returncode)
        self.assertEqual(105, self.recorded()["lines"])

    def test_lower_refuses_to_raise_the_baseline(self):
        self.set_baseline(50)
        before = (self.repo / BASELINE).read_text()
        done = self.size("--lower")
        self.assertNotEqual(0, done.returncode)
        self.assertIn("never raises", done.stdout)
        self.assertEqual(before, (self.repo / BASELINE).read_text())

    def test_lower_sets_a_baseline_that_is_still_unset(self):
        (self.repo / BASELINE).write_text('{\n  "lines": null,\n  "allowancePercent": 5,\n  "updated": null\n}\n')
        git(self.repo, "add", "-A")
        self.assertEqual(0, self.size("--lower").returncode)
        self.assertEqual(105, self.recorded()["lines"])

    def test_no_baseline_file_fails(self):
        (self.repo / BASELINE).unlink()
        self.assertNotEqual(0, self.size().returncode)


class TestBootstrapShipsTheRatchet(unittest.TestCase):
    def test_a_new_repo_gets_the_baseline_the_counter_and_the_gate(self):
        tmp = Path(tempfile.mkdtemp(prefix="olivercode-sizeboot-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        repo = scratch_repo(tmp / "repo")
        done = subprocess.run([sys.executable, str(LAUNCHER), "bootstrap", str(repo)],
                              env=git_env(HOME=str(tmp)), capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stdout)
        self.assertIsNone(json.loads((repo / BASELINE).read_text())["lines"])
        self.assertEqual(5, json.loads((repo / BASELINE).read_text())["allowancePercent"])
        self.assertEqual(SIZE_SH.read_text(), (repo / "scripts" / "size.sh").read_text())
        self.assertIn("Size ratchet", (repo / ".githooks" / "pre-commit").read_text())

    def test_an_existing_baseline_is_not_clobbered(self):
        tmp = Path(tempfile.mkdtemp(prefix="olivercode-sizeboot-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        repo = scratch_repo(tmp / "repo")
        (repo / "docs").mkdir()
        (repo / BASELINE).write_text(baseline_text(777))
        subprocess.run([sys.executable, str(LAUNCHER), "bootstrap", str(repo)],
                       env=git_env(HOME=str(tmp)), capture_output=True, text=True, check=True)
        self.assertEqual(777, json.loads((repo / BASELINE).read_text())["lines"])


if __name__ == "__main__":
    unittest.main()
