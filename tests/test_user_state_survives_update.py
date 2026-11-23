"""Story #762: the user's settings, audit choices and lessons live outside the tracked files and survive every update."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, temp_dir
from test_update_keeps_local_learning import Checkout, git, write

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "audit" / "scripts"))
import audit_mode  # noqa: E402
from lib import lessons, local_config, repo_profiles, state_migrations  # noqa: E402

USER_FILES = ("olivercode.local.json", "shared/repo-profiles.local.json", "docs/backlog-config.local.json", "docs/LESSONS.jsonl")


class WithIgnore(Checkout):
    """The checkout ships OliverCode's own .gitignore, and this device's settings file sits at its root."""

    def setUp(self):
        super().setUp()
        self.release(".gitignore", (REPO_ROOT / ".gitignore").read_text())
        git(self.clone, "pull", "-q", "--ff-only")
        patch = mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(self.clone / "olivercode.local.json")})
        patch.start()
        self.addCleanup(patch.stop)


class SettingsHaveOnePerUserHome(WithIgnore):
    def test_a_preference_an_audit_mode_and_a_lesson_leave_every_tracked_file_alone(self):
        audit_mode.set_mode("full")
        local_config.save_local({"autoCoverLessons": True})
        lessons.add("a check missed", "the skill drifted", "check the override", repo=self.clone)
        write(self.clone, "docs/backlog-config.local.json", '{"repoOwner": "me"}')
        write(self.clone, "shared/repo-profiles.local.json", '{"profiles": {}}')
        self.assertEqual(audit_mode.get_mode(), "full")
        self.assertFalse(lessons.path(self.clone).is_relative_to(self.clone))
        self.assertEqual(git(self.clone, "status", "--porcelain", "--untracked-files=all"), "")

    def test_every_per_user_file_is_ignored_and_untracked_in_this_checkout(self):
        for rel in USER_FILES:
            ignored = subprocess.run(["git", "-C", str(self.clone), "check-ignore", "-q", "--no-index", rel])
            self.assertEqual(ignored.returncode, 0, f"{rel} is not git-ignored")
            tracked = subprocess.run(["git", "-C", str(self.clone), "ls-files", "--error-unmatch", rel], capture_output=True)
            self.assertNotEqual(tracked.returncode, 0, f"{rel} is tracked")


class UntrackedFilesDoNotBlockTheUpdate(WithIgnore):
    def test_an_ignored_lesson_log_and_an_untracked_note_let_the_update_run(self):
        write(self.clone, "docs/LESSONS.jsonl", '{"id": "L-old"}\n')
        write(self.clone, "olivercode.local.json", '{"auditMode": "gated"}')
        write(self.clone, "notes.txt", "mine")
        self.release("skills/shipped/SKILL.md", "shipped v2")
        code, calls, out = self.update()
        self.assertEqual((code, calls), (0, ["install", "sync-hooks", "conform"]), out)
        self.assertEqual((self.clone / "skills" / "shipped" / "SKILL.md").read_text(), "shipped v2")
        self.assertEqual((self.clone / "notes.txt").read_text(), "mine")
        settings = json.loads((self.clone / "olivercode.local.json").read_text())
        self.assertEqual(settings.pop("fleetRegistry"), str(Path(os.environ["OLIVERCODE_FLEET_DIR"]) / "repo-profiles.json"))
        self.assertEqual(settings, {"auditMode": "gated"})
        self.assertIn('{"id": "L-old"}', lessons.path(self.clone).read_text())

    def test_an_untracked_file_the_release_adds_is_refused_with_a_stash_of_that_file_only(self):
        write(self.clone, "skills/new/SKILL.md", "mine")
        self.release("skills/new/SKILL.md", "shipped")
        code, calls, out = self.update()
        self.assertEqual((code, calls), (1, []), out)
        self.assertIn("-- skills/new/SKILL.md", out)
        self.assertEqual((self.clone / "skills" / "new" / "SKILL.md").read_text(), "mine")


class AUserWhoCannotPushIsNotToldToPush(Checkout):
    def test_the_refusal_moves_local_commits_to_a_local_branch_and_the_fix_works(self):
        git(self.clone, "commit", "-q", "--allow-empty", "-m", "local work (#762)")
        mine = git(self.clone, "rev-parse", "HEAD")
        self.release("skills/shipped/SKILL.md", "shipped v2")
        code, _, out = self.update()
        self.assertEqual(code, 1)
        fix = next(line for line in out.splitlines() if line.startswith("Fix: "))[len("Fix: "):]
        self.assertNotIn(" push", fix)
        subprocess.run(fix, shell=True, check=True, capture_output=True, env={**os.environ, **{"GIT_CONFIG_GLOBAL": os.devnull}})
        self.assertEqual(git(self.clone, "rev-parse", "olivercode-local"), mine)
        code, calls, out = self.update()
        self.assertEqual((code, calls), (0, ["install", "sync-hooks", "conform"]), out)


class AReleaseMovesAStateFile(Checkout):
    def test_install_moves_the_old_lesson_log_once_with_a_backup_and_leaves_one_copy(self):
        write(self.clone, "docs/LESSONS.jsonl", '{"id": "L-old"}\n{"id": "L-both"}\n')
        target = lessons.path(self.clone)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"id": "L-both"}\n')
        _, out = self.install()
        self.assertIn("[MIGRATED]", out)
        self.assertFalse((self.clone / "docs" / "LESSONS.jsonl").exists())
        self.assertEqual(target.read_text().splitlines(), ['{"id": "L-both"}', '{"id": "L-old"}'])
        backups = list((self.ohome / "backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertIn("L-old", backups[0].read_text())
        self.assertIn("1", state_migrations.applied())
        _, again = self.install()
        self.assertNotIn("[MIGRATED]", again)
        self.assertEqual(len(list((self.ohome / "backups").iterdir())), 1)

    def test_a_moved_json_file_keeps_the_values_the_new_home_already_holds(self):
        old, new = self.clone / "old.json", self.ohome / "new.json"
        old.write_text('{"a": 1, "b": 1}')
        new.write_text('{"b": 2}')
        moved = state_migrations.run(self.clone, (state_migrations.Migration(99, "test", lambda oc: old, lambda oc: new, "json"),))
        self.assertEqual(len(moved), 1)
        self.assertEqual(json.loads(new.read_text()), {"a": 1, "b": 2})
        self.assertFalse(old.exists())


class AReleaseAddsADefault(unittest.TestCase):
    def test_the_saved_value_wins_and_only_a_missing_key_takes_the_default(self):
        cfg = temp_dir(self) / "local.json"
        cfg.write_text('{"autoCoverLessons": true}')
        with mock.patch.dict(os.environ, {"OLIVERCODE_LOCAL_CONFIG": str(cfg)}), \
                mock.patch.dict(local_config.DEFAULTS, {"autoCoverLessons": False, "aNewSetting": 5}):
            self.assertIs(local_config.setting("autoCoverLessons"), True)
            self.assertEqual(local_config.setting("aNewSetting"), 5)
        self.assertEqual(json.loads(cfg.read_text()), {"autoCoverLessons": True})


class TrackedConfigIsNotUserConfig(unittest.TestCase):
    def test_the_local_backlog_config_overrides_the_tracked_one_key_by_key(self):
        repo = temp_dir(self)
        write(repo, "docs/backlog-config.json", json.dumps({"repoOwner": "up", "repoName": "OliverCode",
                                                            "fields": {"status": {"id": "S1"}, "size": {"id": "Z1"}}}))
        self.assertEqual(local_config.backlog_config(repo)["repoOwner"], "up")
        write(repo, "docs/backlog-config.local.json", json.dumps({"repoOwner": "me", "fields": {"status": {"id": "S2"}}}))
        cfg = local_config.backlog_config(repo)
        self.assertEqual((cfg["repoOwner"], cfg["repoName"]), ("me", "OliverCode"))
        self.assertEqual(cfg["fields"], {"status": {"id": "S2"}, "size": {"id": "Z1"}})
        (repo / "docs" / "backlog-config.json").unlink()
        self.assertEqual(local_config.backlog_config(repo)["repoOwner"], "me")

    def test_a_fork_registers_its_fleet_in_the_ignored_local_registry(self):
        fork = temp_dir(self)
        write(fork, "shared/repo-profiles.json", '{"profiles": {}}')
        self.assertEqual(repo_profiles.registry_write_file(fork), fork / "shared" / "repo-profiles.local.json")
        write(fork, "shared/repo-profiles.local.json", '{"profiles": {"mine": {}}}')
        self.assertEqual(repo_profiles.load_repo_profiles(fork)[0], {"mine": {}})

    def test_no_tracked_config_holds_a_user_value(self):
        profiles = json.loads((REPO_ROOT / "shared" / "repo-profiles.json").read_text())
        self.assertEqual(profiles["profiles"], {}, "shared/repo-profiles.json names a user's repos")
        example = json.loads((REPO_ROOT / "olivercode.local.example.json").read_text())
        paths = [example["skillsRoot"], *example["privateRepos"].values(), *example["repoPaths"].values(),
                 *example["liveCopies"].keys(), *example["liveCopies"].values()]
        self.assertTrue(all("path/" in p for p in paths), paths)
        backlog = json.loads((REPO_ROOT / "shared" / "backlog-config.example.json").read_text())
        self.assertEqual(backlog["repoOwner"], "your-github-org-or-user")
        tracked = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "*.json", "*.jsonl"],
                                 capture_output=True, text=True, check=True).stdout.split()
        for rel in tracked:
            text = (REPO_ROOT / rel).read_text(errors="ignore") if (REPO_ROOT / rel).is_file() else ""
            self.assertNotRegex(text, r"/Users/[A-Za-z]|/home/[a-z]", f"{rel} holds a machine path")


if __name__ == "__main__":
    unittest.main()
