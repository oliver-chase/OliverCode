"""The baseline raise cap, the size counter, `olivercode size` and the baseline bootstrap ships, split from test_size_ratchet so the gate tests run in parallel."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, git, git_env, scratch_repo, temp_dir
from test_size_ratchet import BASELINE, LAUNCHER, SIZE_SH, baseline_text, total_of


class TestRaiseCap(unittest.TestCase):
    """The commit-msg hook refuses a baseline raise over the cap unless the message says L or XL."""

    def setUp(self):
        self.repo = temp_dir(self, "olivercode-raisecap-")
        scratch_repo(self.repo)
        (self.repo / "docs").mkdir()
        (self.repo / ".githooks").mkdir()
        shutil.copy2(REPO_ROOT / "core/templates/project/commit-msg", self.repo / ".githooks/commit-msg")
        (self.repo / BASELINE).write_text(baseline_text(1000))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--no-verify", "-m", "base")
        git(self.repo, "config", "core.hooksPath", ".githooks")

    def commit(self, lines, message):
        (self.repo / BASELINE).write_text(baseline_text(lines))
        git(self.repo, "add", BASELINE)
        return git(self.repo, "commit", "-m", message, check=False)

    def test_a_raise_inside_the_cap_passes(self):
        self.assertEqual(0, self.commit(1020, "Grow a little (#5)").returncode)

    def test_a_raise_over_the_cap_is_blocked(self):
        result = self.commit(1021, "Grow a lot (#5)")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("cap of 20", result.stdout + result.stderr)
        # A one-line baseline is read by key, so allowancePercent is never taken for lines.
        git(self.repo, "reset", "-q", "--hard")
        (self.repo / BASELINE).write_text('{"lines": 1000, "allowancePercent": 5}\n')
        git(self.repo, "commit", "-q", "--no-verify", "-am", "one line (#5)")
        (self.repo / BASELINE).write_text('{"lines": 1021, "allowancePercent": 5}\n')
        git(self.repo, "add", BASELINE)
        result = git(self.repo, "commit", "-m", "Grow a lot (#5)", check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("cap of 20", result.stdout + result.stderr)

    def test_a_raise_over_the_cap_passes_with_a_size_l_line(self):
        self.assertEqual(0, self.commit(1500, "Grow a lot (#5)\n\nSize: L").returncode)

    def test_a_size_xl_line_also_passes(self):
        self.assertEqual(0, self.commit(1500, "Grow a lot (#5)\n\nSize: XL").returncode)

    def test_a_smaller_story_size_does_not_pass(self):
        self.assertNotEqual(0, self.commit(1500, "Grow a lot (#5)\n\nSize: M").returncode)

    def test_lowering_the_baseline_passes(self):
        self.assertEqual(0, self.commit(900, "Clean up (#5)").returncode)

    def test_a_commit_that_leaves_the_baseline_alone_passes(self):
        (self.repo / "a.txt").write_text("a\n")
        git(self.repo, "add", "a.txt")
        self.assertEqual(0, git(self.repo, "commit", "-m", "Other work (#5)", check=False).returncode)

    def test_editing_the_cap_in_the_same_commit_does_not_help(self):
        (self.repo / BASELINE).write_text(baseline_text(1500).replace('"updated"', '"raiseCapPercent": 100,\n  "updated"'))
        git(self.repo, "add", BASELINE)
        result = git(self.repo, "commit", "-m", "Sneaky (#5)", check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("over the cap of 20", result.stdout + result.stderr)

    def test_a_merge_prefixed_message_does_not_skip_the_cap(self):
        result = self.commit(1500, "Merge x")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("over the cap", result.stdout + result.stderr)

    def test_a_merge_prefixed_message_inside_the_cap_still_passes(self):
        self.assertEqual(0, self.commit(1010, "Merge x").returncode)

    def test_the_cap_percent_comes_from_the_baseline_file(self):
        (self.repo / BASELINE).write_text(baseline_text(1000, 5).replace('"updated"', '"raiseCapPercent": 10,\n  "updated"'))
        git(self.repo, "add", BASELINE)
        git(self.repo, "commit", "-q", "--no-verify", "-m", "cap ten (#5)")
        (self.repo / BASELINE).write_text(baseline_text(1090, 5).replace('"updated"', '"raiseCapPercent": 10,\n  "updated"'))
        git(self.repo, "add", BASELINE)
        self.assertEqual(0, git(self.repo, "commit", "-m", "inside ten (#5)", check=False).returncode)


class TestSizeCounter(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-size-")
        self.repo = scratch_repo(self.tmp / "repo")
        (self.repo / "a.txt").write_text("1\n2\n3\n")
        git(self.repo, "add", "a.txt")

    def test_total_is_a_bare_integer_and_agrees_with_the_report(self):
        self.assertEqual(3, total_of(self.repo))
        report = subprocess.run(["bash", str(SIZE_SH), str(self.repo)], env=git_env(),
                                capture_output=True, text=True).stdout
        total_row = next(l for l in report.splitlines() if l.startswith("TOTAL"))
        self.assertEqual("3", total_row.split()[2])
        # The repo's own backlog config wins over a fixture that sorts first.
        for rel, name in (("a/fixtures/backlog-config.json", "fixture"), ("docs/backlog-config.json", "real")):
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(json.dumps({"repoOwner": "o", "repoName": name, "projectNumber": 1,
                                                      "projectOwner": "o"}))
            git(self.repo, "add", rel)
        stub = self.tmp / "bin"
        stub.mkdir()
        (stub / "gh").write_text("#!/bin/sh\nexit 0\n")
        (stub / "gh").chmod(0o755)
        env = {**git_env(), "PATH": f"{stub}:{git_env().get('PATH', '/usr/bin:/bin')}"}
        out = subprocess.run(["bash", str(SIZE_SH), str(self.repo)], env=env, capture_output=True, text=True).stdout
        self.assertIn("Remaining work (o/real)", out)

    def test_staged_counts_the_index_copy(self):
        (self.repo / "a.txt").write_text("1\n" * 10)
        self.assertEqual(3, total_of(self.repo, "--staged"))
        self.assertEqual(10, total_of(self.repo))


class TestSizeCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-sizecmd-")
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
        self.assertIn("200 lines", out)
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


if __name__ == "__main__":
    unittest.main()


class TestSymlinkCountedOnce(unittest.TestCase):
    """A tracked symlink adds no lines, so the working-tree total equals the staged total."""

    def test_worktree_and_staged_totals_agree_with_a_link(self):
        repo = temp_dir(self, "olivercode-size-link-")
        scratch_repo(repo)
        (repo / "hook.sh").write_text("one\ntwo\nthree\n")
        (repo / "link.sh").symlink_to("hook.sh")
        git(repo, "add", "-A")
        worktree = subprocess.run(["bash", str(SIZE_SH), "--total", str(repo)], capture_output=True, text=True, env=git_env()).stdout.strip()
        staged = subprocess.run(["bash", str(SIZE_SH), "--total", "--staged", str(repo)], capture_output=True, text=True, env=git_env()).stdout.strip()
        self.assertEqual((worktree, staged), ("3", "3"))
