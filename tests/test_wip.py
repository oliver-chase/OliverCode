"""Work in progress snapshots: `olivercode wip save|list|restore` and the Stop hook that calls save.

Each case builds a real scratch git repo and a temporary OLIVERCODE_HOME, so nothing touches the machine's repos or home.
"""

import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from _support import REPO_ROOT, git, git_env, quiet, scratch_repo, run_hook, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import claude_settings, wip  # noqa: E402

HOOK = REPO_ROOT / "scripts" / "hooks" / "wip_save.py"


def state(repo):
    """Everything save must leave alone: file bytes, index, branch and HEAD."""
    files = {str(p.relative_to(repo)): p.read_bytes() for p in sorted(repo.rglob("*")) if p.is_file() and ".git" not in p.parts}
    return (files, git(repo, "status", "--porcelain=v2", "--branch").stdout, git(repo, "ls-files", "-s").stdout,
            git(repo, "rev-parse", "HEAD").stdout, git(repo, "branch", "--list").stdout, (repo / ".git" / "index").read_bytes())


class WipCase(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self, resolve=True)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home / "oc")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = scratch_repo(temp_dir(self, resolve=True) / "repo", branch="main")
        (self.repo / "a.txt").write_text("one\n")
        (self.repo / ".gitignore").write_text("ignored.log\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "init")

    def dirty(self):
        (self.repo / "a.txt").write_text("two\n")
        (self.repo / "new.txt").write_text("fresh\n")
        (self.repo / "ignored.log").write_text("noise\n")

    def refs(self):
        return git(self.repo, "for-each-ref", "refs/wip", "--format=%(refname)").stdout.split()


class TestSave(WipCase):
    def test_the_snapshot_subject_holds_a_repo_relative_path_and_no_machine_path(self):
        self.dirty()
        quiet(wip.save, self.repo, "sess1")
        subject = git(self.repo, "log", "-1", "--format=%s", self.refs()[0]).stdout.strip()
        self.assertEqual(subject, "wip .")
        self.assertNotIn(str(self.repo), subject)

    def test_a_dirty_repo_is_snapshotted_and_left_byte_identical(self):
        self.dirty()
        (self.repo / "staged.txt").write_text("staged\n")
        git(self.repo, "add", "staged.txt")
        before = state(self.repo)
        made, _ = quiet(wip.save, self.repo, "sess1")
        self.assertEqual(len(made), 1)
        self.assertEqual(state(self.repo), before)
        self.assertRegex(self.refs()[0], r"^refs/wip/sess1/\d{8}T\d{6}")

    def test_an_untracked_file_is_in_the_snapshot_and_an_ignored_one_is_not(self):
        self.dirty()
        quiet(wip.save, self.repo, "sess1")
        files = git(self.repo, "ls-tree", "-r", "--name-only", self.refs()[0]).stdout.split()
        self.assertIn("new.txt", files)
        self.assertNotIn("ignored.log", files)

    def test_a_clean_repo_makes_no_ref(self):
        made, _ = quiet(wip.save, self.repo, "sess1")
        self.assertEqual(made, [])
        self.assertEqual(self.refs(), [])

    def test_an_unchanged_dirty_repo_does_not_add_a_second_ref(self):
        self.dirty()
        quiet(wip.save, self.repo, "sess1", now=1_700_000_000)
        quiet(wip.save, self.repo, "sess1", now=1_700_000_100)
        self.assertEqual(len(self.refs()), 1)

    def test_a_held_index_lock_skips_the_repo(self):
        self.dirty()
        (self.repo / ".git" / "index.lock").write_text("")
        made, _ = quiet(wip.save, self.repo, "sess1")
        self.assertEqual(made, [])
        self.assertEqual(self.refs(), [])

    def test_a_worktree_of_the_repo_is_snapshotted_too(self):
        tree = self.repo.parent / "tree"
        git(self.repo, "worktree", "add", "-q", "-b", "side", str(tree))
        (tree / "wt.txt").write_text("in the worktree\n")
        made, _ = quiet(wip.save, self.repo, "sess1")
        self.assertEqual(len(made), 1)
        self.assertIn("wt.txt", git(self.repo, "ls-tree", "-r", "--name-only", self.refs()[0]).stdout)

    def test_refs_older_than_seven_days_are_pruned_on_save(self):
        self.dirty()
        quiet(wip.save, self.repo, "old", now=time.time() - 8 * 86400)
        self.assertEqual(len(self.refs()), 1)
        (self.repo / "b.txt").write_text("again\n")
        quiet(wip.save, self.repo, "new")
        self.assertEqual([r.split("/")[2] for r in self.refs()], ["new"])


class TestListAndRestore(WipCase):
    def test_list_shows_the_repo_relative_tree_time_and_file_count(self):
        self.dirty()
        quiet(wip.save, self.repo, "sess1")
        code, out = quiet(wip.command_wip, ["list"], cwd=self.repo)
        self.assertEqual(code, 0)
        self.assertIn("refs/wip/sess1/", out)
        self.assertIn("  .  ", out)
        self.assertIn("2 files", out)

    def test_restore_brings_back_a_changed_and_an_untracked_file_into_a_new_folder(self):
        self.dirty()
        quiet(wip.save, self.repo, "sess1")
        before = state(self.repo)
        target = self.home / "out"
        code, _ = quiet(wip.command_wip, ["restore", self.refs()[0], "--to", str(target)], cwd=self.repo)
        self.assertEqual(code, 0)
        self.assertEqual((target / "a.txt").read_text(), "two\n")
        self.assertEqual((target / "new.txt").read_text(), "fresh\n")
        self.assertEqual(state(self.repo), before)

    def test_restore_defaults_to_a_new_folder_under_the_wip_restore_home(self):
        self.dirty()
        quiet(wip.save, self.repo, "sess1")
        code, out = quiet(wip.command_wip, ["restore", self.refs()[0]], cwd=self.repo)
        self.assertEqual(code, 0)
        self.assertIn("wip-restore", out)
        self.assertEqual(len(list((self.home / "oc" / "wip-restore").glob("*/new.txt"))), 1)

    def test_restore_refuses_a_folder_that_already_holds_files(self):
        self.dirty()
        quiet(wip.save, self.repo, "sess1")
        code, _ = quiet(wip.command_wip, ["restore", self.refs()[0], "--to", str(self.repo)], cwd=self.repo)
        self.assertEqual(code, 1)
        self.assertEqual((self.repo / "a.txt").read_text(), "two\n")


class TestHook(WipCase):
    def run_hook(self, sid="s1"):
        return run_hook(HOOK, {"session_id": sid, "cwd": str(self.repo)}, env=git_env(OLIVERCODE_HOME=str(self.home / "oc"), HOME=str(self.home)))

    def test_the_hook_saves_once_and_then_waits_ten_minutes(self):
        self.dirty()
        first = self.run_hook()
        self.assertEqual((first.returncode, first.stderr), (0, ""))
        self.assertEqual(len(self.refs()), 1)
        (self.repo / "a.txt").write_text("three\n")
        self.run_hook()
        self.assertEqual(len(self.refs()), 1)
        marks = json.loads((self.home / "oc" / "wip-last.json").read_text())
        marks["s1"] -= 11 * 60
        (self.home / "oc" / "wip-last.json").write_text(json.dumps(marks))
        self.run_hook()
        self.assertEqual(len(self.refs()), 2)

    def test_the_throttle_is_per_session(self):
        self.dirty()
        self.run_hook("s1")
        (self.repo / "a.txt").write_text("three\n")
        self.run_hook("s2")
        self.assertEqual(len(self.refs()), 2)

    def test_the_hook_fails_open_with_one_stderr_line(self):
        bad = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True,
                             env=git_env(OLIVERCODE_HOME=str(self.home / "oc"), HOME=str(self.home)))
        self.assertEqual(bad.returncode, 0)
        self.assertLessEqual(len(bad.stderr.strip().splitlines()), 1)


class TestInstallEntry(unittest.TestCase):
    def test_install_adds_the_stop_entry_and_a_rerun_adds_it_to_an_older_file(self):
        path = temp_dir(self) / "settings.json"
        claude_settings.install(path)
        data = json.loads(path.read_text())
        stop = [h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"]]
        self.assertTrue(any(c.endswith('wip_save.py"') for c in stop))
        data["hooks"]["Stop"] = [g for g in data["hooks"]["Stop"] if "wip_save" not in json.dumps(g)]
        path.write_text(json.dumps(data))
        self.assertEqual(claude_settings.missing(path), ["wip_save.py"])
        self.assertEqual(claude_settings.install(path), "updated")
        self.assertEqual(claude_settings.missing(path), [])


class TestEmptyTree(unittest.TestCase):
    def test_the_empty_tree_constant_is_the_one_git_knows(self):
        known = subprocess.run(["git", "hash-object", "-t", "tree", "/dev/null"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(known, wip.EMPTY_TREE)


if __name__ == "__main__":
    unittest.main()
