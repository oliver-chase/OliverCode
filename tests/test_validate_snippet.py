"""The validation-queue block inserted into a repo's own scripts/validate.sh, and kept identical to the template's (#548)."""

import os
import shutil
import stat
import subprocess
import unittest
from unittest import mock

from _support import REPO_ROOT, git, git_env, load_script, quiet, scratch_repo, temp_dir

TEMPLATES = REPO_ROOT / "core" / "templates" / "project"
launcher = load_script("scripts/olivercode", "olivercode_launcher_snippet")
from lib import cmd_fleet, validate_snippet  # noqa: E402

FLEET_SCRIPT = (b'#!/usr/bin/env bash\n# fleet repo validation\nset -euo pipefail\n\n'
                b'REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\ncd "$REPO_ROOT"\n\n'
                b'echo "=== checks ==="\n')


class TestTemplate(unittest.TestCase):
    def test_the_template_validate_sh_holds_exactly_the_snippet(self):
        snippet = (TEMPLATES / "scripts" / "validate-queue.snippet.sh").read_text(encoding="utf-8")
        template = (TEMPLATES / "scripts" / "validate.sh").read_text(encoding="utf-8")
        self.assertIn(snippet, template)
        self.assertEqual(1, template.count(validate_snippet.MARKER.decode()))
        self.assertTrue(snippet.startswith(validate_snippet.MARKER.decode()))


class TestInsert(unittest.TestCase):
    def setUp(self):
        self.oc = temp_dir(self, "oc-snippet-oc-", resolve=True)
        (self.oc / "core" / "templates").mkdir(parents=True)
        shutil.copytree(TEMPLATES, self.oc / "core" / "templates" / "project")
        self.repo = temp_dir(self, "oc-snippet-repo-", resolve=True)
        (self.repo / "scripts").mkdir()
        self.script = self.repo / "scripts" / "validate.sh"

    def write(self, data=FLEET_SCRIPT, mode=0o755):
        self.script.write_bytes(data)
        self.script.chmod(mode)

    def test_a_script_without_the_block_gets_it_once_after_the_cd_line_and_the_rest_is_unchanged(self):
        self.write()
        status, _ = validate_snippet.ensure_queue_snippet(self.oc, self.repo)
        self.assertEqual("added", status)
        after = self.script.read_bytes()
        snippet = (TEMPLATES / "scripts" / "validate-queue.snippet.sh").read_bytes()
        self.assertEqual(1, after.count(validate_snippet.MARKER))
        cut = FLEET_SCRIPT.index(b'cd "$REPO_ROOT"\n') + len(b'cd "$REPO_ROOT"\n')
        self.assertEqual(FLEET_SCRIPT[:cut] + b"\n" + snippet + FLEET_SCRIPT[cut:], after)
        self.assertEqual(FLEET_SCRIPT, after.replace(b"\n" + snippet, b"", 1))

    def test_a_second_run_changes_nothing(self):
        self.write()
        validate_snippet.ensure_queue_snippet(self.oc, self.repo)
        first = self.script.read_bytes()
        self.assertEqual("present", validate_snippet.ensure_queue_snippet(self.oc, self.repo)[0])
        self.assertEqual(first, self.script.read_bytes())

    def test_the_executable_bit_survives(self):
        self.write(mode=0o755)
        validate_snippet.ensure_queue_snippet(self.oc, self.repo)
        self.assertTrue(self.script.stat().st_mode & stat.S_IXUSR)
        self.write(mode=0o644)
        validate_snippet.ensure_queue_snippet(self.oc, self.repo)
        self.assertEqual(0o644, stat.S_IMODE(self.script.stat().st_mode))

    def test_without_a_cd_line_the_block_goes_after_set_euo_pipefail(self):
        original = b"#!/usr/bin/env bash\nset -euo pipefail\necho hi\n"
        self.write(original)
        self.assertEqual("added", validate_snippet.ensure_queue_snippet(self.oc, self.repo)[0])
        lines = self.script.read_bytes().split(b"\n")
        self.assertEqual(b"set -euo pipefail", lines[1])
        self.assertEqual(b"", lines[2])
        self.assertTrue(lines[3].startswith(validate_snippet.MARKER))

    def test_a_script_with_neither_anchor_is_left_alone_with_the_reason(self):
        original = b"#!/usr/bin/env bash\necho hi\n"
        self.write(original)
        status, why = validate_snippet.ensure_queue_snippet(self.oc, self.repo)
        self.assertEqual("skipped", status)
        self.assertIn("no `cd", why)
        self.assertEqual(original, self.script.read_bytes())

    def test_a_repo_with_no_validate_sh_is_left_alone(self):
        self.assertEqual("absent", validate_snippet.ensure_queue_snippet(self.oc, self.repo)[0])
        self.assertFalse(self.script.exists())

    def test_a_dry_run_writes_nothing(self):
        self.write()
        self.assertEqual("added", validate_snippet.ensure_queue_snippet(self.oc, self.repo, dry_run=True)[0])
        self.assertEqual(FLEET_SCRIPT, self.script.read_bytes())

    def fake_home(self, shim=True):
        """A temp HOME whose validate-queue shim logs its calls and prints a slot for acquire."""
        home = temp_dir(self, "oc-snippet-home-", resolve=True)
        if shim:
            (home / ".local" / "bin").mkdir(parents=True)
            fake = home / ".local" / "bin" / "validate-queue"
            fake.write_text('#!/bin/sh\necho "$@" >> "$HOME/calls"\n[ "$1" = acquire ] && echo "$HOME/slot-1.json"\nexit 0\n')
            fake.chmod(0o755)
        return home

    def run_script(self, home, **extra):
        env = {k: v for k, v in os.environ.items() if k != "VALIDATE_QUEUE_SLOT"}
        env.update(HOME=str(home), **extra)
        return subprocess.run(["bash", str(self.script)], capture_output=True, text=True, env=env, cwd=self.repo)

    PROBE = b'#!/usr/bin/env bash\nset -euo pipefail\nREPO_ROOT="$PWD"\ncd "$REPO_ROOT"\necho "slot=${VALIDATE_QUEUE_SLOT:-unset}"\n'

    def test_a_run_with_the_shim_takes_a_slot_through_it_and_releases_it(self):
        self.write(self.PROBE)
        validate_snippet.ensure_queue_snippet(self.oc, self.repo)
        home = self.fake_home()
        top = self.run_script(home)
        self.assertEqual(f"slot={home}/slot-1.json\n", top.stdout, top.stderr)
        self.assertEqual("", top.stderr)
        calls = (home / "calls").read_text().splitlines()
        self.assertTrue(calls[0].startswith(f"acquire --pid ") and calls[0].endswith(f"--label {self.repo.name}"), calls)
        self.assertEqual([f"release {home}/slot-1.json"], calls[1:])

    def test_a_run_without_the_shim_goes_ahead_unqueued_with_one_line_on_stderr(self):
        self.write(self.PROBE)
        validate_snippet.ensure_queue_snippet(self.oc, self.repo)
        out = self.run_script(self.fake_home(shim=False))
        self.assertEqual(0, out.returncode, out.stderr)
        self.assertEqual(1, len(out.stderr.splitlines()), out.stderr)
        self.assertIn("running unqueued", out.stderr)

    def test_a_nested_run_inside_a_held_slot_skips_the_queue(self):
        self.write(self.PROBE)
        validate_snippet.ensure_queue_snippet(self.oc, self.repo)
        home = self.fake_home()
        nested = self.run_script(home, VALIDATE_QUEUE_SLOT="/held/slot-9.json")
        self.assertEqual("slot=/held/slot-9.json\n", nested.stdout, nested.stderr)
        self.assertFalse((home / "calls").exists(), "a nested run takes no slot")

    def test_a_script_with_its_own_exit_trap_keeps_it(self):
        self.write(b'#!/usr/bin/env bash\nset -euo pipefail\ntrap "echo mine" EXIT\nREPO_ROOT="$PWD"\ncd "$REPO_ROOT"\n')
        validate_snippet.ensure_queue_snippet(self.oc, self.repo)
        home = self.fake_home()
        own = self.run_script(home)
        self.assertEqual("mine\n", own.stdout, own.stderr)
        self.assertEqual(1, len((home / "calls").read_text().splitlines()), "only the acquire ran")



class TestSyncHooksInsertsAndCommits(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "oc-snippet-sync-", resolve=True)
        self.oc = self.tmp / "oc"
        (self.oc / "core" / "templates").mkdir(parents=True)
        shutil.copytree(TEMPLATES, self.oc / "core" / "templates" / "project")
        self.fleet = self.tmp / "fleet"
        self.fleet.mkdir()
        (self.tmp / "home").mkdir()
        env = mock.patch.dict(os.environ, {"HOME": str(self.tmp / "home"), "OLIVERCODE_HOME": str(self.tmp / "ochome")})
        env.start()
        self.addCleanup(env.stop)

    def repo(self, script=FLEET_SCRIPT):
        repo = scratch_repo(self.fleet / "alpha")
        (repo / "scripts").mkdir()
        (repo / "scripts" / "validate.sh").write_bytes(script)
        (repo / "scripts" / "validate.sh").chmod(0o755)
        git(repo, "add", "scripts/validate.sh")
        git(repo, "commit", "-q", "--no-verify", "-m", "First commit")
        return repo

    def sync(self, commit=True):
        with mock.patch.object(cmd_fleet, "_private_repos", return_value={"alpha": self.fleet / "alpha"}), \
                mock.patch.object(cmd_fleet._repo_state, "archived", return_value=None), \
                mock.patch.dict(os.environ, git_env(), clear=True):
            return quiet(launcher.command_sync_hooks, self.oc, commit=commit, story="acme/widgets#7")

    def test_sync_hooks_inserts_the_block_and_commit_includes_validate_sh_by_path(self):
        repo = self.repo()
        (repo / "other.txt").write_text("staged elsewhere\n")
        git(repo, "add", "other.txt")
        code, out = self.sync()
        self.assertEqual(0, code, out)
        self.assertIn("alpha: scripts/validate.sh now takes a validation queue slot", out)
        self.assertIn("alpha: committed", out)
        self.assertIn("scripts/validate.sh", git(repo, "show", "--name-only", "--format=", "HEAD").stdout.split())
        self.assertEqual("A  other.txt", git(repo, "status", "--porcelain").stdout.strip())
        self.assertIn(validate_snippet.MARKER, (repo / "scripts" / "validate.sh").read_bytes())

    def test_without_commit_the_block_is_written_and_nothing_is_committed(self):
        repo = self.repo()
        self.sync(commit=False)
        self.assertIn(validate_snippet.MARKER, (repo / "scripts" / "validate.sh").read_bytes())
        self.assertEqual(1, len(git(repo, "log", "--format=%H").stdout.split()))

    def test_bootstrap_adds_the_block_to_an_existing_validate_sh(self):
        repo = self.repo()
        git(repo, "commit", "-q", "--allow-empty", "--no-verify", "-m", "x")
        with mock.patch.dict(os.environ, git_env(), clear=True):
            code, out = quiet(launcher.command_bootstrap, REPO_ROOT, repo, False)
        self.assertIn("scripts/validate.sh now takes a validation queue slot", out)
        self.assertEqual(1, (repo / "scripts" / "validate.sh").read_bytes().count(validate_snippet.MARKER))
        with mock.patch.dict(os.environ, git_env(), clear=True):
            _, again = quiet(launcher.command_bootstrap, REPO_ROOT, repo, False)
        self.assertNotIn("takes a validation queue slot", again)


if __name__ == "__main__":
    unittest.main()
