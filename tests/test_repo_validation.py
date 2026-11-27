"""Gates and checks fit any repo (#1049): one validation detector, the repo's own hooks and default branch, and and the hook check health runs."""

import json
import unittest

from _support import REPO_ROOT, git, load_script, scratch_repo, temp_dir

load_script("scripts/olivercode", "olivercode_launcher")
from lib import cmd_fleet, health_checks, repo_profiles  # noqa: E402  (load_script put scripts/ on the path)


def put(repo, name, text=""):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class ValidationDetectorTests(unittest.TestCase):
    def repo(self):
        return scratch_repo(temp_dir(self))

    def test_each_language_has_a_validation_command(self):
        for files, command in (
            ({"pytest.ini": "[pytest]\n"}, repo_profiles.PYTEST),
            ({"go.mod": "module x\n"}, "go test ./..."),
            ({"Cargo.toml": "[package]\n"}, "cargo test"),
            ({"Makefile": "test:\n\ttrue\n"}, "make test"),
            ({"package.json": json.dumps({"scripts": {"test": "jest"}})}, repo_profiles.NPM_TEST),
        ):
            repo = self.repo()
            for name, text in files.items():
                put(repo, name, text)
            self.assertEqual(repo_profiles.validation_command(repo), command)

    def test_the_npm_init_placeholder_is_not_a_test(self):
        repo = self.repo()
        put(repo, "package.json", json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}))
        self.assertIsNone(repo_profiles.validation_command(repo))

    def test_the_own_script_wins_and_bootstrap_agrees_with_the_helper(self):
        repo = self.repo()
        put(repo, "scripts/validate.sh")
        put(repo, "go.mod", "module x\n")
        self.assertEqual(repo_profiles.validation_command(repo), "bash scripts/validate.sh")



class HooksPathTests(unittest.TestCase):
    def test_a_repo_with_its_own_husky_hooks_keeps_core_hooks_path(self):
        repo = scratch_repo(temp_dir(self))
        put(repo, ".husky/pre-commit", "true\n")
        git(repo, "config", "core.hooksPath", ".husky")
        self.assertEqual(repo_profiles.own_hooks_path(repo), ".husky")
        cmd_fleet._set_hooks_path(repo)
        self.assertEqual(git(repo, "config", "core.hooksPath").stdout.strip(), ".husky")
        self.assertEqual(health_checks.stopped_hook(repo, REPO_ROOT), "")

    def test_a_hooks_path_folder_with_no_hook_file_is_not_the_repos_own_hooks(self):
        repo = scratch_repo(temp_dir(self))
        put(repo, "scripts/build.sh", "true\n")
        git(repo, "config", "core.hooksPath", "scripts")
        self.assertEqual(repo_profiles.own_hooks_path(repo), "")
        self.assertEqual(bool(health_checks.stopped_hook(repo, REPO_ROOT)), True)

    def test_a_repo_with_no_hooks_path_gets_githooks(self):
        repo = scratch_repo(temp_dir(self))
        cmd_fleet._set_hooks_path(repo)
        self.assertEqual(git(repo, "config", "core.hooksPath").stdout.strip(), ".githooks")


class DefaultBranchTests(unittest.TestCase):
    def test_develop_is_the_default_when_origin_says_so(self):
        origin = scratch_repo(temp_dir(self), branch="develop")
        put(origin, "a.txt", "a\n")
        git(origin, "add", "-A")
        git(origin, "commit", "-q", "--no-verify", "-m", "seed")
        clone = temp_dir(self) / "clone"
        git(origin, "clone", "-q", str(origin), str(clone))
        self.assertEqual(repo_profiles.default_branch(clone), "develop")

    def test_a_repo_with_no_origin_and_no_main_has_no_default_branch(self):
        repo = scratch_repo(temp_dir(self), branch="feature")
        put(repo, "a.txt", "a\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "--no-verify", "-m", "seed")
        self.assertEqual(repo_profiles.default_branch(repo), "")


if __name__ == "__main__":
    unittest.main()
